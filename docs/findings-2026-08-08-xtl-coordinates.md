# XTL coordinates and grid values, resolved against real hardware (2026-08-08)

Two bugs, both found only once a real `xtl.vacuum.xm2216` capture was available. Both
were invisible to the test suite because the committed fixture is synthetic.

## Bug 1 — the device's axes are swapped

Symptom: no charger and no robot anywhere on the map. Not misplaced — absent.

The parser read device `x` as the image column and `y` as the row. On the real capture
(`width=139 height=246 xMin=214 yMax=373`, `chargePos {"x":388,"y":398}`) that put the
charger at column `388 - 214 = 174` on a **139**-wide map. Both markers were drawn
off-canvas, and PIL silently clips, so nothing appeared and nothing errored.

The real convention:

```
device x -> image ROW,    anchored by xMin, range [xMin, xMin+height)
device y -> image COLUMN, anchored by yMax, range [yMax, yMax+width)
```

`x` increases upward in the picture, so `x == xMin` is the bottom row — matching
occupancy-grid row 0, which `_build_image` already drew at the bottom. Concretely:

```
img_x = y - yMax
img_y = xMin + height - 1 - x
```

Implemented by swapping x/y in the `img_transformation` and passing `top=xMin`,
`left=yMax`, letting `ImageDimensions.to_img` supply the vertical flip.

How it was pinned: brute-forcing every candidate offset against the occupancy grid gave
228 placements that land on an occupied cell, so the grid alone could not decide it. The
reporter's description of where the dock physically sits ("~1/5 of the map height, ~1/5
from the left") plus a rendered comparison of the surviving candidates settled it. Under
the accepted model the dock lands at 18% from the left and 29% from the top, on floor,
with the robot one pixel away — consistent with a docked robot.

Verification on the real capture: charger `(25, 71)` and robot `(25, 72)`, both inside the
139x246 window; the robot's colour went from **0 px** to **79 px** rendered.

### Why the fixture hid it

The synthetic fixture's window (`107x154`, `xMin=306`, `yMax=379`) is wide enough that the
*wrong* mapping still lands in bounds, so `test_markers_land_inside_the_image` passed
either way. `_expected_pixel` in the tests now encodes the swapped convention, so the
exact-pixel assertions would catch a regression.

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
of a real map. The user saw bare wall outlines with no floor and no rooms, which read as
"I see only the map of my flat".

Now 3 renders as floor and values >= 4 go through `ColorsPalette.get_room_color`, which
means the existing GUI **room colors** option applies to them for free (it feeds
`_overridden_room_colors`, and `get_room_color` wraps ids modulo the palette size). The
reporter confirmed the resulting room layout matches their flat.

Colours went from 3 distinct to 12 on the real capture.

## Confirmed as a side effect: headings are centi-degrees

Real `chargePos` reports `"a":-17999`. That cannot be degrees, which confirms the
centi-degrees conversion added in f7e0257 (previously inferred from the synthetic
fixture's `18000`).

## Still open

- **`map_data.rooms` is not populated.** The room *segments* now render, but rooms are not
  exposed as objects, so room names, per-room sensors and `Drawable.ROOM_NAMES` still do
  nothing. Would need bounding boxes and names per segment id.
- **Grid value 2 is unidentified** (270 cells, small scattered patches). Left as
  MAP_INSIDE. Possibly obstacles or furniture.
- **Marker heading semantics under the swapped axes are unverified.** The angle is now
  correctly scaled, but whether a swapped frame also needs an offset or sign change was
  not tested — it only affects which way the pieslice and bin-cover line point.
- **`path` is still deferred.** The `fields[1]` trace encoding is unreverse-engineered.

## Reproducing

```
python scripts/marker_diagnose.py <diagnostics.json>
```

Walks the failure modes in order and writes the exact PNG the integration serves. Note
diagnostics dumps and their renders contain a floor plan of someone's home — they are
gitignored, keep them out of commits and issue attachments.
