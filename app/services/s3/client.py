# app/services/s3/client.py
import os
from functools import lru_cache
import boto3
from botocore.config import Config
from typing import Literal
Resource = Literal["identity"]


AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")


def s3_client():
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        endpoint_url=f"https://s3.{AWS_REGION}.amazonaws.com",
        config=Config(signature_version="s3v4")
    )

def _bucket_and_kms(resource: Resource):
    """
    バケットとKMSキーを取得

    Args:
        resource (Resource): リソース
    """
    if resource == "identity":
        return KYC_BUCKET_NAME, KMS_ALIAS_KYC
    raise ValueError("unknown resource")

def bucket_exit_check(resource: Resource, key: str):

    """
    バケット存在確認

    Args:
        resource (Resource): リソース
        key (str): キー
    """
    bucket, _ = _bucket_and_kms(resource)
    client = s3_client()
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception:
        return False
    return True

def sms_client():
    return boto3.client(
        "sns",
        region_name=AWS_REGION,
    )


@lru_cache(maxsize=1)
def s3_client_for_mc():
    base = boto3.client("mediaconvert", region_name=AWS_REGION)
    ep = base.describe_endpoints(MaxResults=1)["Endpoints"][0]["Url"]
    return boto3.client("mediaconvert", region_name=AWS_REGION, endpoint_url=ep)

# 環境セット
ENV = os.environ.get("ENV")

# 身分証明バケット
KYC_BUCKET_NAME = os.environ.get("KYC_BUCKET_NAME")
KMS_ALIAS_KYC   = os.environ.get("KMS_ALIAS_KYC") 

# アカウント
ASSETS_BUCKET_NAME = os.environ.get("ASSETS_BUCKET_NAME")

# ビデオバケット
INGEST_BUCKET = os.environ.get("INGEST_BUCKET_NAME") 
KMS_ALIAS_INGEST   = os.environ.get("KMS_ALIAS_INGEST") 

# メディアコンバート
MEDIA_BUCKET_NAME = os.environ.get("MEDIA_BUCKET_NAME")
KMS_ALIAS_MEDIA = os.environ.get("KMS_ALIAS_MEDIA")

MEDIACONVERT_ROLE_ARN = os.environ.get("MEDIACONVERT_ROLE_ARN")
OUTPUT_COVERT_KMS_ARN = os.environ.get("OUTPUT_KMS_ARN")

# SMS認証
SMS_TTL = int(os.getenv("SMS_CODE_TTL_SECONDS", "300"))
RESEND_COOLDOWN = int(os.getenv("SMS_RESEND_COOLDOWN_SECONDS", "60"))
MAX_ATTEMPTS = int(os.getenv("SMS_MAX_ATTEMPTS", "5"))
SNS_SENDER_ID = os.getenv("SNS_SENDER_ID", "mijfans")
SNS_SMS_TYPE = os.getenv("SNS_SMS_TYPE", "Transactional")