"""Dev helper: render the parsed P20 map to a PNG for visual orientation checks.

Not a pytest test. Run: ./.venv/bin/python tests/render_check.py
"""
import base64
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "xiaomi_cloud_map_extractor" / "connector" / "vacuums"))

from map_parser_xtl import XtlMapDataParser  # noqa: E402
from vacuum_map_parser_base.config.color import ColorsPalette  # noqa: E402
from vacuum_map_parser_base.config.drawable import Drawable  # noqa: E402
from vacuum_map_parser_base.config.image_config import ImageConfig  # noqa: E402
from vacuum_map_parser_base.config.size import Sizes  # noqa: E402

diag = json.loads((pathlib.Path(__file__).parent / "fixtures" / "diagnostics_p20.json").read_text())
raw = base64.b64decode(diag["data"]["device_data"]["map_data_raw"])
parser = XtlMapDataParser(ColorsPalette(), Sizes(), list(Drawable), ImageConfig(), [])
md = parser.parse(raw)
img = md.image.data
img = img.resize((img.width * 4, img.height * 4))
out = pathlib.Path(__file__).parent / "render_check.png"
img.save(out)
print("charger:", md.charger, "image:", md.image.dimensions.width, "x", md.image.dimensions.height, "saved:", out)
