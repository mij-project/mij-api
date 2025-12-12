import os
from slack_sdk import WebClient
from app.core.logger import Logger


class SlackService:
    _client = None
    _logger = Logger.get_logger()
    _instance = None

    def __init__(self):
        # luôn giữ instance
        SlackService._instance = self

        if SlackService._client is None:
            token = os.getenv("SLACK_BOT_TOKEN")
            if not token:
                raise RuntimeError("Missing SLACK_BOT_TOKEN")
            SlackService._client = WebClient(token=token)

    @staticmethod
    def initialize():
        if SlackService._instance is None:
            SlackService()
        return SlackService._instance

    def _alert_identity_verification(self, user_profile_name: str):
        admin_channel = "C0A32MQ0HRC"
        if not admin_channel:
            SlackService._logger.error("Missing SLACK_ADMIN_APPROVALS_ALERTS")
            return

        env = os.getenv('ENV', 'dev')
        if env not in ['dev', 'local']:
            return

        try:
            message = (
                f"環境：[{env}]\n"
                f"<!channel>\n:fire::fire::fire:\n"
                f"ユーザー：{user_profile_name}\n"
                "身分証明書申請きましたぞ！！！"
            )
            SlackService._client.chat_postMessage(channel=admin_channel, text=message)
        except Exception:
            SlackService._logger.exception("Error sending Slack message")

    def _alert_profile_verification(self, user_profile_name: str, image_type: int):
        admin_channel = os.getenv("SLACK_ADMIN_APPROVALS_ALERTS")
        if not admin_channel:
            SlackService._logger.error("Missing SLACK_ADMIN_APPROVALS_ALERTS")
            return

        env = os.getenv('ENV', 'dev')
        if env not in ['dev', 'local']:
            return

        try:
            if image_type == 1:
                kind = "プロフィールAvatar"
            elif image_type == 2:
                kind = "プロフィールCover"
            else:
                kind = f"プロフィール(type={image_type})"

            message = (
                f"環境：[{env}]\n"
                f"<!channel>\n:fire::fire::fire:\n"
                f"ユーザー：{user_profile_name}\n"
                f"{kind}申請きましたぞ！！！"
            )
            SlackService._client.chat_postMessage(channel=admin_channel, text=message)
        except Exception:
            SlackService._logger.exception("Error sending Slack message")

    def _alert_post_creation(self, user_profile_name: str):
        admin_channel = os.getenv("SLACK_ADMIN_APPROVALS_ALERTS")
        if not admin_channel:
            SlackService._logger.error("Missing SLACK_ADMIN_APPROVALS_ALERTS")
            return

        env = os.getenv('ENV', 'dev')
        if env not in ['dev', 'local']:
            return

        try:
            message = (
                f"環境：[{env}]\n"
                f"<!channel>\n:fire::fire::fire:\n"
                f"ユーザー：{user_profile_name}\n"
                "投稿申請がきましたぞ！！！"
            )
            SlackService._client.chat_postMessage(channel=admin_channel, text=message)
        except Exception:
            SlackService._logger.exception("Error sending Slack message")

    def _alert_post_update(self, user_profile_name: str):
        admin_channel = os.getenv("SLACK_ADMIN_APPROVALS_ALERTS")
        if not admin_channel:
            SlackService._logger.error("Missing SLACK_ADMIN_APPROVALS_ALERTS")
            return
        
        env = os.getenv('ENV', 'dev')
        if env not in ['dev', 'local']:
            return

        try:
            message = (
                f"環境：[{env}]\n"
                f"<!channel>\n:fire::fire::fire:\n"
                f"ユーザー：{user_profile_name}\n"
                "投稿再申請がきましたぞ！！！"
            )
            SlackService._client.chat_postMessage(channel=admin_channel, text=message)
        except Exception:
            SlackService._logger.exception("Error sending Slack message")

    def _alert_withdrawal_request(self, user_profile_name: str):
        admin_channel = "C0A34P4SAAE"
        if not admin_channel:
            SlackService._logger.error("Missing SLACK_ADMIN_APPROVALS_ALERTS")
            return

        env = os.getenv('ENV', 'dev')
        if env not in ['dev', 'local']:
            return

        try:
            message = (
                f"環境：[{env}]\n"
                f"<!channel>\n:money_with_wings::money_with_wings::money_with_wings:\n"
                f"ユーザー：{user_profile_name}\n"
                "出金申請がきましたぞ！！！"
            )
            SlackService._client.chat_postMessage(channel=admin_channel, text=message)
        except Exception:
            SlackService._logger.exception("Error sending Slack message")