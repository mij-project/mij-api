"""
一時動画アップロード・サンプル動画切り取りAPI
"""
import os
import uuid
import subprocess
from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_user_optional
from app.models.user import Users
from typing import Optional
from pydantic import BaseModel
from app.schemas.video_temp import CreateSampleRequest, TempVideoResponse, SampleVideoResponse
import tempfile
import shutil

router = APIRouter()

# 一時ファイル保存ディレクトリ
TEMP_VIDEO_DIR = os.getenv("TEMP_VIDEO_DIR", "/tmp/mij_temp_videos")
os.makedirs(TEMP_VIDEO_DIR, exist_ok=True)


@router.post("/temp-upload/main-video", response_model=TempVideoResponse)
async def upload_temp_main_video(
    file: UploadFile = File(...),
    user: Users = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """
    本編動画を一時ストレージにアップロード
    """
    try:
        # 一時IDを生成
        temp_video_id = str(uuid.uuid4())

        # ファイル拡張子を取得
        file_ext = os.path.splitext(file.filename)[1] if file.filename else ".mp4"

        # 保存パス
        temp_file_path = os.path.join(TEMP_VIDEO_DIR, f"{temp_video_id}{file_ext}")

        # ファイルを保存
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 動画の長さを取得（ffprobeを使用）
        duration = _get_video_duration(temp_file_path)

        return TempVideoResponse(
            temp_video_id=temp_video_id,
            temp_video_url=f"/temp-videos/{temp_video_id}{file_ext}",
            duration=duration
        )

    except Exception as e:
        print(f"一時動画アップロードエラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/temp-upload/create-sample", response_model=SampleVideoResponse)
async def create_sample_video(
    request: CreateSampleRequest,
    user: Users = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """
    一時保存された本編動画から指定範囲を切り取ってサンプル動画を生成
    """
    try:
        # 本編動画のパスを探索
        temp_video_path = _find_temp_video_file(request.temp_video_id)

        if not temp_video_path:
            raise HTTPException(status_code=404, detail="一時動画が見つかりません")

        # バリデーション: 5分以内
        duration = request.end_time - request.start_time
        if duration > 300:  # 5分 = 300秒
            raise HTTPException(status_code=400, detail="サンプル動画は5分以内にしてください")

        if request.start_time < 0 or request.end_time <= request.start_time:
            raise HTTPException(status_code=400, detail="無効な時間範囲です")

        # サンプル動画ID生成
        sample_video_id = str(uuid.uuid4())
        sample_file_path = os.path.join(TEMP_VIDEO_DIR, f"{sample_video_id}.mp4")

        # ffmpegで切り取り
        _cut_video(
            input_path=temp_video_path,
            output_path=sample_file_path,
            start_time=request.start_time,
            end_time=request.end_time
        )

        return SampleVideoResponse(
            sample_video_url=f"/temp-videos/{sample_video_id}.mp4",
            duration=duration
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"サンプル動画生成エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _find_temp_video_file(temp_video_id: str) -> Optional[str]:
    """
    一時動画ファイルを拡張子なしのIDから探索
    """
    for ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
        file_path = os.path.join(TEMP_VIDEO_DIR, f"{temp_video_id}{ext}")
        if os.path.exists(file_path):
            return file_path
    return None


def _get_video_duration(video_path: str) -> Optional[float]:
    """
    ffprobeを使用して動画の長さを取得
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        print(f"動画の長さ取得エラー: {e}")
        return None


def _cut_video(input_path: str, output_path: str, start_time: float, end_time: float):
    """
    ffmpegを使用して動画を切り取る
    """
    try:
        duration = end_time - start_time

        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-ss", str(start_time),
            "-t", str(duration),
            "-c:v", "libx264",       # H.264エンコード
            "-c:a", "aac",           # AACオーディオ
            "-preset", "fast",       # 高速エンコード
            "-crf", "23",            # 品質設定
            "-y",                    # 上書き許可
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        if result.returncode != 0:
            raise Exception(f"ffmpegエラー: {result.stderr}")

    except subprocess.CalledProcessError as e:
        print(f"動画切り取りエラー: {e.stderr}")
        raise Exception(f"動画の切り取りに失敗しました: {e.stderr}")
    except Exception as e:
        print(f"動画切り取りエラー: {e}")
        raise Exception(f"動画の切り取りに失敗しました: {str(e)}")
