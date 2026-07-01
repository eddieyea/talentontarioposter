#!/usr/bin/env python3
"""
Pre-render PSD templates to flat PNG images + JSON metadata at build time.
Run once locally or as a build step; the Flask app loads PNGs at request
time, avoiding psd-tools memory overhead during poster generation.

Output: templates_prerendered/{name}_base.png, {name}_meta.json, watermark.png
"""
import json
import sys
from pathlib import Path

from PIL import Image
from psd_tools import PSDImage
from psd_tools.api.layers import TypeLayer

TEMPLATES_DIR = Path("templates_psd")
OUT_DIR = Path("templates_prerendered")
OUT_DIR.mkdir(exist_ok=True)

LABEL_TEXTS = {"客户姓名", "移民项目", "获批时间", "目的地"}
FRAME_LAYER_NAME = "矩形 1"
XHS_TEMPLATE = "小红书捷报模板.psd"
WATERMARK_SOURCE_PSD = "境内学签.psd"


def find_frame_bbox(psd):
    for layer in psd.descendants():
        if layer.name == FRAME_LAYER_NAME:
            b = layer.bbox
            return (b.left, b.top, b.right, b.bottom) if hasattr(b, "left") else tuple(b)
    return None


def collect_text_bboxes(psd):
    results = {}
    target_groups = {"客户姓名", "移民项目", "获批时间"}

    def walk(layers):
        for layer in layers:
            if layer.name in target_groups and layer.name not in results:
                if hasattr(layer, "__iter__"):
                    for child in layer:
                        if isinstance(child, TypeLayer) and child.text not in LABEL_TEXTS:
                            b = child.bbox
                            results[layer.name] = (b.left, b.top, b.right, b.bottom) \
                                if hasattr(b, "left") else tuple(b)
                            break
            if hasattr(layer, "__iter__"):
                walk(layer)

    walk(psd)
    return results


def find_group_left_x(psd, group_name):
    def walk(layers):
        for layer in layers:
            if layer.name == group_name and hasattr(layer, "__iter__"):
                xs = []
                for child in layer:
                    if isinstance(child, TypeLayer) and child.text not in LABEL_TEXTS:
                        continue
                    b = child.bbox
                    xs.append(b.left if hasattr(b, "left") else b[0])
                return min(xs) if xs else None
            if hasattr(layer, "__iter__"):
                r = walk(layer)
                if r is not None:
                    return r
    return walk(psd)


def hide_value_layers(psd):
    INFO_BAR_GROUPS = {"客户姓名", "移民项目", "获批时间"}

    def walk(layers):
        for layer in layers:
            if getattr(layer, "name", "") in INFO_BAR_GROUPS and hasattr(layer, "__iter__"):
                for child in layer:
                    if isinstance(child, TypeLayer) and child.text != layer.name:
                        child.visible = False
            elif hasattr(layer, "__iter__") and not isinstance(layer, TypeLayer):
                walk(layer)

    walk(psd)


def find_watermark_layer(psd):
    for layer in psd:
        if layer.name == "白底logo":
            img = layer.composite()
            b = layer.bbox
            bbox = (b.left, b.top, b.right, b.bottom) if hasattr(b, "left") else tuple(b)
            return img, bbox
    return None, None


# ── 朋友圈 templates ──────────────────────────────────────────────────────────
for psd_filename, template_name, is_visa in [
    ("父母担保.psd", "移民捷报", False),
    ("境内学签.psd", "签证捷报", True),
]:
    print(f"Rendering {psd_filename} → {template_name} ...", flush=True)
    psd = PSDImage.open(str(TEMPLATES_DIR / psd_filename))

    frame_bbox = find_frame_bbox(psd)
    text_bboxes = collect_text_bboxes(psd)
    date_grp_x = find_group_left_x(psd, "获批时间") or 1907
    prog_val_x0 = text_bboxes["移民项目"][0] if "移民项目" in text_bboxes else 1353
    wm_img, wm_bbox = find_watermark_layer(psd)

    hide_value_layers(psd)

    title_bbox = None
    if is_visa:
        for layer in psd.descendants():
            if isinstance(layer, TypeLayer) and layer.text == "移民捷报" \
                    and layer.bbox[2] < psd.width:
                layer.visible = False
                b = layer.bbox
                title_bbox = (b.left, b.top, b.right, b.bottom) \
                    if hasattr(b, "left") else tuple(b)
                break

    base = psd.composite().convert("RGB")
    base.save(str(OUT_DIR / f"{template_name}_base.png"))
    print(f"  Saved {template_name}_base.png  {base.size}", flush=True)

    if wm_img:
        wm_img.convert("RGBA").save(str(OUT_DIR / f"{template_name}_watermark.png"))
        print(f"  Saved {template_name}_watermark.png  {wm_img.size}", flush=True)

    # Precompute label restore region crops so build_poster never needs a full canvas copy
    restore_regions = [
        (191,        1817, 539,          1925),
        (983,        1812, prog_val_x0,  1928),
        (date_grp_x, 1807, 2365,        1924),
    ]
    saved_restore = []
    for i, (bx0, by0, bx1, by1) in enumerate(restore_regions):
        if bx1 > bx0:
            base.crop((bx0, by0, bx1, by1)).save(
                str(OUT_DIR / f"{template_name}_restore_{i}.png")
            )
            saved_restore.append([bx0, by0, bx1, by1])

    meta = {
        "frame_bbox": list(frame_bbox) if frame_bbox else None,
        "text_bboxes": {k: list(v) for k, v in text_bboxes.items()},
        "date_grp_x": date_grp_x,
        "prog_val_x0": prog_val_x0,
        "watermark_bbox": list(wm_bbox) if wm_bbox else None,
        "title_bbox": list(title_bbox) if title_bbox else None,
        "restore_regions": saved_restore,
    }
    (OUT_DIR / f"{template_name}_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )
    del psd, base


# ── 小红书 template ───────────────────────────────────────────────────────────
print("Rendering 小红书 template ...", flush=True)
psd = PSDImage.open(str(TEMPLATES_DIR / XHS_TEMPLATE))

frame_bbox = find_frame_bbox(psd)
title_bbox = None
for layer in psd.descendants():
    if isinstance(layer, TypeLayer) and layer.text in ("移民捷报", "签证捷报"):
        b = layer.bbox
        title_bbox = (b.left, b.top, b.right, b.bottom) if hasattr(b, "left") else tuple(b)
        layer.visible = False
        break

base = psd.composite().convert("RGB")
base.save(str(OUT_DIR / "小红书_base.png"))
print(f"  Saved 小红书_base.png  {base.size}", flush=True)
(OUT_DIR / "小红书_meta.json").write_text(json.dumps({
    "frame_bbox": list(frame_bbox) if frame_bbox else None,
    "title_bbox": list(title_bbox) if title_bbox else None,
}, indent=2, ensure_ascii=False))
del psd, base

# Standalone watermark (used for 小红书 proportional placement)
print("Extracting watermark ...", flush=True)
psd = PSDImage.open(str(TEMPLATES_DIR / WATERMARK_SOURCE_PSD))
wm_img, _ = find_watermark_layer(psd)
if wm_img:
    wm_img.convert("RGBA").save(str(OUT_DIR / "watermark.png"))
    print(f"  Saved watermark.png  {wm_img.size}", flush=True)
del psd

print("\nAll templates pre-rendered.", flush=True)
