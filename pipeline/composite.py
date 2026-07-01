"""
Composite poster images from pre-rendered PNG templates + a masked letter image.

build_poster()     → 朋友圈 vertical poster
build_xhs_poster() → 小红书 square poster

PSDs are pre-rendered to PNGs by prerender_templates.py (run at build time).
No psd-tools is loaded during request handling.
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PRERENDERED_DIR = Path(__file__).parent.parent / "templates_prerendered"
ASSETS_DIR      = Path(__file__).parent.parent / "assets"
FONT_PATH       = ASSETS_DIR / "SourceHanSansSC-Bold.otf"

WECHAT_FONT_SIZE          = 173
WECHAT_BAR_COLOR          = (187, 26, 39)
WECHAT_BAR_PROGRAM_FONT_SIZE = 129

XHS_FONT_SIZE = 241

TEXT_WHITE = (255, 255, 255)

_FLAG_TARGET_X = 52
_FLAG_TARGET_Y = 90
_FLAG_TARGET_H = 59

VISA_PROGRAMS = {"境内学签", "境外学签", "境外工签", "境内工签", "澳洲签证"}

PROGRAM_BAR_DISPLAY = {
    "获批信配偶担保":          "配偶担保",
    "配偶担保（邮件版）":      "配偶担保",
    "获批信EE":                "EE获批",
    "省提名":                  "省提名　",   # trailing ideographic space → 4-char width
    "安省省提名-EE+600分":     "EE+600",
    "技工省提名":              "技工获批",
    "优才计划省提名-EE加分":   "EE加分",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _fit_font(text: str, max_w: int, max_h: int, start_size: int) -> ImageFont.FreeTypeFont:
    """Return the largest font whose rendered width fits within max_w."""
    size = start_size
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    while size > 8:
        font = ImageFont.truetype(str(FONT_PATH), size)
        _, _, tw, _ = dummy.textbbox((0, 0), text, font=font)
        if tw <= max_w:
            return font
        size -= 4
    return ImageFont.truetype(str(FONT_PATH), 8)


def _draw_text_over(canvas, bbox, text, font, bg_color, autofit=False):
    """Optionally fill bbox with bg_color then draw text bottom-aligned, left-aligned."""
    draw = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = bbox
    if bg_color is not None:
        draw.rectangle([x0, y0, x1, y1], fill=bg_color)
    if autofit:
        font = _fit_font(text, x1 - x0, y1 - y0, font.size)
    _, _, tw, th = draw.textbbox((0, 0), text, font=font)
    text_y = y1 - th
    if bg_color is not None and text_y < y0:
        draw.rectangle([x0, text_y, x1, y0], fill=bg_color)
    draw.text((x0, text_y), text, font=font, fill=TEXT_WHITE)


def _find_flag_in_letter(letter: Image.Image):
    """Return (y_top, x_left, height) of Canada flag red pixels in the letter."""
    import numpy as np
    arr = np.array(letter)
    roi = arr[:letter.height // 4, :letter.width // 4]
    red = (roi[:, :, 0] > 160) & (roi[:, :, 1] < 60) & (roi[:, :, 2] < 60)
    ys = np.where(red.any(axis=1))[0]
    xs = np.where(red.any(axis=0))[0]
    if len(ys) > 1 and len(xs):
        return int(ys[0]), int(xs[0]), int(ys[-1] - ys[0])
    return 58, 268, 63


def _paste_letter(canvas: Image.Image, frame_bbox: tuple, letter_image: Image.Image,
                  watermark=None, watermark_bbox=None):
    x0, y0, x1, y1 = frame_bbox
    fw, fh = x1 - x0, y1 - y0

    flag_y, flag_x, flag_h = _find_flag_in_letter(letter_image)

    scale = fh / letter_image.height
    new_w = int(letter_image.width * scale)
    new_h = int(letter_image.height * scale)
    scaled = letter_image.resize((new_w, new_h), Image.LANCZOS)

    paste_x = x0 + _FLAG_TARGET_X - int(flag_x * scale)
    paste_y = y0 + _FLAG_TARGET_Y - int(flag_y * scale)

    ImageDraw.Draw(canvas).rectangle([x0, y0, x1, y1], fill=(255, 255, 255))

    src_x0 = max(0, x0 - paste_x)
    src_y0 = max(0, y0 - paste_y)
    src_x1 = min(new_w, x1 - paste_x)
    src_y1 = min(new_h, y1 - paste_y)
    if src_x1 > src_x0 and src_y1 > src_y0:
        region = scaled.crop((src_x0, src_y0, src_x1, src_y1))
        canvas.paste(region.convert(canvas.mode), (max(x0, paste_x), max(y0, paste_y)))

    if watermark and watermark_bbox:
        wm = watermark.convert("RGBA")
        wb_x = watermark_bbox[0] if isinstance(watermark_bbox, tuple) else watermark_bbox.left
        wb_y = watermark_bbox[1] if isinstance(watermark_bbox, tuple) else watermark_bbox.top
        # Composite only over the watermark region to avoid converting the full canvas to RGBA
        wm_w, wm_h = wm.size
        region = canvas.crop((wb_x, wb_y, wb_x + wm_w, wb_y + wm_h)).convert("RGBA")
        region.alpha_composite(wm)
        canvas.paste(region.convert(canvas.mode), (wb_x, wb_y))


def _load_prerendered(name: str):
    """Load pre-rendered base PNG + JSON metadata for the given template name."""
    meta = json.loads((PRERENDERED_DIR / f"{name}_meta.json").read_text())
    base = Image.open(str(PRERENDERED_DIR / f"{name}_base.png")).convert("RGB")
    wm_path = PRERENDERED_DIR / f"{name}_watermark.png"
    wm = Image.open(str(wm_path)).convert("RGBA") if wm_path.exists() else None

    # Load pre-cropped label restore regions (tiny PNGs, avoids full canvas copy at runtime)
    restore_crops = []
    for i, region in enumerate(meta.get("restore_regions", [])):
        crop_path = PRERENDERED_DIR / f"{name}_restore_{i}.png"
        if crop_path.exists():
            restore_crops.append((region, Image.open(str(crop_path)).convert("RGB")))

    return base, wm, meta, restore_crops


# ── 朋友圈 poster ─────────────────────────────────────────────────────────────

def build_poster(
    psd_filename: str,       # kept for API compatibility; ignored (template chosen by program)
    client_name: str,
    program_name: str,
    approved_date: str,
    letter_image: Image.Image,
) -> Image.Image:
    is_visa = program_name in VISA_PROGRAMS
    template_name = "签证捷报" if is_visa else "移民捷报"
    base, wm, meta, restore_crops = _load_prerendered(template_name)

    frame_bbox   = tuple(meta["frame_bbox"])     if meta["frame_bbox"]       else None
    wm_bbox      = tuple(meta["watermark_bbox"]) if meta["watermark_bbox"]   else None
    title_bbox   = tuple(meta["title_bbox"])     if meta.get("title_bbox")   else None
    date_grp_x   = meta["date_grp_x"]
    text_bboxes  = {k: tuple(v) for k, v in meta["text_bboxes"].items()}

    canvas = base.copy()
    bar_program = PROGRAM_BAR_DISPLAY.get(program_name, program_name)

    # Draw 客户姓名 and 获批时间
    for group_name, new_text, bg, max_w, start_size in (
        ("客户姓名", client_name,   WECHAT_BAR_COLOR, 380, WECHAT_FONT_SIZE),
        ("获批时间", approved_date, None,              670, WECHAT_FONT_SIZE),
    ):
        if group_name in text_bboxes:
            font = _fit_font(new_text, max_w, 0, start_size)
            _draw_text_over(canvas, text_bboxes[group_name], new_text, font, bg)

    # Draw 移民项目
    if "移民项目" in text_bboxes:
        bbox = text_bboxes["移民项目"]
        x0, y0, x1, y1 = bbox
        font = _fit_font(bar_program, date_grp_x - x0, 0, WECHAT_BAR_PROGRAM_FONT_SIZE)
        _draw_text_over(canvas, bbox, bar_program, font, None)

    # Restore label regions from pre-cropped images (no full canvas copy needed)
    for (bx0, by0, bx1, by1), crop in restore_crops:
        canvas.paste(crop, (bx0, by0))

    # Draw 签证捷报 for VISA programs (title slot was left blank in prerendered base)
    if is_visa and title_bbox:
        font_title = _fit_font("签证捷报",
                               title_bbox[2] - title_bbox[0],
                               title_bbox[3] - title_bbox[1], 600)
        _draw_text_over(canvas, title_bbox, "签证捷报", font_title, None)

    if frame_bbox:
        _paste_letter(canvas, frame_bbox, letter_image, wm, wm_bbox)

    return canvas


# ── 小红书 poster ──────────────────────────────────────────────────────────────

def build_xhs_poster(program_name: str, letter_image: Image.Image) -> Image.Image:
    base, _, meta, _ = _load_prerendered("小红书")
    frame_bbox = tuple(meta["frame_bbox"]) if meta["frame_bbox"] else None
    title_bbox = tuple(meta["title_bbox"]) if meta.get("title_bbox") else None

    canvas = base.convert("RGB")
    canvas_before_letter = canvas.copy()

    wm_path = PRERENDERED_DIR / "watermark.png"
    wm_img = Image.open(str(wm_path)).convert("RGBA") if wm_path.exists() else None

    if frame_bbox and wm_img:
        fx0, fy0, fx1, fy1 = frame_bbox
        fw, fh = fx1 - fx0, fy1 - fy0
        wm_scaled_w = int(fw * 0.812)
        wm_scaled_h = int(wm_img.height * wm_scaled_w / wm_img.width)
        wm_scaled = wm_img.resize((wm_scaled_w, wm_scaled_h), Image.LANCZOS)
        wm_dest_x = fx0 + int(fw * 0.138)
        wm_dest_y = fy0 + int(fh * 0.272)
        xhs_wm_bbox = (wm_dest_x, wm_dest_y,
                       wm_dest_x + wm_scaled_w, wm_dest_y + wm_scaled_h)
        _paste_letter(canvas, frame_bbox, letter_image, wm_scaled, xhs_wm_bbox)
    elif frame_bbox:
        _paste_letter(canvas, frame_bbox, letter_image, None, None)

    # Restore decorative elements the letter paste whited out
    for bx0, by0, bx1, by1 in (
        (570,  217, 1249, 487),   # title background rectangles + right accent
        (92,  1561,  189, 1661),  # bottom-left red/dark-red squares
    ):
        canvas.paste(canvas_before_letter.crop((bx0, by0, bx1, by1)), (bx0, by0))

    if title_bbox:
        title_text = "签证捷报" if program_name in VISA_PROGRAMS else "移民捷报"
        font = ImageFont.truetype(str(FONT_PATH), XHS_FONT_SIZE)
        _draw_text_over(canvas, title_bbox, title_text, font, None, autofit=True)

    return canvas
