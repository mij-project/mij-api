"""
一時動画アップロード・サンプル動画切り取りAPI
"""
import os
import uuid
import subprocess
import time
from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_user_optional
from app.models.user import Users
from typing import Optional
from pydantic import BaseModel
from app.schemas.video_temp import CreateSampleRequest, TempVideoResponse, SampleVideoResponse
import tempfile
import shutil
from app.core.logger import Logger
logger = Logger.get_logger()
router = APIRouter()

# 一時ファイル保存ディレクトリ
TEMP_VIDEO_DIR = os.getenv("TEMP_VIDEO_DIR", "/tmp/mij_temp_videos")
os.makedirs(TEMP_VIDEO_DIR, exist_ok=True)


@router.post("/video-temp/temp-upload/main-video", response_model=TempVideoResponse)
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
        logger.error(f"一時動画アップロードエラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/video-temp/temp-upload/create-sample", response_model=SampleVideoResponse)
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
        logger.error(f"サンプル動画生成エラー: {e}")
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
        # ファイルの存在確認
        if not os.path.exists(video_path):
            logger.error(f"動画ファイルが見つかりません: {video_path}")
            return None

        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]

        logger.info(f"ffprobeコマンド: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            logger.error(f"ffprobeエラー (return code: {result.returncode}): {result.stderr}")
            return None

        duration = float(result.stdout.strip())
        logger.info(f"動画の長さ: {duration}秒")
        return duration
    except Exception as e:
        logger.error(f"動画の長さ取得エラー: {e}")
        return None


def _cut_video(input_path: str, output_path: str, start_time: float, end_time: float):
    """
    ffmpegを使用して動画を切り取る
    """
    try:
        duration = end_time - start_time

        # 入力ファイルの存在確認
        if not os.path.exists(input_path):
            raise Exception(f"入力ファイルが見つかりません: {input_path}")

        # 出力ディレクトリの存在確認と作成
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        logger.info(f"動画切り取り開始: {input_path} -> {output_path}")
        logger.info(f"開始時間: {start_time}秒, 終了時間: {end_time}秒, 長さ: {duration}秒")

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

        logger.info(f"ffmpegコマンド: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        # 標準出力と標準エラーを出力（デバッグ用）
        if result.stdout:
            logger.info(f"ffmpeg stdout: {result.stdout[-500:]}")  # 最後の500文字のみ
        if result.stderr:
            logger.error(f"ffmpeg stderr: {result.stderr[-500:]}")  # 最後の500文字のみ

        if result.returncode != 0:
            raise Exception(f"ffmpegエラー (return code: {result.returncode}): {result.stderr[-500:]}")

        # 出力ファイルの存在確認
        if not os.path.exists(output_path):
            raise Exception(f"出力ファイルが生成されませんでした: {output_path}")

        logger.info(f"動画切り取り完了: {output_path} (サイズ: {os.path.getsize(output_path)} bytes)")

    except subprocess.CalledProcessError as e:
        logger.error(f"動画切り取りエラー (CalledProcessError): {e.stderr}")
        raise Exception(f"動画の切り取りに失敗しました: {e.stderr[-500:]}")
    except Exception as e:
        logger.error(f"動画切り取りエラー: {e}")
        raise Exception(f"動画の切り取りに失敗しました: {str(e)}")


@router.delete("/video-temp/cleanup/{temp_video_id}")
async def cleanup_temp_files(
    temp_video_id: str,
    user: Users = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """
    一時ファイルを削除（投稿完了後のクリーンアップ用）
    """
    try:
        deleted_files = []

        # 本編動画の削除
        main_video_path = _find_temp_video_file(temp_video_id)
        if main_video_path and os.path.exists(main_video_path):
            os.remove(main_video_path)
            deleted_files.append(os.path.basename(main_video_path))
            logger.info(f"本編動画を削除: {main_video_path}")

        # サンプル動画の削除（temp_video_idから生成された全てのmp4ファイル）
        # 注: サンプル動画IDは別途生成されるため、パターンマッチングで探索
        for file in os.listdir(TEMP_VIDEO_DIR):
            file_path = os.path.join(TEMP_VIDEO_DIR, file)
            # UUIDパターンにマッチするファイルを削除対象とする
            if os.path.isfile(file_path) and file.endswith('.mp4'):
                # ファイル名がUUIDパターンの場合のみ削除（安全性のため）
                try:
                    uuid.UUID(os.path.splitext(file)[0])
                    # 作成時刻が古いファイル（1時間以上前）のみ削除
                    if os.path.getctime(file_path) < (time.time() - 3600):
                        os.remove(file_path)
                        deleted_files.append(file)
                        logger.info(f"古いサンプル動画を削除: {file_path}")
                except ValueError:
                    # UUIDでない場合はスキップ
                    pass

        return {
            "message": "一時ファイルを削除しました",
            "deleted_files": deleted_files
        }

    except Exception as e:
        logger.error(f"一時ファイル削除エラー: {e}")
        # エラーが発生してもクライアント側の処理は継続させる（削除失敗は致命的ではない）
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/temp-videos/{filename:path}")
async def serve_temp_video(filename: str, request: Request):
    """
    一時動画ファイルを配信する（Range Request対応）

    Args:
        filename: ファイル名（拡張子含む）
        request: HTTPリクエスト

    Returns:
        StreamingResponse: 動画ファイル（Range Request対応）
    """
    try:
        # ファイルパスを構築
        file_path = os.path.join(TEMP_VIDEO_DIR, filename)

        # セキュリティ: パストラバーサル攻撃を防ぐ
        normalized_path = os.path.normpath(file_path)
        if not normalized_path.startswith(os.path.normpath(TEMP_VIDEO_DIR)):
            raise HTTPException(status_code=403, detail="アクセスが拒否されました")

        # ファイルが存在するか確認
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="ファイルが見つかりません")

        # ファイルが通常のファイルであることを確認
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=400, detail="無効なファイルです")

        # MIMEタイプを拡張子から判定
        ext = os.path.splitext(filename)[1].lower()
        media_type_mapping = {
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
            ".mkv": "video/x-matroska",
            ".webm": "video/webm",
        }
        media_type = media_type_mapping.get(ext, "application/octet-stream")

        # ファイルサイズを取得
        file_size = os.path.getsize(file_path)

        # Range Requestの処理
        range_header = request.headers.get("range")

        if range_header:
            try:
                # Range: bytes=start-end の形式をパース
                range_match = range_header.replace("bytes=", "").strip().split("-")
                start = int(range_match[0]) if range_match[0] else 0
                end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1

                # endがfile_sizeを超える場合は調整
                end = min(end, file_size - 1)

                # 範囲の検証
                if start < 0 or start >= file_size or end < start:
                    raise HTTPException(status_code=416, detail="範囲が不正です")

                chunk_size = end - start + 1

                async def file_iterator():
                    with open(file_path, "rb") as f:
                        f.seek(start)
                        remaining = chunk_size
                        while remaining > 0:
                            read_size = min(65536, remaining)  # 64KBずつ読み込み
                            chunk = f.read(read_size)
                            if not chunk:
                                break
                            remaining -= len(chunk)
                            yield chunk

                headers = {
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(chunk_size),
                }

                return StreamingResponse(
                    file_iterator(),
                    status_code=206,
                    headers=headers,
                    media_type=media_type
                )
            except ValueError as e:
                logger.error(f"Range header parse error: {e}, header: {range_header}")
                # Range headerのパースに失敗した場合は全体を返す
                pass

        # 通常のレスポンス（Range headerなし、またはパース失敗時）
        async def file_iterator():
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)  # 64KBずつ読み込み
                    if not chunk:
                        break
                    yield chunk

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        }

        return StreamingResponse(
            file_iterator(),
            headers=headers,
            media_type=media_type
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"一時動画配信エラー: {e}")
        raise HTTPException(status_code=500, detail="動画の配信に失敗しました")
