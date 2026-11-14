# Same-host browser acceptance (`F08-B` / `MEL-80`)

This suite executes a real headless Chromium/Google Chrome browser over the
Chrome DevTools Protocol (CDP) against a loopback [`scripts/web-ui.py`](../scripts/web-ui.py)
`/regions` server using an isolated temporary workspace.

## Runner and wrapper

- CDP runner (Node 22+ built-in `WebSocket`/`fetch`, zero extra packages):
  [`scripts/browser-acceptance.mjs`](../scripts/browser-acceptance.mjs)
- Shell wrapper (fails closed if Chrome/Chromium is unavailable; never fakes a pass):
  [`tests/test-browser-acceptance.sh`](../tests/test-browser-acceptance.sh)

## Verified coverage

1. Real `<input type="file">` pass upload (`DOM.setFileInputFiles`) and saved job creation.
2. Mouse pointer drag brush strokes on `<canvas id="paintCanvas">` (`desktop 1440×900`),
   live RGBA overlay pixel verification, button undo/redo, keyboard `Ctrl+Z` (after
   moving focus off selects/inputs), revision save, full `Page.reload`, job reopen, and
   `200 OK` PNG export verification.
3. Native 100% / 200% pixel inspection panel (`#inspectNative`, `#nativeZoom`,
   `#nativeSplit` CSS divider rendering) plus structural crop checking (`#checkNativeStructure`)
   and explicit structural crop locking (`#lockNativeStructure` -> `POST /api/regions/jobs/<id>/structure`).
4. Stale revision conflict (`HTTP 409`) preservation of unsaved brush strokes and
   visible `#error` alert rendering.
5. Emulated mobile portrait viewport (`390×844`, `deviceScaleFactor=2`, `hasTouch=true`),
   horizontal overflow check (`scrollWidth <= innerWidth`), and real CDP
   `Input.dispatchTouchEvent` painting.

## Resolved UI defects (fixed on `feat/region-aware-studio`)

- `UX-KEYBOARD-FOCUS-TRAP` (resolved): `Ctrl+Z` / `Cmd+Z` now executes global brush undo
  even when `<select>` or non-text `<input>` controls retain focus; only text-entry inputs
  (`text`, `search`, `url`, `tel`, `email`, `password`, `number`, `<textarea>`, `isContentEditable`)
  intercept native text undo.
- `MISSING-FAVICON-404` (resolved): `<link rel="icon" href="data:,">` in `studio.html` and
  `204 No Content` for `/favicon.ico` in `scripts/web-ui.py` eliminate console 404 noise.
- `UX-DESKTOP-CANVAS-SCROLL` (resolved): `@media(min-width:781px){main{position:sticky;top:0;align-self:start;max-height:calc(100vh - 67px);overflow:auto}}`
  keeps `#canvasBox` visible in the desktop viewport when scrolling lower `<aside>` controls (`#save`).
- Latest CDP run (`Google Chrome 157.0.8103.79` on `darwin arm64`): `observed_defects: []`,
  `runtime_error_count: 0`, `unexpected_http_error_count: 0`.

## Boundaries

Same-host Chromium CDP verifies real DOM, canvas, pointer, emulated touch, keyboard,
and HTTP/network behaviour on macOS/desktop. It **does not** establish physical Android/iOS
touchscreen ergonomics, stylus pressure/palm rejection, or human visual quality acceptance;
`F08-B` therefore remains `In Progress` (`partial`) until physical target-device checks are recorded.

## Usage

```bash
bash tests/test-browser-acceptance.sh --screenshots-dir /tmp/fidelis-f08b-shots
```
