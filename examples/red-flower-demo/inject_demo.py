import sys, time, json, threading, queue
from pathlib import Path
import frida
import frida_tools

PKG = "com.redqueen.fridaflowerdemo"
HERE = Path(__file__).parent

def parse_args(argv):
    js_path = None
    stop_file = None
    args = list(argv)
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--stop-file":
            stop_file = Path(args[i + 1]); i += 2
        else:
            js_path = Path(a)
            i += 1
    if js_path is None:
        js_path = HERE / "hook.js"
    return js_path, stop_file

def main():
    js_path, stop_file = parse_args(sys.argv[1:])
    dev = frida.get_usb_device(timeout=10)
    proc = None
    for p in dev.enumerate_applications():
        if p.identifier == PKG and p.pid:
            proc = p
            break
    if proc:
        print("ATTACH pid", proc.pid, flush=True)
        session = dev.attach(proc.pid)
    else:
        print("SPAWN (app not running)", flush=True)
        pid = dev.spawn([PKG])
        session = dev.attach(pid)
        dev.resume(pid)

    js = open(js_path, "r", encoding="utf-8").read()
    bridge_path = Path(frida_tools.__file__).parent / "bridges" / "java.js"
    deferred = "setTimeout(function () { Script.evaluate(" + json.dumps(str(Path(js_path).resolve())) + ", " + json.dumps(js) + "); }, 50);"
    js = bridge_path.read_text(encoding="utf-8") + "\nglobalThis.Java = bridge;\n" + deferred

    script = session.create_script(js)
    state = {"stopped": False}

    def on_message(message, data):
        t = message.get("type")
        if t == "send":
            print("PAYLOAD:", message.get("payload"), flush=True)
        elif t == "console":
            print("CON:", message.get("payload"), flush=True)
        elif t == "error":
            print("JS-ERROR:", message.get("description"), flush=True)
            if message.get("stack"):
                print("STACK:", message.get("stack"), flush=True)
        else:
            print("MSG:", t, message, flush=True)

    def cleanup():
        if state["stopped"]:
            return
        state["stopped"] = True
        print("[launcher] stopping: restore + unload + detach", flush=True)
        result=queue.Queue()
        def restore():
            try:result.put((True,script.exports_sync.restore()))
            except Exception as error:result.put((False,repr(error)))
        threading.Thread(target=restore,daemon=True).start()
        try:
            ok,value=result.get(timeout=3)
            print('RESTORE_CONFIRMED' if ok else 'RESTORE_FAILED',value,flush=True)
        except queue.Empty:print('RESTORE_FAILED timeout',flush=True)
        try:
            script.unload()
        except Exception:
            pass
        try:
            session.detach()
        except Exception:
            pass
        print("[launcher] detached, bye", flush=True)

    script.on("message", on_message)
    script.load()
    print("loaded; injection active (stoppable)", flush=True)
    try:
        while True:
            time.sleep(0.5)
            if stop_file is not None and stop_file.exists():
                cleanup()
                break
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()

if __name__ == "__main__":
    main()
