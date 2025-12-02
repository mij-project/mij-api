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
        success_str: Optional[str] = None,
        failure_str: Optional[str] = None,
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
            "success_str": success_str,
            "failure_str": failure_str,
            "success_url": success_url,
            "failure_url": failure_url,
        }

        # オプションパラメータ
        if search_type == 1:
            params["telno"] = telno

        if use_seccode:
            params["use_seccode"] = "yes"

        if send_email:
            params["send_email"] = "yes"

        if sendpoint:
            params["sendpoint"] = sendpoint

        logger.info(f"CREDIX session request: {url}")
        logger.info(f"CREDIX params: money={money}, sendid={sendid}, search_type={search_type}")

        # API呼び出し
        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                response = await client.post(url, data=params)
                response.raise_for_status()

                # レスポンスの bytes を取得
                response_bytes = response.content

                # ★ bytes のまま parse_qs に渡す & encoding="shift_jis" を指定
                result = parse_qs(response_bytes, encoding="shift_jis", errors="replace")

                logger.info(
                    "CREDIX session raw: %s",
                    response_bytes.decode("shift_jis", errors="replace")
                )
                logger.info(f"CREDIX session response (parsed): {result}")

                error_message = result.get("error_message", [None])[0]
                if "error_message" in result:
                    error_message = result["error_message"][0]
                    logger.info(f"CREDIX error message: {error_message}")

                return {
                    "result": result.get("result", [""])[0],
                    "sid": result.get("sid", [""])[0],
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


    async def first_payment(
        self, 
        sendid: str, 
        money: int, 
        telno: str | None = None, 
        email: str | None = None, 
        sendpoint: int = 2, 
        success_str: Optional[str] = None,
        failure_str: Optional[str] = None,
        success_url: Optional[str] = None,
        failure_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """初回決済

        Args:
            sendid: カードID
            money: 決済金額
            telno: 電話番号
            email: メールアドレス
            sendpoint: フリーパラメータ
            success_str: 決済完了メッセージ
            failure_str: 決済失敗メッセージ
            success_url: 決済完了後のリダイレクトURL
            failure_url: 決済失敗後のリダイレクトURL
        """
        url = f"{self.base_url}{settings.CREDIX_ORDER_ENDPOINT}"
        params = {
            "clientip": self.client_ip,
            "zkey": self.zkey,
            "money": money,
            "sendid": sendid,
            "sendpoint": sendpoint,
            "success_str": success_str,
            "failure_str": failure_str,
            "success_url": success_url,
            "failure_url": failure_url,
        }

        logger.info(f"CREDIX first payment request: {url}")
        logger.info(f"CREDIX first payment params: money={money}, sendid={sendid}, sendpoint={sendpoint}")

        # API呼び出し
        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                response = await client.post(url, data=params)
                response.raise_for_status()

                # レスポンスの bytes を取得
                response_bytes = response.content

                # ★ bytes のまま parse_qs に渡す & encoding="shift_jis" を指定
                result = parse_qs(response_bytes, encoding="shift_jis", errors="replace")

                logger.info(
                    "CREDIX session raw: %s",
                    response_bytes.decode("shift_jis", errors="replace")
                )
                logger.info(f"CREDIX first payment response (parsed): {result}")

                error_message = result.get("error_message", [None])[0]
                if "error_message" in result:
                    error_message = result["error_message"][0]
                    logger.info(f"CREDIX error message: {error_message}")

                return {
                    "result": result.get("result", [""])[0],
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
