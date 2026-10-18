# Android shell triage notes

## What local material already covers

The local r0 collection is useful but not a ready-to-run, current APK-unpacking skill:

- `G:/r0env2026/reference/AndroidSecurityStudy/README.md` indexes FRIDA and FART study materials. Much of this material is older and device/API-specific.
- `G:/r0env2026/reference/frida-all-in-one/README.md` has a shell/protection chapter and historical scripts. Check current Frida and ART behavior before reusing examples.
- `snapshot-bound-ui-control/references/android-app-debugging.md` records local Frida 17 bridge and device lessons; it is UI/runtime troubleshooting, not a general unpack workflow.

## Classification cues

- **Whole-DEX encryption / loader shell:** the packaged DEX may contain a small bootstrap while protected payload is stored encrypted or loaded from memory/private app storage. Look for a proxy Application/early startup loader, asset/native payloads, and runtime class-loader changes. Android `BaseDexClassLoader -> DexPathList -> dexElements -> DexFile` explains where loaded DEX paths may appear, but hidden/in-memory loading can differ by Android release.
- **Method extraction:** class/method metadata may remain while code items are stubbed or absent; behavior can be restored only around method execution. A snapshot taken at startup can therefore be incomplete. Correlate a specific method's normal execution with runtime observations; do not assume every class must be eagerly loaded.
- **VMP / Dex2C:** VMP-like methods may dispatch through a shared interpreter and custom bytecode; Dex2C moves logic into native code. A DEX dump cannot reconstruct original source semantics automatically. Follow native boundaries and report what is observable versus inferred.

These are hypotheses, not vendor fingerprints. Android version, ART internals, protector version, and app execution path change the useful observation point. Validate recovered artifacts structurally and preserve the original.

## Reading list and distilled takeaways

1. 看雪, [APP整体加固原理](https://bbs.kanxue.com/thread-291460.htm): `ClassLoader`, `PathList`, `dexElements`, `DexFile` explain how a loader makes classes visible. The article is a self-built demo, useful for concepts, not proof that a commercial packer uses the same implementation.
2. 看雪, [Android从整体加固到抽取加固的实现及原理](https://bbs.kanxue.com/thread-286929-1.htm): contrasts whole-DEX and per-method extraction; demonstrates why runtime timing and loaded-code state matter. Its Android 10 examples need API-level validation.
3. 看雪, [对Android加固的学习与总结](https://bbs.kanxue.com/thread-292003.htm): organizes whole-DEX, extraction, VMP and Dex2C categories and discusses class-loader/ART observation. Treat its vendor-specific dump-point claims as leads that require independent validation.
4. 看雪, [Android加固技术演进与脱壳方法论](https://bbs.kanxue.com/thread-290735.htm): provides a broad taxonomy from file-backed to in-memory loading and VMP. Use as orientation, not as a universal automatic recipe.

## MCP mapping

- JADX-oriented MCPs such as `delamain` are for static APK/DEX/AAB browsing, decompilation, searches, and cross-references; they do not themselves recover runtime-decrypted DEX.
- Frida MCPs provide runtime device/process/session and instrumentation tools. Recovery still depends on target behavior, compatible Frida/ART versions, and a reviewed workflow; a generic Frida MCP is not a one-click universal unpacker.
- Keep static and runtime findings linked by sample SHA-256, package/version, device/API, process, and artifact hashes. Use bounded outputs and save large artifacts to disk rather than model context.
