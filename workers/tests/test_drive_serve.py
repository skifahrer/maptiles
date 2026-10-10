import http.client
import json
import threading
import unittest
from unittest import mock

from load import worker

serve = worker("drive/serve.py", name="drive_serve")

QUOTA = json.dumps({"error": {"errors": [{"reason": "downloadQuotaExceeded"}]}}).encode()


class Resp:
    def __init__(self, status, body=b"", headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def read(self):
        return self.body


class Conn:
    """Answers from a shared script; records (host, path, headers) per request."""

    def __init__(self, host, script, seen):
        self.host, self.script, self.seen = host, script, seen
        self.closed = False

    def request(self, method, path, headers=None):
        self.seen.append((self.host, path, dict(headers or {})))

    def getresponse(self):
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def close(self):
        self.closed = True


class Creds:
    def __init__(self):
        self.tokens = ["t1", "t2"]
        self.renewed = []

    def token(self):
        return self.tokens[0]

    def renew(self, old):
        self.renewed.append(old)
        self.tokens.pop(0)
        return self.tokens[0]


class PoolGet(unittest.TestCase):
    def setUp(self):
        self.script, self.seen, self.conns = [], [], []

        def connect(host, timeout=180):
            c = Conn(host, self.script, self.seen)
            self.conns.append(c)
            return c

        for p in (mock.patch.object(serve, "connect", connect),
                  mock.patch.object(serve.time, "sleep")):
            p.start()
            self.addCleanup(p.stop)

    def test_a_range_answer_returns_and_the_connection_is_reused(self):
        pool = serve.Pool()
        self.script += [Resp(206, b"ab"), Resp(206, b"cd")]
        self.assertEqual(pool.get("F", "bytes=0-1", want=2)[2], b"ab")
        self.assertEqual(pool.get("F", "bytes=2-3", want=2)[2], b"cd")
        self.assertEqual(len(self.conns), 1)
        host, path, _ = self.seen[0]
        self.assertEqual(host, serve.PUBLIC_HOST)
        self.assertIn("id=F", path)

    def test_a_redirect_is_remembered_and_costs_no_try(self):
        pool = serve.Pool()
        self.script += [Resp(302, headers={"Location": "https://cdn.example/x?sig=1"}),
                        Resp(206, b"ab"), Resp(206, b"cd")]
        pool.get("F", "bytes=0-1", want=2, tries=1)
        pool.get("F", "bytes=2-3", want=2, tries=1)
        self.assertEqual([(h, p) for h, p, _ in self.seen[1:]],
                         [("cdn.example", "/x?sig=1")] * 2)

    def test_an_expired_redirect_goes_back_to_the_file(self):
        pool = serve.Pool()
        pool._remember("F", "https://cdn.example/old")
        self.script += [Resp(403), Resp(206, b"ab")]
        pool.get("F", "bytes=0-1", want=2)
        self.assertEqual(self.seen[1][0], serve.PUBLIC_HOST)

    def test_the_token_goes_only_to_the_api_host(self):
        pool = serve.Pool(creds=Creds())
        self.script += [Resp(302, headers={"Location": "https://cdn.example/x"}), Resp(206, b"a")]
        pool.get("F", "bytes=0-0", want=1)
        self.assertEqual(self.seen[0][2]["Authorization"], "Bearer t1")
        self.assertNotIn("Authorization", self.seen[1][2])

    def test_401_renews_once_then_stops_the_pool(self):
        creds = Creds()
        pool = serve.Pool(creds=creds)
        self.script += [Resp(401), Resp(206, b"a")]
        pool.get("F", "bytes=0-0", want=1)
        self.assertEqual(creds.renewed, ["t1"])

        creds.tokens = ["t1", "t2"]
        self.script += [Resp(401), Resp(401)]
        with self.assertRaisesRegex(RuntimeError, "even after renewal"):
            serve.Pool(creds=creds).get("F", "bytes=0-0", want=1)

    def test_a_quota_refusal_stops_every_later_call(self):
        pool = serve.Pool()
        self.script += [Resp(403, QUOTA)]
        with self.assertRaisesRegex(RuntimeError, "download limit"):
            pool.get("F", "bytes=0-0", want=1)
        asked = len(self.seen)
        with self.assertRaises(RuntimeError):
            pool.get("F", "bytes=0-0", want=1)
        self.assertEqual(len(self.seen), asked)

    def test_an_html_page_with_status_200_is_a_refusal(self):
        pool = serve.Pool()
        self.script += [Resp(200, b"<!DOCTYPE html><title>Quota exceeded</title>")]
        with self.assertRaisesRegex(RuntimeError, "download limit"):
            pool.get("F", "bytes=0-9", want=10)
        self.assertTrue(pool.refused)

    def test_a_200_with_the_whole_range_is_accepted(self):
        self.script += [Resp(200, b"abcd")]
        self.assertEqual(serve.Pool().get("F", "bytes=0-3", want=4)[0], 200)

    def test_the_rate_limit_has_its_own_budget(self):
        pool = serve.Pool()
        self.script += [Resp(429, headers={"Retry-After": "0"})] * 3 + [Resp(206, b"a")]
        with mock.patch.object(pool, "_wait_out"):
            self.assertEqual(pool.get("F", "bytes=0-0", want=1, tries=1)[2], b"a")
        self.assertGreater(pool.cooldown, 0)

    def test_network_errors_use_up_the_tries(self):
        self.script += [OSError("reset")] * 3
        with self.assertRaisesRegex(RuntimeError, "3 tries.*reset"):
            serve.Pool().get("F", "bytes=0-0", want=1, tries=3)
        self.assertTrue(all(c.closed for c in self.conns))

    def test_an_unscanned_file_is_acknowledged_only_when_asked(self):
        pool = serve.Pool(creds=Creds())
        self.assertNotIn("acknowledgeAbuse", pool.target("F")[1])
        abusive = json.dumps({"error": {"errors": [{"reason": "cannotDownloadAbusiveFile"}]}}).encode()
        self.script += [Resp(403, abusive), Resp(206, b"a")]
        pool.get("F", "bytes=0-0", want=1)
        self.assertIn("acknowledgeAbuse=true", self.seen[1][1])

    def test_probe_size_reads_content_range(self):
        self.script += [Resp(206, b"a", {"Content-Range": "bytes 0-0/12345"})]
        self.assertEqual(serve.probe_size(serve.Pool(), "F"), 12345)
        self.script += [Resp(206, b"a")]
        with self.assertRaisesRegex(RuntimeError, "no Content-Range"):
            serve.probe_size(serve.Pool(), "F")


class Ranges(unittest.TestCase):
    def test_parse_ranges(self):
        self.assertEqual(serve.parse_ranges("bytes=0-9,20-,-5", 100), [(0, 9), (20, 99), (95, 99)])
        self.assertEqual(serve.parse_ranges("bytes=90-200", 100), [(90, 99)])
        self.assertEqual(serve.parse_ranges("bytes=200-300", 100), [])
        self.assertEqual(serve.parse_ranges("bytes=-500", 100), [(0, 99)])
        self.assertEqual(serve.parse_ranges("bytes=0-1, ,", 100), [(0, 1)])

    def test_reasons(self):
        self.assertEqual(serve.api_error(QUOTA), "downloadQuotaExceeded")
        self.assertEqual(serve.api_error(b'{"error": "invalid_grant"}'), "invalid_grant")
        self.assertIsNone(serve.api_error(b"\x00\x01binary"))
        self.assertIsNone(serve.drive_refusal(b"II*\x00tiff"))
        self.assertIn("HTML page", serve.drive_refusal(b"<html><body>hi</body></html>"))
        self.assertIn("notFound", serve.hard_reason("notFound", True))
        self.assertIsNone(serve.hard_reason("backendError", True))
        self.assertNotEqual(serve.quota_hint(True), serve.quota_hint(False))


class FakePool:
    def __init__(self, data):
        self.data, self.calls = data, []

    def get(self, file_id, rng, want=None):
        self.calls.append(rng)
        if file_id == "broken":
            raise RuntimeError("Drive said no")
        a, b = (int(v) for v in rng.split("=")[1].split("-"))
        return 206, {}, self.data[a:b + 1]


class Handler(unittest.TestCase):
    DATA = bytes(range(256)) * 4

    def setUp(self):
        self.pool = FakePool(self.DATA)
        self.stats = {"requests": 0, "bytes": 0, "failed": 0, "lock": threading.Lock()}
        files = {"dmr5.tif": ("F", len(self.DATA)), "bad.tif": ("broken", 100)}
        self.httpd = serve.Server(("127.0.0.1", 0), serve.make_handler(self.pool, files, self.stats))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def ask(self, method, path, rng=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        conn.request(method, path, headers={"Range": rng} if rng else {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def test_head_tells_the_real_length(self):
        resp, _ = self.ask("HEAD", "/dmr5.tif")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Length"), str(len(self.DATA)))
        self.assertEqual(self.ask("HEAD", "/dmr5.tif.ovr")[0].status, 404)

    def test_a_single_range(self):
        resp, body = self.ask("GET", "/dmr5.tif", "bytes=10-19")
        self.assertEqual(resp.status, 206)
        self.assertEqual(body, self.DATA[10:20])
        self.assertEqual(resp.getheader("Content-Range"), f"bytes 10-19/{len(self.DATA)}")
        self.assertEqual(self.stats["bytes"], 10)

    def test_several_ranges_are_multipart(self):
        resp, body = self.ask("GET", "/dmr5.tif", "bytes=0-3,100-103")
        self.assertEqual(resp.status, 206)
        ctype = resp.getheader("Content-Type")
        self.assertTrue(ctype.startswith("multipart/byteranges; boundary="))
        boundary = ctype.split("boundary=")[1].encode()
        parts = [p for p in body.split(b"--" + boundary) if p.strip(b"\r\n-")]
        self.assertEqual(len(parts), 2)
        for part, (a, b) in zip(parts, ((0, 3), (100, 103))):
            head, payload = part.split(b"\r\n\r\n", 1)
            self.assertIn(f"Content-Range: bytes {a}-{b}/".encode(), head)
            self.assertEqual(payload.rstrip(b"\r\n"), self.DATA[a:b + 1])

    def test_a_range_past_the_end_is_416_not_the_whole_file(self):
        resp, _ = self.ask("GET", "/dmr5.tif", "bytes=5000-6000")
        self.assertEqual(resp.status, 416)
        self.assertEqual(self.pool.calls, [])

    def test_no_range_streams_the_file(self):
        resp, body = self.ask("GET", "/dmr5.tif")
        self.assertEqual((resp.status, body), (200, self.DATA))

    def test_unknown_name_is_404(self):
        self.assertEqual(self.ask("GET", "/other.tif", "bytes=0-1")[0].status, 404)

    def test_a_drive_failure_is_a_502_not_a_hang(self):
        resp, body = self.ask("GET", "/bad.tif", "bytes=0-9")
        self.assertEqual(resp.status, 502)
        self.assertIn(b"Drive said no", body)
        self.assertEqual(self.stats["failed"], 1)


if __name__ == "__main__":
    unittest.main()
