import os
from time import time
import boto3
import subprocess
from pathlib import Path
from common.constants import (
    AWS_REGION,
    AWS_ACCESS,
    AWS_SECRET,
    END_TIME,
    MAIN_VIDEO_BUCKET,
    MAIN_VIDEO_DESTINATION,
    NEED_TRIM,
    START_TIME,
    TEMP_VIDEO_BUCKET,
    TEMP_VIDEO_DESTINATION,
    SAMPLE_VIDEO_BUCKET,
    SAMPLE_VIDEO_DESTINATION,
)
from common.logger import Logger


class BatchMainSampleVideo(Path):
    TEMP_VIDEO_PATH: str = f"{Path(__file__).parent}/temp"

    def __init__(self, logger: Logger):
        self.logger = logger
        self.s3_client = boto3.client(
            "s3",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS,
            aws_secret_access_key=AWS_SECRET,
        )

    def _exec(self):
        self.logger.info(f"TEMP_VIDEO_BUCKET: {TEMP_VIDEO_BUCKET}")
        self.logger.info(f"TEMP_VIDEO_DESTINATION: {TEMP_VIDEO_DESTINATION}")
        self.logger.info(f"SAMPLE_VIDEO_BUCKET: {SAMPLE_VIDEO_BUCKET}")
        self.logger.info(f"SAMPLE_VIDEO_DESTINATION: {SAMPLE_VIDEO_DESTINATION}")
        self.logger.info(f"MAIN_VIDEO_BUCKET: {MAIN_VIDEO_BUCKET}")
        self.logger.info(f"MAIN_VIDEO_DESTINATION: {MAIN_VIDEO_DESTINATION}")
        self.logger.info(f"NEED_TRIM: {NEED_TRIM}")
        self.logger.info(f"START_TIME: {START_TIME}")
        self.logger.info(f"END_TIME: {END_TIME}")

        video_path = self.__download_temp_video()
        if video_path is None:
            return
        self.logger.info(f"NEED_TRIM: {NEED_TRIM}")
        if NEED_TRIM:  # trim sample video
            sample_video_path = self.__cut_video(video_path)
            if sample_video_path is None:
                return
            sample_upload_done = self.__upload_sample_video(
                SAMPLE_VIDEO_BUCKET, SAMPLE_VIDEO_DESTINATION
            )
            if sample_upload_done:
                self.logger.info(
                    f"Sample video upload success to {SAMPLE_VIDEO_BUCKET}/{SAMPLE_VIDEO_DESTINATION}"
                )
            else:
                self.logger.error(
                    f"Sample video upload failed to {SAMPLE_VIDEO_BUCKET}/{SAMPLE_VIDEO_DESTINATION}"
                )
        main_upload_done = self.__upload_main_video(
            MAIN_VIDEO_BUCKET, MAIN_VIDEO_DESTINATION, video_path
        )
        if main_upload_done:
            self.logger.info(
                f"Main video upload success to {MAIN_VIDEO_BUCKET}/{MAIN_VIDEO_DESTINATION}"
            )
        else:
            self.logger.error(
                f"Main video upload failed to {MAIN_VIDEO_BUCKET}/{MAIN_VIDEO_DESTINATION}"
            )
        return

    def __cut_video(self, video_path: str) -> str:
        try:
            self.logger.info(
                f"Cut video from {START_TIME} to {END_TIME} duration {END_TIME - START_TIME} {video_path}"
            )
            cmd = [
                "ffmpeg",
                "-i",
                video_path,
                "-ss",
                str(START_TIME),
                "-t",
                str(END_TIME - START_TIME),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-y",
                f"{BatchMainSampleVideo.TEMP_VIDEO_PATH}/sample_video.mp4",
            ]
            subprocess.run(cmd, check=True)
            return f"{BatchMainSampleVideo.TEMP_VIDEO_PATH}/sample_video.mp4"
        except Exception as e:
            self.logger.error(e)
            return None

    def __download_temp_video(self) -> str:
        try:
            if not os.path.exists(BatchMainSampleVideo.TEMP_VIDEO_PATH):
                os.makedirs(BatchMainSampleVideo.TEMP_VIDEO_PATH, exist_ok=True)

            self.s3_client.download_file(
                TEMP_VIDEO_BUCKET,
                TEMP_VIDEO_DESTINATION,
                f"{BatchMainSampleVideo.TEMP_VIDEO_PATH}/temp_video.mp4",
            )
            return f"{BatchMainSampleVideo.TEMP_VIDEO_PATH}/temp_video.mp4"
        except Exception as e:
            self.logger.error(e)
            return None

    def __upload_sample_video(self, bucket: str, destination: str) -> bool:
        try:
            is_upload = True
            while is_upload:
                self.s3_client.upload_file(
                    f"{BatchMainSampleVideo.TEMP_VIDEO_PATH}/sample_video.mp4",
                    bucket,
                    destination,
                    ExtraArgs={
                        # "SSEKMSKeyId": KMS_ARN,
                        "ServerSideEncryption": "aws:kms",
                    },
                )
                exists = self.__s3_key_exists(bucket, destination)
                if exists:
                    is_upload = False
                time.sleep(0.5)
            return True
        except Exception as e:
            self.logger.error(e)
            return False

    def __upload_main_video(
        self, bucket: str, destination: str, video_path: str
    ) -> bool:
        try:
            is_upload = True
            while is_upload:
                self.s3_client.upload_file(
                    video_path,
                    bucket,
                    destination,
                    ExtraArgs={
                        # "SSEKMSKeyId": KMS_ARN,
                        "ServerSideEncryption": "aws:kms",
                    },
                )
                exists = self.__s3_key_exists(bucket, destination)
                if exists:
                    is_upload = False
                time.sleep(0.5)
            return True
        except Exception as e:
            self.logger.error(e)
            return False

    def __s3_key_exists(self, bucket: str, key: str) -> bool:
        try:
            self.s3_client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception as e:
            self.logger.error(e)
            return False
