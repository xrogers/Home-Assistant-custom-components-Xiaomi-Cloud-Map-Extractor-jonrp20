"""Parser for XTL (Jonr) vacuum maps: JSON + base64 + LZ4 occupancy grid."""

import base64
import json
from typing import Any

import lz4.block
from PIL import Image

from vacuum_map_parser_base.config.color import SupportedColor
from vacuum_map_parser_base.map_data import ImageData, MapData, Path, Point
from vacuum_map_parser_base.map_data_parser import MapDataParser


def decode_field0(outer_json: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """Return (field0_meta, occupancy_grid_bytes) for the primary map field."""
    meta = json.loads(base64.b64decode(outer_json["fields"][0]))
    grid = lz4.block.decompress(base64.b64decode(meta["map"]), uncompressed_size=meta["lz4Len"])
    return meta, grid


# occupancy grid value -> palette color name
_VALUE_COLORS = {
    0: SupportedColor.MAP_OUTSIDE,
    1: SupportedColor.MAP_WALL_V2,
    2: SupportedColor.MAP_INSIDE,
}


class XtlMapDataParser(MapDataParser):
    """XTL (Jonr) map parser."""

    def unpack_map(self, raw_encoded: bytes, *args, **kwargs) -> bytes:
        # The downloaded artifact is already the plain JSON map; nothing to inflate.
        return raw_encoded

    def parse(self, raw: bytes, *args, **kwargs) -> MapData:
        outer = json.loads(raw)
        meta, grid = decode_field0(outer)
        width, height = meta["width"], meta["height"]
        x_min, y_max = meta["xMin"], meta["yMax"]

        image = self._build_image(grid, width, height)

        # Coordinate system, confirmed against real device data: the charger
        # (chargePos) and the live vacuum position (fields[2]) are both reported
        # at y just above yMax, landing near the top of the occupancy grid. So
        # the map window's top-left is (xMin, yMax) with y increasing DOWNWARD,
        # and a device point (x, y) maps to pixel (x - xMin, y - yMax). The grid
        # is stored row 0 = top, matching this.
        #
        # The base library's ImageData.to_img assumes y-up
        # (y_img = height - (p.y - top) - 1). To make it yield (x - xMin, y - yMax)
        # we pre-flip y in the transformation and use top=0, left=xMin.
        def to_library_space(p: Point) -> Point:
            return Point(p.x, (y_max + height - 1) - p.y, p.a)

        map_data = MapData(0, 1)
        map_data.image = ImageData(
            width * height, 0, x_min, height, width,
            self._image_config, image, to_library_space,
        )

        map_data.charger = self._parse_position(meta.get("chargePos"))
        map_data.vacuum_position = self._parse_position(self._field(outer, 2))
        map_data.path = self._decode_path(outer)

        if map_data.image is not None and not map_data.image.is_empty:
            self._image_generator.draw_map(map_data)
        return map_data

    @staticmethod
    def _field(outer: dict[str, Any], index: int) -> Any:
        fields = outer.get("fields") or []
        return fields[index] if index < len(fields) else None

    @staticmethod
    def _parse_position(value: Any) -> Point | None:
        """Parse a {"x","y","a"?} position (dict or JSON string) into a Point."""
        if not value:
            return None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                return None
        if not isinstance(value, dict) or "x" not in value or "y" not in value:
            return None
        return Point(value["x"], value["y"], value.get("a"))

    def _decode_path(self, outer: dict[str, Any]) -> Path | None:
        """Best-effort decode of the vacuum path from fields[1].

        Field 1 (when present) is a JSON header
        {traceId, start, totalCount, trace, lz4Len}; `trace` is base64 -> LZ4 ->
        `lz4Len` bytes. On the real device this decompresses to exactly
        `totalCount` bytes (1 byte per point) -- i.e. NOT x/y coordinate pairs
        but a compact per-step encoding (direction/delta) whose layout is not yet
        reverse-engineered. Until that encoding is understood we cannot produce
        real Point coordinates, so path rendering is deferred and this returns
        None. It must never raise (that would break map parsing).
        """
        try:
            field = self._field(outer, 1)
            if not field:
                return None
            header = json.loads(base64.b64decode(field))
            if "trace" not in header:
                return None
            # Structure recognised (trace/lz4Len), but the 1-byte-per-point
            # encoding is not yet decoded -- defer rather than emit bogus points.
            return None
        except Exception:
            return None

    def _build_image(self, grid: bytes, width: int, height: int) -> "Image.Image":
        img = Image.new("RGBA", (width, height))
        px = img.load()
        outside = self._palette.get_color(SupportedColor.MAP_OUTSIDE)
        for i, value in enumerate(grid):
            color_name = _VALUE_COLORS.get(value)
            px[i % width, i // width] = self._palette.get_color(color_name) if color_name else outside
        return img
