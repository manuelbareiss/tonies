"""Loopback-only, dependency-free browser interface to the existing CLI."""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from tonie_writer import catalog
from tonie_writer.nfcfile import parse_nfc_file

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/theme.js": ("theme.js", "text/javascript"),
    "/locale-en.js": ("locale-en.js", "text/javascript"),
    "/locale-de.js": ("locale-de.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
}


def command_for(payload: dict) -> tuple[list[str], str]:
    """Validate a bounded action; never accept shell commands from the browser."""
    action = payload.get("action")
    if not isinstance(action, str) or action not in {"preview", "write", "read", "doctor", "probe", "index"}:
        raise ValueError("Unknown toolbox action.")
    argv = [sys.executable, "-u", "-m", "tonie_writer"]
    port = payload.get("port", "")
    if not isinstance(port, str) or len(port) > 256 or "\x00" in port:
        raise ValueError("Invalid serial port.")
    if port.strip():
        argv += ["--port", port.strip()]
    for flag in ("verbose", "json"):
        if payload.get(flag) is True:
            argv.append("--" + flag)
    if action in {"preview", "write"}:
        entries = catalog.load_catalog()
        entry = next((e for e in entries if e.id == payload.get("id")), None)
        if entry is None:
            raise ValueError("Choose an available Tonie first.")
        resolved = catalog.resolve(entries, entry.id, language=entry.language)
        if resolved.entry != entry:
            raise ValueError("This catalog identifier is ambiguous; use the CLI to resolve it.")
        if action == "write" and payload.get("confirmed") is not True:
            raise ValueError("Confirm the selected Tonie before writing.")
        mode = payload.get("mode", "full")
        if not isinstance(mode, str) or mode not in {"full", "uid", "blocks"}:
            raise ValueError("Invalid write mode.")
        retries = payload.get("retries", 2)
        if type(retries) is not int or not 1 <= retries <= 10:
            raise ValueError("Retries must be between 1 and 10.")
        argv += ["write", entry.id, "--language", entry.language, "--retries", str(retries)]
        if action == "preview":
            argv.append("--dry-run")
        else:
            argv.append("--yes")  # Only after the GUI confirms this exact ID.
        if mode != "full":
            argv.append("--uid-only" if mode == "uid" else "--blocks-only")
        if payload.get("no_verify") is True:
            argv.append("--no-verify")
    elif action == "probe":
        if payload.get("confirmed") is not True:
            raise ValueError("Confirm the test UID probe first.")
        argv += ["doctor", "--probe-magic"]
    else:
        argv.append(action)
    return argv, "y\n" if action == "probe" else ""


class ToolboxServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, port=None):
        super().__init__(address, Handler)
        self.token = secrets.token_urlsafe(32)
        self.serial_port = port or ""
        self.jobs = {}
        self.job_lock = threading.Lock()
        self.busy = False

    def start_job(self, payload):
        argv, stdin = command_for(payload)
        with self.job_lock:
            if self.busy:
                raise RuntimeError("Another operation is running. Wait for it to finish.")
            self.busy = True
            job_id = secrets.token_hex(8)
            job = {"id": job_id, "action": payload["action"], "output": "", "done": False, "code": None}
            self.jobs[job_id] = job
            for old in list(self.jobs)[:-30]:
                del self.jobs[old]
        def run():
            try:
                with subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding="utf-8", errors="replace") as proc:
                    proc.stdin.write(stdin)
                    proc.stdin.close()
                    for line in proc.stdout:
                        with self.job_lock:
                            job["output"] = (job["output"] + line)[-200000:]
                    code = proc.wait()
                with self.job_lock:
                    job["code"] = code
            except Exception as exc:
                with self.job_lock:
                    job["output"] += str(exc)
                    job["code"] = 1
            finally:
                with self.job_lock:
                    job["done"] = True
                    self.busy = False
        # Let a hardware operation finish even if the server is stopped.
        threading.Thread(target=run, daemon=False).start()
        return {"id": job_id}


class Handler(BaseHTTPRequestHandler):
    # ponytail: idle timeout only; add a request deadline if slow clients matter.
    timeout = 10

    def log_message(self, *_):
        pass

    def send_data(self, status, body, content_type="application/json; charset=utf-8", filename=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'none'",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def trusted(self):
        host = self.headers.get("Host", "")
        expected = f"127.0.0.1:{self.server.server_port}"
        return host == expected

    def do_HEAD(self):
        # Desktop URL openers may probe the page before opening the browser.
        self.do_GET()

    def do_GET(self):
        if not self.trusted():
            self.send_data(403, {"error": "Use the local GUI address printed in your terminal."})
            return
        try:
            url = urlsplit(self.path)
            if url.path in STATIC_FILES:
                filename, mime = STATIC_FILES[url.path]
                self.send_data(200, (STATIC / filename).read_bytes(), mime + "; charset=utf-8")
            else:
                self.get_api(url.path, parse_qs(url.query))
        except (ValueError, OSError, catalog.CatalogError) as exc:
            self.send_data(400, {"error": str(exc)})

    def get_api(self, path, params):
        if path == "/api/config":
            self.send_data(200, {"token": self.server.token, "port": self.server.serial_port})
        elif path == "/api/catalog":
            self.send_data(200, {"tonies": [asdict(e) for e in catalog.load_catalog()]})
        elif path == "/api/search":
            query = params.get("q", [""])[0][:256]
            entries = catalog.load_catalog()
            results = [asdict(match.entry) for match in catalog.search(entries, query)]
            seen = {e["id"] for e in results}
            results += [asdict(e) for e in entries
                        if query.upper().replace(" ", "") in e.uid and e.id not in seen]
            self.send_data(200, {"tonies": results})
        elif path in {"/api/entry", "/api/download"}:
            entry_id = params.get("id", [""])[0]
            entry = next((e for e in catalog.load_catalog() if e.id == entry_id), None)
            if entry is None:
                self.send_data(404, {"error": "Tonie not found."})
            elif path == "/api/download":
                self.send_data(200, (ROOT / entry.path).read_bytes(),
                               "application/octet-stream", Path(entry.path).name)
            else:
                tag = parse_nfc_file(ROOT / entry.path)
                self.send_data(200, {**asdict(entry), "blocks": tag.blocks})
        elif path.startswith("/api/jobs/"):
            with self.server.job_lock:
                job = self.server.jobs.get(path.rsplit("/", 1)[-1])
                job = dict(job) if job is not None else None
            if job is None:
                self.send_data(404, {"error": "Operation not found."})
            else:
                self.send_data(200, job)
        else:
            self.send_data(404, {"error": "Not found."})

    def do_POST(self):
        origin = self.headers.get("Origin")
        expected = f"http://127.0.0.1:{self.server.server_port}"
        if (not self.trusted() or (origin and origin != expected)
                or self.headers.get("X-Toolbox-Token") != self.server.token):
            self.send_data(403, {"error": "Refresh the local GUI before trying again."})
            return
        if self.path != "/api/run":
            self.send_data(404, {"error": "Not found."})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                raise ValueError("Invalid request size.")
            try:
                body = self.rfile.read(size)
            except TimeoutError:
                self.send_data(408, {"error": "Request timed out."})
                return
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Expected an action object.")
            self.send_data(202, self.server.start_job(payload))
        except (ValueError, OSError, catalog.CatalogError) as exc:
            self.send_data(400, {"error": str(exc)})
        except RuntimeError as exc:
            self.send_data(409, {"error": str(exc)})


def serve(listen_port=8765, open_browser=True, port=None):
    if not 0 <= listen_port <= 65535:
        print("error: GUI listen port must be between 0 and 65535.", file=sys.stderr)
        return 1
    try:
        server = ToolboxServer(("127.0.0.1", listen_port), port=port)
    except OSError as exc:
        print(f"error: {exc}. Try './tonie gui --listen-port 8766'.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Tonie Studio → {url}\nKeep this terminal open. Press Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if server.busy:
            print("Waiting for the active operation to finish. Keep the reader connected.", flush=True)
    finally:
        server.server_close()
    return 0
