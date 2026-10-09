# MyCodex v73

- Android and desktop coordinate mapping explicitly handles original image dimensions, preview scaling and cropping. Desktop mappings require known capture bounds.
- Android MCP now provides fresh UI snapshots, control lookup, CPU icon matching and guarded clicks. Expired or changed snapshots are rejected; repeated unchanged clicks are bounded.
- Old tool screenshots preceding a new user instruction are removed from visual input when appropriate; user uploads and fresh screenshots remain available.
- Startup connection retries are bounded and wait for existing work. Local model status requests bypass proxies only for this application's localhost request.
- Preserves 93,000 context, 87,000 compaction threshold, Q4 KV and CPU vision.

Evidence: coordinate checks 8 passed, stale screenshot checks 5 passed, startup retry checks 4 passed. Actual phone control/icon clicks and original CPU vision phone/desktop coordinate checks were recorded locally. These do not establish that every MCP workflow has passed.

Startup health and slot status recovered. A short dialogue probe timed out while a long user request was running; complete dialogue acceptance remains pending. The earlier model exit cause remains unconfirmed.

Package: MyCodex/MyCodex.exe plus CPU icon dependencies in extras/android-ui-libs. Restore those dependencies to G:\LocalCodex\tools\android-ui-libs before using icon matching. Existing model weights, third-party applications and private runtime configuration are not included. No credentials, license keys, phone screenshots or conversation logs are included.
