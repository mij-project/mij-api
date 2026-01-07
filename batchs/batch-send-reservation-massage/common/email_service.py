# app/services/email/send_email.py
from __future__ import annotations

import os
import re
import smtplib
from typing import Mapping, Iterable, Optional, Dict, List, Any

import boto3
from botocore.config import Config
from jinja2 import Environment, FileSystemLoader, select_autoescape
from tenacity import retry, wait_exponential, stop_after_attempt

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr


class EmailService:
    """
    Core Email Service (env-based).
    Config via os.environ only.

    Env keys (defaults):
    - EMAIL_ENABLED=true
    - EMAIL_BACKEND=auto | mailhog | ses
    - ENV=local

    - EMAIL_TEMPLATE_DIR=app/templates

    - MAIL_FROM=no-reply@example.com
    - MAIL_FROM_NAME=mijfans
    - REPLY_TO=(optional)
    - LIST_UNSUBSCRIBE=(optional)

    - MAILHOG_HOST=127.0.0.1
    - MAILHOG_PORT=1025

    - AWS_REGION=ap-northeast-1
    - SES_CONFIGURATION_SET=(optional)
    """

    def __init__(self, template_dir: Optional[str] = None):
        self.template_dir = template_dir
        self.jinja_env = Environment(
            loader=FileSystemLoader(searchpath=self.template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

    # --------------------------
    # Basic config
    # --------------------------
    def is_enabled(self) -> bool:
        return os.environ.get("EMAIL_ENABLED", "true").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    def _env(self) -> str:
        return (os.environ.get("ENV", "local") or "local").lower()

    def _backend(self) -> str:
        backend = (os.environ.get("EMAIL_BACKEND", "auto") or "auto").lower()
        if backend in ("auto", ""):
            return "mailhog" if self._env() in ("local", "dev") else "ses"
        return backend

    def _from_header(self) -> str:
        email_addr = os.environ.get("MAIL_FROM", "no-reply@mijfans.jp")
        display = os.environ.get("MAIL_FROM_NAME", "mijfans")
        return formataddr((display, email_addr))

    def _reply_to(self) -> Optional[str]:
        return os.environ.get("REPLY_TO")

    def _list_unsubscribe(self) -> Optional[str]:
        return os.environ.get("LIST_UNSUBSCRIBE")

    # --------------------------
    # Template
    # --------------------------
    def render(self, template_name: str, **ctx) -> str:
        return self.jinja_env.get_template(template_name).render(**ctx)

    # --------------------------
    # Helpers
    # --------------------------
    @staticmethod
    def html_to_text(html: str) -> str:
        text = re.sub(r"<(script|style).*?>.*?</\1>", "", html, flags=re.S)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
        text = re.sub(r"<.*?>", "", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def build_mime(
        self,
        subject: str,
        to_addr: str,
        html: str,
        text: Optional[str] = None,
        cc: Optional[Iterable[str]] = None,
        bcc: Optional[Iterable[str]] = None,
        reply_to: Optional[str] = None,
        list_unsubscribe: Optional[str] = None,
    ) -> str:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from_header()
        msg["To"] = to_addr

        if cc:
            msg["Cc"] = ", ".join(cc)

        rt = reply_to or self._reply_to()
        if rt:
            msg["Reply-To"] = rt

        lu = list_unsubscribe or self._list_unsubscribe()
        if lu:
            msg["List-Unsubscribe"] = lu

        if not text:
            text = self.html_to_text(html)

        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        return msg.as_string()

    def _email_tags(
        self, base: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, str]]:
        tags = {"env": self._env()}
        if base:
            tags.update({k: str(v) for k, v in base.items()})
        return [{"Name": k, "Value": v} for k, v in tags.items()]

    # --------------------------
    # MailHog
    # --------------------------
    def _send_mailhog(
        self,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        cc: Optional[Iterable[str]] = None,
        bcc: Optional[Iterable[str]] = None,
        reply_to: Optional[str] = None,
        list_unsubscribe: Optional[str] = None,
    ) -> str:
        raw = self.build_mime(
            subject=subject,
            to_addr=to,
            html=html,
            text=text,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            list_unsubscribe=list_unsubscribe,
        )

        host = os.environ.get("MAILHOG_HOST", "127.0.0.1")
        port = int(os.environ.get("MAILHOG_PORT", "1025"))

        recipients = [to]
        if cc:
            recipients.extend(list(cc))
        if bcc:
            recipients.extend(list(bcc))

        mail_from = os.environ.get("MAIL_FROM", "no-reply@mijfans.jp")

        with smtplib.SMTP(host, port) as s:
            s.sendmail(mail_from, recipients, raw)

        return "mailhog-local"

    # --------------------------
    # SES v2
    # --------------------------
    def _ses_client(self):
        return boto3.client(
            "sesv2",
            region_name=os.environ.get("AWS_REGION", "ap-northeast-1"),
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        )

    @retry(
        wait=wait_exponential(multiplier=0.5, min=1, max=10), stop=stop_after_attempt(3)
    )
    def _send_ses(
        self,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        cc: Optional[Iterable[str]] = None,
        bcc: Optional[Iterable[str]] = None,
        reply_to: Optional[str] = None,
    ) -> str:
        client = self._ses_client()

        body = {
            "Html": {"Data": html, "Charset": "UTF-8"},
            "Text": {"Data": text or self.html_to_text(html), "Charset": "UTF-8"},
        }

        destination: Dict[str, List[str]] = {"ToAddresses": [to]}
        if cc:
            destination["CcAddresses"] = list(cc)
        if bcc:
            destination["BccAddresses"] = list(bcc)

        params: Dict[str, Any] = {
            "FromEmailAddress": os.environ.get("MAIL_FROM", "no-reply@mijfans.jp"),
            "Destination": destination,
            "Content": {
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": body,
                }
            },
            "EmailTags": self._email_tags(tags),
        }

        confset = os.environ.get("SES_CONFIGURATION_SET")
        if confset:
            params["ConfigurationSetName"] = confset

        rt = reply_to or self._reply_to()
        if rt:
            params["ReplyToAddresses"] = [rt]

        resp = client.send_email(**params)
        return resp.get("MessageId", "")

    # --------------------------
    # Public core APIs
    # --------------------------
    def send_html(
        self,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        cc: Optional[Iterable[str]] = None,
        bcc: Optional[Iterable[str]] = None,
        reply_to: Optional[str] = None,
        list_unsubscribe: Optional[str] = None,
    ) -> Optional[str]:
        """
        Send HTML email.
        Returns:
        - SES MessageId
        - "mailhog-local" for MailHog
        - None when disabled or failed
        """
        if not self.is_enabled():
            return None

        backend = self._backend()

        try:
            if backend == "mailhog":
                return self._send_mailhog(
                    to=to,
                    subject=subject,
                    html=html,
                    text=text,
                    cc=cc,
                    bcc=bcc,
                    reply_to=reply_to,
                    list_unsubscribe=list_unsubscribe,
                )
            if backend == "ses":
                return self._send_ses(
                    to=to,
                    subject=subject,
                    html=html,
                    text=text,
                    tags=tags,
                    cc=cc,
                    bcc=bcc,
                    reply_to=reply_to,
                )

            raise RuntimeError(f"Unsupported EMAIL_BACKEND: {backend}")
        except Exception as e:
            # Bạn có thể đổi sang structured logger sau
            print(f"[email] send failed backend={backend} to={to} err={e}")
            return None

    def send_templated(
        self,
        to: str,
        subject: str,
        template_html: str,
        ctx: Optional[Mapping[str, object]] = None,
        tags: Optional[Dict[str, str]] = None,
        cc: Optional[Iterable[str]] = None,
        bcc: Optional[Iterable[str]] = None,
        reply_to: Optional[str] = None,
        list_unsubscribe: Optional[str] = None,
    ) -> Optional[str]:
        ctx = ctx or {}
        html = self.render(template_html, **ctx)
        return self.send_html(
            to=to,
            subject=subject,
            html=html,
            text=None,
            tags=tags,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            list_unsubscribe=list_unsubscribe,
        )
