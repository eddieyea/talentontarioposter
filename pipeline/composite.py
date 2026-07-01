"""
Composite poster images from PSD templates + a masked letter image.

build_poster()     → 朋友圈 vertical poster (per-program PSD)
build_xhs_poster() → 小红书 square poster (single shared template)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

TEMPLATES_DIR = Path(__file__).parent.parent / "templates_psd"
ASSETS_DIR = Path(__file__).parent.parent / "assets"
FONT_PATH = ASSETS_DIR / "SourceHanSansSC-Bold.otf"

FRAME_LAYER_NAME = "矩形 1"
LABEL_TEXTS = {"客户姓名", "移民项目", "获批时间", "目的地"}

# 朋友圈 info bar: target ~173px in poster (matched to reference)
WECHAT_FONT_SIZE = 173
WECHAT_BAR_COLOR = (187, 26, 39)

# 小红书 title: 115.5pt at 150 DPI → 241px
XHS_FONT_SIZE = 241
XHS_TITLE_BG_COLOR = (117, 22, 30)

TEXT_WHITE = (255, 255, 255)

# Canada flag anchor point measured from human-created reference poster
# (all values in 朋友圈 poster pixel coordinates, relative to 矩形 1 frame top-left)
_FLAG_TARGET_X = 52    # flag left edge from frame left
_FLAG_TARGET_Y = 90    # flag top edge from frame top
_FLAG_TARGET_H = 59    # flag bounding-box height (drives letter scale)

# Programs whose poster title should read "签证捷报" instead of "移民捷报"
VISA_PROGRAMS = {"境内学签", "境外学签", "境外工签", "澳洲签证"}

# Display text overrides for the 移民项目 info bar slot.
# U+3000 (ideographic space) is used for 省提名 so it renders at the same
# font size as a 4-character CJK string (each U+3000 = one full CJK-width).
PROGRAM_BAR_DISPLAY = {
    "获批信配偶担保": "配偶担保",
    "配偶担保（邮件版）": "配偶担保",
    "获批信EE": "EE获批",
    "省提名": "省提名　",              # trailing ideographic space → 4-char width
    "安省省提名-EE+600分": "EE+600",
    "技工省提名": "技工获批",
    "优才计划省提名-EE加分": "EE加分",
}

# Starting font size for the 移民项目 bar slot, capped to what a standard
# 4-char CJK program name (e.g. 境外学签) produces at max_w=524 (≈129px).
# This prevents short mixed ASCII/CJK strings from rendering oversized.
WECHAT_BAR_PROGRAM_FONT_SIZE = 129


def _find_group_left_x(psd, group_name: str):
    """Return the leftmost x of any non-value child layer inside the named group."""
    from psd_tools.api.layers import TypeLayer
    def walk(layers):
        for layer in layers:
            if layer.name == group_name and hasattr(layer, '__iter__'):
                xs = []
                for child in layer:
                    # Skip value TypeLayers (text ≠ group label name)
                    if isinstance(child, TypeLayer) and child.text not in LABEL_TEXTS:
                        continue
                    b = child.bbox
                    xs.append(b.left if hasattr(b, 'left') else b[0])
                return min(xs) if xs else None
            if hasattr(layer, '__iter__'):
                r = walk(layer)
                if r is not None:
                    return r
    return walk(psd)


def _collect_text_layers(psd) -> dict:
    """Return first-occurrence bboxes for 客户姓名 / 移民项目 / 获批时间 groups."""
    from psd_tools.api.layers import TypeLayer
    results = {}
    target_groups = {"客户姓名", "移民项目", "获批时间"}

    def walk(layers):
        for layer in layers:
            if layer.name in target_groups and layer.name not in results:
                if hasattr(layer, "__iter__"):
                    for child in layer:
                        if isinstance(child, TypeLayer) and child.text not in LABEL_TEXTS:
                            results[layer.name] = child.bbox
                            break
            if len(results) == 3:
                return
            if hasattr(layer, "__iter__"):
                walk(layer)

    walk(psd)
    return results


def _find_frame_bbox(layers):
    for layer in layers:
        if layer.name == FRAME_LAYER_NAME:
            b = layer.bbox
            return b if isinstance(b, tuple) else (b.left, b.top, b.right, b.bottom)
        if hasattr(layer, "__iter__"):
            result = _find_frame_bbox(layer)
            if result:
                return result
    return None


def _find_watermark_layer(psd):
    """Return the composited watermark layer image and its bbox, or (None, None)."""
    for layer in psd:
        if layer.name == "白底logo":
            return layer.composite(), layer.bbox
    return None, None


def _find_flag_in_letter(letter: Image.Image):
    """Return (y_top, x_left, height) of the Canada maple-leaf flag red pixels in the letter."""
    import numpy as np
    arr = np.array(letter)
    # Search only top-left quadrant — the flag is always top-left in IRCC letters
    roi = arr[:letter.height // 4, :letter.width // 4]
    red = (roi[:, :, 0] > 160) & (roi[:, :, 1] < 60) & (roi[:, :, 2] < 60)
    ys = np.where(red.any(axis=1))[0]
    xs = np.where(red.any(axis=0))[0]
    if len(ys) > 1 and len(xs):
        return int(ys[0]), int(xs[0]), int(ys[-1] - ys[0])
    # Fallback values measured from a standard IRCC letter at 300 DPI
    return 58, 268, 63


def _paste_letter(canvas: Image.Image, frame_bbox: tuple, letter_image: Image.Image,
                  watermark=None, watermark_bbox=None):
    x0, y0, x1, y1 = frame_bbox
    fw, fh = x1 - x0, y1 - y0

    # Detect flag position in the letter image
    flag_y, flag_x, flag_h = _find_flag_in_letter(letter_image)

    # Scale letter to fill the frame height (reference covers ~99.5% of frame)
    scale = fh / letter_image.height
    new_w = int(letter_image.width * scale)
    new_h = int(letter_image.height * scale)
    scaled = letter_image.resize((new_w, new_h), Image.LANCZOS)

    # Compute paste position: flag should land at (x0+_FLAG_TARGET_X, y0+_FLAG_TARGET_Y)
    paste_x = x0 + _FLAG_TARGET_X - int(flag_x * scale)
    paste_y = y0 + _FLAG_TARGET_Y - int(flag_y * scale)

    # Fill entire frame with white first (covers any PSD background peeking through gaps)
    canvas_draw = ImageDraw.Draw(canvas)
    canvas_draw.rectangle([x0, y0, x1, y1], fill=(255, 255, 255))

    # Crop the scaled letter to only the part that falls inside the frame and paste
    src_x0 = max(0, x0 - paste_x)
    src_y0 = max(0, y0 - paste_y)
    src_x1 = min(new_w, x1 - paste_x)
    src_y1 = min(new_h, y1 - paste_y)
    if src_x1 > src_x0 and src_y1 > src_y0:
        region = scaled.crop((src_x0, src_y0, src_x1, src_y1))
        dest_x = max(x0, paste_x)
        dest_y = max(y0, paste_y)
        canvas.paste(region.convert(canvas.mode), (dest_x, dest_y))
    # Re-apply watermark at its PSD-native canvas position.
    # The layer's pixel alpha is already pre-multiplied with the PSD layer opacity (~20%),
    # so we use it as-is without further reduction.
    if watermark and watermark_bbox:
        wm = watermark.convert("RGBA")
        wb_x = watermark_bbox[0] if isinstance(watermark_bbox, tuple) else watermark_bbox.left
        wb_y = watermark_bbox[1] if isinstance(watermark_bbox, tuple) else watermark_bbox.top
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.alpha_composite(wm, dest=(wb_x, wb_y))
        canvas.paste(canvas_rgba.convert(canvas.mode))


def _fit_font(text: str, max_w: int, max_h: int, start_size: int) -> ImageFont.FreeTypeFont:
    """Return the largest font whose rendered width fits within max_w."""
    size = start_size
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    while size > 8:
        font = ImageFont.truetype(str(FONT_PATH), size)
        _, _, tw, th = dummy.textbbox((0, 0), text, font=font)
        if tw <= max_w:
            return font
        size -= 4
    return ImageFont.truetype(str(FONT_PATH), 8)


def _draw_text_over(
    canvas: Image.Image,
    bbox: tuple,
    text: str,
    font: ImageFont.FreeTypeFont,
    bg_color,           # tuple or None — None = no background fill
    autofit: bool = False,
):
    """Optionally fill bbox with bg_color then draw text bottom-aligned, left-aligned."""
    draw = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = bbox
    if bg_color is not None:
        draw.rectangle([x0, y0, x1, y1], fill=bg_color)
    if autofit:
        font = _fit_font(text, x1 - x0, y1 - y0, font.size)
    _, _, tw, th = draw.textbbox((0, 0), text, font=font)
    text_y = y1 - th
    # Extend background upward to fully cover the text if it overflows above y0
    if bg_color is not None and text_y < y0:
        draw.rectangle([x0, text_y, x1, y0], fill=bg_color)
    # Bottom-align: anchor text bottom at y1; text grows upward if larger than bbox
    draw.text((x0, text_y), text, font=font, fill=TEXT_WHITE)


# ── 朋友圈 poster ─────────────────────────────────────────────────────────────

def _hide_value_layers(psd):
    """Hide only the value TypeLayers inside the info bar groups before compositing.

    Targets only direct TypeLayer children of groups named '客户姓名', '移民项目',
    '获批时间' whose text differs from the group name (i.e. they are value layers,
    not label layers).  All other TypeLayers (title, footer, etc.) are left alone.
    """
    from psd_tools.api.layers import TypeLayer
    INFO_BAR_GROUPS = {"客户姓名", "移民项目", "获批时间"}

    def walk(layers):
        for layer in layers:
            if getattr(layer, 'name', '') in INFO_BAR_GROUPS and hasattr(layer, '__iter__'):
                for child in layer:
                    if isinstance(child, TypeLayer) and child.text != layer.name:
                        child.visible = False
            elif hasattr(layer, '__iter__') and not isinstance(layer, TypeLayer):
                walk(layer)

    walk(psd)


def build_poster(
    psd_filename: str,
    client_name: str,
    program_name: str,
    approved_date: str,
    letter_image: Image.Image,
) -> Image.Image:
    from psd_tools import PSDImage
    from psd_tools.api.layers import TypeLayer
    psd = PSDImage.open(str(TEMPLATES_DIR / psd_filename))

    text_bboxes = _collect_text_layers(psd)
    frame_bbox = _find_frame_bbox(psd)
    watermark, watermark_bbox = _find_watermark_layer(psd)

    # Hide stored value text so composite() renders a clean slate for Pillow to draw on.
    # Also hide the title TypeLayer for VISA_PROGRAMS so we can draw 签证捷报 on top.
    _hide_value_layers(psd)
    title_bbox_wechat = None
    if program_name in VISA_PROGRAMS:
        for layer in psd.descendants():
            if isinstance(layer, TypeLayer) and layer.text == "移民捷报" \
                    and layer.bbox[2] < psd.width:
                layer.visible = False
                title_bbox_wechat = layer.bbox
                break
    canvas = psd.composite()
    label_composite = canvas.copy()  # labels/decorators only; used to restore z-order below

    # max_w: value must not reach next section's accent bar.
    # 客户姓名 value x0=573 → 移民项目 accent bar x=983 → room=410, use 380 (30px pad)
    # 移民项目 value x0=1353 → 获批时间 accent bar x=1907 → room=554, use 524 (30px pad)
    # 获批时间 value x0=2389 → canvas right=3195 → room=806, capped at 670 so date
    #   renders at ~120px matching the other two sections (656px wide at 120px)
    date_grp_x = _find_group_left_x(psd, "获批时间") or 1907
    prog_val_x0 = text_bboxes["移民项目"][0] if "移民项目" in text_bboxes else 1353

    bar_program = PROGRAM_BAR_DISPLAY.get(program_name, program_name)

    # Draw 客户姓名 and 获批时间 normally
    for group_name, new_text, bg, max_w, start_size in (
        ("客户姓名", client_name,   WECHAT_BAR_COLOR, 380, WECHAT_FONT_SIZE),
        ("获批时间", approved_date, None,              670, WECHAT_FONT_SIZE),
    ):
        if group_name in text_bboxes:
            bbox = text_bboxes[group_name]
            font = _fit_font(new_text, max_w, bbox[3] - bbox[1], start_size)
            _draw_text_over(canvas, bbox, new_text, font, bg, autofit=False)

    # Draw 移民项目: left-aligned at value x0, max_w = full section width up to
    # 获批时间 group left edge (no padding) so the font is as large as possible.
    # Background fill not needed — value TypeLayers are hidden so PSD bar is already red.
    if "移民项目" in text_bboxes:
        bbox = text_bboxes["移民项目"]
        x0, y0, x1, y1 = bbox
        max_w_prog = date_grp_x - x0
        font = _fit_font(bar_program, max_w_prog, y1 - y0, WECHAT_BAR_PROGRAM_FONT_SIZE)
        _draw_text_over(canvas, bbox, bar_program, font, None, autofit=False)

    # Restore label/decorator regions on top.
    # 移民项目: restore up to prog_val_x0 (label + slash, capped at value x0).
    # 获批时间: starts at date_grp_x (dynamic per template).
    for bx0, by0, bx1, by1 in (
        (191,        1817, 539,          1925),
        (983,        1812, prog_val_x0,  1928),
        (date_grp_x, 1807, 2365,        1924),
    ):
        if bx1 > bx0:
            canvas.paste(label_composite.crop((bx0, by0, bx1, by1)), (bx0, by0))

    # Draw 签证捷报 over the (now-empty) title area for VISA_PROGRAMS
    if title_bbox_wechat:
        font_title = _fit_font("签证捷报", title_bbox_wechat[2] - title_bbox_wechat[0],
                               title_bbox_wechat[3] - title_bbox_wechat[1], 600)
        _draw_text_over(canvas, title_bbox_wechat, "签证捷报", font_title, None, autofit=False)

    if frame_bbox:
        _paste_letter(canvas, frame_bbox, letter_image, watermark, watermark_bbox)

    return canvas


# ── 小红书 poster ──────────────────────────────────────────────────────────────

XHS_TEMPLATE = "小红书捷报模板.psd"
# Borrow watermark from this 朋友圈 PSD (all share the same 白底logo layer)
_WATERMARK_SOURCE_PSD = "境内学签.psd"


def _get_standalone_watermark():
    """Extract watermark layer from a 朋友圈 PSD and return (image, bbox)."""
    from psd_tools import PSDImage
    psd = PSDImage.open(str(TEMPLATES_DIR / _WATERMARK_SOURCE_PSD))
    return _find_watermark_layer(psd)


def build_xhs_poster(
    program_name: str,
    letter_image: Image.Image,
) -> Image.Image:
    from psd_tools import PSDImage
    from psd_tools.api.layers import TypeLayer
    psd = PSDImage.open(str(TEMPLATES_DIR / XHS_TEMPLATE))

    frame_bbox = _find_frame_bbox(psd)

    # Find and HIDE the title TypeLayer before compositing so we draw fresh text
    # on top of the untouched decorative background (no fill needed).
    title_layer = None
    title_bbox = None
    for layer in psd.descendants():
        if isinstance(layer, TypeLayer) and layer.text in ("移民捷报", "签证捷报"):
            title_layer = layer
            title_bbox = layer.bbox
            layer.visible = False
            break

    canvas = psd.composite()
    # Keep a copy so we can restore decorative elements covered by letter paste.
    canvas_before_letter = canvas.copy()

    # Scale the 朋友圈 watermark to fit the 小红书 frame proportionally.
    # In 朋友圈: frame_w=2824, wm placed at x_off=390 (frac 0.138), y_off=1135 (frac 0.272),
    # wm_w=2293 (frac 0.812 of frame_w). Apply same fractions to 小红书 frame.
    wm_img, _ = _get_standalone_watermark()
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

    # Restore decorative elements the letter paste may have whited out.
    # Title background decorations and bottom-left squares are inside the frame and get erased.
    XHS_DECORATIONS = [
        (570, 217, 1249, 487),   # title area: 3 colored rectangles + right accent
        (92, 1561, 189, 1661),   # bottom-left red/dark-red squares
    ]
    for bx0, by0, bx1, by1 in XHS_DECORATIONS:
        canvas.paste(canvas_before_letter.crop((bx0, by0, bx1, by1)), (bx0, by0))

    # Draw title text on the restored background (no fill needed — background is intact).
    if title_bbox:
        title_text = "签证捷报" if program_name in VISA_PROGRAMS else "移民捷报"
        font = ImageFont.truetype(str(FONT_PATH), XHS_FONT_SIZE)
        _draw_text_over(canvas, title_bbox, title_text, font, None, autofit=True)

    return canvas
