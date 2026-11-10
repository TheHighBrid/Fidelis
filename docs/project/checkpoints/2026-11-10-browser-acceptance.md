# Same-host browser acceptance checkpoint · 2026-11-10

## Scope and delivery

F08-B / MEL-80 same-host Chromium acceptance runner and empirical browser receipt,
branched cleanly (`--no-track`) from `f84287993c9bc213dc47859b297a5a275381101d`
(`origin/feat/region-aware-studio`) on isolated branch
`work/mel-80-browser-acceptance`. `F08-B` advances from `Todo` to `In Progress`
(`partial`) until physical touch hardware (Android/iOS/tablet) and human visual
signoff are also recorded. Remote Linear `MEL-80` sync remains pending.

## Environment and browser receipt

- **Host OS / Architecture**: `darwin arm64` (`macOS` M1 host loopback `127.0.0.1`)
- **Browser**: `Google Chrome 157.0.8103.50` (`HeadlessChrome/157.0.0.0`)
- **Runner**: `tests/test-browser-acceptance.sh` → `scripts/browser-acceptance.mjs`
  against live `scripts/web-ui.py --bind 127.0.0.1 --region-workspace <tmp>`
- **Viewports verified**: Desktop (`1440×900`) and Mobile touch-emulated (`390×844`, `dpr=2`, `maxTouchPoints=5`)

## Interaction checks and screenshots

All functional assertions passed with `runtime_error_count=0` and
`unexpected_http_error_count=0`, and rendered PNG screenshots were visually inspected:

- File upload via `DOM.setFileInputFiles`, job creation (`r1`), desktop mouse brush paint (`painted_alpha_sum=839456`), `Ctrl+Z` undo, `Redo`, Save (`r2`), full page reload & reopen (`persisted_alpha_sum=839436`), and `200 OK` full-res PNG export.
- Native 100% (`256px`) / 200% (`512px`) crop zoom and split divider (`30%` / `inset(0px 70% 0px 0px)`).
- Stale revision conflict (`409`: `"Job changed; reload the current revision before saving"`) keeping unsaved stroke intact.
- Mobile `390×844` zero horizontal overflow (`scrollWidth=390`, `innerWidth=390`) and real `Input.dispatchTouchEvent` `skin` painting.

## Observed defects on baseline `f842879`

1. `UX-KEYBOARD-FOCUS-TRAP` (minor): `Ctrl+Z` ignored while focus remains on `<select id="paintMode">` (`activeElement=SELECT`).
2. `MISSING-FAVICON-404` (minor): `/favicon.ico` returns HTTP `404` (2x across load/reload).
3. `UX-DESKTOP-CANVAS-SCROLL` (minor): scrolling `#save` into view at `1440×900` pushes `#canvasBox` off-screen (`bottom < 0`) because sidebar and canvas share page scroll.

## Verification

- `bash tests/test-browser-acceptance.sh`: exit `0` (`Google Chrome 157.0.8103.50`).
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`: passes all **125 baseline Python tests**.
- `node --check scripts/browser-acceptance.mjs`, `tests/test-web-ui.sh`, `tests/smoke-test.sh`, `json.tool`, and `git diff --check` verified after final edits.

## Remaining limits and next action

- Fix or triage the 3 recorded minor UI defects (`studio.html` focus-trap/sticky canvas/favicon) in a targeted UI change once PR #12 merges or in an agreed follow-up.
- Execute manual physical Android/mobile touch & stylus session plus human creative review to close `F08-B`.
