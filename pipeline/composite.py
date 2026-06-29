"""
Composite poster images from PSD templates + a masked letter image.

build_poster()     → 朋友圈 vertical poster (per-program PSD)
build_xhs_poster() → 小红书 square poster (single shared template)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from psd_tools import PSDImage
from psd_tools.api.layers import TypeLayer

TEMPLATES_DIR = Path(__file__).parent.parent / "templates_psd"
ASSETS_DIR = Path(__file__).parent.parent / "assets"
FONT_PATH = ASSETS_DIR / "SourceHanSansSC-Bold.otf"

FRAME_LAYER_NAME = "矩形 1"
LABEL_TEXTS = {"客户姓名", "移民项目", "获批时间", "目的地"}

# 朋友圈 info bar: 52pt at 200 DPI → 144px
WECHAT_FONT_SIZE = 144
WECHAT_BAR_COLOR = (187, 26, 39)

# 小红书 title: 115.5pt at 150 DPI → 241px
XHS_FONT_SIZE = 241
XHS_TITLE_BG_COLOR = (117, 22, 30)

TEXT_WHITE = (255, 255, 255)

# Programs whose poster title should read "签证捷报" instead of "移民捷报"
VISA_PROGRAMS = {"境内学签", "境外学签", "境外工签", "澳洲签证"}


def _collect_text_layers(psd) -> dict:
    """Return first-occurrence bboxes for 客户姓名 / 移民项目 / 获批时间 groups."""
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


def _paste_letter(canvas: Image.Image, frame_bbox: tuple, letter_image: Image.Image,
                  watermark=None, watermark_bbox=None):
    x0, y0, x1, y1 = frame_bbox
    fw, fh = x1 - x0, y1 - y0
    resized = letter_image.resize((fw, fh), Image.LANCZOS)
    canvas.paste(resized.convert(canvas.mode), (x0, y0))
    # Re-apply watermark on top of the pasted letter
    if watermark and watermark_bbox:
        wm = watermark.convert("RGBA")
        # Scale watermark proportionally to frame size if it came from a different PSD
        wm_src_w = watermark_bbox[2] - watermark_bbox[0]
        wm_src_h = watermark_bbox[3] - watermark_bbox[1]
        scale = min(fw / wm_src_w, fh / wm_src_h) if wm_src_w > fw or wm_src_h > fh else 1.0
        if scale != 1.0:
            wm = wm.resize((int(wm.width * scale), int(wm.height * scale)), Image.LANCZOS)
        r, g, b, a = wm.split()
        a = a.point(lambda p: int(p * 0.35))
        wm = Image.merge("RGBA", (r, g, b, a))
        # Centre watermark within the frame
        wx0 = x0 + (fw - wm.width) // 2
        wy0 = y0 + (fh - wm.height) // 2
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.alpha_composite(wm, dest=(wx0, wy0))
        canvas.paste(canvas_rgba.convert(canvas.mode))


def _fit_font(text: str, max_w: int, max_h: int, start_size: int) -> ImageFont.FreeTypeFont:
    """Return the largest font that fits text within max_w × max_h."""
    size = start_size
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    while size > 8:
        font = ImageFont.truetype(str(FONT_PATH), size)
        _, _, tw, th = dummy.textbbox((0, 0), text, font=font)
        if tw <= max_w and th <= max_h:
            return font
        size -= 4
    return ImageFont.truetype(str(FONT_PATH), 8)


def _draw_text_over(
    canvas: Image.Image,
    bbox: tuple,
    text: str,
    font: ImageFont.FreeTypeFont,
    bg_color: tuple,
    autofit: bool = False,
):
    """Fill bbox with bg_color then draw text vertically centred, left-aligned."""
    draw = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = bbox
    draw.rectangle([x0, y0, x1, y1], fill=bg_color)
    if autofit:
        font = _fit_font(text, x1 - x0, y1 - y0, font.size)
    _, _, tw, th = draw.textbbox((0, 0), text, font=font)
    draw.text((x0, y0 + (y1 - y0 - th) // 2), text, font=font, fill=TEXT_WHITE)


# ── 朋友圈 poster ─────────────────────────────────────────────────────────────

def build_poster(
    psd_filename: str,
    client_name: str,
    program_name: str,
    approved_date: str,
    letter_image: Image.Image,
) -> Image.Image:
    psd = PSDImage.open(str(TEMPLATES_DIR / psd_filename))

    text_bboxes = _collect_text_layers(psd)
    frame_bbox = _find_frame_bbox(psd)
    watermark, watermark_bbox = _find_watermark_layer(psd)
    canvas = psd.composite()

    font = ImageFont.truetype(str(FONT_PATH), WECHAT_FONT_SIZE)
    for group_name, new_text in (
        ("客户姓名", client_name),
        ("移民项目", program_name),
        ("获批时间", approved_date),
    ):
        if group_name in text_bboxes:
            _draw_text_over(canvas, text_bboxes[group_name], new_text, font, WECHAT_BAR_COLOR, autofit=True)

    if frame_bbox:
        _paste_letter(canvas, frame_bbox, letter_image, watermark, watermark_bbox)

    return canvas


# ── 小红书 poster ──────────────────────────────────────────────────────────────

XHS_TEMPLATE = "小红书捷报模板.psd"
# Borrow watermark from this 朋友圈 PSD (all share the same 白底logo layer)
_WATERMARK_SOURCE_PSD = "境内学签.psd"


def _get_standalone_watermark():
    """Extract watermark layer from a 朋友圈 PSD and return (image, bbox)."""
    psd = PSDImage.open(str(TEMPLATES_DIR / _WATERMARK_SOURCE_PSD))
    return _find_watermark_layer(psd)


def build_xhs_poster(
    program_name: str,
    letter_image: Image.Image,
) -> Image.Image:
    psd = PSDImage.open(str(TEMPLATES_DIR / XHS_TEMPLATE))

    frame_bbox = _find_frame_bbox(psd)

    # Find the title TypeLayer ("移民捷报")
    title_bbox = None
    for layer in psd.descendants():
        if isinstance(layer, TypeLayer) and layer.text in ("移民捷报", "签证捷报"):
            title_bbox = layer.bbox
            break

    canvas = psd.composite()

    # Get watermark from 朋友圈 PSD and scale it to fit the 小红书 frame
    wm_img, wm_bbox = _get_standalone_watermark()

    # Paste letter with watermark
    if frame_bbox:
        _paste_letter(canvas, frame_bbox, letter_image, wm_img, wm_bbox)

    # Overwrite title with correct wording
    if title_bbox:
        title_text = "签证捷报" if program_name in VISA_PROGRAMS else "移民捷报"
        font = ImageFont.truetype(str(FONT_PATH), XHS_FONT_SIZE)
        _draw_text_over(canvas, title_bbox, title_text, font, XHS_TITLE_BG_COLOR, autofit=True)

    return canvas
