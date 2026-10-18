---
name: android-packer-analysis
description: Triage and analyze Android APK protectors when JADX output is incomplete, classes are loaded dynamically, or a user asks about an app shell. Use for authorized APKs and test devices; this is not an iOS FairPlay workflow.
---

# Android APK protector triage

Use only on apps the user owns or is explicitly authorized to test. Start with static APK facts and classify from observed evidence; a blank JADX method alone does not prove a particular protector.

1. Record the APK path, SHA-256, package/version, signing certificate, min/target SDK, ABIs, DEX inventory, manifest Application, and native libraries. Preserve the original sample.
2. Run static JADX/manifest/resource/string analysis first. Compare DEX structure and method bodies. Route ordinary static work to the configured JADX MCP; use Frida/ADB only when runtime behavior is needed and the test device is authorized.
3. Distinguish whole-DEX encryption with runtime loading, extracted method bodies that are restored only when executed, and VMP/Dex2C-style translation into custom bytecode or native code. Keep the classification provisional and cite the evidence.
4. For runtime questions, verify Android/API level, ABI, package PID, Frida client/server compatibility, and app process before attaching. Observe class loaders, DEX paths, and relevant ART loading behavior. Exercise the specific normal app flow that loads the code; avoid indiscriminate class enumeration on large apps.
5. If the authorized goal requires a recovered artifact, use an existing reviewed tool against that authorized sample, keep outputs in the project artifact folder, and validate DEX magic/version, file bounds, checksum/signature, duplicate DEX entries, and whether JADX can parse representative classes. Report missing methods and limitations rather than claiming a complete dump.
6. Keep runtime observation separate from app modification. Do not add stealth, anti-detection bypass, identity spoofing, entitlement/DRM circumvention, or access-control bypass. Do not install or redistribute a recovered third-party app without authorization.

Read [references/packer-notes.md](references/packer-notes.md) when choosing a branch or interpreting incomplete DEX output. Recheck tool/API compatibility against the actual Android version; older article examples are not universal recipes.
