# MyCodex v81: snapshot-bound UI control

This release is based on the v80 request-continuity runtime. It preserves the v80 request assembly and KV/cache settings while adding a cross-platform UI-control skill for Android and Windows.

## Changes

- Runtime identity: `2026-10-10-runtime-81`.
- Added `snapshot-bound-ui-control` to the published skill catalog and the PyInstaller-bundled skill directory.
- Updated `wish-to-result` routing so UI actions require a live snapshot, current-frame target identification, same-snapshot coordinate mapping, guarded clicks, and visual verification.
- Remembered coordinates and prior screenshots are hints only. An unchanged accessibility tree is not a click result.

## Preserved behavior

- v80 request-prefix continuity and v76 request/history baseline.
- Existing KV configuration and desktop installation are unchanged by this GitHub release; the package is published separately and is not deployed over the running desktop app.

## Build and upload evidence

Build source commit: `bc06efd42c86c1602e15823dd2478e578d775490`.

Package: `MyCodex-v81-windows.zip` (`40713244` bytes, SHA-256 `833c9b8afa9e20c8d0913770172cf1c976f106de30e684fd7bdc067a2f2bd1ac`). ZIP CRC and the bundled skill paths were verified. The desktop application was not replaced by this upload.
