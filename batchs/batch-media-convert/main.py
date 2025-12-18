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

EXTINF_RE = re.compile(r"^#EXTINF:([0-9.]+),\s*$")


# -----------------------------
# small utils
# -----------------------------
def run(cmd: List[str], capture: bool = False) -> subprocess.CompletedProcess:
    if capture:
        return subprocess.run(
            cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    return subprocess.run(cmd, check=True)


def guess_content_type(path: str) -> str:
    ct, _ = mimetypes.guess_type(path)
    return ct or "application/octet-stream"


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


# -----------------------------
# ffprobe helpers
# -----------------------------
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


def ffprobe_video_info(path: str) -> tuple[int, int, int]:
    """
    Return (w,h,rotate) in "display orientation".
    If rotate is 90/270, swap w/h.
    """
    cp = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:stream_tags=rotate",
            "-of",
            "json",
            path,
        ],
        capture=True,
    )
    st = json.loads(cp.stdout)["streams"][0]
    w = int(st["width"])
    h = int(st["height"])
    rotate = int(st.get("tags", {}).get("rotate", "0") or 0) % 360
    if rotate in (90, 270):
        w, h = h, w
    return w, h, rotate


def ffprobe_fps(path: str) -> float:
    cp = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate",
            "-of",
            "json",
            path,
        ],
        capture=True,
    )
    st = json.loads(cp.stdout)["streams"][0]
    fr = st.get("avg_frame_rate", "0/1")
    try:
        num, den = fr.split("/")
        den_f = float(den)
        return float(num) / den_f if den_f != 0 else 0.0
    except Exception:
        return 0.0


def ffprobe_h264_profile_level(path: str) -> tuple[str, float]:
    cp = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=profile,level",
            "-of",
            "json",
            path,
        ],
        capture=True,
    )
    st = json.loads(cp.stdout)["streams"][0]
    profile = (st.get("profile") or "").strip()
    level_raw = st.get("level", 0)  # 30, 40, 42...
    try:
        level = float(level_raw) / 10.0
    except Exception:
        level = 0.0
    return profile, level


def avc1_from_profile_level(profile: str, level: float) -> str:
    """
    MediaConvert-like avc1 string (good enough for most hls.js use).
    High -> 0x64, Main -> 0x4D, else -> 0x42.
    constraint flags -> 0.
    """
    p = profile.lower()
    if "high" in p:
        profile_idc = 0x64
    elif "main" in p:
        profile_idc = 0x4D
    else:
        profile_idc = 0x42

    constraints = 0x00
    level_idc = int(round(level * 10))
    level_idc = max(0, min(level_idc, 255))
    return f"avc1.{profile_idc:02x}{constraints:02x}{level_idc:02x}"


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


# -----------------------------
# HLS playlist helpers
# -----------------------------
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


def write_master_m3u8_mediaconvert_like(
    out_dir: str, rid: str, variants: List[dict]
) -> str:
    p = os.path.join(out_dir, f"{rid}.m3u8")
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-INDEPENDENT-SEGMENTS",
    ]
    for v in variants:
        lines.append(
            "#EXT-X-STREAM-INF:"
            f"BANDWIDTH={v['bandwidth']},"
            f"AVERAGE-BANDWIDTH={v['avg_bandwidth']},"
            f'CODECS="{v["codecs"]}",'
            f"RESOLUTION={v['w']}x{v['h']},"
            f"FRAME-RATE={v['fps']:.3f}"
        )
        lines.append(f"{rid}_{v['label']}.m3u8")
    lines.append("")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return p


# -----------------------------
# rendition policy (MediaConvert-ish)
# -----------------------------
def pick_renditions(
    in_w: int, in_h: int
) -> List[Tuple[str, int, int, int, int, int, str]]:
    """
    Return list of (label, target_w, target_h, maxrate_k, buf_k, crf, a_br)
    NOTE: target_w/target_h here are "nominal" targets used for scaling rules.
    - landscape: we lock HEIGHT, width auto (-2)
    - portrait: lock WIDTH, height auto (-2)
    """
    is_portrait = in_h > in_w

    if is_portrait:
        r = [
            ("480p", 480, 854, 1200, 2400, 23, "96k"),
            ("720p", 720, 1280, 2500, 5000, 21, "128k"),
            ("1080p", 1080, 1920, 4500, 9000, 20, "128k"),
        ]
        if in_h >= 3840:
            r.append(("2160p", 2160, 3840, 12000, 24000, 18, "192k"))
        return r

    r = [
        ("480p", 854, 480, 1200, 2400, 23, "96k"),
        ("720p", 1280, 720, 2500, 5000, 21, "128k"),
        ("1080p", 1920, 1080, 4500, 9000, 20, "128k"),
    ]
    if in_h >= 2160:
        r.append(("2160p", 3840, 2160, 12000, 24000, 18, "192k"))
    return r


# -----------------------------
# encode (key point: NO PAD, width/height auto to preserve AR)
# -----------------------------
def build_ffmpeg_cmd(
    input_path: str,
    out_dir: str,
    rid: str,
    encode_run_id: str,
    renditions: List[Tuple[str, int, int, int, int, int, str]],
    is_portrait: bool,
) -> List[str]:
    n = len(renditions)
    split_tags = [f"v{i}" for i in range(n)]
    out_tags = [f"v{i}o" for i in range(n)]

    fc = f"[0:v]split={n}" + "".join([f"[{t}]" for t in split_tags]) + ";"
    parts = []

    # MediaConvert-like: preserve aspect ratio, do NOT pad into a fixed canvas.
    for i, (_label, tw, th, *_rest) in enumerate(renditions):
        if is_portrait:
            # lock width (tw), height auto
            scale = f"scale=w={tw}:h=-2:flags=fast_bilinear"
        else:
            # lock height (th), width auto
            scale = f"scale=w=-2:h={th}:flags=fast_bilinear"

        parts.append(f"[{split_tags[i]}]{scale},setsar=1[{out_tags[i]}]")

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

    common_v = [
        "-c:v",
        "libx264",
        "-preset",
        "superfast",
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

    common_a = [
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-ar",
        "48000",
    ]

    # let ffmpeg use CPU cores; do NOT cap threads here
    for i, (label, _tw, _th, maxrate_k, buf_k, crf, a_br) in enumerate(renditions):
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


def first_segment_path(
    out_dir: str, rid: str, label: str, encode_run_id: str
) -> Optional[str]:
    seg_glob = os.path.join(out_dir, f"{rid}_{label}{encode_run_id}__*.ts")
    segs = sorted(glob.glob(seg_glob))
    return segs[0] if segs else None


def first_segment_wh(
    out_dir: str, rid: str, label: str, encode_run_id: str
) -> tuple[int, int]:
    seg0 = first_segment_path(out_dir, rid, label, encode_run_id)
    if not seg0:
        return (0, 0)
    return ffprobe_video_wh(seg0)


def send_webhook(*, url: str, secret: str, detail: dict) -> None:
    if not url:
        return
    r = requests.post(
        url, json={"detail": detail}, headers={"x-hook-secret": secret}, timeout=20
    )
    r.raise_for_status()


# -----------------------------
# main
# -----------------------------
def main() -> None:
    INPUT_BUCKET = os.environ.get("INPUT_BUCKET", "mij-ingest-dev")
    INPUT_KEY = os.environ.get("INPUT_KEY", "post-media/0d3c6214-977a-456e-b93b-2e953da114b5/sample/fb996f20-cf91-4d28-a190-3b4653f54356/267d03be-71f2-48f4-be34-8f8a35df066a.mp4")
    OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "mij-media-dev")
    OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "transcode-mc/0d3c6214-977a-456e-b93b-2e953da114b5/fb996f20-cf91-4d28-a190-3b4653f54356/cd729d4a-e9ef-4503-9ea4-61a19e6887aa/hls/")
    KMS_KEY_ARN = os.environ.get("KMS_KEY_ARN", "alias/mij-media-kms-dev")

    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
    WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

    USERMETA = json.loads(os.environ.get("USERMETA_JSON", "{}")) or {}
    RID = USERMETA.get("renditionJobId") or str(uuid.uuid4())
    ENCODE_RUN_ID = os.environ.get("ENCODE_RUN_ID") or str(uuid.uuid4())

    JOB_ID = os.environ.get("JOB_ID") or f"ecs-{int(time.time())}"
    QUEUE_ARN = os.environ.get("QUEUE_ARN") or "arn:aws:ecs:queue/Default"

    base_dir = Path(__file__).parent / "media"
    in_dir = base_dir / "input"
    out_dir = base_dir / "output"
    shutil.rmtree(in_dir, ignore_errors=True)
    shutil.rmtree(out_dir, ignore_errors=True)
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    in_path = in_dir / "input.mp4"

    base_s3 = f"s3://{OUTPUT_BUCKET}/{OUTPUT_PREFIX.strip('/')}"
    try:
        logger.info(f"INPUT_BUCKET={INPUT_BUCKET}")
        logger.info(f"INPUT_KEY={INPUT_KEY}")
        logger.info(f"OUTPUT_BUCKET={OUTPUT_BUCKET}")
        logger.info(f"OUTPUT_PREFIX={OUTPUT_PREFIX}")
        logger.info(f"RID={RID}")

        # 1) download
        s3.download_file(INPUT_BUCKET, INPUT_KEY, str(in_path))

        # 2) probe
        duration_ms = ffprobe_duration_ms(str(in_path))
        w_disp, h_disp, _rot = ffprobe_video_info(str(in_path))
        is_portrait = h_disp > w_disp
        fps = ffprobe_fps(str(in_path))
        if fps <= 0:
            fps = 25.0

        renditions = pick_renditions(w_disp, h_disp)

        # 3) encode
        cmd = build_ffmpeg_cmd(
            input_path=str(in_path),
            out_dir=str(out_dir),
            rid=RID,
            encode_run_id=ENCODE_RUN_ID,
            renditions=renditions,
            is_portrait=is_portrait,
        )
        run(cmd)

        # 4) rewrite media playlists (integer EXTINF like MediaConvert)
        for label, *_rest in renditions:
            pl = os.path.join(str(out_dir), f"{RID}_{label}.m3u8")
            items = parse_hls_items(pl)
            write_mediaconvert_like_media_playlist(pl, items)

        # 5) master playlist (MediaConvert-like fields)
        variants = []
        for label, _tw, _th, maxrate_k, _buf_k, _crf, a_br in renditions:
            audio_bps = 128_000 if a_br == "128k" else 96_000

            # RESOLUTION should reflect real encoded dims (like MediaConvert shows 1440x1080 etc.)
            w_real, h_real = first_segment_wh(str(out_dir), RID, label, ENCODE_RUN_ID)

            # BANDWIDTH ~ MaxBitrate + audio (close enough)
            bw = int(maxrate_k * 1000 + audio_bps)

            # AVERAGE-BANDWIDTH ~ avg video + audio
            avg_video = avg_bitrate_from_segments(
                str(out_dir), RID, label, ENCODE_RUN_ID, duration_ms
            )
            avg_bw = int(avg_video + audio_bps)

            seg0 = first_segment_path(str(out_dir), RID, label, ENCODE_RUN_ID)
            if seg0:
                prof, lvl = ffprobe_h264_profile_level(seg0)
                avc1 = avc1_from_profile_level(prof, lvl)
            else:
                avc1 = "avc1.640028"

            codecs = f"{avc1},mp4a.40.2"
            variants.append(
                {
                    "label": label,
                    "w": w_real,
                    "h": h_real,
                    "bandwidth": bw,
                    "avg_bandwidth": avg_bw,
                    "codecs": codecs,
                    "fps": float(fps),
                }
            )

        write_master_m3u8_mediaconvert_like(str(out_dir), RID, variants)

        # 6) upload
        upload_dir_sse_kms(str(out_dir), OUTPUT_BUCKET, OUTPUT_PREFIX, KMS_KEY_ARN)

        # 7) webhook detail
        output_details = []
        for v in variants:
            output_details.append(
                {
                    "outputFilePaths": [
                        f"{base_s3}/{RID}_{v['label']}.m3u8",
                    ],
                    "durationInMs": duration_ms,
                    "videoDetails": {
                        "widthInPx": v["w"],
                        "heightInPx": v["h"],
                        "averageBitrate": int(v["avg_bandwidth"]),
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
