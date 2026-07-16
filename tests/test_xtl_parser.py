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
    assert md.charger == Point(388, 398, 18000)


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
    # value -> color mapping is verified directly on real decoded grid data.
    img = _parser()._build_image(grid, width, height)
    px = img.load()
    for value, i in samples.items():
        # palette colors are RGB; PIL stores them in the RGBA image with alpha 255
        want = tuple(expected[value]) + (255,) if len(expected[value]) == 3 else tuple(expected[value])
        assert px[i % width, i // width] == want


def test_parse_reads_vacuum_position_from_field2(raw_map_bytes):
    # fields[2] holds the live vacuum position {"x","y","a","i"} on the real device
    md = _parser().parse(raw_map_bytes)
    assert md.vacuum_position == Point(387, 399, 6)


def test_charger_maps_onto_the_image(raw_map_bytes, field0):
    # The charger (and vacuum) sit near the top of the window: with the y-down
    # transform (pixel = x-xMin, y-yMax) they must land INSIDE the image, not
    # off-canvas as the earlier y-up transform produced (y = -19).
    md = _parser().parse(raw_map_bytes)
    p = md.charger.to_img(md.image.dimensions)
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
