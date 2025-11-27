import os
from app.constants.enums import BannerType

FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://mijfans.jp")

class WelcomeMessage:
    MESSAGE = "妄想の種へようこそ！\n\n・追加してほしい機能\n・改善してほしい点\n・その他ご意見\n\nどんなことでも気軽に運営へメッセージしてください。\nmijfansは、ユーザー様の声をもとにより使いやすく、\nより快適なサービスへ進化していきます。"
    SECOND_MESSAGE = "いつでもご意見をお聞かせください。"


class IdentityVerificationMessage:
    IDENTITY_APPROVED_MESSAGE = """mijfans 身分証明書の審査が完了しました
-name- 様

身分証明書の審査が完了いたしました。

> ✅ **審査結果: 承認**
> おめでとうございます！クリエイターとしての活動を開始できます。

沢山のファンがあなたのコンテンツを楽しみにお待ちしています。
ぜひ素敵なコンテンツをお届けください。

お問い合わせ: support@mijfans.jp

※ このメールは自動送信されています。返信はできません。
"""

    IDENTITY_REJECTED_MESSAGE = f"""mijfans 身分証明書の審査が完了しました

-name- 様

身分証明書の審査が完了いたしました。

> ❌ **審査結果: 拒否**
> 誠に申し訳ございませんが、今回の申請は承認されませんでした。

書類を再確認の上、再度申請をお願いいたします。
ご不明な点がございましたら、サポートまでお問い合わせください。

再申請はこちらのリンクから行えます。

<a href="{FRONTEND_URL}/creator/request" style="color:#2563eb;text-decoration:none;">身分証明書の再申請</a>

お問い合わせ: support@mijfans.jp

※ このメールは自動送信されています。返信はできません。
"""