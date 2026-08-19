from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from radar.telegram.bot import TelegramResearchBot


class _Handler(BaseHTTPRequestHandler):
    bot: TelegramResearchBot
    secret: str = ""

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in {"/", "/healthz"}:
            self._json(200, {"ok": True, "service": "research-navigator", "version": "1.0"})
            return
        self._json(404, {"ok": False})

    def do_POST(self) -> None:
        if self.path != "/telegram":
            self._json(404, {"ok": False})
            return
        if self.secret:
            got = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if got != self.secret:
                self._json(403, {"ok": False, "error": "invalid webhook secret"})
                return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            update = json.loads(self.rfile.read(length).decode("utf-8"))
            self.bot.process_update(update)
            self._json(200, {"ok": True})
        except Exception as exc:
            print(f"[webhook] update failed: {exc}")
            self._json(500, {"ok": False, "error": type(exc).__name__})

    def log_message(self, fmt: str, *args) -> None:
        print("[webhook] " + fmt % args)


def serve(config_path: str, host: str, port: int) -> None:
    _Handler.bot = TelegramResearchBot(config_path)
    _Handler.secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"[webhook] Research Navigator V1.0 listening on {host}:{port}")
    server.serve_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Telegram webhook server for Research Navigator")
    parser.add_argument("--config", default="config/radar.json")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")))
    args = parser.parse_args(argv)
    serve(args.config, args.host, args.port)


if __name__ == "__main__":
    main()
