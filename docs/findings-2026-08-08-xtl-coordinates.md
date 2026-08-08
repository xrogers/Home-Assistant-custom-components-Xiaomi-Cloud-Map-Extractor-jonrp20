# XTL coordinates, grid values and scale, resolved against real hardware (2026-08-08)

Three bugs. All of them were invisible to the test suite, because the committed fixture is
synthetic and its window is wide enough to keep every wrong variant in bounds.

## Bug 1 — the window anchors are swapped relative to their names

Symptom, in two stages: first no charger and no robot anywhere on the map; then, after a
partial fix, both markers a little down and to the right of where they belong.

The real convention on `xtl.vacuum.xm2216`:

```
device y -> image COLUMN:  img_x = y - yMax
device x -> image ROW:     img_y = x - (totalHeight - xMin - height)
```

Device `x` is a **top-down** row index on the `totalHeight`-row canvas, while `xMin` is the
window's offset from the canvas **bottom**. Flipping x into a bottom-up index with
`totalHeight - 1 - x` lets the window be anchored at `top=xMin` and lets
`ImageDimensions.to_img` supply its own y-flip, which together give the formula above.

### How it was pinned — after two wrong guesses

`fields[3]` carries room definitions with `centerX`/`centerY` **and names**, `fields[9]`
carries room polygons, and the occupancy values **are** those rooms' `room_id`s. Fitting
the 8 rooms' polygon bounding boxes against their grid cells gives **exact integer
agreement on all 16 bounds**, with the two constants falling out as `yMax` (373) and
`totalHeight - xMin - 1` (585). Rendering the room *names* at their mapped centres then
puts every label inside its own coloured region — Salon, Gabinet, Kuchnia, Łazienka,
Łazienka1, Przedsionek and both Sypialnias.

| mapping | charger | verdict |
|---|---|---|
| `xMin`→x, `yMax`→y (original) | col 174 | off-canvas, invisible |
| axes swapped, x-row mirrored (`83202c1`) | (25, 71) | wrong row |
| anchors swapped, axes kept (`5d3bf24`) | (15, 61) | wrong column *and* row |
| **y→col, x→row from canvas bottom** | **(25, 45)** | **all 8 room labels correct** |

On the docked capture this puts the charger at `(25, 48)` and the robot at `(25, 47)` — one
pixel apart, as a docked robot should be.

**Lesson, learned the hard way twice.** Both wrong guesses were "confirmed" by weak
evidence: a verbal description of where the dock sits, and then a wall obstacle the
reporter identified as the dock. Brute-forcing offsets against the occupancy grid yields
**228** placements that all land on an occupied cell, so "it lands on floor" and "it lands
in roughly the right area" discriminate almost nothing. What finally worked was a reference
set with many independent points and unambiguous labels. Prefer that over any amount of
plausible-looking agreement — and prefer it *before* shipping, not after.

## Bug 2 — only 3 of 9 grid values were rendered

`_VALUE_COLORS` mapped values 0, 1 and 2. The real grid uses **0..8**:

| value | count | meaning |
|---|---|---|
| 0 | 11002 | unexplored |
| 1 | 1683 | wall |
| 2 | 270 | (small scattered patches; left as MAP_INSIDE) |
| 3 | 10435 | plain floor |
| 4–8 | 10804 | per-room segment ids (5 rooms) |

Everything from 3 up fell through to the background colour: **21239 of 34194 cells (62%)**
of a real map. The user saw bare wall outlines with no floor and no rooms, which reads as
"I see only the map of my flat".

Now 3 renders as floor and values >= 4 go through `ColorsPalette.get_room_color`, so the
existing GUI **room colors** option applies to them for free (it feeds
`_overridden_room_colors`, and `get_room_color` wraps ids modulo the palette size). The
reporter confirmed the resulting room layout matches their flat. Distinct colours on the
real capture went from 3 to 12.

## Bug 3 — the raster was never scaled or trimmed

`ImageDimensions.to_img` multiplies marker coordinates by `scale` and offsets them by the
trim, but the base library **never touches the raster**; producing it at the matching size
is the parser's job, and `_build_image` returned a plain `width x height` image.

So at any scale other than 1 the bitmap stayed 1:1 while markers were placed `scale x`
further out — the charger and robot drifted right and down in proportion to the scale,
while the rooms looked correct at every scale. Trim had the same mismatch.

`_trim_and_scale` now crops then resizes, mirroring `ImageData.__init__`'s integer trim
arithmetic exactly so the raster and `dimensions` cannot disagree. Verified on the real
capture: at scales 1, 2, 3 and 4.5 the charger pixel is exactly `scale x` its scale-1
position and stays in bounds, and with trim applied the raster size equals the declared
`(dimensions.width * scale, dimensions.height * scale)`.

## Confirmed as a side effect: headings are centi-degrees

Real `chargePos` reports `"a":-17999`. That cannot be degrees, which confirms the
centi-degrees conversion added in f7e0257 (previously only inferred from the synthetic
fixture's `18000`).

## Unresolved: the live position can fall outside the map window

On a capture taken mid-clean, `fields[2]` reported `{"x":424,"y":534}`. Under the confirmed
mapping that is column **161** on a **139**-wide map — 23 cells beyond the window's y range
`[373, 512)`. The row (81) is in bounds; only the column is not. So the robot marker cannot
be drawn, which is exactly the reported "vacuum position stopped showing".

This is not the coordinate bug above; the mapping is confirmed by 8 rooms. Observations:

- The map's own content only spans y up to 508 (max room-polygon y), so the window really
  does stop short of the reported position.
- `cleanValues` was `[6, 7, 5, 11]`, i.e. the lower rooms, but the reported position maps
  to row 81 in the upper half — inconsistent with the cleaning state.
- Swapping the robot's x/y *would* place it in room 6 (one of those being cleaned), but
  that same swap breaks the docked capture, where unswapped values put the robot one pixel
  from the charger. So a swap is not the explanation.

Candidate causes, undecided on one capture: the raster lags the live position (the map is
regenerated less often), or the live position uses a different frame from `chargePos` and
the room data. **Needs 2–3 more captures taken while the robot is driving**, ideally with a
note of which room it was in, before guessing again.

Meanwhile `_warn_if_off_canvas` logs a warning whenever a position maps outside the image.
PIL clips silently, so this class of failure was previously invisible — no marker, no error,
no log line — which is how the original mapping bug survived so long.

## Still open

- **`map_data.rooms` is not populated.** The room *segments* now render, but rooms are not
  exposed as objects, so room names, per-room sensors and `Drawable.ROOM_NAMES` still do
  nothing. Would need bounding boxes and names per segment id.
- **Grid value 2 is unidentified** (270 cells, small scattered patches). Left as
  MAP_INSIDE. Possibly obstacles or furniture.
- **Marker heading semantics are unverified.** The angle is correctly scaled, but whether
  the swapped anchors also imply a sign or offset change was not tested; it only affects
  which way the pieslice and bin-cover line point.
- **`path` is still deferred.** The `fields[1]` trace encoding is unreverse-engineered.
- **`rotate` is untested** against a real capture now that the raster is scaled.

## Reproducing

```
python scripts/marker_diagnose.py <diagnostics.json>
```

Walks the failure modes in order and writes the exact PNG the integration serves. Note
diagnostics dumps and their renders contain a floor plan of someone's home — they are
gitignored; keep them out of commits and issue attachments.
