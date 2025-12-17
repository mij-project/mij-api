"""
CREDIXクライアント
"""
import httpx
from typing import Dict, Any, Optional
from urllib.parse import parse_qs
from app.core.config import settings
from app.core.logger import Logger


logger = Logger.get_logger()


class CredixClient:
    """CREDIXクライアント"""

    def __init__(self):
        self.base_url = settings.CREDIX_API_BASE_URL
        self.client_ip = settings.CREDIX_CLIENTIP
        self.zkey = settings.CREDIX_ZKEY

    async def create_session(
        self,
        sendid: str,
        money: int,
        email: str | None = None,
        search_type: int | None = None,
        use_seccode: bool = True,
        send_email: bool = True,
        sendpoint: Optional[str] = None,
        success_url: Optional[str] = None,
        failure_url: Optional[str] = None,
        is_repeater: bool = False,
    ) -> Dict[str, Any]:
        """
        CREDIXセッション発行API呼び出し（初回決済・リピーター決済共通）

        Args:
            sendid: カードID（初回決済の場合は新規生成、リピーター決済の場合は既存のもの）
            money: 決済金額
            email: メールアドレス
            search_type: 会員検索条件（1=clientip+telno+sendid, 2=clientip+sendid）※リピーター決済時のみ使用
            use_seccode: セキュリティコード入力要否
            send_email: メール送信フラグ
            sendpoint: フリーパラメータ
            success_str: 決済完了メッセージ（Shift-JIS）
            failure_str: 決済失敗メッセージ（Shift-JIS）
            success_url: 決済完了後のリダイレクトURL
            failure_url: 決済失敗後のリダイレクトURL
            is_repeater: リピーター決済かどうか
        Returns:
            セッション発行レスポンス
            {
                "result": "ok" | "ng",
                "sid": "セッションID",
                "error_message": "エラーメッセージ"  # resultが"ng"の場合のみ
            }
        """
        # リピーター決済と初回決済でエンドポイントを切り替え
        if is_repeater:
            url = f"{self.base_url}{settings.CREDIX_REPEATER_ENDPOINT}"
            # リピーター決済の場合、search_typeが指定されていない場合はデフォルト値2を使用
            if search_type is None:
                search_type = 2
        else:
            url = f"{self.base_url}{settings.CREDIX_SESSION_ENDPOINT}"

        # パラメータ構築
        params = {
            "clientip": self.client_ip,
            "zkey": self.zkey,
            "money": money,
            "sendid": sendid,
            "redirect_type": 2,  # 成功時のみリダイレクト
            "search_type": 2
        }

        # リダイレクトURL
        if success_url:
            params["success_url"] = success_url
        if failure_url:
            params["failure_url"] = failure_url

        # フリーパラメータ
        if sendpoint:
            params["sendpoint"] = sendpoint

        logger.info(f"CREDIX session request: {url}")
        logger.info(f"CREDIX params: money={money}, sendid={sendid}, is_repeater={is_repeater}, search_type={search_type}")

        # API呼び出し
        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                response = await client.post(url, data=params)
                response.raise_for_status()

                # レスポンスの bytes を取得
                response_bytes = response.content

                # bytes のまま parse_qs に渡す & encoding="shift_jis" を指定
                result_raw = parse_qs(response_bytes, encoding="shift_jis", errors="replace")

                # バイト列のキーと値を文字列にデコード
                result = {}
                for key, value_list in result_raw.items():
                    # キーをデコード（バイト列の場合）
                    if isinstance(key, bytes):
                        decoded_key = key.decode("shift_jis", errors="replace")
                    else:
                        decoded_key = key

                    # 値のリストをデコード
                    decoded_values = []
                    for value in value_list:
                        if isinstance(value, bytes):
                            decoded_values.append(value.decode("shift_jis", errors="replace"))
                        else:
                            decoded_values.append(value)

                    result[decoded_key] = decoded_values

                # 変数に正しく格納
                result_value = result.get("result", [""])[0] if result.get("result") else ""
                sid = result.get("sid", [""])[0] if result.get("sid") else ""
                error_message = result.get("error_message", [None])[0] if result.get("error_message") else None

                logger.info(f"CREDIX result: {result_value}")
                logger.info(f"CREDIX sid: {sid}")
                if error_message:
                    logger.error(f"CREDIX error message: {error_message}")

                return {
                    "result": result_value,
                    "sid": sid,
                    "error_message": error_message,
                }

        except httpx.HTTPStatusError as e:
            logger.error(f"CREDIX API HTTP error: {e}")
            raise
        except httpx.TimeoutException:
            logger.error("CREDIX API timeout")
            raise
        except Exception as e:
            logger.error(f"CREDIX API error: {e}")
            raise


    def get_payment_url(self) -> str:
        """
        決済画面URLを取得（初回決済・リピーター決済共通）

        Returns:
            決済画面URL
        """
        return f"{self.base_url}{settings.CREDIX_ORDER_ENDPOINT}"


# シングルトンインスタンス
credix_client = CredixClient()
