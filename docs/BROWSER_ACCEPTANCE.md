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
   `#nativeSplit` CSS divider rendering).
4. Stale revision conflict (`HTTP 409`) preservation of unsaved brush strokes and
   visible `#error` alert rendering.
5. Emulated mobile portrait viewport (`390×844`, `deviceScaleFactor=2`, `hasTouch=true`),
   horizontal overflow check (`scrollWidth <= innerWidth`), and real CDP
   `Input.dispatchTouchEvent` painting.

## Observed defects (recorded against PR #12 baseline `f842879`)

- `UX-KEYBOARD-FOCUS-TRAP` (minor): pressing `Ctrl+Z` while focus remains on `<select id="paintMode">`
  is ignored because [`studio.html`](../fidelis/studio/studio.html) skips global undo whenever
  `document.activeElement.tagName` matches `INPUT|SELECT|TEXTAREA`.
- `MISSING-FAVICON-404` (minor): initial load and reload emit `404` for `/favicon.ico`.
- `UX-DESKTOP-CANVAS-SCROLL` (minor): scrolling lower sidebar actions (`#save`) into view
  at `1440×900` scrolls `#canvasBox` off the top of the viewport (`bottom < 0`) because
  `<aside>` and `<main>` share document scroll.

## Boundaries

Same-host Chromium CDP verifies real DOM, canvas, pointer, emulated touch, keyboard,
and HTTP/network behaviour on macOS/desktop. It **does not** establish physical Android/iOS
touchscreen ergonomics, stylus pressure/palm rejection, or human visual quality acceptance;
`F08-B` therefore remains `In Progress` (`partial`) until physical target-device checks are recorded.

## Usage

```bash
bash tests/test-browser-acceptance.sh --screenshots-dir /tmp/fidelis-f08b-shots
```
