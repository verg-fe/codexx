# MyCodex v80 release and KV audit

- Desktop launcher now targets the corrected v80 package on G:; the pre-change launcher and prior package remain backed up on G:.
- v76 and v78 used `q4_0` K/V cache, prompt caching enabled, 8192 MiB prompt-cache RAM, idle-slot caching, the G: cache directory, and `--ctx-checkpoints 4`.
- v79 raised `--ctx-checkpoints` to 16. The corrected v80 source/build restores 4 and records that value in active-model policy. The settings file remains at 95,000 context, 92,000 compact threshold, `q4_0`, and vision GPU offload disabled.
- v79 also contains a guarded “release VRAM” UI path and prefix diagnostics; these are retained. Prefix diagnostics compare consecutive rendered text-token prefixes only. They are not the inference server’s actual KV-cache-hit counter.
- The v78 request-context work remains: long tool outputs are archived with summaries, adjacent bare “continue” messages are merged, old generated reference tails are pruned, and MCP tool schemas are loaded from a searchable directory. These reduce repeated input, but change request text/history and can affect how much prefix remains identical between calls. They are not KV storage parameters and were not reverted in this build.
- Source and build checks confirm the v80 model arguments use `q4_0`, prompt caching, 8192 MiB cache RAM, idle-slot caching, `G:\LocalCodex\cache`, and 4 context checkpoints. The package starts and authenticated gateway health reports runtime 80. The inference backend is currently unavailable (`/slots` returns 502 connection refused), so actual model-side KV hit rate has not been measured.

## Build evidence

- Package executable SHA-256: `'F41E4DE10176AD447B99E876B9BC77453E8335A25BA5CA85EA4CB1C66F1FE64D'`
- Desktop launcher SHA-256: `'CF11DA7761AF74148B212669C621463051EEB0972DD6966540B211FC41CF16F7'`
- Candidate output: `G:\LocalCodex-work\mycodex-repair-20261009\deploy\MyCodex-v80-kv-match\MyCodex`
- Previous package backup: `G:\LocalCodex-work\mycodex-repair-20261009\deploy\MyCodex-v80\MyCodex (rollback copy)`