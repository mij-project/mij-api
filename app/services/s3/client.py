# app/services/s3/client.py
import os
from functools import lru_cache
import boto3
from botocore.config import Config
from typing import Literal
from app.core.logger import Logger

logger = Logger.get_logger()
Resource = Literal["identity"]


AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")

# 環境セット
ENV = os.environ.get("ENV")

# 身分証明バケット
KYC_BUCKET_NAME = os.environ.get("KYC_BUCKET_NAME")
KMS_ALIAS_KYC = os.environ.get("KMS_ALIAS_KYC")

# アカウント
ASSETS_BUCKET_NAME = os.environ.get("ASSETS_BUCKET_NAME")

# ビデオバケット
INGEST_BUCKET = os.environ.get("INGEST_BUCKET_NAME")
KMS_ALIAS_INGEST = os.environ.get("KMS_ALIAS_INGEST")

# メディアコンバート
MEDIA_BUCKET_NAME = os.environ.get("MEDIA_BUCKET_NAME")
KMS_ALIAS_MEDIA = os.environ.get("KMS_ALIAS_MEDIA")

# 一時保存バケット
TEMP_VIDEO_BUCKET_NAME = os.environ.get("TMP_VIDEO_BUCKET")

MEDIACONVERT_ROLE_ARN = os.environ.get("MEDIACONVERT_ROLE_ARN")
OUTPUT_COVERT_KMS_ARN = os.environ.get("OUTPUT_KMS_ARN")

# SMS認証
SMS_TTL = int(os.getenv("SMS_CODE_TTL_SECONDS", "300"))
RESEND_COOLDOWN = int(os.getenv("SMS_RESEND_COOLDOWN_SECONDS", "60"))
MAX_ATTEMPTS = int(os.getenv("SMS_MAX_ATTEMPTS", "5"))
SNS_SENDER_ID = os.getenv("SNS_SENDER_ID", "mijfans")
SNS_SMS_TYPE = os.getenv("SNS_SMS_TYPE", "Transactional")

# バナー画像
BANNER_BUCKET_NAME = os.environ.get("BANNER_BUCKET_NAME")
BANNER_IMAGE_URL = os.environ.get("BANNER_IMAGE_URL", "")

# ECS設定
ECS_SUBNETS = (
    os.environ.get("ECS_SUBNETS", "").split(",")
    if os.environ.get("ECS_SUBNETS")
    else []
)
ECS_SECURITY_GROUPS = (
    os.environ.get("ECS_SECURITY_GROUPS", "").split(",")
    if os.environ.get("ECS_SECURITY_GROUPS")
    else []
)
ECS_ASSIGN_PUBLIC_IP = os.environ.get("ECS_ASSIGN_PUBLIC_IP", "ENABLED")


def s3_client(is_use_accelerate_endpoint: bool = False):
    """S3クライアントを取得

    Returns:
        boto3.client: S3クライアント
    """
    if is_use_accelerate_endpoint:
        return boto3.client(
            "s3",
            region_name=AWS_REGION,
            config=Config(
                signature_version="s3v4", s3={"use_accelerate_endpoint": True}
            ),
        )
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        config=Config(signature_version="s3v4"),
    )


def ecs_client():
    return boto3.client(
        "ecs",
        region_name=AWS_REGION,
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
    if "/" in m3u8_key:
        directory_prefix = m3u8_key.rsplit("/", 1)[0] + "/"
    else:
        # ルートディレクトリの場合
        directory_prefix = ""

    try:
        # ディレクトリ配下の全オブジェクトをリスト
        paginator = client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=directory_prefix)

        deleted_count = 0
        for page in pages:
            if "Contents" not in page:
                continue

            # 削除対象のオブジェクトを収集
            objects_to_delete = []
            for obj in page["Contents"]:
                key = obj["Key"]
                # HLS関連ファイル（.m3u8, .ts, .vtt等）を削除対象に
                if key.endswith((".m3u8", ".ts", ".vtt", ".jpg", ".png")):
                    objects_to_delete.append({"Key": key})

            # バッチ削除（最大1000件まで一度に削除可能）
            if objects_to_delete:
                response = client.delete_objects(
                    Bucket=bucket, Delete={"Objects": objects_to_delete}
                )
                deleted_count += len(objects_to_delete)
                logger.info(
                    f"Deleted {len(objects_to_delete)} HLS files from {directory_prefix}"
                )

                # 削除エラーがあればログ出力
                if "Errors" in response:
                    for error in response["Errors"]:
                        logger.error(
                            f"Error deleting {error['Key']}: {error['Message']}"
                        )

        logger.info(f"Total deleted {deleted_count} HLS-related files")
        return deleted_count

    except Exception as e:
        logger.error(f"Failed to delete HLS directory {directory_prefix}: {e}")
        raise


def delete_ffmpeg_directory(bucket: str, storage_key: str):
    """
    storage_keyからffmpeg以降のディレクトリを削除

    Args:
        bucket (str): S3バケット名
        storage_key (str): ストレージキー（例: "transcode-mc/.../ffmpeg/..."）
    """
    client = s3_client()

    # ffmpegディレクトリのパスを取得
    # 例: "transcode-mc/.../ffmpeg/51081f73-..." -> "transcode-mc/.../ffmpeg/"
    if "/ffmpeg/" in storage_key:
        # ffmpeg/の位置を見つけて、その後のパスを削除対象のプレフィックスにする
        ffmpeg_index = storage_key.find("/ffmpeg/")
        directory_prefix = storage_key[: ffmpeg_index + len("/ffmpeg/")]
    else:
        # ffmpegが見つからない場合は何もしない
        logger.info(f"No /ffmpeg/ found in storage_key: {storage_key}")
        return 0

    try:
        # ディレクトリ配下の全オブジェクトをリスト
        paginator = client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=directory_prefix)

        deleted_count = 0
        for page in pages:
            if "Contents" not in page:
                continue

            # 削除対象のオブジェクトを収集
            objects_to_delete = []
            for obj in page["Contents"]:
                key = obj["Key"]
                objects_to_delete.append({"Key": key})

            # バッチ削除（最大1000件まで一度に削除可能）
            if objects_to_delete:
                response = client.delete_objects(
                    Bucket=bucket, Delete={"Objects": objects_to_delete}
                )
                deleted_count += len(objects_to_delete)
                logger.info(
                    f"Deleted {len(objects_to_delete)} files from {directory_prefix}"
                )

                # 削除エラーがあればログ出力
                if "Errors" in response:
                    for error in response["Errors"]:
                        logger.error(
                            f"Error deleting {error['Key']}: {error['Message']}"
                        )

        logger.info(f"Total deleted {deleted_count} files from ffmpeg directory")
        return deleted_count

    except Exception as e:
        logger.error(f"Failed to delete ffmpeg directory {directory_prefix}: {e}")
        raise


def delete_hls_directory_full(bucket: str, storage_key: str):
    """
    storage_keyからhls以降のディレクトリを削除

    Args:
        bucket (str): S3バケット名
        storage_key (str): ストレージキー（例: "transcode-mc/.../hls/..."）
    """
    client = s3_client()

    # hlsディレクトリのパスを取得
    # 例: "transcode-mc/.../hls/2cc79976-....m3u8" -> "transcode-mc/.../hls/"
    if "/hls/" in storage_key:
        # hls/の位置を見つけて、その後のパスを削除対象のプレフィックスにする
        hls_index = storage_key.find("/hls/")
        directory_prefix = storage_key[: hls_index + len("/hls/")]
    else:
        # hlsが見つからない場合は何もしない
        logger.info(f"No /hls/ found in storage_key: {storage_key}")
        return 0

    try:
        # ディレクトリ配下の全オブジェクトをリスト
        paginator = client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=directory_prefix)

        deleted_count = 0
        for page in pages:
            if "Contents" not in page:
                continue

            # 削除対象のオブジェクトを収集
            objects_to_delete = []
            for obj in page["Contents"]:
                key = obj["Key"]
                objects_to_delete.append({"Key": key})

            # バッチ削除（最大1000件まで一度に削除可能）
            if objects_to_delete:
                response = client.delete_objects(
                    Bucket=bucket, Delete={"Objects": objects_to_delete}
                )
                deleted_count += len(objects_to_delete)
                logger.info(
                    f"Deleted {len(objects_to_delete)} files from {directory_prefix}"
                )

                # 削除エラーがあればログ出力
                if "Errors" in response:
                    for error in response["Errors"]:
                        logger.error(
                            f"Error deleting {error['Key']}: {error['Message']}"
                        )

        logger.info(f"Total deleted {deleted_count} files from hls directory")
        return deleted_count

    except Exception as e:
        logger.error(f"Failed to delete hls directory {directory_prefix}: {e}")
        raise


def upload_ogp_image_to_s3(s3_key: str, image_data: bytes) -> str:
    """
    OGP画像をS3（ASSETS_BUCKET_NAME）にアップロード

    Args:
        s3_key: S3キー
        image_data: 画像バイナリデータ

    Returns:
        str: アップロードしたS3キー

    Raises:
        Exception: アップロード失敗時
    """
    try:
        client = s3_client()
        client.put_object(
            Bucket=ASSETS_BUCKET_NAME,
            Key=s3_key,
            Body=image_data,
            ContentType="image/png",
            CacheControl="public, max-age=31536000, immutable",
        )
        print(f"Successfully uploaded OGP image to S3: {ASSETS_BUCKET_NAME}/{s3_key}")
        return s3_key
    except Exception as e:
        print(f"Failed to upload OGP image to S3: {e}")
        raise


@lru_cache(maxsize=1)
def s3_client_for_mc():
    base = boto3.client("mediaconvert", region_name=AWS_REGION)
    ep = base.describe_endpoints(MaxResults=1)["Endpoints"][0]["Url"]
    return boto3.client("mediaconvert", region_name=AWS_REGION, endpoint_url=ep)
