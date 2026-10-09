# MyCodex v76

Includes v73 startup recovery and coordinate tools, plus v74/v75 improvements:

- Phone tool screenshots use control text before CPU vision. User image attachments remain available to vision.
- Unfamiliar/custom symbols can explicitly request CPU vision; permissions are bound to image hashes and expire after 180 seconds.
- New phone and desktop crop tools preserve the original screenshot, save crop offsets and create losslessly compressed PNG files without resizing the retained pixels.
- New mapping tools restore normalized or preview-pixel coordinates to the original image. Phone points use existing guarded clicks. Desktop physical coordinates require known capture bounds and correct click API DPI units.
- Changed/expired crops and snapshots are rejected. Template matching is an optional aid; similarity does not establish a symbol's meaning.
- Stream interruptions get diagnostic records and explicit failure handling. The exact cause of the reported prior interruption remains unconfirmed.
- Preserves 95,000 context, 92,000 compaction threshold, Q4 KV and CPU vision.

Evidence: 8 crop checks and 8 image-routing checks passed. Packaged MCP tool discovery and real phone control snapshot reading passed. A real phone crop kept pixels identical, reduced 1080x2400 to 151x235 and 190103 to 5128 bytes, and restored its center to (665,1702), matching the control bounds. A prior desktop capture was also cropped and mapped. These checks performed no live clicks; the complete Huihui crop/vision/click flow and performance improvement remain pending acceptance. The user's later report of successfully clicking (665,1702) is separate from these tests.

Runtime status at packaging: The 95,000 / 92,000 settings have been saved; runtime application waits for an idle owned model. A separate v76 build directory avoids overwriting files loaded by another process.

Restore: run MyCodex/MyCodex.exe. Copy extras/android-ui-libs to G:\LocalCodex\tools\android-ui-libs for CPU icon matching. Existing model weights, third-party applications and private runtime settings are not included. Configure tools/model paths for the destination host. No credentials, license keys, raw phone screenshots or conversation logs are included.
