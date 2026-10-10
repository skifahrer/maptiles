"""A local HTTP server with Range, for readers that must not download everything."""
import http.server
import threading


class Handler(http.server.BaseHTTPRequestHandler):
    blobs, cut_after, ranges_off, requests = {}, {}, False, []

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = self.blobs.get(self.path)
        if body is None:
            self.send_error(404)
            return
        rng = self.headers.get("Range", "")
        self.requests.append((self.path, rng))
        if not rng.startswith("bytes=") or self.ranges_off:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        a, _, b = rng[6:].partition("-")
        a, b = int(a), min(int(b) if b else len(body) - 1, len(body) - 1)
        chunk = body[a:b + 1]
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {a}-{b}/{len(body)}")
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        cut = self.cut_after.pop(self.path, None)
        self.wfile.write(chunk if cut is None else chunk[:cut])


def serve(blobs):
    """`(server, base url)`; `blobs` maps a path to its bytes."""
    Handler.blobs, Handler.cut_after, Handler.ranges_off, Handler.requests = dict(blobs), {}, False, []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
