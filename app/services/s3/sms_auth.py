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

APP_ENV = os.getenv("APP_ENV")

def send_sms(phone: str, message: str) -> None:
    try:
        if APP_ENV == "dev":
            phone = "+819070098590"
            print(f"[LOCAL SMS] to={phone} body={message}")
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
        raise HTTPException(status_code=500, detail=str(e))