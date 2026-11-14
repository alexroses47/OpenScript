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


def shared_token():
    """Per-user secret shared by the engine and the local server.

    Kept in a private per-user file and reused, so a server left running by
    an earlier session keeps accepting the engine's requests.
    """
    token = os.environ.get("OPENSCRIPT_TOKEN")
    if token:
        return token
    if os.name == "nt":
        folder = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
                              "OpenScript")
    else:
        folder = os.path.join(os.environ.get("XDG_RUNTIME_DIR")
                              or os.path.expanduser("~/.cache"), "openscript")
    path = os.path.join(folder, "token")
    try:
        with open(path, encoding="ascii") as f:
            token = f.read().strip()
    except OSError:
        token = ""
    if not token:
        import secrets
        token = secrets.token_hex(24)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(token)
    return token


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
    security_selftest(server)
    print("SELFTEST OK")
    return 0


def security_selftest(server):
    """A hostile document must not read local files or reach the network,
    and only the engine (right host, no Origin, right token) may use the server."""
    import http.client
    from http.server import ThreadingHTTPServer

    secret = os.path.join(tempfile.gettempdir(), "openscript-selftest-secret.txt")
    with open(secret, "w") as f:
        f.write("TOP-SECRET")
    url = "file:///" + secret.replace(os.sep, "/").lstrip("/")
    hostile = ('<html><head><title>x</title></head><body>'
               '<p class="action">a <a rel="attachment" href="%s">x</a></p>'
               '<p class="action"><img src="%s"><img src="http://192.0.2.1/x.png"></p>'
               '<p class="action" style="background:url(%s)">b</p></body></html>'
               % (url, url, url))
    for mode in ("film", "comic"):
        pdf = server.render_pdf(server.with_format(hostile, mode, "A4"))
        assert b"/EmbeddedFile" not in pdf and b"TOP-SECRET" not in pdf, "attachment leaked"
    for bad in (url, "http://192.0.2.1/x.png", "https://example.com/x.css"):
        try:
            server.NO_FETCH(bad)
        except Exception:
            pass
        else:
            raise AssertionError("fetch allowed: " + bad)
    os.remove(secret)

    # HTTP access control, on a throw-away port
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    saved = server.ALLOWED_HOSTS, server.TOKEN
    server.ALLOWED_HOSTS, server.TOKEN = {"127.0.0.1:%d" % port}, "selftest-token"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def status(path, headers=None, body=b"<html></html>"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        conn.putrequest("POST", path, skip_host=True)
        hdrs = {"Host": "127.0.0.1:%d" % port, "Content-Length": str(len(body))}
        hdrs.update(headers or {})
        for k, v in hdrs.items():
            conn.putheader(k, v)
        conn.endheaders()
        conn.send(body)
        code = conn.getresponse().status
        conn.close()
        return code

    try:
        ok = "/export/fountain?mode=film&token=selftest-token"
        assert status(ok) == 200, "valid request"
        assert status("/export/fountain?mode=film") == 403, "missing token"
        assert status("/export/fountain?mode=film&token=wrong") == 403, "bad token"
        assert status(ok, {"Host": "evil.example:%d" % port}) == 403, "foreign host"
        assert status(ok, {"Origin": "https://evil.example"}) == 403, "web origin"
        assert status(ok, {"Content-Length": str(server.MAX_BODY + 1)}, b"") == 413, "too large"
    finally:
        httpd.shutdown()
        server.ALLOWED_HOSTS, server.TOKEN = saved
    print("SECURITY SELFTEST OK")


def main():
    log_path = os.path.join(tempfile.gettempdir(), "openscript-server.log")
    log = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log  # windowed exe has no console

    if "--selftest" not in sys.argv:
        # must be set before importing server, and is inherited by the engine
        os.environ["OPENSCRIPT_TOKEN"] = shared_token()
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
