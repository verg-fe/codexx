# MyCodex v80: restore v76 request behavior

This supplemental v80 build restores the v76 application/request behavior while retaining the MCP and Skill additions. The v76 baseline is commit `45b05110debfda1f1909a24690957c4e2571a5b4`.

## Kept on top of v76

- Delamain MCP integration and its example configuration/source archive.
- MobileRE Skill and the existing MCP/Skill set.
- Optional `tool_catalog_search` MCP directory. It only looks up names/descriptions/schemas. It does not filter, remove, or selectively load any advertised MCP schema; the full tool list remains available.
- Runtime identity/build label `2026-10-09-runtime-80`.

## Restored to v76

The regular app, prompt/history assembly, gateway request construction, and model catalog are restored to the v76 baseline. The v78 request-context changes for adjacent “continue” merging, generated-tail pruning, and long tool-output archival are absent. Existing v76 image-observation and thread-history behavior remains unchanged. The only gateway difference from v76 is registering the lookup-only MCP tool directory.

KV configuration matches v76: `q4_0`, prompt cache enabled, 8192 MiB prompt-cache RAM, idle-slot caching, cache under `G:\LocalCodex\cache`, and `--ctx-checkpoints 4`. Settings are context 95,000 and compact threshold 92,000; vision GPU offload remains disabled.

## Verification evidence

- Candidate package launched from G:; authenticated `/health` returned HTTP 200 and runtime 80.
- `/slots` returned HTTP 502 because the local inference backend was not running. Therefore the configured KV values are restored, but model-side KV reuse/hit rate has not been measured in this run.
- Package SHA-256: `cb7f236b158f5bd8b253485c983898029c39cb9c339a9d53ada450c829c8103f` (76,973,334 bytes).
- Executable SHA-256: `09de769b9727d949aee66a3514112e5091a5b4c14822bc852c20c1357f441134`.
- Desktop launcher SHA-256: `c6a2b5e1c8a180fc171317c08257c6341036558748432775e924b46f4e40f442`.
