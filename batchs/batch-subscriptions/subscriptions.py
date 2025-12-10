import os
import time
import requests
from threading import Thread
from datetime import datetime, timezone
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
from common.db_session import get_db
from common.logger import Logger
from models.subscriptions import Subscriptions
from models.user_providers import UserProviders
from models.payments import Payments
from models.payment_transactions import PaymentTransactions
from slack_sdk import WebClient
from common.constants import ENV


class SubscriptionsDomain:
    def __init__(self, logger: Logger):
        # self.db: Session = next(get_db())
        self.logger = logger
        self.thread_pool = []
        self.slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN", ""))
        self.slack_channel = os.environ.get("SLACK_CHANNEL", "C0A0YDFF5PS")

    def _exec(self):
        db: Session = next(get_db())
        subscriptions = self._query_inday_need_to_pay_subscriptions(db)
        if not subscriptions:
            self.logger.info("No subscriptions found")
            return
        for subscription in subscriptions:
            thread = Thread(
                target=self._task_process_subscription, args=(subscription,)
            )
            thread.start()
            self.thread_pool.append(thread)

        for thread in self.thread_pool:
            thread.join()

        return

    def _query_inday_need_to_pay_subscriptions(self, db: Session):
        now = datetime.now(timezone.utc)
        return (
            db.query(Subscriptions, UserProviders, Payments)
            .join(
                UserProviders,
                and_(
                    Subscriptions.user_id == UserProviders.user_id,
                    UserProviders.is_main_card == True,
                ),
            )
            .join(Payments, Subscriptions.payment_id == Payments.id)
            .filter(
                and_(
                    func.date(Subscriptions.next_billing_date) == now.date(),
                    Subscriptions.access_type == 1,
                )
            )
            .all()
        )

    def _task_process_subscription(self, subscription: tuple):
        db: Session = next(get_db())
        done = False
        need_change_status = None
        try:
            while not done:
                try:
                    subs: Subscriptions = subscription[0]
                    user_provider: UserProviders = subscription[1]
                    payment: Payments = subscription[2]

                    if subs.status == 2:
                        self.__mark_subscription_as_cancelled(db, subs)
                        self.logger.info(f"Subscription {subs.id} marked as cancelled")
                    elif subs.status == 1:
                        self.__process_next_subscription(db, subs, user_provider, payment)
                        need_change_status = subs.id
                    done = True
                except Exception as e:
                    db.rollback()
                    self.logger.exception(f"Error processing subscription: {e}")
                    self.__slack_error_notification(str(subscription[0].user_id))
                    time.sleep(60)

            if need_change_status:
                self.__change_status_of_subscription(db, need_change_status)
        finally:
            db.close()

    def __slack_error_notification(self, user_id: str):
        self.slack_client.chat_postMessage(
            channel=self.slack_channel,
            text=f"Error processing subscription: {user_id}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"<!channel>\n [{ENV}] Error processing subscription userID: {user_id}",
                    },
                }
            ],
        )

    def __mark_subscription_as_cancelled(self, db: Session, subscription: Subscriptions):
        now = datetime.now(timezone.utc)
        subs = (
            db.query(Subscriptions)
            .filter(Subscriptions.id == subscription.id)
            .first()
        )
        if not subs:
            self.logger.error(f"Subscription {subscription.id} not found")
            return
        subs.status = 3
        # subs.canceled_at = now
        subs.updated_at = now
        db.add(subs)
        db.commit()
        return

    def __process_next_subscription(
        self,
        db: Session,
        subscription: Subscriptions,
        user_provider: UserProviders,
        payment: Payments,
    ):
        now = datetime.now(timezone.utc)
        txn = PaymentTransactions(
            type=2,
            status=1,
            provider_id=subscription.provider_id,
            order_id=subscription.order_id,
            user_id=subscription.user_id,
            session_id=f"{subscription.user_id}-batch-subscriptions-{int(now.timestamp())}",
            created_at=now,
            updated_at=now,
        )
        db.add(txn)
        db.commit()

        payload_to_credix = {
            "clientip": os.environ.get("CREDIX_CLIENT_IP", "1011004877"),
            "send": "cardsv",
            "cardnumber": "9999999999999992",
            "expyy": "00",
            "expmm": "00",
            "money": payment.payment_amount,
            "telno": "0000000000",
            "sendid": str(user_provider.sendid),
            "sendpoint": str(f"B_{txn.id}"),
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        self.logger.info(f"Payload to Credix: {payload_to_credix}")
        response = requests.post(
            os.environ.get(
                "CREDIX_API_URL", "https://secure.credix-web.co.jp/cgi-bin/secure.cgi"
            ),
            data=payload_to_credix,
            headers=headers,
            timeout=10,
        )
        if response.status_code != 200:
            self.logger.error(f"Error processing subscription: {response.text}")
            raise Exception(f"Error processing subscription: {response.text}")
        res_text = str(response.text)
        if res_text != "Success_order":
            raise Exception(f"Error processing subscription: {res_text}")

    def __change_status_of_subscription(self, db: Session, subscription_id: str):
        now = datetime.now(timezone.utc)
        subs = (
            db.query(Subscriptions)
            .filter(Subscriptions.id == subscription_id)
            .first()
        )
        if not subs:
            self.logger.error(f"Subscription {subscription_id} not found")
            return
        subs.status = 3
        subs.updated_at = now
        db.add(subs)
        db.commit()
        return
