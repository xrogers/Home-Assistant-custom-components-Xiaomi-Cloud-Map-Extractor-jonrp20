#!/usr/bin/env python3
"""Render the XTL occupancy grid in all four orientations so a human can pick
the one that matches the Xiaomi Home app.

Why this exists
---------------
The XTL map window is described by `xMin`, `yMax`, `width`, `height`. Whether
device y grows upward or downward -- and therefore whether occupancy-grid row 0
is the top or the bottom of the picture -- was never established against a real
device. The committed fixture is synthetic, and its only orientation assertion
("the charger lands somewhere inside the image") holds for a mapping *and* its
vertical mirror, so the test suite cannot tell the two apart.

Run this against a diagnostics download from a real vacuum, compare the four
PNGs against the app, and report which filename matches. That answer pins the
convention; then the parser can be fixed with a test that actually constrains it.

Usage
-----
    python scripts/orientation_probe.py <diagnostics.json> [-o outdir]

Get <diagnostics.json> from Home Assistant:
    Settings -> Devices & Services -> Xiaomi Cloud Map Extractor
    -> the three-dot menu on the device -> "Download diagnostics".

Each output PNG is upscaled and annotated:
    magenta square = charger (chargePos)   cyan circle = vacuum (fields[2])
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import sys

from PIL import Image, ImageDraw

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(
    0, str(REPO / "custom_components" / "xiaomi_cloud_map_extractor" / "connector" / "vacuums")
)

from map_parser_xtl import decode_field0  # noqa: E402

# Grid value -> RGB. Deliberately not the HA palette: high contrast reads better
# when eyeballing orientation against a phone screenshot.
VALUE_RGB = {0: (32, 32, 32), 1: (235, 235, 235), 2: (60, 110, 200)}

# name -> (flip_x, flip_y) applied to both the bitmap and the markers
ORIENTATIONS = {
    "a_asis": (False, False),
    "b_flip_vertical": (False, True),
    "c_flip_horizontal": (True, False),
    "d_rotate_180": (True, True),
}


def load_outer(path: pathlib.Path) -> dict:
    """Accept either a diagnostics download or a bare map JSON."""
    blob = json.loads(path.read_text())
    raw = blob.get("data", {}).get("device_data", {}).get("map_data_raw")
    if raw is not None:
        return json.loads(base64.b64decode(raw))
    if "fields" in blob:
        return blob
    raise SystemExit(
        f"{path}: no map found. Expected diagnostics JSON with "
        "data.device_data.map_data_raw, or a raw map JSON with a 'fields' key."
    )


def parse_pos(value) -> tuple[int, int] | None:
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, dict) or "x" not in value or "y" not in value:
        return None
    return int(value["x"]), int(value["y"])


def render(grid: bytes, meta: dict, flip_x: bool, flip_y: bool, scale: int) -> Image.Image:
    width, height = meta["width"], meta["height"]
    img = Image.new("RGB", (width, height), VALUE_RGB[0])
    px = img.load()
    for i, value in enumerate(grid):
        x, y = i % width, i // width
        if flip_x:
            x = width - 1 - x
        if flip_y:
            y = height - 1 - y
        px[x, y] = VALUE_RGB.get(value, VALUE_RGB[0])

    img = img.resize((width * scale, height * scale), Image.NEAREST)
    draw = ImageDraw.Draw(img)

    # Markers use the same window offset the parser uses for x, and the plain
    # y-down offset for y; the flips above then cover every combination.
    for value, color, shape in (
        (meta.get("chargePos"), (255, 0, 220), "square"),
        (_field(meta["_outer"], 2), (0, 230, 230), "circle"),
    ):
        pos = parse_pos(value)
        if pos is None:
            continue
        mx, my = pos[0] - meta["xMin"], pos[1] - meta["yMax"]
        if flip_x:
            mx = width - 1 - mx
        if flip_y:
            my = height - 1 - my
        cx, cy = (mx + 0.5) * scale, (my + 0.5) * scale
        r = max(4, scale * 2)
        box = (cx - r, cy - r, cx + r, cy + r)
        if shape == "square":
            draw.rectangle(box, outline=color, width=max(2, scale // 2))
        else:
            draw.ellipse(box, outline=color, width=max(2, scale // 2))
    return img


def _field(outer: dict, index: int):
    fields = outer.get("fields") or []
    return fields[index] if index < len(fields) else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("diagnostics", type=pathlib.Path)
    ap.add_argument("-o", "--outdir", type=pathlib.Path, default=pathlib.Path("orientation_probe"))
    ap.add_argument("--scale", type=int, default=4, help="pixel upscale factor (default 4)")
    args = ap.parse_args()

    outer = load_outer(args.diagnostics)
    meta, grid = decode_field0(outer)
    meta["_outer"] = outer

    args.outdir.mkdir(parents=True, exist_ok=True)
    print(
        f"window {meta['width']}x{meta['height']} "
        f"xMin={meta['xMin']} yMax={meta['yMax']} resolution={meta.get('resolution')}"
    )
    print(f"chargePos={meta.get('chargePos')!r}  vacuum={_field(outer, 2)!r}")

    for name, (flip_x, flip_y) in ORIENTATIONS.items():
        path = args.outdir / f"{name}.png"
        render(grid, meta, flip_x, flip_y, args.scale).save(path)
        print(f"wrote {path}")

    print(
        "\n'a_asis' is what the integration renders today. Compare all four against "
        "the Xiaomi Home app and report which one matches, including whether the "
        "charger marker sits in the right room."
    )


if __name__ == "__main__":
    main()
