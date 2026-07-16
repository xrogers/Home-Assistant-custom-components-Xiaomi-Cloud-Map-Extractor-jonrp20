# Jonr P20 (`xtl.vacuum.xm2216`) map support — design

## Goal
Add live-map support for the Jonr P20 Pro to a personal fork of the Xiaomi Cloud
Map Extractor (v3.0.0-alpha-24 baseline), installable on the user's Home
Assistant (2026.7.2, HAOS) via HACS as a custom repository. Deployment to the HA
box is over the SSH & Web Terminal add-on.

## Context (verified)
- Model `xtl.vacuum.xm2216`, Xiaomi server `de`. Currently resolves to
  `VacuumApi.UNSUPPORTED` → renders the "is not supported" placeholder.
- The download half already works: the component fetches the raw map from Xiaomi
  cloud (`get_interim_file_url` / `..._pro`) even for unsupported models. Only a
  **parser** is missing.
- Raw map format (confirmed against the user's real diagnostics sample):
  - Outer JSON: `{"mapId":0, "fields":[<10 base64 strings>], "cleanValues":[]}`.
  - `fields[0]` = base64 → JSON with keys: `expanded, totalWidth(800),
    totalHeight(800), width, height, xMin, yMax, resolution(=5 cm/px),
    timestamp, map, lz4Len, direction, chargePos{x,y,a}`.
    - `map` = base64 → **LZ4 block** decompress (`uncompressed_size=lz4Len`) →
      `width*height` byte occupancy grid. Verified: 107×154 = 16478 = `lz4Len`;
      decompress 506→16478 bytes; renders as the user's real floor plan.
    - Pixel values observed: `0`=outside/unknown, `1`=wall, `2`=floor/cleaned.
    - `chargePos` is in absolute map units; pixel = `(x-xMin, yMax-y)`.
  - `fields[1]` = base64 → LZ4 vacuum path/trace (per issue #621: ~N points).
  - `fields[2..9]` = rooms / zones / obstacles; empty in this sample.

## Approach
Vendor a parser inside the component (no new PyPI package). Four edits mirror the
existing per-vendor pattern (e.g. `vacuum_viomi.py`).

### Changes
1. `connector/vacuums/base/model.py`
   - Add `VacuumApi.XTL = "XTL"`.
   - Register model: add `API_EXCEPTIONS["xtl.vacuum.xm2216"] = VacuumApi.XTL`
     (exception map, since `xtl.` matches no existing prefix; a
     `"xtl.vacuum."` prefix in `AVAILABLE_APIS` is the alternative if more XTL
     models appear).
2. `connector/vacuums/map_parser_xtl/` (vendored parser package)
   - `XtlMapDataParser(MapDataParser)`:
     - `unpack_map(raw: bytes) -> bytes`: return raw JSON unchanged (or
       json-normalized); the archive is plain JSON, not gzip/zlib.
     - `parse(decoded) -> MapData`: decode `fields[0]`, LZ4-inflate the grid,
       build `ImageData` via the base library's image builder using the palette /
       drawables / sizes from `VacuumConfig`; set `charger`, `vacuum_position`
       (from `chargePos`/`direction` until a live-position field is found),
       decode `fields[1]` into `Path`; compute `calibration()` from `resolution`,
       `xMin`, `yMax`, `totalWidth/Height`.
   - LZ4 dependency: add `lz4` to `manifest.json` requirements.
3. `connector/vacuums/vacuum_xtl.py`
   - `XtlCloudVacuum(BaseXiaomiCloudVacuumV2)`: `vacuum_platform()->XTL`,
     `map_archive_extension` (JSON), instantiate + expose `XtlMapDataParser`.
4. `connector/__init__.py`
   - Add `XtlCloudVacuum` to `AVAILABLE_VACUUM_PLATFORMS`.

## Scope (v1 vs later)
- **v1 (must):** map image (walls/floor/outside), charger marker, calibration so
  the Lovelace card aligns; correct orientation vs. the physical home.
- **v1 (if present in data):** vacuum path (`fields[1]`).
- **Later:** rooms/zones/obstacles once fields with non-empty data are captured;
  live vacuum position if a distinct field exists.

## Testing / verification
- Unit: decode the captured sample → assert grid dimensions, `lz4Len`, charger
  pixel mapping, non-crashing `parse()` → `MapData` with a non-empty image.
- Visual: render the parsed `MapData.image` and compare to the physical layout
  and orientation (rotate/flip as needed — jazzvivi2 needed a 180° flip).
- End-to-end: deploy fork to HA over SSH, reload integration, confirm the map
  entity shows the floor plan instead of "not supported".

## Risks / unknowns
- `fields[1]` path encoding (point struct/stride) not yet decoded — needs the
  full sample (current copy was truncated after field 0).
- Orientation/mirroring of the grid vs. real home — resolve visually.
- `MapData`/`ImageData` builder API of `vacuum-map-parser-base==0.1.5` — inspect
  the installed package during implementation to match `image.as_dict()` /
  `calibration()` expectations of the card.
- Upstream is effectively stalled; this stays a personal fork unless Piotr picks
  it up (issue #621).
