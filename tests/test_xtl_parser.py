import json
from map_parser_xtl import decode_field0


def test_decode_field0_dimensions(raw_map_bytes):
    outer = json.loads(raw_map_bytes)
    meta, grid = decode_field0(outer)
    assert len(grid) == meta["width"] * meta["height"] == meta["lz4Len"]
    assert set(grid) <= {0, 1, 2}


from vacuum_map_parser_base.config.color import ColorsPalette, SupportedColor
from vacuum_map_parser_base.config.drawable import Drawable
from vacuum_map_parser_base.config.image_config import ImageConfig
from vacuum_map_parser_base.config.size import Sizes
from vacuum_map_parser_base.map_data import Point


def _parser():
    from map_parser_xtl import XtlMapDataParser
    return XtlMapDataParser(ColorsPalette(), Sizes(), list(Drawable), ImageConfig(), [])


def test_parse_produces_nonempty_image(raw_map_bytes, field0):
    md = _parser().parse(raw_map_bytes)
    assert md.image is not None and not md.image.is_empty
    assert md.image.dimensions.width == field0["width"]
    assert md.image.dimensions.height == field0["height"]


def test_parse_reads_charger_from_json_string_chargepos(raw_map_bytes):
    md = _parser().parse(raw_map_bytes)
    assert md.charger == Point(388, 398, 180.0)


def test_headings_are_converted_from_centidegrees_to_degrees(raw_map_bytes):
    # The device reports heading in centi-degrees: chargePos "a": 18000 is 180.00
    # degrees. The base library treats Point.a as DEGREES -- _draw_vacuum computes
    # a / 180 * pi and _draw_pieslice feeds it straight to PIL -- so passing 18000
    # through raw wrapped to 18000 % 360 == 0 and drew the dock facing exactly
    # backwards. Any real heading was mangled the same way (9000 -> 120 degrees).
    md = _parser().parse(raw_map_bytes)
    assert md.charger.a == 180.0
    assert md.vacuum_position.a == 0.06


def test_build_image_maps_grid_values_to_palette_colors(raw_map_bytes):
    outer = json.loads(raw_map_bytes)
    meta, grid = decode_field0(outer)
    width, height = meta["width"], meta["height"]

    # one grid index for each occupancy value present in the fixture
    samples = {}
    for i, value in enumerate(grid):
        if value not in samples:
            samples[value] = i
    assert set(samples) == {0, 1, 2}

    palette = ColorsPalette()
    expected = {
        0: palette.get_color(SupportedColor.MAP_OUTSIDE),
        1: palette.get_color(SupportedColor.MAP_WALL_V2),
        2: palette.get_color(SupportedColor.MAP_INSIDE),
    }

    # Assert on a freshly built image (no draw_map overlays / rotation) so the
    # value -> color mapping is verified directly on decoded grid data.
    img = _parser()._build_image(grid, width, height)
    px = img.load()
    for value, i in samples.items():
        # palette colors are RGB; PIL stores them in the RGBA image with alpha 255
        want = tuple(expected[value]) + (255,) if len(expected[value]) == 3 else tuple(expected[value])
        # grid row 0 is the BOTTOM of the picture - see _expected_pixel
        assert px[i % width, height - 1 - i // width] == want


def _rgba(color) -> tuple:
    return tuple(color) + (255,) if len(color) == 3 else tuple(color)


def test_build_image_puts_grid_row0_at_image_bottom():
    # Uses a hand-built asymmetric grid on purpose: the committed fixture is a
    # plain rectangle and is perfectly symmetric top-to-bottom (rows == rows[::-1]),
    # so no assertion against it can distinguish a vertically flipped bitmap.
    # Grid row 0 carries the lowest device y (yMax) and must therefore render at
    # the BOTTOM, so the bitmap agrees with the marker mapping in _expected_pixel.
    width, height = 3, 2
    grid = bytes([1, 1, 1, 2, 2, 2])  # row 0 = wall, row 1 = inside
    px = _parser()._build_image(grid, width, height).load()

    palette = ColorsPalette()
    assert px[0, height - 1] == _rgba(palette.get_color(SupportedColor.MAP_WALL_V2))
    assert px[0, 0] == _rgba(palette.get_color(SupportedColor.MAP_INSIDE))


def test_build_image_renders_floor_and_room_values():
    # Real device grids use values 0..8: 0 unknown, 1 wall, 3 floor, 4+ room ids.
    # Only 0/1/2 were mapped, so on a real capture 21239 of 34194 cells (62%) fell
    # through to the background colour and the user saw bare wall outlines with no
    # floor and no rooms.
    width, height = 3, 3
    grid = bytes([0, 1, 2, 3, 4, 5, 6, 7, 8])  # row 0 = [0,1,2], row 2 = [6,7,8]
    px = _parser()._build_image(grid, width, height).load()

    palette = ColorsPalette()
    # grid row 0 renders at the bottom, so grid row r -> image row height-1-r
    assert px[1, 2] == _rgba(palette.get_color(SupportedColor.MAP_WALL_V2))  # value 1
    assert px[0, 1] == _rgba(palette.get_color(SupportedColor.MAP_INSIDE))  # value 3 = floor
    assert px[1, 1] == _rgba(palette.get_room_color(4))  # value 4 = room 4
    assert px[2, 0] == _rgba(palette.get_room_color(8))  # value 8 = room 8
    assert px[0, 2] == _rgba(palette.get_color(SupportedColor.MAP_OUTSIDE))  # value 0


def test_parse_reads_vacuum_position_from_field2(raw_map_bytes):
    # fields[2] holds the live vacuum position {"x","y","a","i"} on the real device
    md = _parser().parse(raw_map_bytes)
    assert md.vacuum_position == Point(387, 399, 0.06)


def _expected_pixel(field0: dict, x: int, y: int) -> tuple[int, int]:
    """Where a device point must land in the rendered image.

    The device's axes are swapped relative to the picture: device `x` is the image
    ROW (anchored by xMin, increasing upward so x == xMin is the bottom row), and
    device `y` is the image COLUMN (anchored by yMax). Confirmed against a real
    xtl.vacuum.xm2216 capture -- see docs/findings-2026-08-08-xtl-coordinates.md.
    """
    return y - field0["yMax"], field0["xMin"] + field0["height"] - 1 - x


def test_charger_maps_to_exact_pixel(raw_map_bytes, field0):
    # Asserting the EXACT pixel, not merely "somewhere inside the image". The
    # weaker check this replaced was satisfied by the correct mapping *and* by its
    # vertical mirror (img_y 134 vs 19, summing to height-1), which is why the
    # flipped map in 264f7a0 shipped green.
    md = _parser().parse(raw_map_bytes)
    p = md.charger.to_img(md.image.dimensions)
    assert (p.x, p.y) == _expected_pixel(field0, 388, 398)


def test_vacuum_position_maps_to_exact_pixel(raw_map_bytes, field0):
    md = _parser().parse(raw_map_bytes)
    p = md.vacuum_position.to_img(md.image.dimensions)
    assert (p.x, p.y) == _expected_pixel(field0, 387, 399)


def test_markers_land_inside_the_image(raw_map_bytes, field0):
    md = _parser().parse(raw_map_bytes)
    for point in (md.charger, md.vacuum_position):
        p = point.to_img(md.image.dimensions)
        assert 0 <= p.x < field0["width"]
        assert 0 <= p.y < field0["height"]


def test_path_deferred_when_field1_present(raw_map_bytes):
    # fields[1] is present on the real device (JSON header with a "trace" blob),
    # but its 1-byte-per-point encoding is not yet reverse-engineered, so path
    # decoding is intentionally deferred to None (never raising).
    outer = json.loads(raw_map_bytes)
    assert outer["fields"][1]  # guard: fixture really does carry a path field
    md = _parser().parse(raw_map_bytes)
    assert md.path is None
