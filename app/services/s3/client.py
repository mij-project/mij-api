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

def delete_object(bucket: str, key: str):
    client = s3_client()
    client.delete_object(Bucket=bucket, Key=key)

def delete_hls_directory(bucket: str, m3u8_key: str):
    """
    HLS動画の.m3u8ファイルとその関連ファイル（.tsセグメント、プレイリスト等）を削除

    Args:
        bucket (str): S3バケット名
        m3u8_key (str): .m3u8ファイルのキー（例: "path/to/video/playlist.m3u8"）
    """
    client = s3_client()

    # .m3u8ファイルのディレクトリパスを取得
    # 例: "path/to/video/playlist.m3u8" -> "path/to/video/"
    if '/' in m3u8_key:
        directory_prefix = m3u8_key.rsplit('/', 1)[0] + '/'
    else:
        # ルートディレクトリの場合
        directory_prefix = ''

    try:
        # ディレクトリ配下の全オブジェクトをリスト
        paginator = client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket, Prefix=directory_prefix)

        deleted_count = 0
        for page in pages:
            if 'Contents' not in page:
                continue

            # 削除対象のオブジェクトを収集
            objects_to_delete = []
            for obj in page['Contents']:
                key = obj['Key']
                # HLS関連ファイル（.m3u8, .ts, .vtt等）を削除対象に
                if key.endswith(('.m3u8', '.ts', '.vtt', '.jpg', '.png')):
                    objects_to_delete.append({'Key': key})

            # バッチ削除（最大1000件まで一度に削除可能）
            if objects_to_delete:
                response = client.delete_objects(
                    Bucket=bucket,
                    Delete={'Objects': objects_to_delete}
                )
                deleted_count += len(objects_to_delete)
                print(f"Deleted {len(objects_to_delete)} HLS files from {directory_prefix}")

                # 削除エラーがあればログ出力
                if 'Errors' in response:
                    for error in response['Errors']:
                        print(f"Error deleting {error['Key']}: {error['Message']}")

        print(f"Total deleted {deleted_count} HLS-related files")
        return deleted_count

    except Exception as e:
        print(f"Failed to delete HLS directory {directory_prefix}: {e}")
        raise


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