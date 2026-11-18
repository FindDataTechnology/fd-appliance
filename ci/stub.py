"""CI stub：在 8000 上提供内核的 /health，在 3000 上提供 paas 的 /api/config。

只用 stdlib：一个 stub 服务不该为了自己再去拉依赖，那会让「构建交付栈」这一步
多一个可能失败的原因，而它本来就是为了验交付栈能不能构建。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def make_handler(payload: dict, status: int = 200):
    body = json.dumps(payload, ensure_ascii=False).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (stdlib 命名)
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):  # 别把 CI 日志刷满
            pass

    return Handler


def serve(port: int, payload: dict) -> None:
    HTTPServer(("0.0.0.0", port), make_handler(payload)).serve_forever()


def main() -> None:
    threading.Thread(target=serve, args=(8000, {"status": "ok"}), daemon=True).start()
    # paas 的健康门探的是 /api/config，返回体形状不重要，200 才是判据
    serve(3000, {"documentsEnabled": False, "ready": True})


if __name__ == "__main__":
    main()
