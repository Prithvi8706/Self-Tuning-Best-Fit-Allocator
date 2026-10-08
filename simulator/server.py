"""HTTP JSON API for the simulator UI, plus static serving of the built frontend.

Standard library only. Endpoints:

    GET  /api/meta                       algorithms, workload families, corpus traces
    POST /api/trace/validate             {text}                       -> issues + summary
    POST /api/sim                        {workload, algorithm}        -> session payload
    GET  /api/sim/<id>/frames?start=&count=                           -> heap frames
    POST /api/compare                    {workload, algorithms}       -> job id
    POST /api/experiment                 {family, first_seed, ...}    -> job id
    GET  /api/jobs/<id>                                               -> state, progress, result
"""
import itertools
import json
import mimetypes
import os
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict
from urllib.parse import parse_qs, urlparse

from engine.algorithms.arbf import W
from engine.trace import Op, TraceError
from framework.experiment import ALGORITHMS_BY_NAME, FIXED_MARGINS
from framework.generator import trace_peak_live
from simulator import analysis
from simulator.explain import RULES
from simulator.session import Session, SessionStore
from simulator.workload import WorkloadError, build_workload, catalogue, parse_trace_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(ROOT, "web", "dist")
LABELS = {"first_fit": "First Fit", "best_fit": "Best Fit", "worst_fit": "Worst Fit", "next_fit": "Next Fit",
          "arbf": "ARBF"}
MAX_BODY = 4 * 1024 * 1024
MAX_JOBS = 32


class Jobs:
    """Runs long requests on a worker thread; the browser polls for progress."""

    def __init__(self):
        self._jobs: Dict[str, dict] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def start(self, fn: Callable[[Callable[[int, int], None]], dict]) -> str:
        with self._lock:
            jid = f"j{next(self._ids)}"
            self._jobs[jid] = {"state": "running", "done": 0, "total": 0}
            for old in list(self._jobs)[:-MAX_JOBS]:
                del self._jobs[old]
        job = self._jobs[jid]

        def progress(done: int, total: int) -> None:
            job["done"], job["total"] = done, total

        def run() -> None:
            try:
                job["result"] = fn(progress)
                job["state"] = "done"
            except (ValueError, TraceError) as exc:
                job["error"], job["state"] = str(exc), "error"
            except Exception as exc:  # surfaced to the UI rather than lost in a thread
                traceback.print_exc()
                job["error"], job["state"] = f"internal error: {exc}", "error"

        threading.Thread(target=run, daemon=True).start()
        return jid

    def get(self, jid: str) -> dict:
        job = self._jobs.get(jid)
        if job is None:
            raise KeyError(f"unknown job {jid!r}")
        return job


SESSIONS = SessionStore()
JOBS = Jobs()


def meta() -> dict:
    try:
        cat = catalogue()
    except ImportError as exc:               # the corpus loader needs the study's dependencies (scipy)
        from framework.workloads import FAMILIES
        cat = {"families": [{"name": f.name, "role": f.role, "description": f.description}
                            for f in FAMILIES.values()], "corpus": [], "corpus_error": str(exc)}
    return {"algorithms": [{"name": n, "label": LABELS[n], "rule": RULES[n]} for n in ALGORITHMS_BY_NAME],
            "margins": list(FIXED_MARGINS), "arbf_window": W, "unit_bytes": 16,
            "experiment_event_budget": analysis.MAX_EXPERIMENT_EVENTS, **cat}


def validate_trace(body: dict) -> dict:
    trace, labels, issues = parse_trace_text(str(body.get("text", "")))
    out = {"ok": not issues, "issues": [{"line": i.line, "message": i.message} for i in issues]}
    if trace is not None:
        allocs = sum(e.op is Op.ALLOC for e in trace)
        out["summary"] = {"events": len(trace), "allocs": allocs, "frees": len(trace) - allocs,
                          "peak_live": trace_peak_live(trace),
                          "largest_request": max((e.size for e in trace if e.op is Op.ALLOC), default=0)}
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "arbf-simulator"

    def log_message(self, fmt, *args):     # quiet: only errors are interesting
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    # ---------------------------------------------------------------- plumbing

    def _send_json(self, payload, status=HTTPStatus.OK) -> None:
        data = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status, message: str) -> None:
        self._send_json({"error": message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("request body too large")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _dispatch(self, handler: Callable[[], None]) -> None:
        try:
            handler()
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc.args[0]) if exc.args else "not found")
        except (ValueError, TraceError, WorkloadError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            traceback.print_exc()
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"internal error: {exc}")

    # ----------------------------------------------------------------- routes

    def do_GET(self):
        url = urlparse(self.path)
        parts = url.path.strip("/").split("/")
        if parts[0] != "api":
            return self._static(url.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}

        def route():
            if parts[1:] == ["meta"]:
                return self._send_json(meta())
            if len(parts) == 4 and parts[1] == "sim" and parts[3] == "frames":
                session = SESSIONS.get(parts[2])
                frames = session.frames(int(query.get("start", -1)), int(query.get("count", 1)))
                return self._send_json({"frames": frames})
            if len(parts) == 3 and parts[1] == "jobs":
                return self._send_json(JOBS.get(parts[2]))
            raise KeyError(f"no route GET {url.path}")

        self._dispatch(route)

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")

        def route():
            body = self._body()
            if parts == ["api", "trace", "validate"]:
                return self._send_json(validate_trace(body))
            if parts == ["api", "sim"]:
                session = Session(build_workload(body.get("workload") or {}), str(body.get("algorithm")))
                return self._send_json({"id": SESSIONS.add(session), **session.payload()})
            if parts == ["api", "compare"]:
                workload = build_workload(body.get("workload") or {})       # validate before queueing
                algorithms = body.get("algorithms")
                return self._send_json({"job": JOBS.start(lambda p: analysis.compare(workload, algorithms, p))})
            if parts == ["api", "experiment"]:
                return self._send_json({"job": JOBS.start(lambda p: analysis.experiment(body, p))})
            raise KeyError(f"no route POST {self.path}")

        self._dispatch(route)

    def _static(self, path: str) -> None:
        if not os.path.isdir(STATIC_DIR):
            return self._error(HTTPStatus.NOT_FOUND,
                               "frontend not built: run `npm install && npm run build` in web/")
        target = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not target.startswith(STATIC_DIR + os.sep) or not os.path.isfile(target):
            target = os.path.join(STATIC_DIR, "index.html")               # single-page app
        with open(target, "rb") as f:
            data = f.read()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"ARBF simulator on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
