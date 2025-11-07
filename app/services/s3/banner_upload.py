import os
import uuid
import io
from typing import Tuple

from fastapi import UploadFile, HTTPException
from botocore.exceptions import ClientError
from PIL import Image, ImageOps

from app.services.s3.client import s3_client, BANNER_BUCKET_NAME, BANNER_IMAGE_URL

# 許可する画像形式
ALLOWED_CONTENT_TYPES = [
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif"
]

# 最大ファイルサイズ (5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024

# 圧縮設定
JPEG_QUALITY = 85
WEBP_QUALITY = 80


def validate_banner_image(file: UploadFile) -> None:
    """
    バナー画像のバリデーション

    Args:
        file: アップロードファイル

    Raises:
        HTTPException: バリデーションエラー
    """
    # Content-Typeチェック
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"許可されていないファイル形式です。許可形式: {', '.join(ALLOWED_CONTENT_TYPES)}"
        )


def get_file_extension(content_type: str) -> str:
    """
    Content-Typeから拡張子を取得

    Args:
        content_type: Content-Type

    Returns:
        str: 拡張子
    """
    ext_map = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif"
    }
    return ext_map.get(content_type, "jpg")


def compress_image(contents: bytes, content_type: str) -> Tuple[bytes, str]:
    """
    画像を圧縮し、必要に応じてContent-Typeを更新

    Args:
        contents: 画像のバイト列
        content_type: 元のContent-Type

    Returns:
        Tuple[bytes, str]: (圧縮後のバイト列, Content-Type)
    """
    # GIFはアニメーション対応などの理由からそのまま扱う
    if content_type == "image/gif":
        return contents, content_type

    try:
        image = Image.open(io.BytesIO(contents))
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="画像の読み込みに失敗しました。ファイルが壊れているか未対応の形式です。"
        )

    image = ImageOps.exif_transpose(image)

    buffer = io.BytesIO()

    if content_type == "image/jpeg":
        # JPEGは再圧縮する
        image = image.convert("RGB")
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        return buffer.getvalue(), "image/jpeg"

    if content_type == "image/png":
        # PNGはWebPに変換して容量削減
        if image.mode not in ("RGBA", "LA"):
            image = image.convert("RGB")
        image.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=6)
        return buffer.getvalue(), "image/webp"

    if content_type == "image/webp":
        # WebPは再圧縮
        if image.mode not in ("RGB", "RGBA", "LA"):
            image = image.convert("RGB")
        image.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=6)
        return buffer.getvalue(), "image/webp"

    # その他の形式はJPEGとして扱う
    image = image.convert("RGB")
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return buffer.getvalue(), "image/jpeg"


async def upload_banner_image(file: UploadFile) -> Tuple[str, str]:
    """
    バナー画像をS3にアップロード

    Args:
        file: アップロードファイル

    Returns:
        Tuple[str, str]: (S3キー, 画像URL)

    Raises:
        HTTPException: アップロードエラー
    """
    # バリデーション
    validate_banner_image(file)

    contents = await file.read()

    # 画像圧縮
    contents, content_type = compress_image(contents, file.content_type)

    # ファイルサイズチェック（圧縮後）
    file_size = len(contents)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"圧縮後のファイルサイズが大きすぎます。最大サイズ: {MAX_FILE_SIZE / 1024 / 1024}MB"
        )

    # S3キーを生成
    ext = get_file_extension(content_type)
    file_uuid = str(uuid.uuid4())
    s3_key = f"banners/{file_uuid}.{ext}"

    try:
        # S3クライアント取得
        client = s3_client()

        # S3にアップロード
        client.put_object(
            Bucket=BANNER_BUCKET_NAME,
            Key=s3_key,
            Body=contents,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )

        image_url = f"{BANNER_IMAGE_URL}/{s3_key}"

        return s3_key, image_url

    except ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"S3アップロードに失敗しました: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"予期しないエラーが発生しました: {str(e)}"
        )


def delete_banner_image(image_key: str) -> bool:
    """
    S3からバナー画像を削除

    Args:
        image_key: S3キー

    Returns:
        bool: 成功フラグ
    """
    try:
        client = s3_client()
        client.delete_object(
            Bucket=BANNER_BUCKET_NAME,
            Key=image_key
        )
        return True
    except Exception as e:
        print(f"Failed to delete banner image {image_key}: {e}")
        return False
