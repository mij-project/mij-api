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
        telno: str | None = None,
        email: str | None = None,
        search_type: int = 2,
        use_seccode: bool = True,
        send_email: bool = True,
        sendpoint: Optional[str] = None,
        # success_str: Optional[str] = None,
        # failure_str: Optional[str] = None,
        success_url: Optional[str] = None,
        failure_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        CREDIXセッション発行API呼び出し

        Args:
            sendid: カードID（初回決済の場合は新規生成、リピーター決済の場合は既存のもの）
            money: 決済金額
            telno: 電話番号
            email: メールアドレス
            search_type: 会員検索条件（1=clientip+telno+sendid, 2=clientip+sendid）
            use_seccode: セキュリティコード入力要否
            send_email: メール送信フラグ
            sendpoint: フリーパラメータ
            success_str: 決済完了メッセージ
            failure_str: 決済失敗メッセージ
            redirect_url: 決済完了後のリダイレクトURL
            failure_url: 決済失敗後のリダイレクトURL
        Returns:
            セッション発行レスポンス
            {
                "result": "ok" | "ng",
                "sid": "セッションID",
                "error_message": "エラーメッセージ"  # resultが"ng"の場合のみ
            }
        """
        url = f"{self.base_url}{settings.CREDIX_SESSION_ENDPOINT}"

        # パラメータ構築
        params = {
            "clientip": self.client_ip,
            "zkey": self.zkey,
            "money": money,
            "search_type": search_type,
            "sendid": sendid,
            "redirect_type": 2,
            "success_url": success_url,
            "failure_url": failure_url,
        }

        # オプションパラメータ
        if search_type == 1:
            params["telno"] = telno

        if use_seccode:
            params["use_seccode"] = "yes"

        if sendpoint:
            params["sendpoint"] = sendpoint

        logger.info(f"CREDIX session request🔥🔥🔥: {url}")
        logger.info(f"CREDIX params: money={money}, sendid={sendid}, search_type={search_type}")

        # API呼び出し
        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                response = await client.post(url, data=params)
                response.raise_for_status()

                # レスポンスの bytes を取得
                response_bytes = response.content

                # ★ bytes のまま parse_qs に渡す & encoding="shift_jis" を指定
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

                logger.info(f"CREDIX result🔥🔥🔥: {result_value}")
                logger.info(f"CREDIX sid🔥🔥🔥: {sid}")
                logger.info(f"CREDIX error message🔥🔥🔥: {error_message}")

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
        決済画面URLを取得

        Returns:
            決済画面URL
        """
        return f"{self.base_url}{settings.CREDIX_ORDER_ENDPOINT}"


# シングルトンインスタンス
credix_client = CredixClient()
