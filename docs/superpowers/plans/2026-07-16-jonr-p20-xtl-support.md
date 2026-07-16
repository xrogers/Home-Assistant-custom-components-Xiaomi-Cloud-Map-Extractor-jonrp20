# Jonr P20 (`xtl.vacuum.xm2216`) Map Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add live-map rendering for the Jonr P20 Pro (`xtl.vacuum.xm2216`) to a personal fork of the Xiaomi Cloud Map Extractor.

**Architecture:** The component already downloads the raw map from Xiaomi cloud for any model; only a parser is missing. We add a new `VacuumApi.XTL`, register the model, vendor an `XtlMapDataParser` that turns the device's JSON+base64+LZ4 map into a `vacuum_map_parser_base.MapData`, and wire it into a new `XtlCloudVacuum` platform class. Then deploy the fork to Home Assistant over SSH and verify end-to-end.

**Tech Stack:** Python 3.14, Home Assistant custom component, `vacuum-map-parser-base==0.1.5`, `lz4`, Pillow, numpy (test-only), pytest.

## Global Constraints

- Baseline: upstream tag `v3.0.0-alpha-24`, already committed in this repo.
- Parser library API is pinned: `vacuum-map-parser-base==0.1.5`. Match its exact signatures (below).
- New runtime dependency `lz4` MUST be added to `custom_components/xiaomi_cloud_map_extractor/manifest.json` `requirements`.
- Follow the existing per-vendor pattern exactly (mirror `connector/vacuums/vacuum_viomi.py`).
- Do NOT edit any other vendor's parser or class.
- Component path prefix (call it `CC`): `custom_components/xiaomi_cloud_map_extractor`.
- Occupancy grid semantics (verified from the real sample): pixel value `0` = outside/unknown, `1` = wall, `2` = inside/floor.
- Field 0 JSON keys: `expanded, totalWidth, totalHeight, width, height, xMin, yMax, resolution, timestamp, map, lz4Len, direction, chargePos{x,y,a}`. `map` is base64 → LZ4 block → `width*height` bytes. `chargePos` is in absolute map units.

### Verified library interfaces (from `vacuum-map-parser-base==0.1.5`)

```python
class MapDataParser(ABC):
    def __init__(self, palette, sizes, drawables, image_config, texts): ...
    def create_empty(self, text: str) -> MapData: ...
    @abstractmethod
    def parse(self, raw: bytes, *args, **kwargs) -> MapData: ...
    @abstractmethod
    def unpack_map(self, raw_encoded: bytes, *args, **kwargs) -> bytes: ...
    # self._image_generator: ImageGenerator  (created in __init__)

# ImageData(size:int, top:int, left:int, height:int, width:int,
#           image_config:ImageConfig, data:PIL.Image,
#           img_transformation:Callable[[Point],Point],
#           additional_layers=None)
# MapData(calibration_center:float=0, calibration_diff:float=0)
#   attrs set here: .image, .charger (Point), .vacuum_position (Point), .path (Path)
# Point(x, y, a=None)
# Path(point_length:int|None, point_size:int|None, angle:int|None, path:list[list[Point]])
# palette.get_color(SupportedColor.MAP_OUTSIDE|MAP_WALL_V2|MAP_INSIDE) -> RGBA tuple
# image_generator.draw_map(map_data)  # draws charger/path/vacuum overlays onto map_data.image.data
```

---

## File Structure

- Create: `CC/connector/vacuums/map_parser_xtl.py` — the vendored `XtlMapDataParser` (single module; imports only the installed `vacuum_map_parser_base`, no intra-package relative imports so it is unit-testable in isolation).
- Create: `CC/connector/vacuums/vacuum_xtl.py` — the `XtlCloudVacuum` platform class.
- Modify: `CC/connector/vacuums/base/model.py` — add `VacuumApi.XTL` + register model.
- Modify: `CC/connector/__init__.py` — add `XtlCloudVacuum` to `AVAILABLE_VACUUM_PLATFORMS`.
- Modify: `CC/manifest.json` — add `"lz4"` to `requirements`.
- Create: `tests/conftest.py`, `tests/fixtures/diagnostics_p20.json`, `tests/test_xtl_parser.py`, `tests/test_model_detect.py`.

---

## Task 0: Test harness + real-device fixture

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/fixtures/diagnostics_p20.json`
- Create: `requirements-dev.txt`

**Interfaces:**
- Produces: pytest fixture `raw_map_bytes` → `bytes` (the device's raw JSON map) and `field0` → `dict`; a `.venv` with all deps.

- [ ] **Step 1: Create the dev requirements file**

`requirements-dev.txt`:
```
vacuum-map-parser-base==0.1.5
lz4
Pillow
numpy
pytest
```

- [ ] **Step 2: Create the venv and install**

```bash
cd /mnt/ebcc776b-7e46-44f3-aee5-3fc5a503b133/jonr-p20-xcme
python3 -m venv .venv
./.venv/bin/pip install -q -r requirements-dev.txt
./.venv/bin/python -c "import lz4, PIL, numpy, vacuum_map_parser_base; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 3: Obtain the COMPLETE diagnostics from the P20 (user action, over SSH)**

The full raw map is required for the path task and end-to-end tests. On the HA box (SSH & Web Terminal add-on), after opening the P20 device page → ⋮ → Download diagnostics, place the downloaded JSON at a readable path and copy it into the repo:
```bash
# on dev machine, replace <src> with the path where you dropped the diagnostics json
cp <src>/config_entry-xiaomi_cloud_map_extractor-*.json \
   tests/fixtures/diagnostics_p20.json
```
The file must contain `data.device_data.map_data_raw` (a base64 string).

- [ ] **Step 4: Write `tests/conftest.py`**

```python
import base64
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
# make the vendored parser importable in isolation
sys.path.insert(0, str(REPO / "custom_components" / "xiaomi_cloud_map_extractor" / "connector" / "vacuums"))


@pytest.fixture
def raw_map_bytes() -> bytes:
    diag = json.loads((pathlib.Path(__file__).parent / "fixtures" / "diagnostics_p20.json").read_text())
    b64 = diag["data"]["device_data"]["map_data_raw"]
    return base64.b64decode(b64)


@pytest.fixture
def field0(raw_map_bytes) -> dict:
    outer = json.loads(raw_map_bytes)
    return json.loads(base64.b64decode(outer["fields"][0]))
```

- [ ] **Step 5: Verify the fixture loads**

```bash
./.venv/bin/python -c "
import json,base64,pathlib
d=json.loads(pathlib.Path('tests/fixtures/diagnostics_p20.json').read_text())
o=json.loads(base64.b64decode(d['data']['device_data']['map_data_raw']))
f0=json.loads(base64.b64decode(o['fields'][0]))
print('fields:',len(o['fields']),'dims:',f0['width'],'x',f0['height'],'lz4Len:',f0['lz4Len'])
"
```
Expected: prints `fields: 10` and `dims: <w> x <h>` with `w*h == lz4Len`.

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt tests/conftest.py tests/fixtures/diagnostics_p20.json
git commit -m "test: add dev harness and real P20 diagnostics fixture"
```

---

## Task 1: Register `VacuumApi.XTL` and the model

**Files:**
- Modify: `CC/connector/vacuums/base/model.py`
- Test: `tests/test_model_detect.py`

**Interfaces:**
- Produces: `VacuumApi.XTL` enum member; `VacuumApi.detect("xtl.vacuum.xm2216") == VacuumApi.XTL`.

- [ ] **Step 1: Write the failing test**

`tests/test_model_detect.py` (uses the `vacuum_api` fixture from `conftest.py`, which loads `base/model.py` in isolation without the HA-coupled package `__init__` chain — do NOT import the module through the `custom_components...` package path, it pulls `aiohttp`/`homeassistant`):
```python
def test_detect_xtl(vacuum_api):
    assert vacuum_api.detect("xtl.vacuum.xm2216") == vacuum_api.XTL


def test_detect_existing_unchanged(vacuum_api):
    assert vacuum_api.detect("viomi.vacuum.v8") == vacuum_api.VIOMI
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_model_detect.py -v
```
Expected: FAIL — `AttributeError: XTL` (member does not exist yet).

- [ ] **Step 3: Add the enum member**

In `CC/connector/vacuums/base/model.py`, inside `class VacuumApi(StrEnum)`, add after `XIAOMI = "XIAOMI"`:
```python
    XTL = "XTL"
```

- [ ] **Step 4: Register the model in `API_EXCEPTIONS`**

In the same file, add to the `API_EXCEPTIONS` dict:
```python
    "xtl.vacuum.xm2216": VacuumApi.XTL,
```

- [ ] **Step 5: Run test to verify it passes**

```bash
./.venv/bin/python -m pytest tests/test_model_detect.py -v
```
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add custom_components/xiaomi_cloud_map_extractor/connector/vacuums/base/model.py tests/test_model_detect.py
git commit -m "feat: register xtl.vacuum.xm2216 as VacuumApi.XTL"
```

---

## Task 2: Decode field 0 → occupancy grid

**Files:**
- Create: `CC/connector/vacuums/map_parser_xtl.py`
- Test: `tests/test_xtl_parser.py`

**Interfaces:**
- Produces: module-level `decode_field0(outer_json: dict) -> tuple[dict, "numpy-free bytes"]`. To avoid a numpy runtime dep in the component, the function returns `(meta: dict, grid: bytes)` where `grid` is the raw `width*height` occupancy bytes and `meta` is field 0's JSON dict. Consumed by Task 3.

- [ ] **Step 1: Write the failing test**

`tests/test_xtl_parser.py`:
```python
import json
from map_parser_xtl import decode_field0


def test_decode_field0_dimensions(raw_map_bytes):
    outer = json.loads(raw_map_bytes)
    meta, grid = decode_field0(outer)
    assert len(grid) == meta["width"] * meta["height"] == meta["lz4Len"]
    assert set(grid) <= {0, 1, 2}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_xtl_parser.py::test_decode_field0_dimensions -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'map_parser_xtl'`.

- [ ] **Step 3: Create the module with `decode_field0`**

`CC/connector/vacuums/map_parser_xtl.py`:
```python
"""Parser for XTL (Jonr) vacuum maps: JSON + base64 + LZ4 occupancy grid."""

import base64
import json
from typing import Any

import lz4.block


def decode_field0(outer_json: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """Return (field0_meta, occupancy_grid_bytes) for the primary map field."""
    meta = json.loads(base64.b64decode(outer_json["fields"][0]))
    grid = lz4.block.decompress(base64.b64decode(meta["map"]), uncompressed_size=meta["lz4Len"])
    return meta, grid
```

- [ ] **Step 4: Run test to verify it passes**

```bash
./.venv/bin/python -m pytest tests/test_xtl_parser.py::test_decode_field0_dimensions -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/xiaomi_cloud_map_extractor/connector/vacuums/map_parser_xtl.py tests/test_xtl_parser.py
git commit -m "feat: decode XTL field 0 occupancy grid (base64+LZ4)"
```

---

## Task 3: Build `MapData` with the rendered image

**Files:**
- Modify: `CC/connector/vacuums/map_parser_xtl.py`
- Test: `tests/test_xtl_parser.py`

**Interfaces:**
- Consumes: `decode_field0` (Task 2); library interfaces (Global Constraints).
- Produces: `class XtlMapDataParser(MapDataParser)` with `unpack_map(raw)->bytes` (identity) and `parse(raw)->MapData` where `MapData.image` is a non-empty `ImageData`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_xtl_parser.py`:
```python
from vacuum_map_parser_base.config.color import ColorsPalette
from vacuum_map_parser_base.config.drawable import Drawable
from vacuum_map_parser_base.config.image_config import ImageConfig
from vacuum_map_parser_base.config.size import Sizes


def _parser():
    from map_parser_xtl import XtlMapDataParser
    return XtlMapDataParser(ColorsPalette(), Sizes(), list(Drawable), ImageConfig(), [])


def test_parse_produces_nonempty_image(raw_map_bytes, field0):
    md = _parser().parse(raw_map_bytes)
    assert md.image is not None and not md.image.is_empty
    assert md.image.dimensions.width == field0["width"]
    assert md.image.dimensions.height == field0["height"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_xtl_parser.py::test_parse_produces_nonempty_image -v
```
Expected: FAIL — `ImportError: cannot import name 'XtlMapDataParser'`.

- [ ] **Step 3: Implement the parser class**

Append to `CC/connector/vacuums/map_parser_xtl.py`:
```python
from PIL import Image

from vacuum_map_parser_base.config.color import SupportedColor
from vacuum_map_parser_base.map_data import ImageData, MapData, Point
from vacuum_map_parser_base.map_data_parser import MapDataParser

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

        image = self._build_image(grid, width, height)

        # Absolute map units -> image pixels. Grid row 0 is the top of the window
        # at y == yMax; x grows right from xMin. `to_img` in the base library does
        # ((p.x-left)*scale, (height-(p.y-top)-1)*scale), so with left=xMin and
        # top=(yMax-height) the identity transform lands absolute points on pixels.
        x_min, y_max = meta["xMin"], meta["yMax"]
        top = y_max - height
        map_data = MapData(0, 1)
        map_data.image = ImageData(
            width * height, top, x_min, height, width,
            self._image_config, image, lambda p: p,
        )

        charge = meta.get("chargePos")
        if isinstance(charge, str):
            charge = json.loads(charge)
        if charge:
            map_data.charger = Point(charge["x"], charge["y"], charge.get("a"))

        if map_data.image is not None and not map_data.image.is_empty:
            self._image_generator.draw_map(map_data)
        return map_data

    def _build_image(self, grid: bytes, width: int, height: int) -> "Image.Image":
        img = Image.new("RGBA", (width, height))
        px = img.load()
        outside = self._palette.get_color(SupportedColor.MAP_OUTSIDE)
        for i, value in enumerate(grid):
            color_name = _VALUE_COLORS.get(value)
            px[i % width, i // width] = self._palette.get_color(color_name) if color_name else outside
        return img
```

- [ ] **Step 4: Run test to verify it passes**

```bash
./.venv/bin/python -m pytest tests/test_xtl_parser.py -v
```
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/xiaomi_cloud_map_extractor/connector/vacuums/map_parser_xtl.py tests/test_xtl_parser.py
git commit -m "feat: XtlMapDataParser builds MapData image + charger"
```

---

## Task 4: Verify orientation and charger placement (visual)

**Files:**
- Create: `tests/render_check.py` (dev helper, not a pytest test)
- Modify (only if needed): `CC/connector/vacuums/map_parser_xtl.py`

**Interfaces:**
- Consumes: `XtlMapDataParser.parse` (Task 3).
- Produces: a rendered PNG for visual comparison; possibly a corrected orientation in `_build_image`.

- [ ] **Step 1: Write the render helper**

`tests/render_check.py`:
```python
import base64, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "xiaomi_cloud_map_extractor" / "connector" / "vacuums"))
from map_parser_xtl import XtlMapDataParser
from vacuum_map_parser_base.config.color import ColorsPalette
from vacuum_map_parser_base.config.drawable import Drawable
from vacuum_map_parser_base.config.image_config import ImageConfig
from vacuum_map_parser_base.config.size import Sizes

diag = json.loads((pathlib.Path(__file__).parent / "fixtures" / "diagnostics_p20.json").read_text())
raw = base64.b64decode(diag["data"]["device_data"]["map_data_raw"])
p = XtlMapDataParser(ColorsPalette(), Sizes(), list(Drawable), ImageConfig(), [])
md = p.parse(raw)
img = md.image.data
img = img.resize((img.width * 4, img.height * 4))
out = pathlib.Path(__file__).parent / "render_check.png"
img.save(out)
print("charger:", md.charger, "saved:", out)
```

- [ ] **Step 2: Render and inspect**

```bash
./.venv/bin/python tests/render_check.py
```
Expected: prints charger point and writes `tests/render_check.png`. Open the PNG and compare to the physical home layout.

- [ ] **Step 3: If orientation is wrong, correct it**

Only if the image is mirrored/upside-down relative to reality (jazzvivi2 reported needing a 180° flip): adjust `_build_image` by transforming the pixel index, e.g. for 180°:
```python
        px[width - 1 - (i % width), height - 1 - (i // width)] = ...
```
Re-run Step 2 until the layout and the charger marker match the real dock location. Document the chosen transform in a code comment.

- [ ] **Step 4: Commit (only if a change was made)**

```bash
git add custom_components/xiaomi_cloud_map_extractor/connector/vacuums/map_parser_xtl.py tests/render_check.py
git commit -m "fix: correct XTL map orientation to match physical layout"
```

---

## Task 5: Decode the vacuum path (field 1) — best-effort

**Files:**
- Modify: `CC/connector/vacuums/map_parser_xtl.py`
- Test: `tests/test_xtl_parser.py`

**Interfaces:**
- Consumes: full `raw_map_bytes` fixture (Task 0).
- Produces: `XtlMapDataParser.parse` additionally sets `MapData.path` when field 1 is non-empty; never raises if the format is unrecognised.

- [ ] **Step 1: Inspect field 1's decoded bytes**

```bash
./.venv/bin/python -c "
import base64,json,pathlib,lz4.block
d=json.loads(pathlib.Path('tests/fixtures/diagnostics_p20.json').read_text())
o=json.loads(base64.b64decode(d['data']['device_data']['map_data_raw']))
f1=o['fields'][1]
print('field1 raw len:', len(f1))
if f1:
    b=base64.b64decode(f1)
    print('decoded len:', len(b), 'first 32 bytes:', b[:32].hex())
    # try to read an embedded json header like field 0 uses
    try:
        j=json.loads(b); print('json keys:', list(j.keys()) if isinstance(j,dict) else type(j))
    except Exception as e:
        print('not plain json:', e)
"
```
Expected: prints field 1's structure. Per issue #621 it holds LZ4-compressed path points. Note whether it carries its own `lz4Len`/`map`-style header (like field 0) or is a flat point array.

- [ ] **Step 2: Write the failing test (guarded on non-empty field 1)**

Append to `tests/test_xtl_parser.py`:
```python
import json as _json


def test_path_is_parsed_or_absent(raw_map_bytes):
    outer = _json.loads(raw_map_bytes)
    md = _parser().parse(raw_map_bytes)
    if outer["fields"][1]:
        assert md.path is not None
        assert md.path.point_length == sum(len(sp) for sp in md.path.path)
    else:
        assert md.path is None
```

- [ ] **Step 3: Run test to verify it fails (or passes trivially if field 1 empty)**

```bash
./.venv/bin/python -m pytest tests/test_xtl_parser.py::test_path_is_parsed_or_absent -v
```
Expected: FAIL if field 1 is populated (path not yet built); PASS if field 1 is empty in the sample (then Steps 4–5 are deferred until a sample with a path is captured — note this in the commit).

- [ ] **Step 4: Implement `_decode_path` using the structure found in Step 1**

Add to `map_parser_xtl.py` a `_decode_path(self, outer) -> Path | None` and call it in `parse` (set `map_data.path`). Use the exact layout observed in Step 1. Template for the common case where field 1 mirrors field 0 (JSON header with `map`+`lz4Len`, then int16 x/y pairs in absolute units):
```python
from vacuum_map_parser_base.map_data import Path

def _decode_path(self, outer):
    field = outer["fields"][1]
    if not field:
        return None
    meta = json.loads(base64.b64decode(field))
    blob = lz4.block.decompress(base64.b64decode(meta["map"]), uncompressed_size=meta["lz4Len"])
    import struct
    pts = [Point(x, y) for (x, y) in struct.iter_unpack("<hh", blob)]
    return Path(len(pts), 1, 0, [pts]) if pts else None
```
If Step 1 showed a different layout (e.g. a flat point array with no header, or float32 stride), adapt the decode and `struct` format accordingly; the test in Step 2 pins correctness.

- [ ] **Step 5: Run test to verify it passes**

```bash
./.venv/bin/python -m pytest tests/test_xtl_parser.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/xiaomi_cloud_map_extractor/connector/vacuums/map_parser_xtl.py tests/test_xtl_parser.py
git commit -m "feat: decode XTL vacuum path (field 1)"
```

---

## Task 6: Wire up `XtlCloudVacuum` + register + manifest

**Files:**
- Create: `CC/connector/vacuums/vacuum_xtl.py`
- Modify: `CC/connector/__init__.py`
- Modify: `CC/manifest.json`
- Test: `tests/test_xtl_parser.py`

**Interfaces:**
- Consumes: `XtlMapDataParser` (Tasks 2–5); `BaseXiaomiCloudVacuumV2`, `VacuumApi.XTL` (Task 1).
- Produces: `XtlCloudVacuum` registered so `AVAILABLE_VACUUM_PLATFORMS[VacuumApi.XTL] is XtlCloudVacuum`.

- [ ] **Step 1: Write the failing test**

Importing `connector/__init__.py` pulls the full Home Assistant stack (`aiohttp`, `homeassistant`), which is not in the test venv. So verify registration and the platform class by reading source (deterministic, no import). Create `tests/test_wiring.py`:
```python
import pathlib

CC = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "xiaomi_cloud_map_extractor"


def test_vacuum_xtl_declares_xtl_platform():
    src = (CC / "connector" / "vacuums" / "vacuum_xtl.py").read_text()
    assert "class XtlCloudVacuum(BaseXiaomiCloudVacuumV2)" in src
    assert "return VacuumApi.XTL" in src
    assert "XtlMapDataParser" in src


def test_xtl_registered_in_available_platforms():
    src = (CC / "connector" / "__init__.py").read_text()
    assert "from .vacuums.vacuum_xtl import XtlCloudVacuum" in src
    assert "XtlCloudVacuum," in src  # present in the AVAILABLE_VACUUM_PLATFORMS list literal


def test_manifest_requires_lz4():
    import json
    manifest = json.loads((CC / "manifest.json").read_text())
    assert "lz4" in manifest["requirements"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_wiring.py -v
```
Expected: FAIL — `vacuum_xtl.py` does not exist yet / import line and `lz4` not present.

- [ ] **Step 3: Create `vacuum_xtl.py`** (mirror of `vacuum_viomi.py`)

`CC/connector/vacuums/vacuum_xtl.py`:
```python
from typing import Self

from .base.model import VacuumConfig, VacuumApi
from .base.vacuum_v2 import BaseXiaomiCloudVacuumV2
from .map_parser_xtl import XtlMapDataParser


class XtlCloudVacuum(BaseXiaomiCloudVacuumV2):
    _xtl_map_data_parser: XtlMapDataParser

    def __init__(self: Self, vacuum_config: VacuumConfig) -> None:
        super().__init__(vacuum_config)
        self._xtl_map_data_parser = XtlMapDataParser(
            vacuum_config.palette,
            vacuum_config.sizes,
            vacuum_config.drawables,
            vacuum_config.image_config,
            vacuum_config.texts,
        )

    @staticmethod
    def vacuum_platform() -> VacuumApi:
        return VacuumApi.XTL

    @property
    def map_archive_extension(self: Self) -> str:
        return "json"

    @property
    def map_data_parser(self: Self) -> XtlMapDataParser:
        return self._xtl_map_data_parser
```

- [ ] **Step 4: Register in `connector/__init__.py`**

Add the import near the other vacuum imports:
```python
from .vacuums.vacuum_xtl import XtlCloudVacuum
```
Add `XtlCloudVacuum,` to the list literal inside `AVAILABLE_VACUUM_PLATFORMS` (before `UnsupportedCloudVacuum`).

- [ ] **Step 5: Add `lz4` to the manifest**

In `CC/manifest.json`, add `"lz4"` to the `requirements` array (e.g. right after `"pycryptodome",`).

- [ ] **Step 6: Run test to verify it passes**

```bash
./.venv/bin/python -m pytest tests/test_wiring.py -v
```
Expected: PASS (all three).

- [ ] **Step 7: Full test run + commit**

```bash
./.venv/bin/python -m pytest tests/ -v
git add custom_components/xiaomi_cloud_map_extractor/connector/vacuums/vacuum_xtl.py \
        custom_components/xiaomi_cloud_map_extractor/connector/__init__.py \
        custom_components/xiaomi_cloud_map_extractor/manifest.json tests/test_wiring.py
git commit -m "feat: register XtlCloudVacuum platform + lz4 requirement"
```

---

## Task 7: Deploy to Home Assistant and verify end-to-end

**Files:** none (deployment + manual verification)

**Interfaces:**
- Consumes: the committed fork.

- [ ] **Step 1: Push the fork to a Git remote**

Create a GitHub repo (e.g. `<user>/xiaomi-cloud-map-extractor-jonr`), then:
```bash
git remote add origin <repo-url>
git push -u origin master
```

- [ ] **Step 2: Install the fork on HA via HACS**

HACS → ⋮ → Custom repositories → add the fork URL as an Integration. Install it (it will override the existing one), then restart Home Assistant. (Alternatively, over the SSH & Web Terminal add-on, `git clone` the fork and copy `custom_components/xiaomi_cloud_map_extractor` into `/config/custom_components/`, replacing the existing folder.)

- [ ] **Step 3: Confirm `lz4` is available**

After restart, in the SSH add-on:
```bash
python3 -c "import lz4; print(lz4.__version__)"
```
Expected: prints a version. If HA failed to auto-install it, check the integration setup log; the `requirements` entry should have triggered install.

- [ ] **Step 4: Reload the integration and check the map**

Settings → Devices & Services → Xiaomi Cloud Map Extractor → reload. Open the camera/map entity for "Roboute Cleaningman".
Expected: the floor plan renders (no more "Vacuum xtl.vacuum.xm2216 is not supported"). Enable debug logging if needed:
```yaml
logger:
  logs:
    custom_components.xiaomi_cloud_map_extractor: debug
```

- [ ] **Step 5: Verify against reality**

Confirm the rendered map matches the physical home orientation and the charger marker sits at the real dock. If off, revisit Task 4's transform, re-commit, push, and re-pull on HA.

- [ ] **Step 6: (Optional) Offer the work upstream**

Comment on issue #621 with the findings and a link to the fork so others with the P20 can use it and Piotr can merge if he returns.

---

## Self-Review Notes

- **Spec coverage:** enum+register (Task 1 ✔), vendored parser with `unpack_map`/`parse` (Tasks 2–3 ✔), LZ4 grid (Task 2 ✔), image build (Task 3 ✔), charger + calibration via `MapData(0,1)` + `img_transformation` (Task 3 ✔), orientation tuning (Task 4 ✔), path field 1 (Task 5 ✔), `XtlCloudVacuum` + `AVAILABLE_VACUUM_PLATFORMS` + `lz4` manifest (Task 6 ✔), SSH/HACS deploy + verify (Task 7 ✔).
- **Deferred by design:** rooms/zones/obstacles (fields 2–9) — empty in the captured sample; add when a populated sample exists. Live vacuum position — no distinct field identified yet; charger stands in.
- **Known tunables (empirical, not guessed as final):** grid orientation (Task 4), field 1 point stride (Task 5 Step 1), calibration accuracy for the Lovelace card.
