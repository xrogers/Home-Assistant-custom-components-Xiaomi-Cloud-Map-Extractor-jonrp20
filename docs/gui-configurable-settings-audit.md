# Audit: which camera/map settings could be GUI-configurable

Scope: what the options flow exposes today, what the code and
`vacuum-map-parser-base` support but the GUI does not, and what each gap would cost.

## Already configurable (Settings → Devices & Services → Configure)

`options_flow.py` exposes five steps, all reachable from the `init` menu:

| Step | Covers |
|---|---|
| `image_config` | scale (0.1–20), rotate (0–359), trim left/right/top/bottom |
| `colors` | every `SupportedColor` + per-colour alpha |
| `room_colors_step1/2` | per-room-id colours (two-step: pick ids, then colours) |
| `drawables` | multi-select over the `Drawable` enum |
| `sizes` | all 8 `Size` values (vacuum/charger/obstacle radii, path widths) |

This is already a broad surface. Anything added benefits from existing plumbing:
`__init__.py:62` registers `add_update_listener(async_reload_entry)`, so saving options
reloads the entry and new values take effect immediately — a new option needs **no**
extra reload wiring.

## Gap 1 — Polling interval (recommended first)

`DEFAULT_UPDATE_INTERVAL: Final = timedelta(seconds=10)` (`const.py:20`), passed at
`coordinator.py:32`. Hardcoded, not exposed anywhere.

Every 10 s the integration polls the Xiaomi cloud. That is aggressive for a cloud API
users don't control, and there is currently no way to back off short of editing the
source. This is the most likely "extra setting" a user actually wants.

**Cost: low.** Add `CONF_UPDATE_INTERVAL` to `const.py`, one `NumberSelector` in the
`image_config` step (or a new `general` step), read it in the coordinator with the
existing constant as the fallback default, and add `en.json` strings. No library change.
Needs a migration path for entries whose options predate the key — read with
`.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)` rather than bumping `VERSION`.

## Gap 2 — Host / token / map API not editable after setup

`CONF_HOST`, `CONF_TOKEN` and `CONF_USED_MAP_API` live in `entry.data`, set once during
`async_step_confirm_data`. There is **no** `async_step_reconfigure` anywhere in the
integration.

Consequences: a vacuum that changes IP, a re-provisioned token, or a wrong
auto-detected `used_map_api` all require deleting and re-adding the integration. Reauth
only re-runs credentials. (Reauth *can* reach `confirm_data`, but that path hits the
`existing_entry is None` crash noted in the findings doc.)

`used_map_api` matters for this fork specifically: `VacuumApi.detect` picks the parser
from the model string, and a user whose model is misdetected has no GUI recovery.

**Cost: low-moderate.** HA has first-class `async_step_reconfigure` for exactly this, and
the existing `confirm_data` step is nearly reusable as-is. Fix the `existing_entry`
crash at the same time.

## Gap 3 — Texts: dead end-to-end

Not merely absent from the GUI — the whole feature is inert:

- the options step is commented out (`options_flow.py:216–225`)
- `__init__.py:100` hardcodes `texts = []`, so `entry.options[CONF_TEXTS]` is **written at
  entry creation and never read**
- the constants exist and are unused (`CONF_TEXT_VALUE/_X/_Y/_COLOR/_FONT/_FONT_SIZE`)
- the library supports it: `Text(text, x, y, color, font, font_size)`

**Cost: moderate**, and the reason it was commented out is real: HA config-flow schemas
cannot express a variable-length list of composite objects. Options:

1. Two-step flow mirroring `room_colors` — step 1 chooses how many texts / their labels,
   step 2 renders per-text fields. Consistent with existing UX, no new concepts.
2. A single multi-line field parsed as JSON, with validation errors surfaced on the
   field. Much less code, uglier UX.
3. A `TextSelector` per slot with a fixed cap (e.g. 5 texts). Crude but simple.

Whichever, `__init__.py:100` must be wired to read the option or the GUI will silently do
nothing. Lower value than gaps 1–2 — these are cosmetic map labels.

## Not gaps (deliberately superseded)

Legacy YAML options that `legacy.py` still names but no longer maps:

- `attributes` — superseded by dedicated sensor/binary_sensor entities plus a fixed
  attribute set in `entity.py:77`.
- `store_map_raw` / `store_map_image` / `store_map_path` — superseded by
  `diagnostics.py` (Download diagnostics).
- `auto_update` — HA covers this natively with per-entity "Enable polling for updates".
- `force_api` — became `CONF_USED_MAP_API`; see gap 2 for the editability problem.
- `map_transformation` — was just the container for scale/rotate/trim, all exposed.

## Worth knowing: there is no flip/mirror setting

`ImageConfig` has `scale`, `rotate` and `trim` only — no horizontal/vertical flip. A
rotation cannot express a mirror, so a user whose map renders mirrored (as in the XTL
flip bug fixed in 5742b80) has **no** GUI workaround. Adding one means either an upstream
`ImageConfig` field or a post-parse transpose in this integration. Only worth doing if
mirroring turns out to vary per device/firmware rather than being a fixed per-model
property.

## Exposing an axis flip: what it actually takes

**Not just the GUI.** `ImageConfig` is a library dataclass carrying only `scale`,
`rotate` and `trim`, so there is nowhere to put the flags — the plumbing is most of the
work. Eight touch points:

| # | File | Change |
|---|---|---|
| 1 | `const.py` | `CONF_IMAGE_CONFIG_FLIP_X` / `_FLIP_Y` |
| 2 | `config_flow.py` | add both to `_default_image_config()`, default `False` |
| 3 | `options_flow.py` | two `BooleanSelector` fields in the `image_config` step |
| 4 | `translations/en.json` | labels under `options.step.image_config.data` |
| 5 | `__init__.py` | read from options with `.get(key, False)` |
| 6 | `connector/vacuums/base/model.py` | carry the flags on `VacuumConfig` |
| 7 | `connector/vacuums/vacuum_xtl.py` | pass them into `XtlMapDataParser` |
| 8 | `map_parser_xtl.py` | apply to **both** the bitmap and the marker mapping |

Notes that matter:

- Step 8 is where the flip bug fixed in 5742b80 came from. The bitmap row mapping in
  `_build_image` and the `top`/transform passed to `ImageData` must flip **together**, or
  the dock detaches from the walls. Any test must pin both (see
  `test_build_image_puts_grid_row0_at_image_bottom`, which needs an asymmetric grid — the
  fixture is symmetric and cannot detect a flip).
- `calibration()` derives from `to_img`, so calibration points follow automatically. No
  extra work, but worth re-checking after the change.
- Use `.get(key, False)` rather than bumping `VERSION` — entries created before the key
  exists must keep working.
- This lands **XTL-only**. The other parsers come from separate upstream packages, so a
  generic flip would need an upstream `ImageConfig` field.
- A flip is not expressible via the existing `rotate`, so there is no shortcut.

Rough size: ~80 lines plus tests. Mechanical, but spread across eight files.

## Suggested order

1. Polling interval — cheapest, most user-visible.
2. `async_step_reconfigure` for host/token/API, plus the `existing_entry` crash fix.
3. Texts, if anyone asks; pick approach 1 for UX consistency.
