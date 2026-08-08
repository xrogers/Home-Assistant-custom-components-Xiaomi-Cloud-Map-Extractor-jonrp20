"""Parser for XTL (Jonr) vacuum maps: JSON + base64 + LZ4 occupancy grid."""

import base64
import json
from typing import Any

from PIL import Image

from vacuum_map_parser_base.config.color import SupportedColor
from vacuum_map_parser_base.map_data import ImageData, MapData, Path, Point
from vacuum_map_parser_base.map_data_parser import MapDataParser


def lz4_decompress_block(src: bytes, uncompressed_size: int) -> bytes:
    """Decompress an LZ4 *block* (not frame) in pure Python.

    Home Assistant OS has no C toolchain, so the compiled `lz4` package cannot
    be built there. The map's `map`/`trace` payloads are LZ4 block format; this
    implements decompression only (literal/match sequences), which is all we
    need. Verified byte-for-byte against the `lz4` library on real device data.
    """
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        literal_length = token >> 4
        if literal_length == 15:
            while True:
                b = src[i]
                i += 1
                literal_length += b
                if b != 255:
                    break
        out += src[i:i + literal_length]
        i += literal_length
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        match_length = (token & 0x0F) + 4  # 4 == LZ4 minimum match
        if (token & 0x0F) == 15:
            while True:
                b = src[i]
                i += 1
                match_length += b
                if b != 255:
                    break
        start = len(out) - offset
        for j in range(match_length):  # byte-by-byte to allow overlap
            out.append(out[start + j])
    if len(out) != uncompressed_size:
        raise ValueError(f"LZ4 block size mismatch: {len(out)} != {uncompressed_size}")
    return bytes(out)


def decode_field0(outer_json: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """Return (field0_meta, occupancy_grid_bytes) for the primary map field."""
    meta = json.loads(base64.b64decode(outer_json["fields"][0]))
    grid = lz4_decompress_block(base64.b64decode(meta["map"]), meta["lz4Len"])
    return meta, grid


# Device headings ("a") are centi-degrees; the parser base library wants degrees.
_CENTIDEGREES_PER_DEGREE = 100

# Occupancy grid value -> palette color name. Real captures use 0..8: 0 is
# unexplored, 1 is wall, 3 is plain floor, and 4 and up are per-room segment ids.
# Anything not listed here is treated as a room id (see _build_image), because an
# earlier version mapped only 0/1/2 and every other value fell through to the
# background: on a real map that silently hid 21239 of 34194 cells (62%), leaving
# bare wall outlines with no floor and no rooms.
_VALUE_COLORS = {
    0: SupportedColor.MAP_OUTSIDE,
    1: SupportedColor.MAP_WALL_V2,
    2: SupportedColor.MAP_INSIDE,
    3: SupportedColor.MAP_INSIDE,
}

# Grid values at or above this are per-room segment ids, colored via the palette's
# room colors so the existing GUI "room colors" option applies to them.
_FIRST_ROOM_VALUE = 4


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

        image = self._trim_and_scale(self._build_image(grid, width, height), width, height)

        # Coordinate system, pinned against a real xtl.vacuum.xm2216 capture: the
        # ANCHORS are swapped relative to their names, but the axes are not.
        #
        #   device x -> image COLUMN, anchored by yMax, range [yMax, yMax+width)
        #   device y -> image ROW,    anchored by xMin, range [xMin, xMin+height)
        #
        # So `xMin` is the minimum of the *y* range and `yMax` the minimum of the
        # *x* range. y increases upward in the picture, so y == xMin is the bottom
        # row, matching occupancy-grid row 0 (see _build_image).
        #
        #     img_x = x - yMax
        #     img_y = xMin + height - 1 - y
        #
        # which is exactly what ImageDimensions.to_img produces from an identity
        # transformation with top=xMin and left=yMax.
        #
        # How this was pinned: the reporter identified the dock as the upper of two
        # obstacles against the left wall (the lower one is an air purifier). That
        # obstacle occupies image rows 56..68 around columns 14..16. This mapping
        # puts the charger at (15, 61) and the docked robot at (14, 61) -- inside
        # it. Using xMin for x and yMax for y instead gives (25, 71), which is
        # down-and-right of the obstacle in open floor, and reading x as the row
        # gives column 174 on a 139-wide map, i.e. off-canvas and invisible.
        #
        # None of these are distinguishable on the synthetic fixture, whose window
        # is wide enough to keep every variant in bounds.
        map_data = MapData(0, 1)
        map_data.image = ImageData(
            width * height, x_min, y_max, height, width,
            self._image_config, image, lambda p: p,
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
        """Parse a {"x","y","a"?} position (dict or JSON string) into a Point.

        `a` is a heading in centi-degrees (chargePos reports 18000 for 180.00
        degrees), but the base library treats Point.a as DEGREES: _draw_vacuum
        computes `a / 180 * pi` and _draw_pieslice passes it straight to PIL. Left
        raw, 18000 wraps to 18000 % 360 == 0 and the dock is drawn facing exactly
        backwards; a real heading of 90 degrees arrives as 9000 and is drawn at
        9000 % 360 == 120. So convert to degrees here, at the boundary.
        """
        if not value:
            return None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                return None
        if not isinstance(value, dict) or "x" not in value or "y" not in value:
            return None
        angle = value.get("a")
        return Point(value["x"], value["y"], None if angle is None else angle / _CENTIDEGREES_PER_DEGREE)

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

    def _trim_and_scale(self, img: "Image.Image", width: int, height: int) -> "Image.Image":
        """Crop by the configured trim and resize by the configured scale.

        `ImageDimensions.to_img` multiplies marker coordinates by `scale` and
        offsets them by the trim, but the base library never touches the raster --
        producing it at the matching size is the parser's job. While this was
        missing, any scale other than 1 left the bitmap at 1:1 while markers were
        placed at scale x their true position, so the charger and robot drifted
        right and down in proportion to the scale. Trim had the same mismatch.

        The integer trim arithmetic mirrors `ImageData.__init__` exactly so the
        cropped raster and `dimensions` cannot disagree.
        """
        trim = self._image_config.trim
        left = int(trim.left * width / 100)
        right = int(trim.right * width / 100)
        top = int(trim.top * height / 100)
        bottom = int(trim.bottom * height / 100)
        if left or right or top or bottom:
            # to_img places img_y == 0 at the row `top` pixels below the untrimmed
            # top edge, so the crop is in image space, not device space.
            img = img.crop((left, top, width - right, height - bottom))

        scale = self._image_config.scale
        if scale != 1:
            img = img.resize(
                (int(img.width * scale), int(img.height * scale)), Image.NEAREST
            )
        return img

    def _build_image(self, grid: bytes, width: int, height: int) -> "Image.Image":
        """Render the occupancy grid.

        Grid row 0 carries the lowest device y (yMax), so it is drawn at the
        BOTTOM of the image to match the y-up marker mapping in `parse`. The
        bitmap and the markers must flip together or the charger detaches from
        the walls.
        """
        img = Image.new("RGBA", (width, height))
        px = img.load()
        colors = {v: self._palette.get_color(c) for v, c in _VALUE_COLORS.items()}
        for value in set(grid) - colors.keys():
            colors[value] = (
                self._palette.get_room_color(value)
                if value >= _FIRST_ROOM_VALUE
                else self._palette.get_color(SupportedColor.MAP_OUTSIDE)
            )
        for i, value in enumerate(grid):
            px[i % width, height - 1 - i // width] = colors[value]
        return img
