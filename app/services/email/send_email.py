# app/services/email/send_email.py
from __future__ import annotations
from email.utils import formataddr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Mapping, Iterable
import re
import smtplib
import boto3
from botocore.config import Config
from tenacity import retry, wait_exponential, stop_after_attempt
from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.core.config import settings  # pydantic Settings想定
import os
from app.core.logger import Logger
logger = Logger.get_logger()
# --------------------------
# Jinja2
# --------------------------
TEMPLATE_DIR = getattr(settings, "EMAIL_TEMPLATE_DIR", "app/templates")
jinja_env = Environment(
    loader=FileSystemLoader(searchpath=TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)

def render(template_name: str, **ctx) -> str:
    return jinja_env.get_template(template_name).render(**ctx)

# --------------------------
# Helpers
# --------------------------
def _html_to_text(html: str) -> str:
    """超簡易HTML→TEXT。依存を増やさずに最低限の可読化。"""
    text = re.sub(r"<(script|style).*?>.*?</\1>", "", html, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<.*?>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def _build_mime(
    subject: str,
    from_addr: str,
    to_addr: str,
    html: str,
    text: str | None = None,
    reply_to: str | None = None,
    list_unsubscribe: str | None = None,
    cc: Iterable[str] | None = None,
    bcc: Iterable[str] | None = None,
) -> str:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    if list_unsubscribe:
        # 例: <mailto:unsubscribe@mijfans.jp>, <https://mijfans.jp/unsub?u=abc>
        msg["List-Unsubscribe"] = list_unsubscribe

    if not text:
        text = _html_to_text(html)

    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg.as_string()

def _from_header() -> str:
    display = getattr(settings, "MAIL_FROM_NAME", "") or "mijfans"
    return formataddr((display, settings.MAIL_FROM))

def _email_tags(base: dict[str, str] | None = None) -> list[dict[str, str]]:
    tags = {"env": getattr(settings, "ENV", "local")}
    if base:
        tags.update({k: str(v) for k, v in base.items()})
    return [{"Name": k, "Value": v} for k, v in tags.items()]

# --------------------------
# MailHog（ローカルSMTP）
# --------------------------
def _send_via_mailhog(to: str, subject: str, html: str, text: str | None = None) -> str:
    raw = _build_mime(
        subject=subject,
        from_addr=_from_header(),
        to_addr=to,
        html=html,
        text=text,
        reply_to=getattr(settings, "REPLY_TO", None),
        list_unsubscribe=getattr(settings, "LIST_UNSUBSCRIBE", None),
    )
    host = getattr(settings, "MAILHOG_HOST", "127.0.0.1")
    port = int(getattr(settings, "MAILHOG_PORT", 1025))
    with smtplib.SMTP(host, port) as s:
        s.sendmail(settings.MAIL_FROM, [to], raw)
    # MailHogはMessageId返さないのでダミー
    return "mailhog-local"

# --------------------------
# SES v2（API）
# --------------------------
def _ses_client():
    return boto3.client(
        "sesv2",
        region_name=getattr(settings, "AWS_REGION", "ap-northeast-1"),
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )

@retry(wait=wait_exponential(multiplier=0.5, min=1, max=10), stop=stop_after_attempt(3))
def _send_via_ses_simple(
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    tags: dict[str, str] | None = None,
) -> str:
    client = _ses_client()
    body = {"Html": {"Data": html, "Charset": "UTF-8"}}
    if text:
        body["Text"] = {"Data": text, "Charset": "UTF-8"}
    else:
        body["Text"] = {"Data": _html_to_text(html), "Charset": "UTF-8"}

    
    reply_to = getattr(settings, "REPLY_TO", None)
    unsubscribe_email = reply_to or "support@mijfans.jp"

    headers = [
        {
            "Name": "List-Unsubscribe",
            # mailto 形式が一番無難
            "Value": f"<mailto:{unsubscribe_email}>",
        },
        {
            "Name": "List-Unsubscribe-Post",
            # 1-click unsubscribe 対応クライアント向け
            "Value": "List-Unsubscribe=One-Click",
        },
    ]

    params = {
        "FromEmailAddress": _from_header(),           # "Name <no-reply@...>"
        "Destination": {"ToAddresses": [to]},
        "Content": {
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": body,
                "Headers": headers,
            }
        },
        "EmailTags": _email_tags(tags),
    }

    confset = getattr(settings, "SES_CONFIGURATION_SET", None)
    if confset:
        params["ConfigurationSetName"] = confset

    reply_to = getattr(settings, "REPLY_TO", None)
    if reply_to:
        params["ReplyToAddresses"] = [reply_to]

    resp = client.send_email(**params)
    return resp.get("MessageId", "")

# --------------------------
# パブリックAPI（既存名を維持）
# --------------------------
def send_thanks_email(to: str, name: str | None = None) -> None:
    """事前登録サンクスメール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = "【mijfans】事前登録が完了しました"
    html = render("prereg_thanks.html", name=name or "")
    _send_backend(to=to, subject=subject, html=html, tags={"category": "prereg_thanks"})

def send_templated_email(
    to: str,
    subject: str,
    template_html: str,
    ctx: Mapping[str, object],
    tags: dict[str, str] | None = None,
) -> None:
    """Jinja2テンプレで送信（ENVに応じてMailHog/SESを自動切替）"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    html = render(template_html, **ctx)
    _send_backend(to=to, subject=subject, html=html, tags=tags or {})

def send_email_verification(to: str, verify_url: str, display_name: str | None = None) -> None:
    """メール認証メール"""
    subject = "【mijfans】メールアドレスの確認をお願いします"
    ctx = {
        "name": display_name or "",
        "verify_url": verify_url,
        "brand": "mijfans",
        "support_email": os.getenv("SUPPORT_EMAIL", "support@mijfans.jp"),
        "expire_hours": os.getenv("EMAIL_VERIFY_TTL_HOURS", "24"),
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="verify_email.html",
        ctx=ctx,
        tags={"category": "verify"},
    )

def send_identity_approval_email(to: str, display_name: str | None = None) -> None:
    """身分証明承認完了メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = "【mijfans】身分証明書の審査が完了しました"
    ctx = {
        "name": display_name or "",
        "brand": "mijfans",
        "status": 1,  # 承認
        "support_email": os.getenv("SUPPORT_EMAIL", "support@mijfans.jp"),
        "reapply_url": f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/creator/request",
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="approval_complete.html",
        ctx=ctx,
        tags={"category": "identity_approval"},
    )

def send_identity_rejection_email(to: str, display_name: str | None = None, notes: str | None = None) -> None:
    """身分証明拒否通知メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = "【mijfans】身分証明書の審査結果について"
    ctx = {
        "name": display_name or "",
        "brand": "mijfans",
        "status": 0,  # 拒否
        "notes": notes or "申請内容を再度ご確認ください。",
        "support_email": os.getenv("SUPPORT_EMAIL", "support@mijfans.jp"),
        "reapply_url": f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/creator/request",
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="approval_complete.html",
        ctx=ctx,
        tags={"category": "identity_rejection"},
    )

def send_password_reset_email(to: str, reset_url: str, display_name: str | None = None) -> None:
    """パスワードリセットメール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = "【mijfans】パスワードリセットのご案内"
    ctx = {
        "name": display_name or "",
        "reset_url": reset_url,
        "brand": "mijfans",
        "support_email": os.getenv("SUPPORT_EMAIL", "support@mijfans.jp"),
        "expire_hours": os.getenv("PASSWORD_RESET_TTL_HOURS", "1"),
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="password_reset.html",
        ctx=ctx,
        tags={"category": "password_reset"},
    )

def send_post_approval_email(to: str, display_name: str | None = None, post_id: str | None = None) -> None:
    """投稿承認完了メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = "【mijfans】投稿が承認されました"
    ctx = {
        "name": display_name or "",
        "brand": "mijfans",
        "status": 1,  # 承認
        "post_url": f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/post/detail?post_id={post_id}",
        "support_email": os.getenv("SUPPORT_EMAIL", "support@mijfans.jp"),
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="post_notification.html",
        ctx=ctx,
        tags={"category": "post_approval"},
    )

def send_post_rejection_email(to: str, display_name: str | None = None, notes: str | None = None, post_id: str | None = None) -> None:
    """投稿拒否通知メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = "【mijfans】投稿が拒否されました"
    ctx = {
        "name": display_name or "",
        "brand": "mijfans",
        "status": 0,  # 拒否
        "notes": notes or "申請内容を再度ご確認ください。",
        "post_url": f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/account/post/{post_id}",
        "support_email": os.getenv("SUPPORT_EMAIL", "support@mijfans.jp"),
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="post_notification.html",
        ctx=ctx,
        tags={"category": "post_rejection"},
    )

def send_profile_image_approval_email(to: str, display_name: str | None = None, redirect_url: str | None = None) -> None:
    """プロフィール画像承認完了メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = "【mijfans】プロフィール画像が承認されました"
    ctx = {
        "name": display_name or "",
        "brand": "mijfans",
        "status": 1,  # 承認
        "profile_url": redirect_url or f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/account/edit",
        "support_email": os.getenv("SUPPORT_EMAIL", "support@mijfans.jp"),
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="profile_notification.html",
        ctx=ctx,
        tags={"category": "profile_image_approval"},
    )

def send_profile_image_rejection_email(to: str, display_name: str | None = None, notes: str | None = None, redirect_url: str | None = None) -> None:
    """プロフィール画像拒否通知メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = "【mijfans】プロフィール画像が拒否されました"
    ctx = {
        "name": display_name or "",
        "brand": "mijfans",
        "status": 0,  # 拒否
        "notes": notes or "申請内容を再度ご確認ください。",
        "profile_url": redirect_url or f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/account/edit",
        "support_email": os.getenv("SUPPORT_EMAIL", "support@mijfans.jp"),
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="profile_notification.html",
        ctx=ctx,
        tags={"category": "profile_image_rejection"},
    )

def send_follow_notification_email(to: str, name: str | None = None, username: str | None = None, redirect_url: str | None = None) -> None:
    """フォロー通知メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = "【mijfans】フォロー通知"
    ctx = {
        "name": name or "", 
        "brand": "mijfans",
        "username": username or "",
        "redirect_url": redirect_url or os.environ.get("FRONTEND_URL", "https://mijfans.jp/"),
        "support_email": os.getenv("SUPPORT_EMAIL", "support@mijfans.jp"),
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="follow_notification.html",
        ctx=ctx,
        tags={"category": "follow_notification"},
    )

def send_like_notification_email(to: str, name: str | None = None, username: str | None = None, redirect_url: str | None = None) -> None:
    """いいね通知メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = "【mijfans】いいね通知"
    ctx = {
        "name": name or "",
        "brand": "mijfans",
        "username": username or "",
        "redirect_url": redirect_url or os.environ.get("FRONTEND_URL", "https://mijfans.jp/"),
        "support_email": os.getenv("SUPPORT_EMAIL", "support@mijfans.jp"),
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="like_notification.html",
        ctx=ctx,
        tags={"category": "follow_notification"},
    )


def send_payment_succuces_email(
    to: str, 
    content_url: str | None = None, 
    transaction_id: int | None = None, 
    contents_name: str | None = None, 
    payment_date: str | None = None,
    amount: int | None = None,
    sendid: str | None = None,
    user_name: str | None = None,
    user_email: str | None = None,
    purchase_history_url: str | None = None,
) -> None:
    """決済完了メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = f"【mijfans】決済結果のご連絡"
    ctx = {
        "content_url": content_url or "",
        "transaction_id": transaction_id,
        "contents_name": contents_name,
        "amount": amount,
        "payment_date": payment_date,
        "sendid": sendid,
        "user_name": user_name,
        "user_email": user_email,
        "purchase_history_url": purchase_history_url or "",
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="payment_succuces.html",
        ctx=ctx,
        tags={"category": "payment_succuces"},
    )

def send_payment_faild_email(
    to: str,
    transaction_id: int | None = None,
    failure_date: str | None = None,
    sendid: str | None = None,
    user_name: str | None = None,
    user_email: str | None = None,
) -> None:
    """決済失敗メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = f"【mijfans】決済失敗のご連絡"
    ctx = {
        "transaction_id": transaction_id,
        "failure_date": failure_date,
        "sendid": sendid,
        "user_name": user_name,
        "user_email": user_email,
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="payment_faild.html",
        ctx=ctx,
        tags={"category": "payment_faild"},
    )


def send_selling_info_email(
    to: str, 
    buyer_name: str | None = None, 
    contents_name: str | None = None,
    seller_name: str | None = None,
    content_url: str | None = None, 
    contents_type: str | None = None,
    dashboard_url: str | None = None) -> None:
    """商品購入通知メール"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = f"【mijfans】商品購入通知"
    ctx = {
        "buyer_name": buyer_name,
        "contents_name": contents_name,
        "seller_name": seller_name,
        "content_url": content_url,
        "contents_type": contents_type,
        "dashboard_url": dashboard_url,
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="selling_info.html",
        ctx=ctx,
        tags={"category": "selling_info"},
    )


def send_cancel_subscription_email(
    to: str,
    user_name: str | None = None,
    creator_user_name: str | None = None,
    plan_name: str | None = None,
    plan_url: str | None = None,
) -> None:
    """プラン解約通知メール（販売者向け）"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = f"【mijfans】プラン解約通知"
    ctx = {
        "user_name": user_name,
        "creator_user_name": creator_user_name,
        "plan_name": plan_name,
        "plan_url": plan_url,
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="cancel_subscription.html",
        ctx=ctx,
        tags={"category": "cancel_subscription"},
    )


def send_buyer_cancel_subscription_email(
    to: str,
    user_name: str | None = None,
    creator_user_name: str | None = None,
    plan_name: str | None = None,
    plan_url: str | None = None,
) -> None:
    """プラン解約通知メール（購入者向け）"""
    if not getattr(settings, "EMAIL_ENABLED", True):
        return
    subject = f"【mijfans】プラン解約のご連絡"
    ctx = {
        "user_name": user_name,
        "creator_user_name": creator_user_name,
        "plan_name": plan_name,
        "plan_url": plan_url,
    }
    send_templated_email(
        to=to,
        subject=subject,
        template_html="buyer_cancel_subscription.html",
        ctx=ctx,
        tags={"category": "buyer_cancel_subscription"},
    )

# --------------------------
# 実体：バックエンド切替
# --------------------------
def _send_backend(to: str, subject: str, html: str, tags: dict[str, str] | None = None) -> None:
    backend = (getattr(settings, "EMAIL_BACKEND", "") or "").lower()
    try:
        if backend in ("", "auto"):
            # ENVで自動判定: local/dev → mailhog、それ以外 → ses
            env = (getattr(settings, "ENV", "local") or "local").lower()
            backend = "mailhog" if env in ("local", "dev") else "ses"

        if backend == "mailhog":
            _send_via_mailhog(to=to, subject=subject, html=html)
        elif backend == "ses":
            _send_via_ses_simple(to=to, subject=subject, html=html, tags=tags)
        else:
            raise RuntimeError(f"Unsupported EMAIL_BACKEND: {backend}")
    except Exception as e:
        # 必要に応じて構造化ログへ
        logger.error(f"[email] send failed backend={backend} to={to} err={e}")
