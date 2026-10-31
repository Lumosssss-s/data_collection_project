# H5 预览服务：静态托管 miniapp/dist + /api/* 反代到后端 8002，入口 Basic Auth。
# 启动前置：必须注入 MEDICAL_H5_AUTH_USER 与 MEDICAL_H5_AUTH_PASS，否则拒绝启动。
import base64
import hmac
import http.server
import os
import socketserver
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(REPO_ROOT, "miniapp", "dist")
API_UPSTREAM = "http://127.0.0.1:8002"
PORT = 3100

AUTH_USER = os.environ.get("MEDICAL_H5_AUTH_USER", "").strip()
AUTH_PASS = os.environ.get("MEDICAL_H5_AUTH_PASS", "").strip()

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # BaseRequestHandler.__init__ 内部会直接调用 handle()，计时起点必须先赋值
        self._start = time.time()
        super().__init__(*args, directory=ROOT, **kwargs)

    # 静默默认访问日志，改用 log_request 的精简格式
    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        if not isinstance(code, str):
            code = int(code)
        print("%s %s %s %.3fs" % (self.command, self.path, code, time.time() - self._start), flush=True)

    def log_error(self, fmt, *args):
        print("[error] %s" % (fmt % args), file=sys.stderr, flush=True)

    def _authorized(self):
        token = self.headers.get("Authorization", "")
        if not token.startswith("Basic "):
            return False
        try:
            given = base64.b64decode(token[6:].strip(), validate=True)
        except Exception:
            return False
        expected = ("%s:%s" % (AUTH_USER, AUTH_PASS)).encode("utf-8")
        return hmac.compare_digest(given, expected)

    def _reject(self):
        body = b'{"detail":"unauthorized"}'
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="h5-preview"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _guard(self):
        if self._authorized():
            return True
        self._reject()
        return False

    def _proxy(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(API_UPSTREAM + self.path, data=body, method=method)
        # 只透传后端需要的两个头，不回显凭据
        for h in ("Content-Type", "Authorization"):
            if self.headers.get(h):
                req.add_header(h, self.headers[h])
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                ct = resp.headers.get("Content-Type", "application/json")
                if "text/event-stream" in ct:
                    # SSE：逐块透传不缓冲，否则流式问答退化为一次性返回
                    self.send_response(resp.status)
                    self.send_header("Content-Type", ct)
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.close_connection = True
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    return
                data = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            msg = ('{"detail":"proxy error: %s"}' % e).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_GET(self):
        if not self._guard():
            return
        if self.path.startswith("/api/"):
            self._proxy("GET")
            return
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if self._guard():
            self._proxy("POST")

    def do_PUT(self):
        if self._guard():
            self._proxy("PUT")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    if not AUTH_USER or not AUTH_PASS:
        sys.stderr.write(
            "拒绝启动：未设置 MEDICAL_H5_AUTH_USER / MEDICAL_H5_AUTH_PASS（未提供 Basic Auth 凭据，不回退为无鉴权服务）\n"
        )
        sys.exit(2)
    if not os.path.isdir(ROOT):
        sys.stderr.write("拒绝启动：静态目录不存在 %s\n" % ROOT)
        sys.exit(3)
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        print("h5_preview on :%d -> static=%s api=%s auth_user=%s" % (PORT, ROOT, API_UPSTREAM, AUTH_USER), flush=True)
        httpd.serve_forever()
