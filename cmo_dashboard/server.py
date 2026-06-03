"""Optional stdlib static server for the generated dashboard.

Serves dashboard/index.html (and anything in dashboard/) over HTTP for local
viewing. READ-ONLY: it never executes items, never mutates the store, and
exposes no write endpoints. Action rows in the dashboard are display-only.

    python -m cmo_dashboard.server            # serve ./dashboard on :8765
    python -m cmo_dashboard.server --port 9000

Then open http://127.0.0.1:8765/ in a browser. (You can also just open
dashboard/index.html directly from disk — it has no runtime dependencies.)
"""
from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH_DIR = ROOT / "dashboard"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - read-only server, refuse writes
        self.send_error(405, "This dashboard is display-only (no execution).")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(port: int = 8765, host: str = "127.0.0.1") -> None:
    if not (DASH_DIR / "index.html").exists():
        print("dashboard/index.html not found — run `python -m cmo_dashboard.build` first.")
    handler = functools.partial(_QuietHandler, directory=str(DASH_DIR))
    with socketserver.TCPServer((host, port), handler) as httpd:
        print(f"Serving {DASH_DIR} at http://{host}:{port}/  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Serve the generated dashboard (read-only).")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    serve(ap.parse_args().port, ap.parse_args().host)
