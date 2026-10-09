# MyCodex v78

Includes the existing UI coordinate, crop/compression and startup repairs, plus input-token reduction:

- Keeps real user instructions/corrections and the newest generated reference context. Removes historical duplicate MyCodex reference tails from the inference copy only; the original session archive is preserved.
- Stops repeating full memory-operation instructions on every new user request; deduplicates identical top-level instruction blocks.
- Provides an MCP tool directory. Native coding and small history/skill lookup tools remain available; other original MCP schemas are loaded through tool_catalog_search. Search preserves exact original names/parameters, executes no application action and enables the selected tools for the current user request. Older clients without the directory retain their original tools.
- Archives already observed long historical text outputs under G:\LocalCodex\tool-output-archives. Keeps error excerpts, file paths and head/tail excerpts with a full-output path. Fresh unread outputs and image blocks remain intact.
- Merges only adjacent bare continue messages; actual requirements, corrections and approval text are preserved.
- Records component sizes and reduction counters without logging complete input bodies.

Evidence and limits:

- 14 targeted reduction checks and 6 reference-context checks passed.
- On one real compacted-history sample, removing 16 repeated reference tails reduced retained message-text tokens from 27477 to 6852 (20625 fewer). This excludes system instructions, tool schemas and chat-template overhead.
- Packaged MCP directory search, original schema preservation, selected-tool availability and a real read-only android_devices call passed. The local registry sample had 58 tools: initially 2 loaded, 3 after one search; tool-schema JSON tokenization dropped from 5826 to 188. This is not the complete live native-client catalogue or whole-request token count.
- Full autonomous Huihui directory discovery across every MCP workflow, whole-request token savings and crop/vision/click acceptance remain pending. Historical log excerpts do not prove task success; exact details remain available in archived files.

Runtime was updated while idle: gateway runtime-78 and model health are verified; context is 95000, compaction threshold 92000, Q4 KV and CPU vision. The idle update did not restart the model.

Restore: run MyCodex/MyCodex.exe. Copy extras/android-ui-libs to G:\LocalCodex\tools\android-ui-libs for CPU icon matching. Existing model weights, third-party applications and private runtime settings are not included. Configure paths for the destination host. No credentials, license keys, raw phone screenshots or conversation logs are included. The archive/reference measurements contain counts only.
