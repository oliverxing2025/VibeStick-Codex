#!/usr/bin/env python3
"""Generate square PNG variants and LVGL ARGB8888 C assets."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


SIZES = (40, 32)
ALPHA_TRIM_THRESHOLD = 8


def _crop_visible_square(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value >= ALPHA_TRIM_THRESHOLD else 0)
    bounds = mask.getbbox()
    if bounds is None:
        raise SystemExit("Source icon has no visible pixels")

    left, top, right, bottom = bounds
    size = max(right - left, bottom - top)
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    square_left = max(0, min(image.width - size, center_x - size // 2))
    square_top = max(0, min(image.height - size, center_y - size // 2))
    return image.crop((square_left, square_top, square_left + size, square_top + size))


def _bgra_bytes(image: Image.Image) -> bytes:
    rgba = image.convert("RGBA").tobytes()
    output = bytearray(len(rgba))
    for offset in range(0, len(rgba), 4):
        red, green, blue, alpha = rgba[offset : offset + 4]
        output[offset : offset + 4] = bytes((blue, green, red, alpha))
    return bytes(output)


def _format_bytes(data: bytes) -> str:
    lines = []
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        lines.append("    " + ", ".join(f"0x{value:02x}" for value in chunk) + ",")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    source = Image.open(args.source).convert("RGBA")
    if source.width != source.height:
        raise SystemExit(f"Source icon must be square, got {source.width}x{source.height}")
    source = _crop_visible_square(source)

    asset_dir = args.project_root / "firmware/sticks3/assets/providers/codex"
    generated_dir = args.project_root / "firmware/sticks3/generated"
    asset_dir.mkdir(parents=True, exist_ok=True)

    images: dict[int, Image.Image] = {}
    for size in SIZES:
        image = source.resize((size, size), Image.Resampling.LANCZOS)
        image.save(asset_dir / f"icon-{size}.png", optimize=True)
        images[size] = image

    header = """#pragma once

#include "lvgl.h"

extern const lv_image_dsc_t vibe_stick_provider_codex_icon_40;
extern const lv_image_dsc_t vibe_stick_provider_codex_icon_32;
"""
    (generated_dir / "vibe_stick_ui_assets.h").write_text(header)

    sections = ['#include "vibe_stick_ui_assets.h"', ""]
    for size in SIZES:
        symbol = f"vibe_stick_provider_codex_icon_{size}"
        data = _bgra_bytes(images[size])
        sections.extend(
            [
                f"static const uint8_t {symbol}_data[] = {{",
                _format_bytes(data),
                "};",
                f"const lv_image_dsc_t {symbol} = {{",
                "    .header = {",
                "        .magic = LV_IMAGE_HEADER_MAGIC,",
                "        .cf = LV_COLOR_FORMAT_ARGB8888,",
                "        .flags = 0,",
                f"        .w = {size},",
                f"        .h = {size},",
                f"        .stride = {size * 4},",
                "        .reserved_2 = 0,",
                "    },",
                f"    .data_size = sizeof({symbol}_data),",
                f"    .data = {symbol}_data,",
                "    .reserved = NULL,",
                "};",
                "",
            ]
        )
    (generated_dir / "vibe_stick_ui_assets.c").write_text("\n".join(sections))


if __name__ == "__main__":
    main()
