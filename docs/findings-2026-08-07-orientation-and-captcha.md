# Findings: map orientation + captcha lockout (2026-08-07)

## Issue 2 — captcha lockout (FIXED)

**Symptom (reported):** wrong credentials → captcha appears → correct captcha text →
"credentials are incorrect", but the old credentials are never cleared, so the user is
stuck until Home Assistant restarts.

**Root cause:** `config_flow.py` `async_step_auth_captcha` had no exit back to the
credentials form.

Trace:

1. `async_step_auth_credentials` stores `_username`/`_password` on the flow handler and
   on the connector, then calls `login_with_credentials`.
2. Wrong password + captcha challenge → `_login_with_credentials_step_2` stashes
   `self._sign`, fetches the captcha image, raises `CaptchaRequiredException`.
3. User submits the correct captcha → `continue_login_with_captcha` calls
   `_login_with_credentials_step_2(self._sign, code)`, which **re-sends the same stored
   wrong password**. There is no way to change it from this step.
4. Xiaomi returns 200 without `ssecurity` → `raise InvalidCredentialsException()`
   (`connector.py:248`).
5. That is a `XiaomiCloudMapExtractorException` subclass, so the flow caught it, set
   `errors["base"]`, then **fell through and re-rendered the captcha form** from
   `self._captcha_exception.image_data` — an already-consumed captcha image, alongside a
   now-stale `_sign`.

So every retry was unwinnable: same bad password, spent sign, stale image, and the form
only ever asked for a captcha code. The "until restart" part fits the reauth path — HA
keeps one in-progress reauth flow per entry, so the poisoned handler instance survives
until restart.

**Fix:** added `_restart_auth()`, which clears `_username`, `_password`, `_connector`,
`_captcha_exception`, `_two_factor_exception` and `_wait_for_login_task`, and records an
error for the next form. On credential rejection the captcha step now returns to
`async_step_auth_credentials` (showing `cloud_login_error`) instead of looping. Also
guarded the render path against a cleared `_captcha_exception` (previously an
`AttributeError`). The 2FA step had the identical defect and got the same treatment.

**Testing:** `homeassistant` is not installed in `.venv` and the suite deliberately
avoids HA-coupled imports, so there is no automated config-flow test. This fix is
verified by code inspection only and needs a manual pass against a real account.

## Issue 1 — map orientation / dock position (ROOT CAUSE FOUND, FIX PENDING)

**Symptom (reported):** "map rotation is different from the app, and the base location
isn't correct."

**The orientation was never validated.** `tests/fixtures/diagnostics_p20.json` carries
`"_note": "Synthetic fixture (rectangular floor plan). Not real device/home data."`, and
it was added in the *same commit* as the parser. The parser comment claiming the
coordinate system was "confirmed against real device data" is not backed by anything in
the repo — the fixture's `chargePos` was authored to match the assumption it supposedly
confirms.

**The defect: the y-flip is applied twice.**

`ImageDimensions.to_img` (base library) already flips y:

```python
Point((p.x - left) * scale, (height - (p.y - top) - 1) * scale)
```

`map_parser_xtl.parse` *also* pre-flips y in `to_library_space`, then passes `top=0`:

```python
def to_library_space(p): return Point(p.x, (y_max + height - 1) - p.y, p.a)
map_data.image = ImageData(width*height, 0, x_min, height, width, ...)
```

The two flips cancel, so markers land at `pixel_y = y - yMax` (y-down). Passing
`top=y_max` with an identity transform instead yields `pixel_y = yMax + height - 1 - y`
(y-up) — the natural reading, given `xMin`/`yMax` is the standard bounding-box pairing
for a y-up canvas.

On the fixture the two differ by an exact vertical mirror:

| mapping | charger img_y | vacuum img_y |
|---|---|---|
| current (pre-flip, `top=0`) | 19 | 20 |
| identity + `top=y_max` | 134 | 133 |

`19 + 134 == 153 == height - 1`. **Both land inside the image**, which is all
`test_charger_maps_onto_the_image` asserts — so the suite cannot distinguish the correct
mapping from its mirror. That is why this shipped.

**Confirmed as a vertical flip, not a rotation** (reporter checked against the app). That
matches the defect above exactly, and means x was never wrong — `pixel_x = x - xMin`
stands.

**Fix applied:**

- `parse`: dropped the `to_library_space` pre-flip, pass `top=y_max` with an identity
  transform. Yields `img_y = yMax + height - 1 - y`. Passing the real `top` also makes
  `ImageConfig` trim behave, since the base library offsets trim by `top`.
- `_build_image`: `px[i % width, height - 1 - i // width]` — grid row 0 now draws at the
  bottom.

Both had to move together or the dock would have detached from the walls.

**Tests.** The window mapping is now pinned by exact-pixel assertions
(`test_charger_maps_to_exact_pixel`, `test_vacuum_position_maps_to_exact_pixel`) rather
than the old "lands somewhere inside the image" check that passed for both orientations.

Bitmap orientation could not be tested against the fixture at all — it is a plain
rectangle and perfectly symmetric top-to-bottom (`rows == rows[::-1]`), so any assertion
on it is vacuous. `test_build_image_puts_grid_row0_at_image_bottom` uses a hand-built 3x2
asymmetric grid instead.

Both halves were mutation-checked: reverting the bitmap flip fails exactly the bitmap
test; restoring the double y-flip fails exactly the two marker tests. 15 tests pass.

**Still unverified against hardware:** the fix rests on the reporter's visual comparison
plus the code-level double-flip, not on a real map capture. `scripts/orientation_probe.py`
renders all four orientations from a diagnostics download and remains the tool for
confirming on-device; `b_flip_vertical.png` corresponds to what now ships.

### Correction

An earlier revision of this doc (and the message of commit 5742b80) claimed
`tests/render_check.py` "saves only the bare bitmap without markers, so its PNG is
byte-identical before and after this fix". **Both halves of that are wrong.**

`render_check.py` saves `md.image.data` *after* `parse()` has run `draw_map`, so the
charger and vacuum markers are composited into it. Verified by counting colours in the
output: opaque white pixels for the vacuum (`SupportedColor.ROBO`) and the alpha-blended
charger fill `(67,184,201)` from `(102,254,218,127)` over the floor colour.

The "byte-identical" claim was an artefact of my checking `git status` rather than the
file: `tests/render_check.png` is gitignored (`.gitignore:155`) and untracked, so git
never reports it as modified no matter what changes. It is a usable orientation check
after all, though `scripts/orientation_probe.py` is still better for this purpose because
it renders all four candidate orientations at once and marks the dock distinctly.

Also worth recording, since it looks alarming when first observed: on this fixture the
charger contributes only ~3 visible pixels despite `charger_radius: 6`. That is not a
bug. The synthetic fixture has the vacuum docked (charger 388,398 vs vacuum 387,399), and
`draw_map` iterates the drawables in enum order, so `VACUUM_POSITION` paints its opaque
white disc over `CHARGER` which was drawn earlier. They separate on real data whenever the
robot is away from the dock.

## Unrelated latent bug spotted (not fixed)

`config_flow.py` `async_step_confirm_data`: when `self.source == SOURCE_REAUTH` but
`existing_entry` is `None`, `existing_entry.data.copy()` raises `AttributeError`. The
`if existing_entry or self.source == SOURCE_REAUTH:` guard admits that case.

## Draft reply for the GitHub thread

> Thanks for testing — both were real bugs, and both are now fixed.
>
> The orientation and the wrong dock position were one bug: the y-axis flip was applied
> twice, once in my parser and once inside `vacuum-map-parser-base`. The two cancelled, so
> the map rendered mirrored top-to-bottom with the dock drawn at the mirrored row. It's a
> vertical flip rather than a rotation, so left/right was always correct.
>
> My test didn't catch it for two reasons, both my fault: it only checked that the dock
> landed *somewhere* inside the image, which is true of the correct mapping and of its
> mirror; and the fixture I committed is synthetic and perfectly symmetric top-to-bottom,
> so it couldn't distinguish the two orientations even in principle. Both are fixed —
> exact-pixel assertions for the dock and vacuum, and a hand-built asymmetric grid for the
> bitmap. I also mutation-checked them, so this specific regression can't come back green.
>
> Separately, the captcha lockout is fixed. Entering a wrong password and then a correct
> captcha used to trap you on the captcha form permanently: it kept re-sending the stored
> bad password with an already-spent captcha, and the form never offered a way back to the
> credentials, so a restart was the only escape. It now returns you to the
> username/password form with an error. The 2FA step had the same flaw and got the same fix.
>
> Worth flagging: I don't own this hardware, so the orientation fix rests on your visual
> comparison plus the code-level defect, not on a capture from a real device. If anything
> still looks off, `scripts/orientation_probe.py` on a diagnostics download renders all four
> orientations side by side and will settle it.
