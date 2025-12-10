from fastapi import HTTPException
from PIL import Image, ImageOps
import io
from typing import Dict, Tuple, Optional, List
from app.services.s3.client import KMS_ALIAS_MEDIA
import boto3

REGION = "ap-northeast-1"
S3 = boto3.client("s3", region_name=REGION)
REKOG = boto3.client("rekognition", region_name=REGION)

# ---- helpers ----
def _s3_download_bytes(bucket: str, key: str) -> bytes:
    try:
        obj = S3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as e:
        raise HTTPException(500, f"S3 get_object failed: {e}")

def _s3_put_bytes(bucket: str, key: str, data: bytes, content_type: str) -> None:
    try:
        S3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=KMS_ALIAS_MEDIA,
        )
    except Exception as e:
        raise HTTPException(500, f"S3 put_object failed: {e}")

def _is_supported_magic(img_bytes: bytes) -> bool:
    sig = img_bytes[:12]
    # JPEG / PNG / WebP（簡易判定）
    if sig.startswith(b"\xff\xd8"):  # JPEG
        return True
    if sig.startswith(b"\x89PNG"):   # PNG
        return True
    if sig.startswith(b"RIFF") and img_bytes[8:12] == b"WEBP":  # WebP
        return True
    # HEICはpillow-heifが開ける場合があるので厳密魔法は省略
    return False

def _sanitize_and_variants(
    img_bytes: bytes,
    *,
    blur_boxes: Optional[List[Tuple[int, int, int, int]]] = None,
    blur_radius: int = 15,
) -> Dict[str, Tuple[bytes, str]]:
    """
    出力:
      {
        "original.jpg":    (bytes, "image/jpeg"),
        "1080w.webp":      (bytes, "image/webp"),
        "blurred.webp":    (bytes, "image/webp"),
      }
    """
    try:
        im = Image.open(io.BytesIO(img_bytes))
    except Exception:
        raise HTTPException(400, "Unsupported or corrupted image")

    # EXIFに基づく自動回転 + sRGB化（簡易）
    im = ImageOps.exif_transpose(im)
    im = im.convert("RGB")

    # original（再保存JPEG：EXIF除去・圧縮最適化）
    out_original = io.BytesIO()
    im.save(out_original, format="JPEG", quality=85, optimize=True)
    original_bytes = out_original.getvalue()

    # 1080w（横1080px基準のWebP）
    w_target = 1080
    im_1080 = im.copy()
    if im_1080.width > w_target:
        h = int(im_1080.height * (w_target / im_1080.width))
        im_1080 = im_1080.resize((w_target, h), Image.LANCZOS)
    out_1080 = io.BytesIO()
    im_1080.save(out_1080, format="WEBP", quality=78, method=6)
    w1080_bytes = out_1080.getvalue()

    # thumb（256pxサムネWebP）
    im_t = im.copy()
    im_t.thumbnail((256, 256), Image.LANCZOS)
    out_thumb = io.BytesIO()
    im_t.save(out_thumb, format="WEBP", quality=75, method=6)
    thumb_bytes = out_thumb.getvalue()

    # ★ ぼかし（全面 or 指定領域）
    im_blurred = _apply_blur(im, boxes=blur_boxes, radius=blur_radius)
    out_blurred = io.BytesIO()
    im_blurred.save(out_blurred, format="WEBP", quality=80, method=6)
    blurred_bytes = out_blurred.getvalue()

    # ぼかし版サムネ
    im_blurred_t = im_blurred.copy()
    im_blurred_t.thumbnail((256, 256), Image.LANCZOS)
    out_blurred_thumb = io.BytesIO()
    im_blurred_t.save(out_blurred_thumb, format="WEBP", quality=80, method=6)
    blurred_thumb_bytes = out_blurred_thumb.getvalue()

    return {
        "original.jpg":        (original_bytes, "image/jpeg"),
        "1080w.webp":          (w1080_bytes,   "image/webp"),
        "blurred.webp":        (blurred_bytes,  "image/webp"),
    }

def _moderation_check(img_bytes: bytes, min_conf: float = 80.0) -> Dict:
    """
    任意: 不適切判定。NGなら {'flagged': True, 'labels': [...]} を返す。

    ヌード系コンテンツは許容し、以下のカテゴリのみブロック:
    - Drugs (薬物)
    - Hate Symbols (ヘイトシンボル)
    """
    try:
        resp = REKOG.detect_moderation_labels(Image={"Bytes": img_bytes})
        labels = resp.get("ModerationLabels", [])

        # ブロックするカテゴリ（ヌード系を除外）
        BLOCKED_CATEGORIES = [
            "Drugs",
            "Hate Symbols",
        ]

        # ブロック対象カテゴリに該当するラベルのみチェック
        flagged_labels = [
            l for l in labels
            if l["Confidence"] >= min_conf and any(
                blocked in l.get("Name", "") or blocked in l.get("ParentName", "")
                for blocked in BLOCKED_CATEGORIES
            )
        ]

        flagged = len(flagged_labels) > 0
        return {"flagged": flagged, "labels": labels}
    except Exception:
        # Rekognition障害時は通し、ログのみ（必要なら厳格にfailに変更）
        return {"flagged": False, "labels": []}
    
def _make_variant_keys(base_key: str) -> dict:
    # "transcode-mc/{creator}/{post}/ffmpeg/{uuid}.ext" -> stem=".../{uuid}"
    stem, _ext = base_key.rsplit(".", 1)
    return {
        "original.jpg": f"{stem}_original.jpg",
        "1080w.webp":   f"{stem}_1080w.webp",
        "blurred.webp": f"{stem}_blurred.webp",
    }

def _apply_blur(
    im: Image.Image,
    boxes: Optional[List[Tuple[int, int, int, int]]] = None,
    radius: int = 15,
) -> Image.Image:
    """
    画像にガウスぼかしを適用。
    - boxes を指定しない/空: 画像全体に適用
    - boxes を指定: 各矩形領域のみに適用
    radius: ぼかしの強さ（大きいほど強くぼかす、デフォルト15）
    """
    from PIL import ImageFilter

    im_blurred = im.copy()

    if not boxes:
        # 全面ぼかし
        return im_blurred.filter(ImageFilter.GaussianBlur(radius=radius))

    # 領域ぼかし
    for (l, t, r, b) in boxes:
        # 領域は画像範囲にクリップ
        l2 = max(0, min(l, im_blurred.width))
        t2 = max(0, min(t, im_blurred.height))
        r2 = max(l2, min(r, im_blurred.width))
        b2 = max(t2, min(b, im_blurred.height))
        if r2 - l2 <= 0 or b2 - t2 <= 0:
            continue
        crop = im_blurred.crop((l2, t2, r2, b2))
        crop_blurred = crop.filter(ImageFilter.GaussianBlur(radius=radius))
        im_blurred.paste(crop_blurred, (l2, t2))
    return im_blurred


# ========== OGP画像生成関連 ==========

def create_blurred_background(image: Image.Image, target_size: Tuple[int, int]) -> Image.Image:
    """
    ボカシ背景画像を作成（OGP画像用）

    Args:
        image: 元画像
        target_size: 目標サイズ (width, height)

    Returns:
        Image.Image: ボカシ処理された背景画像
    """
    from PIL import ImageFilter

    # アスペクト比を保持してリサイズ
    img_ratio = image.width / image.height
    target_ratio = target_size[0] / target_size[1]

    if img_ratio > target_ratio:
        # 画像の方が横長
        new_height = target_size[1]
        new_width = int(new_height * img_ratio)
    else:
        # 画像の方が縦長
        new_width = target_size[0]
        new_height = int(new_width / img_ratio)

    resized = image.resize((int(new_width), int(new_height)), Image.LANCZOS)

    # 中央でクロップ（整数座標に変換）
    left = int((new_width - target_size[0]) // 2)
    top = int((new_height - target_size[1]) // 2)
    right = int(left + target_size[0])
    bottom = int(top + target_size[1])
    cropped = resized.crop((left, top, right, bottom))

    # ボカシフィルタを適用
    blurred = cropped.filter(ImageFilter.GaussianBlur(radius=15))

    # 暗くする（オーバーレイ効果）
    overlay = Image.new("RGB", target_size, (0, 0, 0))
    blurred = Image.blend(blurred, overlay, alpha=0.3)

    return blurred


def create_circular_avatar(image: Image.Image, size: int) -> Image.Image:
    """
    円形のアバター画像を作成（OGP画像用）

    Args:
        image: 元画像
        size: アバターサイズ

    Returns:
        Image.Image: 円形アバター画像（RGBA）
    """
    from PIL import ImageDraw

    # 正方形にリサイズ（整数サイズに変換）
    size = int(size)
    image = image.resize((size, size), Image.LANCZOS)

    # 円形マスクを作成
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)

    # RGBAモードに変換してマスクを適用
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(image, (0, 0))
    output.putalpha(mask)

    return output


def download_image_from_url(url: str) -> Optional[Image.Image]:
    """
    URLから画像をダウンロード

    Args:
        url: 画像URL

    Returns:
        Image.Image: PIL Image オブジェクト、失敗時はNone
    """
    import requests

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
        return image.convert("RGB")
    except Exception as e:
        print(f"Failed to download image from {url}: {e}")
        return None


def _draw_default_avatar(canvas: Image.Image, x: int, y: int, size: int) -> None:
    """
    デフォルトアバター（NO IMAGE風）を描画

    Args:
        canvas: 描画先キャンバス
        x: X座標
        y: Y座標
        size: アバターサイズ
    """
    import os

    # no-image.pngを読み込んで使用
    no_image_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "no-image.png")

    try:
        # no-image.pngを読み込み
        no_image = Image.open(no_image_path)

        # サイズ調整して円形に切り抜き
        circular_avatar = create_circular_avatar(no_image, size)

        # キャンバスに貼り付け
        canvas.paste(circular_avatar, (int(x), int(y)), circular_avatar)

    except Exception as e:
        print(f"Failed to load no-image.png: {e}")
        # フォールバック: 簡易的な円形アバターを描画
        from PIL import ImageDraw

        avatar = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(avatar)
        draw.ellipse([(0, 0, size, size)], fill="#6ccaf1")

        # 人型シルエット
        head_radius = int(size // 6)
        head_x = int(size // 2)
        head_y = int(size // 3)
        draw.ellipse(
            [(head_x - head_radius, head_y - head_radius),
             (head_x + head_radius, head_y + head_radius)],
            fill="#ffffff"
        )

        body_top_y = int(head_y + head_radius + size // 20)
        body_bottom_y = int(size)
        body_width_top = int(size // 3)
        body_width_bottom = int(size * 0.6)

        points = [
            (int(head_x - body_width_top // 2), body_top_y),
            (int(head_x + body_width_top // 2), body_top_y),
            (int(head_x + body_width_bottom // 2), body_bottom_y),
            (int(head_x - body_width_bottom // 2), body_bottom_y),
        ]
        draw.polygon(points, fill="#ffffff")

        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([(0, 0, size, size)], fill=255)
        avatar.putalpha(mask)

        canvas.paste(avatar, (int(x), int(y)), avatar)


def generate_ogp_image(
    thumbnail_url: str,
    avatar_url: Optional[str],
    profile_name: str,
    username: str,
) -> bytes:
    """
    OGP画像を生成

    Args:
        thumbnail_url: サムネイル画像URL
        avatar_url: アバター画像URL（オプション）
        profile_name: プロフィール名
        username: ユーザー名

    Returns:
        bytes: 生成されたOGP画像のバイナリデータ（PNG形式）
    """
    from PIL import ImageDraw, ImageFont, ImageFilter
    import os
    from pathlib import Path

    # 定数定義
    OGP_WIDTH = 1200
    OGP_HEIGHT = 630
    BORDER_WIDTH = 10
    BORDER_COLOR = "#6ccaf1"
    MIJFANS_COLOR = "#6ccaf1"
    TEXT_COLOR = "#ffffff"
    AVATAR_SIZE = 80
    MARGIN = 30

    # フォント設定（日本語対応優先）
    FONT_PATHS_JP = [
        # macOS - 日本語対応
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",  # Hiragino Sans
        "/System/Library/Fonts/ヒラギノ角ゴ ProN W3.otf",
        # Linux - 日本語対応
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Noto Sans CJK
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]

    FONT_PATHS_EN = [
        # macOS - 英数字
        "/System/Library/Fonts/Helvetica.ttc",  # Helvetica
        "/System/Library/Fonts/Supplemental/Arial.ttf",  # Arial
        # Linux - 英数字
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # DejaVu Sans
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",  # Liberation Sans
    ]

    def get_font_jp(size: int) -> ImageFont.FreeTypeFont:
        """日本語フォントを取得"""
        for font_path in FONT_PATHS_JP:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue
        # フォールバック
        return ImageFont.load_default()

    def get_font_en(size: int) -> ImageFont.FreeTypeFont:
        """英数字フォントを取得"""
        for font_path in FONT_PATHS_EN:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue
        # フォールバック
        return ImageFont.load_default()

    # 1. サムネイル画像をダウンロード
    thumbnail_image = download_image_from_url(thumbnail_url)
    if not thumbnail_image:
        raise HTTPException(500, "Failed to download thumbnail image")

    # 2. ボカシ背景を作成
    background = create_blurred_background(thumbnail_image, (OGP_WIDTH, OGP_HEIGHT))

    # 3. 描画用キャンバスを作成
    canvas = Image.new("RGB", (OGP_WIDTH, OGP_HEIGHT), (255, 255, 255))
    canvas.paste(background, (0, 0))
    draw = ImageDraw.Draw(canvas)

    # 4. 外枠を描画
    for i in range(BORDER_WIDTH):
        draw.rectangle(
            [(i, i), (OGP_WIDTH - 1 - i, OGP_HEIGHT - 1 - i)],
            outline=BORDER_COLOR
        )

    # 5. アバター画像を配置（左下）- 整数座標に変換
    avatar_x = int(MARGIN)
    avatar_y = int(OGP_HEIGHT - MARGIN - AVATAR_SIZE)

    if avatar_url:
        avatar_image = download_image_from_url(avatar_url)
        if avatar_image:
            circular_avatar = create_circular_avatar(avatar_image, AVATAR_SIZE)
            canvas.paste(circular_avatar, (avatar_x, avatar_y), circular_avatar)
        else:
            # アバター画像のダウンロード失敗時: デフォルトアバターを描画
            _draw_default_avatar(canvas, avatar_x, avatar_y, AVATAR_SIZE)
    else:
        # アバター画像がない場合: デフォルトアバターを描画
        _draw_default_avatar(canvas, avatar_x, avatar_y, AVATAR_SIZE)

    # 6. プロフィール情報を配置（アバターの右側）- 整数座標に変換
    profile_x = int(avatar_x + AVATAR_SIZE + 15)
    profile_y_top = int(avatar_y + 15)
    profile_y_bottom = int(avatar_y + 45)

    # プロフィール名（日本語対応フォント使用）
    font_profile = get_font_jp(20)
    draw.text((profile_x, profile_y_top), profile_name, fill=TEXT_COLOR, font=font_profile)

    # ユーザー名（英数字専用フォント）
    font_username = get_font_en(16)
    username_text = f"@{username}"
    draw.text((profile_x, profile_y_bottom), username_text, fill=TEXT_COLOR, font=font_username)

    # 7. mijfansロゴ（右下）- PNGロゴを配置
    logo_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "logo-mijfans.png")

    try:
        # PNGロゴを読み込んで配置
        logo_image = Image.open(logo_path)

        # ロゴサイズを調整（幅150px）
        logo_width = 150
        aspect_ratio = logo_image.height / logo_image.width
        logo_height = int(logo_width * aspect_ratio)
        logo_image = logo_image.resize((logo_width, logo_height), Image.LANCZOS)

        # RGBAモードに変換（透過対応）
        if logo_image.mode != 'RGBA':
            logo_image = logo_image.convert('RGBA')

        logo_x = int(OGP_WIDTH - MARGIN - logo_image.width)
        logo_y = int(OGP_HEIGHT - MARGIN - logo_image.height)
        canvas.paste(logo_image, (logo_x, logo_y), logo_image)
    except Exception as e:
        print(f"Failed to load PNG logo: {e}")
        # PNG読み込み失敗時はテキストで代替
        font_mijfans = get_font_en(36)
        mijfans_text = "mijfans"
        bbox = draw.textbbox((0, 0), mijfans_text, font=font_mijfans)
        text_width = int(bbox[2] - bbox[0])
        mijfans_x = int(OGP_WIDTH - MARGIN - text_width)
        mijfans_y = int(OGP_HEIGHT - MARGIN - 40)
        # 縁取り
        for offset_x, offset_y in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
            draw.text((mijfans_x + offset_x, mijfans_y + offset_y), mijfans_text, fill="#000000", font=font_mijfans)
        draw.text((mijfans_x, mijfans_y), mijfans_text, fill=MIJFANS_COLOR, font=font_mijfans)

    # 9. 画像をバイナリデータに変換
    img_byte_arr = io.BytesIO()
    canvas.save(img_byte_arr, format='PNG', optimize=True)
    img_byte_arr.seek(0)

    return img_byte_arr.getvalue()


def generate_profile_ogp_image(
    cover_url: Optional[str],
    avatar_url: Optional[str],
    profile_name: str,
    username: str,
) -> bytes:
    """
    プロフィールOGP画像を生成

    Args:
        cover_url: カバー画像URL（オプション）
        avatar_url: アバター画像URL（オプション）
        profile_name: プロフィール名
        username: ユーザー名

    Returns:
        bytes: 生成されたOGP画像のバイナリデータ（PNG形式）
    """
    from PIL import ImageDraw, ImageFont
    import os

    # 定数定義
    OGP_WIDTH = 1200
    OGP_HEIGHT = 630
    BORDER_WIDTH = 10
    BORDER_COLOR = "#6ccaf1"
    MIJFANS_COLOR = "#6ccaf1"
    TEXT_COLOR = "#ffffff"
    AVATAR_SIZE = 80
    MARGIN = 30

    # フォント設定（日本語対応優先）
    FONT_PATHS_JP = [
        # macOS - 日本語対応
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴ ProN W3.otf",
        # Linux - 日本語対応
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]

    FONT_PATHS_EN = [
        # macOS - 英数字
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        # Linux - 英数字
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]

    def get_font_jp(size: int) -> ImageFont.FreeTypeFont:
        """日本語フォントを取得"""
        for font_path in FONT_PATHS_JP:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def get_font_en(size: int) -> ImageFont.FreeTypeFont:
        """英数字フォントを取得"""
        for font_path in FONT_PATHS_EN:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    # 1. 背景画像を取得
    background_image = None
    if cover_url:
        background_image = download_image_from_url(cover_url)

    if not background_image:
        # フォールバック: main-image.pngを使用
        main_image_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "main-image.png")
        try:
            background_image = Image.open(main_image_path)
            background_image = background_image.convert("RGB")
        except Exception as e:
            print(f"Failed to load main-image.png: {e}")
            # 最終フォールバック: 単色背景
            background_image = Image.new("RGB", (OGP_WIDTH, OGP_HEIGHT), (100, 100, 100))

    # 2. 背景画像をリサイズ（ボカシなし）
    img_ratio = background_image.width / background_image.height
    target_ratio = OGP_WIDTH / OGP_HEIGHT

    if img_ratio > target_ratio:
        new_height = OGP_HEIGHT
        new_width = int(new_height * img_ratio)
    else:
        new_width = OGP_WIDTH
        new_height = int(new_width / img_ratio)

    resized = background_image.resize((int(new_width), int(new_height)), Image.LANCZOS)

    # 中央でクロップ
    left = int((new_width - OGP_WIDTH) // 2)
    top = int((new_height - OGP_HEIGHT) // 2)
    right = int(left + OGP_WIDTH)
    bottom = int(top + OGP_HEIGHT)
    background = resized.crop((left, top, right, bottom))

    # 3. 描画用キャンバスを作成
    canvas = Image.new("RGB", (OGP_WIDTH, OGP_HEIGHT), (255, 255, 255))
    canvas.paste(background, (0, 0))
    draw = ImageDraw.Draw(canvas)

    # 4. 外枠を描画
    for i in range(BORDER_WIDTH):
        draw.rectangle(
            [(i, i), (OGP_WIDTH - 1 - i, OGP_HEIGHT - 1 - i)],
            outline=BORDER_COLOR
        )

    # 5. アバター画像を配置（左下）
    avatar_x = int(MARGIN)
    avatar_y = int(OGP_HEIGHT - MARGIN - AVATAR_SIZE)

    if avatar_url:
        avatar_image = download_image_from_url(avatar_url)
        if avatar_image:
            circular_avatar = create_circular_avatar(avatar_image, AVATAR_SIZE)
            canvas.paste(circular_avatar, (avatar_x, avatar_y), circular_avatar)
        else:
            _draw_default_avatar(canvas, avatar_x, avatar_y, AVATAR_SIZE)
    else:
        _draw_default_avatar(canvas, avatar_x, avatar_y, AVATAR_SIZE)

    # 6. プロフィール情報を配置（アバターの右側）
    profile_x = int(avatar_x + AVATAR_SIZE + 15)
    profile_y_top = int(avatar_y + 15)
    profile_y_bottom = int(avatar_y + 45)

    # プロフィール名（日本語対応フォント使用）
    font_profile = get_font_jp(20)
    draw.text((profile_x, profile_y_top), profile_name, fill=TEXT_COLOR, font=font_profile)

    # ユーザー名（英数字専用フォント）
    font_username = get_font_en(16)
    username_text = f"@{username}"
    draw.text((profile_x, profile_y_bottom), username_text, fill=TEXT_COLOR, font=font_username)

    # 7. mijfansロゴ（右下）
    logo_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "logo-mijfans.png")

    try:
        logo_image = Image.open(logo_path)
        logo_width = 450  # 4x size
        aspect_ratio = logo_image.height / logo_image.width
        logo_height = int(logo_width * aspect_ratio)
        logo_image = logo_image.resize((logo_width, logo_height), Image.LANCZOS)

        if logo_image.mode != 'RGBA':
            logo_image = logo_image.convert('RGBA')

        logo_x = int(OGP_WIDTH - MARGIN - logo_image.width)
        logo_y = int(OGP_HEIGHT - 20 - logo_image.height)  # 下に寄せる
        canvas.paste(logo_image, (logo_x, logo_y), logo_image)
    except Exception as e:
        print(f"Failed to load PNG logo: {e}")
        # テキストで代替
        font_mijfans = get_font_en(36)
        mijfans_text = "mijfans"
        bbox = draw.textbbox((0, 0), mijfans_text, font=font_mijfans)
        text_width = int(bbox[2] - bbox[0])
        mijfans_x = int(OGP_WIDTH - MARGIN - text_width)
        mijfans_y = int(OGP_HEIGHT - MARGIN - 40)
        for offset_x, offset_y in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
            draw.text((mijfans_x + offset_x, mijfans_y + offset_y), mijfans_text, fill="#000000", font=font_mijfans)
        draw.text((mijfans_x, mijfans_y), mijfans_text, fill=MIJFANS_COLOR, font=font_mijfans)

    # 8. 画像をバイナリデータに変換
    img_byte_arr = io.BytesIO()
    canvas.save(img_byte_arr, format='PNG', optimize=True)
    img_byte_arr.seek(0)

    return img_byte_arr.getvalue()