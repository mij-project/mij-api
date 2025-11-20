# app/services/s3/presign.py
from typing import Literal, Optional, Union, List
from .client import (
    s3_client, 
    INGEST_BUCKET,
    KMS_ALIAS_INGEST,
    ASSETS_BUCKET_NAME,
    KYC_BUCKET_NAME,
    KMS_ALIAS_KYC, 
    MEDIA_BUCKET_NAME,
    KMS_ALIAS_MEDIA,
    TEMP_VIDEO_BUCKET_NAME,
)
from app.schemas.video_temp import CompletedPart

Resource = Literal["ingest", "identity", "public", "media", "temp-video"]

def _bucket_and_kms(resource: Resource):
    if resource == "ingest":
        return INGEST_BUCKET, KMS_ALIAS_INGEST
    elif resource == "identity":
        return KYC_BUCKET_NAME, KMS_ALIAS_KYC
    elif resource == "public":
        return ASSETS_BUCKET_NAME
    elif resource == "media":
        return MEDIA_BUCKET_NAME, KMS_ALIAS_MEDIA
    elif resource == "temp-video":
        return TEMP_VIDEO_BUCKET_NAME
    raise ValueError("unknown resource")

def presign_put(
    resource: Resource,
    key: str,
    content_type: str,
    expires_in: int = 300
) -> dict:
    """
    Presign upload

    Args:
        resource (Resource): リソース
        key (str): キー
        content_type (str): コンテントタイプ
        expires_in (int): 有効期限

    Returns:
        dict: プレシグネットURL
    """
    bucket, kms_alias = _bucket_and_kms(resource)
    client = s3_client()
    params = {
        "Bucket": bucket,
        "Key": key,
        "ContentType": content_type,
    }
    required_headers = {
        "Content-Type": content_type,
    }

    # SSE-KMS を明示する場合（デフォルト暗号化を設定しているなら省略可）
    params["ServerSideEncryption"] = "aws:kms"
    params["SSEKMSKeyId"] = kms_alias
    required_headers["x-amz-server-side-encryption"] = "aws:kms"
    required_headers["x-amz-server-side-encryption-aws-kms-key-id"] = kms_alias

    url = client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )
    return {
        "key": key,
        "upload_url": url,
        "expires_in": expires_in,
        "required_headers": required_headers,
    }

def presign_get(
    resource: Resource,
    key: str,
    expires_in: int = 43200,
    filename: str | None = None,
    inline: bool = True,
    content_type: str | None = None,
) -> dict:
    bucket, _alias = _bucket_and_kms(resource)
    client = s3_client()

    params = {"Bucket": bucket, "Key": key}

    # ブラウザ表示/再生を安定させたい場合は指定（S3に正しいContent-Typeが付いていれば省略可）
    if content_type:
        params["ResponseContentType"] = content_type

    if filename:
        dispo = "inline" if inline else "attachment"
        params["ResponseContentDisposition"] = f'{dispo}; filename="{filename}"'

    url = client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_in
    )
    return {"download_url": url, "expires_in": expires_in}

def presign_put_public(
    resource: Resource,
    key: str,
    content_type: str,
    expires_in: int = 300,
) -> dict:
    """
    Public object upload (no KMS). Objects will be served via CloudFront OAC.
    Make sure the S3 bucket has default encryption = SSE-S3 (AES256).
    """
    bucket = _bucket_and_kms(resource)
    client = s3_client()

    cache_control = "public, max-age=31536000, immutable"

    params = {
        "Bucket": bucket,
        "Key": key,
        "ContentType": content_type,
        "CacheControl": cache_control,
    }

    required_headers = {
        "Content-Type": content_type,
        "Cache-Control": cache_control,
    }

    url = client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )

    return {
        "key": key,
        "upload_url": url,
        "expires_in": expires_in,
        "required_headers": required_headers,
    }


def init_multipart_temp_video(
    resource: Resource,
    key: str,
    content_type: str,
    expires_in: int = 5400,  # 5400秒 = 1時間30分
) -> dict:
    """
    一時動画用のマルチパートアップロードを初期化し、
    upload_id を返すヘルパー
    """
    bucket = _bucket_and_kms(resource)
    client = s3_client()

    # マルチパートアップロード開始
    resp = client.create_multipart_upload(
        Bucket=bucket,
        Key=key,
        ContentType=content_type,  # ここはお好みで。要らなければ外してOK
    )

    upload_id = resp["UploadId"]

    return {
        "bucket": bucket,
        "key": key,
        "upload_id": upload_id,
        "expires_in": expires_in,
    }


def presign_multipart_part_temp_video(
    resource: Resource,
    key: str,
    upload_id: str,
    part_number: int,
    expires_in: int = 5400,
) -> dict:
    """
    マルチパートアップロード用の署名付きPUT URLを生成（upload_part 用）
    """
    bucket = _bucket_and_kms(resource)
    client = s3_client()

    params = {
        "Bucket": bucket,
        "Key": key,
        "UploadId": upload_id,
        "PartNumber": part_number,
    }

    url = client.generate_presigned_url(
        ClientMethod="upload_part",
        Params=params,
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )

    return {
        "key": key,
        "upload_id": upload_id,
        "part_number": part_number,
        "upload_url": url,
        "expires_in": expires_in,
    }


def presign_get_temp_video(
    resource: Resource,
    key: str,
    expires_in: int = 3600,
    content_type: str | None = None,
) -> dict:
    """
    一時動画用の署名付きGET URLを生成

    Args:
        resource: リソース名（"temp-video"を想定）
        key: S3オブジェクトキー
        expires_in: 有効期限（秒）
        content_type: コンテンツタイプ（オプション）

    Returns:
        dict: 署名付きURLと有効期限
    """
    bucket = _bucket_and_kms(resource)
    client = s3_client()

    params = {"Bucket": bucket, "Key": key}

    # ブラウザでの再生用にContent-Typeを指定
    if content_type:
        params["ResponseContentType"] = content_type

    # インライン表示（ダウンロードではなくブラウザで再生）
    params["ResponseContentDisposition"] = "inline"

    url = client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_in
    )

    return {
        "download_url": url,
        "expires_in": expires_in
    }


def complete_multipart_temp_video(
    resource: Union[Resource, str],
    key: str,
    upload_id: str,
    parts: List[CompletedPart],
) -> dict:
    """
    マルチパートアップロードを完了する
    """
    bucket = _bucket_and_kms(resource)
    client = s3_client()

    # PartNumber の昇順に並び替え（S3は昇順を要求）
    multipart_parts = [
        {"PartNumber": p.part_number, "ETag": p.etag}
        for p in sorted(parts, key=lambda x: x.part_number)
    ]

    resp = client.complete_multipart_upload(
        Bucket=bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": multipart_parts},
    )

    # 返却用の情報をまとめる（必要に応じてフィールド追加・削除OK）
    return {
        "bucket": bucket,
        "s3_key": key,
        "upload_id": upload_id,
        "location": resp.get("Location"),
        "version_id": resp.get("VersionId"),
        "etag": resp.get("ETag"),
    }

def multipart_create(resource: Resource, key: str, content_type: str) -> dict:
    bucket, kms_alias = _bucket_and_kms(resource)
    client = s3_client()
    resp = client.create_multipart_upload(
        Bucket=bucket,
        Key=key,
        ContentType=content_type,
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=kms_alias,
    )
    return {"upload_id": resp["UploadId"]}

def multipart_sign_part(resource: Resource, key: str, upload_id: str, part_number: int, expires_in: int = 3600) -> str:
    bucket, _ = _bucket_and_kms(resource)
    client = s3_client()
    url = client.generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": bucket,
            "Key": key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=expires_in,
    )
    return url

def multipart_complete(resource: Resource, key: str, upload_id: str, parts: list[dict]) -> dict:
    """
    parts: [{"ETag": "...","PartNumber": 1}, ...]
    """
    bucket, _ = _bucket_and_kms(resource)
    client = s3_client()
    client.complete_multipart_upload(
        Bucket=bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )
    return {"ok": True}

def get_bucket_name(resource: Resource) -> str:
    """
    リソース名からバケット名を取得

    Args:
        resource (Resource): リソース名

    Returns:
        str: バケット名
    """
    result = _bucket_and_kms(resource)
    if isinstance(result, tuple):
        return result[0]
    return result

def delete_object(resource: Resource, key: str):
    """
    S3オブジェクトを削除

    Args:
        resource (Resource): リソース名
        key (str): S3オブジェクトキー
    """
    bucket = get_bucket_name(resource)
    client = s3_client()
    client.delete_object(Bucket=bucket, Key=key)