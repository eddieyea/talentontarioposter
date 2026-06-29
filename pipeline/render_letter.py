import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

PII_CONFIG = Path(__file__).parent.parent / "config" / "pii_regions.json"
MASK_COLOR = (176, 176, 176)  # #B0B0B0 grey


def render_and_mask(pdf_path: str, dpi: int = 300) -> Image.Image:
    """Render page 1 of the PDF at `dpi`, mask PII regions, return PIL Image."""
    doc = fitz.open(pdf_path)
    page = doc[0]

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()

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

    return img
