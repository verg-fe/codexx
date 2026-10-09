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

Build and package hashes are recorded in `verification/v81/release-manifest.json` after packaging.
