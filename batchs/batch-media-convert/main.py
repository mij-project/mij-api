import json
import os
import pathlib
import re
import shutil
import subprocess
import boto3
import requests
import time
import uuid
import glob
import mimetypes
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from common.logger import Logger

s3 = boto3.client("s3")
logger = Logger.get_logger()


# ---------- small utils ----------
def run(cmd: List[str], capture: bool = False) -> subprocess.CompletedProcess:
    if capture:
        return subprocess.run(
            cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    return subprocess.run(cmd, check=True)


def guess_content_type(path: str) -> str:
    ct, _ = mimetypes.guess_type(path)
    return ct or "application/octet-stream"


def ffprobe_duration_ms(path: str) -> int:
    cp = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            path,
        ],
        capture=True,
    )
    dur = float(json.loads(cp.stdout)["format"]["duration"])
    return int(dur * 1000)


def ffprobe_video_wh(path: str) -> tuple[int, int]:
    cp = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            path,
        ],
        capture=True,
    )
    st = json.loads(cp.stdout)["streams"][0]
    return int(st["width"]), int(st["height"])


def upload_dir_sse_kms(
    local_dir: str, bucket: str, prefix: str, kms_key_arn: str
) -> None:
    base = pathlib.Path(local_dir)
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(base).as_posix()
        key = f"{prefix.rstrip('/')}/{rel}"
        s3.upload_file(
            str(p),
            bucket,
            key,
            ExtraArgs={
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": kms_key_arn,
                "ContentType": guess_content_type(str(p)),
            },
        )


# ---------- playlist rewrite (integer EXTINF like MediaConvert) ----------
EXTINF_RE = re.compile(r"^#EXTINF:([0-9.]+),\s*$")


def parse_hls_items(m3u8_path: str) -> List[Tuple[float, str]]:
    items: List[Tuple[float, str]] = []
    cur: Optional[float] = None
    with open(m3u8_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = EXTINF_RE.match(line)
            if m:
                cur = float(m.group(1))
                continue
            if line.startswith("#"):
                continue
            if cur is None:
                continue
            items.append((cur, line))
            cur = None
    return items


def write_mediaconvert_like_media_playlist(
    out_path: str, items: List[Tuple[float, str]]
) -> None:
    rounded = [(int(round(d)), uri) for d, uri in items]
    target = max([d for d, _ in rounded], default=6)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{target}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]
    for d, uri in rounded:
        lines.append(f"#EXTINF:{d},")
        lines.append(uri)
    lines.append("#EXT-X-ENDLIST")
    lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_master_m3u8(
    out_dir: str, rid: str, variants: List[Tuple[str, int, int, int]]
) -> str:
    # variants: (label,w,h,bandwidth)
    p = os.path.join(out_dir, f"{rid}.m3u8")
    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for label, w, h, bw in variants:
        lines.append(f"#EXT-X-STREAM-INF:BANDWIDTH={bw},RESOLUTION={w}x{h}")
        lines.append(f"{rid}_{label}.m3u8")
    lines.append("")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return p


# ---------- loudness csv (MediaConvert-like schema) ----------
def run_loudness_series(input_path: str, out_txt: str, apply_loudnorm: bool) -> None:
    # ebur128 metadata -> ametadata print lavfi.r128.I to file
    af = f"ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.I:file={out_txt}"
    if apply_loudnorm:
        af = "loudnorm=I=-23," + af

    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-nostats",
            "-i",
            input_path,
            "-vn",
            "-af",
            af,
            "-f",
            "null",
            "-",
        ]
    )


def parse_ametadata_series(txt_path: str) -> Dict[int, float]:
    # Map second(1-based) -> integrated loudness value
    pts_time: Optional[float] = None
    series: Dict[int, float] = {}

    with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if "pts_time:" in line:
                m = re.search(r"pts_time:([0-9.]+)", line)
                if m:
                    pts_time = float(m.group(1))
                continue
            if line.startswith("lavfi.r128.I=") and pts_time is not None:
                val = float(line.split("=", 1)[1])
                sec = int(pts_time) + 1
                series[sec] = val
    return series


def write_loudness_csv(
    csv_path: str, input_series: Dict[int, float], output_series: Dict[int, float]
) -> None:
    max_sec = max([*input_series.keys(), *output_series.keys()], default=1)
    lines = ["Seconds,Dialnorm,InputIntegratedLoudness,OutputIntegratedLoudness"]
    for s in range(1, max_sec + 1):
        in_i = input_series.get(
            s, list(input_series.values())[-1] if input_series else 0.0
        )
        out_i = output_series.get(
            s, list(output_series.values())[-1] if output_series else -23.0
        )
        lines.append(f"{s},0,{in_i:.6f},{out_i:.6f}")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------- ffmpeg encode (single dir, mediaconvert-like naming) ----------
def build_ffmpeg_cmd(
    input_path: str,
    out_dir: str,
    rid: str,
    encode_run_id: str,
    renditions: List[
        Tuple[str, int, int, int, int, int, str]
    ],  # label,w,h,maxrate_k,buf_k,crf,a_br
) -> List[str]:
    n = len(renditions)
    split_tags = [f"v{i}" for i in range(n)]
    out_tags = [f"v{i}o" for i in range(n)]

    fc = f"[0:v]split={n}" + "".join([f"[{t}]" for t in split_tags]) + ";"
    parts = []
    for i, (_label, w, h, *_rest) in enumerate(renditions):
        parts.append(
            f"[{split_tags[i]}]"
            f"scale=w={w}:h={h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1"
            f"[{out_tags[i]}]"
        )
    filter_complex = fc + ";".join(parts)

    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        input_path,
        "-filter_complex",
        filter_complex,
    ]

    # gần “MediaConvert feel”: cố định keyframe theo 6s, GOP ~2s (tương đương gopsize=2s trong job bạn)
    common_v = [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-profile:v",
        "high",
        "-bf",
        "2",
        "-sc_threshold",
        "0",
        "-g",
        "48",
        "-keyint_min",
        "48",
        "-force_key_frames",
        "expr:gte(t,n_forced*6)",
    ]
    # audio normalize gần giống “CORRECT_AUDIO” (không match byte nhưng đủ đồng nhất)
    common_a = [
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-af",
        "loudnorm=I=-23",
    ]

    for i, (label, _w, _h, maxrate_k, buf_k, crf, a_br) in enumerate(renditions):
        pl = os.path.join(out_dir, f"{rid}_{label}.m3u8")
        seg = os.path.join(out_dir, f"{rid}_{label}{encode_run_id}__%05d.ts")
        cmd += [
            "-map",
            f"[{out_tags[i]}]",
            "-map",
            "0:a:0?",
            *common_v,
            "-crf",
            str(crf),
            "-maxrate",
            f"{maxrate_k}k",
            "-bufsize",
            f"{buf_k}k",
            *common_a,
            "-b:a",
            a_br,
            "-f",
            "hls",
            "-hls_time",
            "6",
            "-hls_list_size",
            "0",
            "-hls_playlist_type",
            "vod",
            "-hls_flags",
            "independent_segments+round_durations",
            "-hls_segment_filename",
            seg,
            pl,
        ]
    return cmd


def avg_bitrate_from_segments(
    out_dir: str, rid: str, label: str, encode_run_id: str, duration_ms: int
) -> int:
    prefix = f"{rid}_{label}{encode_run_id}__"
    files = glob.glob(os.path.join(out_dir, f"{prefix}*.ts"))
    total_bytes = sum(os.path.getsize(p) for p in files)
    seconds = max(duration_ms / 1000.0, 0.001)
    return int((total_bytes * 8) / seconds)


def send_webhook(
    *,
    url: str,
    secret: str,
    detail: dict,
) -> None:
    if not url:
        return
    r = requests.post(
        url, json={"detail": detail}, headers={"x-hook-secret": secret}, timeout=20
    )
    r.raise_for_status()


def main() -> None:
    # --- required env ---
    INPUT_BUCKET = os.environ.get("INPUT_BUCKET", "mij-ingest-dev")
    INPUT_KEY = os.environ.get(
        "INPUT_KEY",
        "post-media/8ada4b6e-62d5-4918-b321-6c1432accd9c/main/4306cf4e-b9fe-4021-81a4-1983aa8e8543/44f42430-f878-47af-b331-27226f8eb32b.mp4",
    )

    OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "mij-media-dev")
    OUTPUT_PREFIX = os.environ.get(
        "OUTPUT_PREFIX",
        "transcode-mc/8ada4b6e-62d5-4918-b321-6c1432accd9c/4306cf4e-b9fe-4021-81a4-1983aa8e8543/e0d58381-132f-4800-8dd5-c796192c4c64/test-hls/",
    )

    KMS_KEY_ARN = os.environ.get("KMS_KEY_ARN", "alias/mij-media-kms-dev")

    WEBHOOK_URL = os.environ.get(
        "WEBHOOK_URL", "http://localhost:8000/webhooks/mediaconvert"
    )
    WEBHOOK_SECRET = os.environ.get(
        "WEBHOOK_SECRET",
        "ed4ea5a8087ebe7d2de592c7700056ed8cdaf0feae7116793e0bac09b8ea9cbc",
    )

    USERMETA = json.loads(os.environ.get("USERMETA_JSON", "{}")) or {
        "postId": "4306cf4e-b9fe-4021-81a4-1983aa8e8543",
        "assetId": "60d5d3f7-759f-4a09-aebe-afdd78f88c48",
        "renditionJobId": "2bb778fb-6802-4257-8c3e-e3112b11983c",
        "type": "final-hls",
        "env": "dev",
    }
    RID = USERMETA.get("renditionJobId") or str(uuid.uuid4())

    ENCODE_RUN_ID = os.environ.get("ENCODE_RUN_ID") or str(uuid.uuid4())

    JOB_ID = os.environ.get("JOB_ID") or f"ecs-{int(time.time())}"
    QUEUE_ARN = os.environ.get("QUEUE_ARN") or "arn:aws:ecs:queue/Default"

    media_dir = "media"
    in_path = Path(__file__).parent / media_dir / "input"
    out_dir = Path(__file__).parent / media_dir / "output"
    shutil.rmtree(in_path, ignore_errors=True)
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    renditions = [
        ("360p", 640, 360, 800, 1600, 23, "96k"),
        ("480p", 854, 480, 1200, 2400, 23, "96k"),
        ("720p", 1280, 720, 2500, 5000, 21, "128k"),
        ("1080p", 1920, 1080, 4500, 9000, 20, "128k"),
    ]

    base_s3 = f"s3://{OUTPUT_BUCKET}/{OUTPUT_PREFIX.strip('/')}"
    try:
        # 1) download
        s3.download_file(INPUT_BUCKET, INPUT_KEY, in_path)

        # 2) duration
        duration_ms = ffprobe_duration_ms(in_path)
        in_w, in_h = ffprobe_video_wh(in_path)
        if max(in_w, in_h) >= 3840 and min(in_w, in_h) >= 2160:
            renditions.append(("2160p", 3840, 2160, 12000, 24000, 18, "192k"))
            logger.info(f"Detected 4K input {in_w}x{in_h}, enable 2160p rendition")
        # 3) loudness series (input vs output)
        logs_dir = Path(__file__).parent / "media"
        logs_dir.mkdir(parents=True, exist_ok=True)

        in_txt = str(logs_dir / "loud_in.txt")
        out_txt = str(logs_dir / "loud_out.txt")

        run_loudness_series(in_path, in_txt, apply_loudnorm=False)
        run_loudness_series(in_path, out_txt, apply_loudnorm=True)
        in_series = parse_ametadata_series(in_txt)
        out_series = parse_ametadata_series(out_txt)

        # create loudness csv per rendition (MediaConvert tạo per output)
        for label, *_rest in renditions:
            csv_path = os.path.join(out_dir, f"{RID}_{label}_loudness.csv")
            write_loudness_csv(csv_path, in_series, out_series)

        # 4) encode
        cmd = build_ffmpeg_cmd(in_path, out_dir, RID, ENCODE_RUN_ID, renditions)
        run(cmd)

        # 5) rewrite variant playlists to integer EXTINF/targetduration
        for label, *_rest in renditions:
            pl = os.path.join(out_dir, f"{RID}_{label}.m3u8")
            items = parse_hls_items(pl)
            write_mediaconvert_like_media_playlist(pl, items)

        # 6) master playlist
        # bandwidth roughly = maxrate(video)+audio
        variants = []
        for label, w, h, maxrate_k, _buf_k, _crf, a_br in renditions:
            audio_bps = 128_000 if a_br == "128k" else 96_000
            variants.append((label, w, h, maxrate_k * 1000 + audio_bps))
        write_master_m3u8(out_dir, RID, variants)

        # 7) upload
        upload_dir_sse_kms(out_dir, OUTPUT_BUCKET, OUTPUT_PREFIX, KMS_KEY_ARN)

        # 8) build MediaConvert-like detail + send webhook
        output_details = []
        for label, w, h, _maxrate_k, _buf_k, _crf, _a_br in renditions:
            avg_br = avg_bitrate_from_segments(
                out_dir, RID, label, ENCODE_RUN_ID, duration_ms
            )
            output_details.append(
                {
                    "outputFilePaths": [
                        f"{base_s3}/{RID}_{label}.m3u8",
                        f"{base_s3}/{RID}_{label}_loudness.csv",
                    ],
                    "durationInMs": duration_ms,
                    "videoDetails": {
                        "widthInPx": w,
                        "heightInPx": h,
                        "averageBitrate": avg_br,
                    },
                }
            )

        detail = {
            "timestamp": int(time.time() * 1000),
            "accountId": os.environ.get("AWS_ACCOUNT_ID", ""),
            "queue": QUEUE_ARN,
            "jobId": JOB_ID,
            "status": "COMPLETE",
            "userMetadata": USERMETA,
            "outputGroupDetails": [
                {
                    "type": "HLS_GROUP",
                    "playlistFilePaths": [f"{base_s3}/{RID}.m3u8"],
                    "outputDetails": output_details,
                }
            ],
            "paddingInserted": 0,
            "blackVideoDetected": 0,
            "warnings": [],
        }
        logger.info(detail)
        send_webhook(url=WEBHOOK_URL, secret=WEBHOOK_SECRET, detail=detail)

    except Exception as e:
        logger.error(f"Error: {e}")
        try:
            detail = {
                "timestamp": int(time.time() * 1000),
                "accountId": os.environ.get("AWS_ACCOUNT_ID", ""),
                "queue": QUEUE_ARN,
                "jobId": JOB_ID,
                "status": "ERROR",
                "userMetadata": USERMETA,
                "outputGroupDetails": [],
                "paddingInserted": 0,
                "blackVideoDetected": 0,
                "warnings": [],
                "errorMessage": str(e),
            }
            logger.info(detail)
            send_webhook(url=WEBHOOK_URL, secret=WEBHOOK_SECRET, detail=detail)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
