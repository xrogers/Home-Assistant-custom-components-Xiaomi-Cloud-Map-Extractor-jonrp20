#!/usr/bin/env python3
"""Explain why the charger / vacuum markers are (or aren't) visible on the map.

Runs the real parse pipeline using the options from YOUR config entry -- not the
defaults -- and reports, in order, every reason a marker can fail to appear:

  1. the drawable is switched off in options
  2. the device didn't report the position at all (no chargePos / empty fields[2])
  3. the marker is drawn but too small to notice at the configured scale
  4. the vacuum's opaque disc is sitting on top of the charger (robot docked)

Usage
-----
    python scripts/marker_diagnose.py <diagnostics.json>

Get <diagnostics.json> from Home Assistant:
    Settings -> Devices & Services -> Xiaomi Cloud Map Extractor
    -> the three-dot menu on the device -> "Download diagnostics".
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(
    0, str(REPO / "custom_components" / "xiaomi_cloud_map_extractor" / "connector" / "vacuums")
)

from map_parser_xtl import XtlMapDataParser, decode_field0  # noqa: E402
from vacuum_map_parser_base.config.color import ColorsPalette, SupportedColor  # noqa: E402
from vacuum_map_parser_base.config.drawable import Drawable  # noqa: E402
from vacuum_map_parser_base.config.image_config import ImageConfig, TrimConfig  # noqa: E402
from vacuum_map_parser_base.config.size import Size, Sizes  # noqa: E402


def build_from_options(options: dict):
    """Rebuild palette/drawables/sizes/image_config exactly as __init__.py does."""
    ic = options.get("image_config") or {}
    image_config = ImageConfig(
        ic.get("scale", 1),
        ic.get("rotate", 0),
        TrimConfig(
            ic.get("trim_left", 0), ic.get("trim_right", 0),
            ic.get("trim_top", 0), ic.get("trim_bottom", 0),
        ),
    )
    colors = options.get("colors") or {}
    palette = ColorsPalette(
        {SupportedColor(k): tuple(v) for k, v in colors.items()},
        {k: tuple(v) for k, v in (options.get("room_colors") or {}).items()},
    ) if colors else ColorsPalette()

    drawable_values = options.get("drawables")
    drawables = [Drawable(d) for d in drawable_values] if drawable_values else list(Drawable)

    size_values = options.get("sizes") or {}
    sizes = Sizes({Size(k): v for k, v in size_values.items()}) if size_values else Sizes()
    return palette, drawables, image_config, sizes


def rgba(color) -> tuple:
    return tuple(color) + (255,) if len(color) == 3 else tuple(color)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("diagnostics", type=pathlib.Path)
    args = ap.parse_args()

    blob = json.loads(args.diagnostics.read_text())
    data = blob.get("data", blob)
    entry = data.get("config_entry_data") or {}
    options = entry.get("options") or {}
    raw_b64 = (data.get("device_data") or {}).get("map_data_raw")
    if raw_b64 is None:
        raise SystemExit("no device_data.map_data_raw in this diagnostics file")

    outer = json.loads(base64.b64decode(raw_b64))
    meta, _grid = decode_field0(outer)
    fields = outer.get("fields") or []
    field2 = fields[2] if len(fields) > 2 else None

    print(f"model            : {(entry.get('data') or {}).get('model')}")
    print(f"options present  : {'yes' if options else 'NO - falling back to library defaults'}")

    palette, drawables, image_config, sizes = build_from_options(options)

    print("\n1. drawables")
    for d in (Drawable.CHARGER, Drawable.VACUUM_POSITION):
        on = d in drawables
        print(f"   {d.value:16s} {'ON' if on else 'OFF  <-- enable it in Configure -> Drawables'}")

    print("\n2. device reported positions")
    print(f"   chargePos      : {meta.get('chargePos')!r}"
          + ("" if meta.get("chargePos") else "   <-- device sent none, nothing to draw"))
    print(f"   fields[2]      : {field2!r}"
          + ("" if field2 else "   <-- device sent none, nothing to draw"))

    print("\n3. geometry / size")
    print(f"   scale          : {image_config.scale}")
    print(f"   vacuum_radius  : {sizes.get_size(Size.VACUUM_RADIUS)}")
    print(f"   charger_radius : {sizes.get_size(Size.CHARGER_RADIUS)}")
    print(f"   map window     : {meta['width']}x{meta['height']} px before scale")

    md = XtlMapDataParser(palette, sizes, drawables, image_config, []).parse(
        json.dumps(outer).encode()
    )
    if md.charger is not None:
        print(f"   charger pixel  : {md.charger.to_img(md.image.dimensions)}")
    if md.vacuum_position is not None:
        print(f"   vacuum pixel   : {md.vacuum_position.to_img(md.image.dimensions)}")

    print("\n4. what actually landed in the rendered PNG")
    counts: dict[tuple, int] = {}
    for px in md.image.data.convert("RGBA").get_flattened_data():
        counts[px] = counts.get(px, 0) + 1
    robo = rgba(palette.get_color(SupportedColor.ROBO))
    print(f"   distinct colours: {len(counts)}")
    print(f"   robot colour {robo} -> {counts.get(robo, 0)} px"
          + ("" if counts.get(robo) else "   <-- robot NOT visible"))
    charger_fill = palette.get_color(SupportedColor.CHARGER)
    print(f"   charger fill {tuple(charger_fill)} has alpha "
          f"{charger_fill[3] if len(charger_fill) > 3 else 255}; it is alpha-blended, so look for a "
          "tinted patch rather than an exact colour match")

    if md.charger and md.vacuum_position:
        c = md.charger.to_img(md.image.dimensions)
        v = md.vacuum_position.to_img(md.image.dimensions)
        gap = max(abs(c.x - v.x), abs(c.y - v.y))
        if gap <= sizes.get_size(Size.VACUUM_RADIUS):
            print(f"\n   NOTE: charger and robot are {gap:g} px apart, within the robot radius."
                  "\n   The robot's opaque disc is drawn after the charger and hides it."
                  "\n   Send the robot away from the dock and re-download diagnostics.")

    out = args.diagnostics.with_suffix(".rendered.png")
    md.image.data.save(out)
    print(f"\nwrote {out} - this is exactly what the integration serves.")


if __name__ == "__main__":
    main()
