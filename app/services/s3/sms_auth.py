import os
from fastapi import HTTPException
from app.services.s3.client import (
    sms_client, 
    SNS_SENDER_ID,
    SNS_SMS_TYPE,
    SMS_TTL,
    RESEND_COOLDOWN,
    MAX_ATTEMPTS,
)
from app.core.logger import Logger
logger = Logger.get_logger()
APP_ENV = os.getenv("APP_ENV")

def send_sms(phone: str, message: str) -> None:
    try:
        logger.info(f"[SMS] APP_ENV: {APP_ENV}")
        if APP_ENV == "dev":
            phone = "+819070098590"
            logger.info(f"[LOCAL SMS] to={phone} body={message}")
            return
        
        sns_client = sms_client()
        sns_client.publish(
            PhoneNumber=phone,
            Message=message,
            MessageAttributes={
                "AWS.SNS.SMS.SMSType": {"DataType":"String","StringValue":SNS_SMS_TYPE},
                "AWS.SNS.SMS.SenderID": {"DataType":"String","StringValue":SNS_SENDER_ID}
        },
    )
    except Exception as e:
        logger.error(f"[SMS] send_sms error: {e}")
        raise HTTPException(status_code=500, detail=str(e))