import json
import numpy as np
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

PII_CONFIG = Path(__file__).parent.parent / "config" / "pii_regions.json"
MASK_COLOR = (213, 213, 213)  # #D5D5D5 light grey

# Pixels above the Canada flag to keep as top margin (matches designer's reference placement)
FLAG_TOP_MARGIN_PX = 57  # at 300 DPI: flag lands 57px from top of cropped image


def _find_flag_top(img: Image.Image) -> int:
    """Find the top-most row containing Canada flag red pixels in the top half of the image."""
    arr = np.array(img)
    half = arr.shape[0] // 2
    area = arr[:half, :img.width // 2]  # top-left quadrant only
    red = (area[:, :, 0] > 170) & (area[:, :, 1] < 80) & (area[:, :, 2] < 80)
    ys = np.where(red.any(axis=1))[0]
    return int(ys[0]) if len(ys) else 0


def render_and_mask(pdf_path: str, dpi: int = 300) -> Image.Image:
    """Render page 1, mask PII, and crop top white space so Canada flag is near top."""
    doc = fitz.open(pdf_path)
    page = doc[0]

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()

    # Apply PII masks before cropping (coordinates are in full-page space)
    scale = dpi / 72
    regions = json.loads(PII_CONFIG.read_text())["ircc_standard"]
    draw = ImageDraw.Draw(img)
    for r in regions:
        box = (
            int(r["x0"] * scale),
            int(r["y0"] * scale),
            int(r["x1"] * scale),
            int(r["y1"] * scale),
        )
        draw.rectangle(box, fill=MASK_COLOR)

    # Crop top white space: detect Canada flag, leave FLAG_TOP_MARGIN_PX above it
    flag_top = _find_flag_top(img)
    crop_top = max(0, flag_top - FLAG_TOP_MARGIN_PX)
    if crop_top > 0:
        img = img.crop((0, crop_top, img.width, img.height))

    return img
