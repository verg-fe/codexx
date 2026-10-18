# MyCodex v93 - IDA MCP recovery

## Release contents

- Windows runtime package: [`MyCodex-v93-windows.zip`](https://github.com/verg-fe/codexx/releases/download/v93-20261018/MyCodex-v93-windows.zip)
- SHA-256: `4b393e1f36a7008b7731743fa9a6367305fbc6af94b0bb670e01bca04f289aee`
- The archive contains the complete 270-file onedir deployment, including `MyCodex.exe` and `_internal/`; extract the archive, open `MyCodex-v93/`, and run `MyCodex.exe`.
- Model weights, user conversations, runtime logs, and local credentials are not included. The old ARTEX skill is absent from this package.

## Changes

- IDA MCP connection checks recover from a refused local connection by starting the configured IDA Pro instance and retrying within a bound, while avoiding duplicate IDA processes.
- The IDA local skill and tool-routing guidance are updated alongside the runtime.
- The source snapshot also includes the context-compaction/task-continuation, MCP/Skill lazy-loading, and screenshot OCR updates present in this build.
- The build carries the packaged MCP, mobile app, and 13 current skills from the v93 deployment snapshot. The old ARTEX skill is not included.
- The release tag/package is v93; the internal adapter compatibility string remains `2026-10-15-runtime-89`. They identify different layers.

## Verification limits

The existing v93 build and deployment files were packaged and checked for archive integrity before upload. This upload did not perform fresh-process end-to-end IDA MCP acceptance; the release does not claim that connection was verified in a clean process.

Build timestamp: 2026-10-15 11:11:40 (Asia/Shanghai).
