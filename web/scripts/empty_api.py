"""A stand-in API that answers like Pheri's on a night when nothing came in, for screenshotting the empty state.

    python web/scripts/empty_api.py      # serves :8000; then `node scripts/evidence.mjs <dir> empty`
"""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DELAY_S = float(os.environ.get("STANDIN_DELAY_S", "0"))  # > 0: the brief answers late, to show the loading state

EMPTY_BRIEF = {"night": "2026-10-30T00:30:00+00:00", "morning": "2026-10-30T01:45:00+00:00",
               "read": {"messages": 0, "by_language": {}, "voice_notes": {"read": 0, "unreadable": 0}},
               "customers": 0, "scheduled": [], "need_you": [], "blocked": [], "stopped": [], "unreadable_voice": [],
               "voice_stand_in": False, "proof": None, "public_demo": False, "mode": "replay"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = {"mode": "replay", "public_demo": False} if self.path.startswith("/health") else EMPTY_BRIEF
        if DELAY_S and not self.path.startswith("/health"):
            time.sleep(DELAY_S)
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
