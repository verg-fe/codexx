# Local Red Flower Frida demo

Authorized package only: com.redqueen.fridaflowerdemo.
Click shows a black flower, then an account/password dialog. No backend; inputs are not read, saved or sent.
Requirements: Frida 17.22.2 client/server and installed frida-tools Java bridge. Configure YOUR_USER and YOUR_ADB_SERIAL in the launch scripts.
Run start_demo.ps1 to keep injection active. Run stop_demo.ps1 to restore the original listener, remove the UI and detach.
Verified on 2026-10-07: actual root touch click, black flower and dialog; measured delays 1170/1165 ms for a 1000 ms timer; graceful stop and reload; persistent launcher exit 0.
No private phone databases, conversations, credentials, screenshots or raw logs are included.
