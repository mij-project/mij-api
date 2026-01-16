import os
import boto3
import subprocess
from pathlib import Path
from uuid import UUID

from PIL import Image

from models.message_assets import MessageAssets
from common.logger import Logger
from common.db_session import get_db
from sqlalchemy.orm import Session
from common.constants import DATABASE_URL


class GenerateMessageAssetsThumbnail:
    def __init__(self, logger: Logger):
        self.db: Session = next(get_db())
        self.logger = logger

        self.bucket = os.environ.get("BUCKET", "mij-message-assets-dev")

        # You are passing storage_key here (string). We'll support both UUID and storage_key.
        self.message_assets_id = os.environ.get(
            "MESSAGE_ASSETS_ID",
            "b84514f8-cad5-4df4-8911-19f6444db25d",
        )

        self.s3 = boto3.client("s3", region_name="ap-northeast-1")

        # KMS Key ID or Alias (both OK)
        # examples:
        # - "alias/mij-message-assets-kms-dev"
        # - "arn:aws:kms:ap-northeast-1:123456789012:key/...."
        self.encryption_key = os.environ.get("ENCRYPTION_KEY", "alias/stg-mij-message-assets-kms")

        self.local_temp_dir = Path(__file__).parent / "temp"
        self.local_temp_dir.mkdir(parents=True, exist_ok=True)

        self.thumbnail_filename = "thumbnail.jpg"
        self.thumbnail_content_type = "image/jpeg"
        self.max_long_edge = 640

    def exec(self):
        self.logger.info("Start generating message assets thumbnail")
        self.logger.info(f"Bucket: {self.bucket}")
        self.logger.info(f"Message assets id: {self.message_assets_id}")
        self.logger.info(f"KMS key: {self.encryption_key}")
        self.logger.info(f"DB URL: {DATABASE_URL}")
        message_assets = self.__get_message_assets()
        if not message_assets:
            self.logger.error(f"Message assets not found: {self.message_assets_id}")
            return

        asset_type = message_assets.asset_type
        storage_key = message_assets.storage_key

        # 1) download original
        local_src = self.__download_s3_to_file(storage_key)

        # 2) generate thumbnail
        local_thumb = self.local_temp_dir / f"thumb_{message_assets.id}.jpg"
        if asset_type == 1:
            self.__generate_image_thumbnail(local_src, local_thumb)
        elif asset_type == 2:
            self.__generate_video_thumbnail(local_src, local_thumb)
        else:
            self.logger.error(f"Invalid asset type: {asset_type}")
            return

        # 3) upload thumbnail (same folder) with KMS encryption
        thumb_key = self.__build_thumbnail_key(storage_key)
        self.__upload_file_to_s3_with_kms(local_thumb, thumb_key)

        # 4) update DB
        message_assets.thumbnail_storage_key = thumb_key
        self.db.add(message_assets)
        self.db.commit()

        self.logger.info(f"Uploaded thumbnail: s3://{self.bucket}/{thumb_key}")

    def __get_message_assets(self):
        # Try UUID
        try:
            asset_uuid = UUID(self.message_assets_id)
            return (
                self.db.query(MessageAssets)
                .filter(MessageAssets.id == asset_uuid)
                .first()
            )
        except Exception as e:
            self.logger.error(f"Error getting message assets: {e}")
            return None

    def __download_s3_to_file(self, storage_key: str) -> str:
        local_path = self.local_temp_dir / Path(storage_key).name

        self.logger.info(f"Downloading: s3://{self.bucket}/{storage_key} -> {local_path}")
        self.s3.download_file(self.bucket, storage_key, str(local_path))
        return str(local_path)

    def __build_thumbnail_key(self, storage_key: str) -> str:
        parent = str(Path(storage_key).parent).replace("\\", "/")
        return f"{parent}/{self.thumbnail_filename}"

    def __upload_file_to_s3_with_kms(self, local_path: Path, storage_key: str):
        extra_args = {
            "ContentType": self.thumbnail_content_type,
            "CacheControl": "public, max-age=31536000, immutable",
            # KMS encryption:
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": self.encryption_key,
        }

        self.logger.info(f"Uploading (KMS): {local_path} -> s3://{self.bucket}/{storage_key}")
        self.s3.upload_file(
            str(local_path),
            self.bucket,
            storage_key,
            ExtraArgs=extra_args,
        )

    def __generate_image_thumbnail(self, src_path: str, out_path: Path):
        with Image.open(src_path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            w, h = img.size
            long_edge = max(w, h)
            if long_edge > self.max_long_edge:
                if w >= h:
                    new_w = self.max_long_edge
                    new_h = int(h * self.max_long_edge / w)
                else:
                    new_h = self.max_long_edge
                    new_w = int(w * self.max_long_edge / h)
                img = img.resize((new_w, new_h), Image.LANCZOS)

            img.save(str(out_path), format="JPEG", quality=82, optimize=True, progressive=True)

    def __generate_video_thumbnail(self, src_path: str, out_path: Path):
        # Needs ffmpeg in runtime
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", "1.0",
            "-i", src_path,
            "-frames:v", "1",
            "-vf", f"scale='if(gt(iw,ih),{self.max_long_edge},-2)':'if(gt(ih,iw),{self.max_long_edge},-2)'",
            "-q:v", "2",
            str(out_path),
        ]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
