"""OpenScript launcher for Windows (frozen with PyInstaller as OpenScript.exe).

Starts the local render/export server (PDF, preview, Fountain, FDX, ODT,
DOCX) in a background thread, then runs the bundled Celtx 2.9.7 engine
(app\\celtx.exe) and exits when it closes. Linux uses the shell launcher.
"""
import os
import socket
import subprocess
import sys
import tempfile
import threading


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


SAMPLE = """<html><head><title>Prueba</title>
<meta name="Author" content="OpenScript"></head><body>
<p class="sceneheading"><br></p><p class="shot">Un panel de prueba.</p>
<p class="character">Ana</p><p class="dialog">Hola.</p>
<p class="caption">Un r&oacute;tulo.</p></body></html>"""


def selftest(server):
    """Exercise every renderer once (used by CI); exit code 0 = OK."""
    import exporters
    pdf = server.render_pdf(server.with_format(SAMPLE, "comic", "A4"))
    assert pdf.startswith(b"%PDF"), "pdf"
    prev = server.render_preview(server.with_format(SAMPLE, "comic", "A4"))
    assert b'class="page"' in prev, "preview"
    assert b"PANEL 1.1" in exporters.to_fountain(SAMPLE, "comic"), "fountain"
    assert b"<FinalDraft" in exporters.to_fdx(SAMPLE, "comic"), "fdx"
    film = SAMPLE.replace("shot", "action")
    assert server.render_pdf(server.with_format(film, "film", "USLetter")).startswith(b"%PDF")
    print("SELFTEST OK")
    return 0


def main():
    log_path = os.path.join(tempfile.gettempdir(), "openscript-server.log")
    log = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log  # windowed exe has no console

    import server  # noqa: E402  (after redirecting output)

    if "--selftest" in sys.argv:
        try:
            return selftest(server)
        except Exception as ex:  # report and fail
            print("SELFTEST FAILED:", repr(ex))
            return 1

    if "--server" in sys.argv:
        # Server only (used by the Linux launcher inside the AppImage).
        if not port_in_use(server.PORT):
            server.serve()
        return 0

    if not port_in_use(server.PORT):
        threading.Thread(target=server.serve, daemon=True).start()

    app = os.path.join(base_dir(), "app", "celtx.exe")
    if not os.path.isfile(app):
        print("celtx.exe not found at", app)
        return 1
    proc = subprocess.Popen([app] + sys.argv[1:], cwd=os.path.dirname(app))
    code = proc.wait()
    # The engine re-launches itself in a new process (e.g. on first run after
    # registering components), so keep the server alive while any celtx.exe
    # is still running instead of following only the first process.
    import time
    while engine_running():
        time.sleep(2)
    return code


def engine_running():
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq celtx.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=0x08000000)  # CREATE_NO_WINDOW
        return "celtx.exe" in out.stdout.lower()
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
