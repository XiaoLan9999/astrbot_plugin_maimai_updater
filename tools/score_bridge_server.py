from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Awaitable, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maimai_official_interface import (
    ChimeSessionError, MaimaiOfficialClient, OfficialProtocolUnavailableError,
)
from remote_scores import validate_details
from utils import is_probable_sgid, validate_sgid_freshness


async def fetch_official(sgid: str) -> dict:
    result = await MaimaiOfficialClient(timeout=45).fetch_from_sgid(sgid)
    return {
        "protocol": 1,
        "rating": result.rating,
        "music_details": validate_details(result.music_details),
    }


def make_server(
    address: tuple[str, int], access_token: str,
    fetch: Callable[[str], Awaitable[dict]] = fetch_official,
) -> ThreadingHTTPServer:
    if not access_token:
        raise ValueError("MAIMAI_SCORE_SERVICE_TOKEN is required")
    request_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _respond(self, status: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                self._respond(200, {"protocol": 1, "status": "ok"})
            else:
                self._respond(404, {"error": "not_found"})

        def do_POST(self):
            self.connection.settimeout(15)
            if self.path != "/v1/scores":
                self._respond(404, {"error": "not_found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192:
                    raise ValueError
                request_body = self.rfile.read(size)
            except (ValueError, OSError):
                self._respond(400, {"error": "invalid_request"})
                return
            expected = f"Bearer {access_token}".encode("utf-8")
            supplied = self.headers.get("Authorization", "").encode("utf-8")
            if not hmac.compare_digest(supplied, expected):
                self._respond(401, {"error": "unauthorized"})
                return
            try:
                payload = json.loads(request_body)
                if not isinstance(payload, dict) or set(payload) != {"sgid"}:
                    raise ValueError
                sgid = payload["sgid"]
                if not isinstance(sgid, str) or not is_probable_sgid(sgid):
                    raise ValueError
                if not validate_sgid_freshness(sgid, max_age_seconds=600).ok:
                    self._respond(409, {"error": "invalid_credential"})
                    return
            except (TypeError, ValueError, OSError):
                self._respond(400, {"error": "invalid_request"})
                return
            if not request_lock.acquire(blocking=False):
                self._respond(503, {"error": "busy"})
                return
            try:
                result = asyncio.run(fetch(sgid))
                self._respond(200, result)
            except ChimeSessionError:
                self._respond(409, {"error": "invalid_credential"})
            except OfficialProtocolUnavailableError:
                self._respond(503, {"error": "unavailable"})
            except Exception as exc:
                print(f"Score request failed: {type(exc).__name__}", file=sys.stderr)
                self._respond(502, {"error": "score_fetch_failed"})
            finally:
                request_lock.release()

    return ThreadingHTTPServer(address, Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Maimai full-score service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18250)
    args = parser.parse_args()
    token = os.environ.get("MAIMAI_SCORE_SERVICE_TOKEN", "")
    if not token:
        parser.error("Set MAIMAI_SCORE_SERVICE_TOKEN before starting the service")
    server = make_server((args.host, args.port), token)
    print(f"Score service listening on {args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
