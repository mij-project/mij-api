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
from app.schemas.video_temp import (
    CreateSampleRequest,
    TempVideoMultipartInitResponse,
    SampleVideoResponse,
    TempVideoPartPresignResponse,
    TempVideoMultipartCompleteRequest,
    BulkPartPresignRequest,
    BulkPartPresignResponse,
    PartPresignUrl,
)
import tempfile
import shutil
from app.core.logger import Logger
from app.services.s3.keygen import temp_video_key
from app.services.s3.presign import init_multipart_temp_video, presign_multipart_part_temp_video, complete_multipart_temp_video, presign_get_temp_video
logger = Logger.get_logger()
router = APIRouter()

# 一時ファイル保存ディレクトリ
TEMP_VIDEO_DIR = os.getenv("TEMP_VIDEO_DIR", "/tmp/mij_temp_videos")
os.makedirs(TEMP_VIDEO_DIR, exist_ok=True)


@router.post("/video-temp/temp-upload/main-video", response_model=TempVideoMultipartInitResponse)
async def upload_temp_main_video(
    filename: str = Form(...),
    content_type: str = Form(...),
    user: Users = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """
    本編動画を一時保存バケットにマルチパートアップロードするための
    アップロードID (upload_id) を発行する
    """
    try:
        # ユーザー認証チェック
        if not user:
            raise HTTPException(status_code=401, detail="ログインが必要です")

        # ファイル拡張子を取得
        file_ext = os.path.splitext(filename)[1].lstrip('.') if filename else "mp4"

        # 一時保存ビデオキーを生成
        s3_key = temp_video_key(str(user.id), filename, file_ext)

        # 署名付きPUT URLを生成
        multipart = init_multipart_temp_video("temp-video", s3_key, content_type)

        return TempVideoMultipartInitResponse(
            s3_key=s3_key,
            bucket=multipart["bucket"],
            upload_id=multipart["upload_id"],
            expires_in=multipart["expires_in"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"署名付きURL発行エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/video-temp/temp-upload/main-video/part-presign", response_model=TempVideoPartPresignResponse)
async def presign_temp_main_video_part(
    s3_key: str = Form(...),
    upload_id: str = Form(...),
    part_number: int = Form(...),
    user: Users = Depends(get_current_user_optional),
):
    """
    マルチパートアップロード用: 各パートの署名付きURLを発行
    """
    try:
        if not user:
            raise HTTPException(status_code=401, detail="ログインが必要です")

        presign = presign_multipart_part_temp_video(
            resource="temp-video",
            key=s3_key,
            upload_id=upload_id,
            part_number=part_number,
        )

        return TempVideoPartPresignResponse(
            s3_key=s3_key,
            upload_id=upload_id,
            part_number=part_number,
            upload_url=presign["upload_url"],
            expires_in=presign["expires_in"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"マルチパートアップロード用: 各パートの署名付きURL発行エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/video-temp/temp-upload/bulk-part-presign", response_model=BulkPartPresignResponse)
async def bulk_presign_temp_main_video_parts(
    request: BulkPartPresignRequest,
    user: Users = Depends(get_current_user_optional),
):
    """
    マルチパートアップロード用: 複数パートの署名付きURLを一括発行
    並列アップロードを可能にするため、一度に複数のURLを取得
    """
    try:
        if not user:
            raise HTTPException(status_code=401, detail="ログインが必要です")

        # S3キーにユーザーIDが含まれているか確認（セキュリティチェック）
        if not request.s3_key.startswith(f"temp-videos/{user.id}/"):
            raise HTTPException(status_code=403, detail="アクセス権限がありません")

        # パート数の上限チェック（S3の制限: 最大10,000パート）
        if len(request.part_numbers) > 10000:
            raise HTTPException(status_code=400, detail="パート数が上限を超えています（最大10,000）")

        # 有効期限を2時間に設定（大容量ファイル対応）
        expires_in = 7200

        urls: list[PartPresignUrl] = []
        for part_number in request.part_numbers:
            presign = presign_multipart_part_temp_video(
                resource="temp-video",
                key=request.s3_key,
                upload_id=request.upload_id,
                part_number=part_number,
                expires_in=expires_in,
            )
            urls.append(PartPresignUrl(
                part_number=part_number,
                upload_url=presign["upload_url"],
            ))

        return BulkPartPresignResponse(
            s3_key=request.s3_key,
            upload_id=request.upload_id,
            urls=urls,
            expires_in=expires_in,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"一括署名付きURL発行エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/video-temp/playback-url/{s3_key:path}")
async def get_temp_video_playback_url(
    s3_key: str,
    user: Users = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """
    一時保存された動画の再生用署名付きGET URLを取得
    """
    try:
        # ユーザー認証チェック
        if not user:
            raise HTTPException(status_code=401, detail="ログインが必要です")

        # S3キーにユーザーIDが含まれているか確認（セキュリティチェック）
        if not s3_key.startswith(f"temp-videos/{user.id}/"):
            raise HTTPException(status_code=403, detail="アクセス権限がありません")

        # 署名付きGET URLを生成（1時間有効）

        presign_data = presign_get_temp_video(
            "temp-video",
            s3_key,
            expires_in=3600,  # 1時間
            content_type="video/mp4"
        )

        return {
            "playback_url": presign_data["download_url"],
            "expires_in": presign_data["expires_in"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"再生用URL取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/video-temp/temp-upload/main-video/complete")
async def complete_temp_main_video_upload(
    req: TempVideoMultipartCompleteRequest,
    user: Users = Depends(get_current_user_optional),
):
    try:
        if not user:
            raise HTTPException(status_code=401, detail="ログインが必要です")

        resp = complete_multipart_temp_video(
            resource="temp-video",
            key=req.s3_key,
            upload_id=req.upload_id,
            parts=req.parts,
        )
        return resp
    except Exception:
        # 必要であれば abort_multipart_upload を呼ぶ
        raise HTTPException(
            status_code=500,
            detail="マルチパートアップロードの完了に失敗しました",
        )

@router.post("/video-temp/temp-upload/create-sample", response_model=SampleVideoResponse)
async def create_sample_video(
    request: CreateSampleRequest,
    user: Users = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """
    S3の一時保存バケットにある本編動画から指定範囲を切り取ってサンプル動画を生成
    """
    try:
        # ユーザー認証チェック
        if not user:
            raise HTTPException(status_code=401, detail="ログインが必要です")

        # S3キー（temp_video_id）にユーザーIDが含まれているか確認（セキュリティチェック）
        s3_key = request.temp_video_id
        if not s3_key.startswith(f"temp-videos/{user.id}/"):
            raise HTTPException(status_code=403, detail="アクセス権限がありません")

        # バリデーション: 5分以内
        duration = request.end_time - request.start_time
        if duration > 300:  # 5分 = 300秒
            raise HTTPException(status_code=400, detail="サンプル動画は5分以内にしてください")

        if request.start_time < 0 or request.end_time <= request.start_time:
            raise HTTPException(status_code=400, detail="無効な時間範囲です")

        # S3から一時ファイルをダウンロード
        from app.services.s3.client import s3_client, TEMP_VIDEO_BUCKET_NAME
        import tempfile

        s3 = s3_client()

        # 一時ディレクトリに動画をダウンロード
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_input:
            s3.download_file(TEMP_VIDEO_BUCKET_NAME, s3_key, temp_input.name)
            temp_input_path = temp_input.name

        # サンプル動画の一時ファイルパスを生成
        sample_video_id = str(uuid.uuid4())
        temp_output_path = os.path.join(TEMP_VIDEO_DIR, f"{sample_video_id}.mp4")

        try:
            # ffmpegで切り取り
            _cut_video(
                input_path=temp_input_path,
                output_path=temp_output_path,
                start_time=request.start_time,
                end_time=request.end_time
            )

            return SampleVideoResponse(
                sample_video_url=f"/temp-videos/{sample_video_id}.mp4",
                duration=duration
            )
        finally:
            # 入力ファイルを削除
            if os.path.exists(temp_input_path):
                os.remove(temp_input_path)

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
