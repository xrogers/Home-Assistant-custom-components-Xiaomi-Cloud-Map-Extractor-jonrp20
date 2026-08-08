# XTL coordinates, grid values and scale, resolved against real hardware (2026-08-08)

Three bugs. All of them were invisible to the test suite, because the committed fixture is
synthetic and its window is wide enough to keep every wrong variant in bounds.

## Bug 1 — the window anchors are swapped relative to their names

Symptom, in two stages: first no charger and no robot anywhere on the map; then, after a
partial fix, both markers a little down and to the right of where they belong.

The real convention on `xtl.vacuum.xm2216`:

```
device x -> image COLUMN, anchored by yMax, range [yMax, yMax+width)
device y -> image ROW,    anchored by xMin, range [xMin, xMin+height)
```

So `xMin` is the minimum of the **y** range and `yMax` the minimum of the **x** range. The
axes themselves are *not* swapped — `x` really is horizontal. `y` increases upward in the
picture, so `y == xMin` is the bottom row, matching occupancy-grid row 0.

```
img_x = x - yMax
img_y = xMin + height - 1 - y
```

That is exactly what `ImageDimensions.to_img` produces from an **identity**
transformation with `top=xMin`, `left=yMax`.

### How it was pinned, and how it was first got wrong

The original parser used `xMin` for x and `yMax` for y, giving column `388 - 214 = 174` on
a **139**-wide real map. PIL clips silently, so both markers were drawn off-canvas: no
marker, no error, no log line.

The first attempted fix swapped the axes as well as the anchors, giving `(25, 71)`. That is
in bounds and in the right general region, so it looked correct. It was not: it sits
down-and-right of the true position in open floor.

Brute-forcing candidate offsets against the occupancy grid produced 228 placements that
all land on an occupied cell, so the grid alone could not decide it. What settled it was
the reporter identifying the dock as **the upper of two obstacles against the left wall**
(the lower one is an air purifier). Profiling the left wall's leftmost occupied column per
row locates that obstacle at image **rows 56–68, columns 14–16**:

| mapping | charger | verdict |
|---|---|---|
| `xMin`→x, `yMax`→y (original) | col 174 | off-canvas, invisible |
| axes swapped (first fix) | (25, 71) | in open floor, down-right of the dock |
| **anchors swapped, axes kept** | **(15, 61)** | **inside the obstacle** |

The docked robot lands at `(14, 61)`, one column from the charger — consistent with a
robot sitting on its dock.

Lesson worth keeping: a candidate that lands "in roughly the right area" is not
confirmation. The two wrong variants both looked plausible against a verbal description of
where the dock was ("~1/5 of the height, ~1/5 from the left"); only a feature with a known
pixel footprint could discriminate them.

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
