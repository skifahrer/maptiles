import threading
import unittest
from unittest import mock

from load import worker

auth = worker("drive/auth.py", name="drive_auth")
api = auth.api
store = worker("drive/store.py", name="drive_store")
cache = worker("drive/cache.py", name="drive_cache")


class FakeConn:
    def __init__(self, answers):
        self.answers = answers

    def request(self, *a, **kw):
        nxt = self.answers.pop(0)
        if isinstance(nxt, Exception):
            raise nxt

    def getresponse(self):
        return mock.Mock(status=200, read=lambda: b'{"ok": 1}')

    def close(self):
        pass


class RequestJson(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(api.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def connect_with(self, answers):
        conns = []

        def connect(host, timeout=60):
            conns.append(host)
            return FakeConn(answers)
        return mock.patch.object(api.drive, "connect", connect), conns

    def test_retries_then_succeeds(self):
        patch, conns = self.connect_with([OSError("reset"), OSError("reset"), None])
        with patch:
            self.assertEqual(api.request_json("GET", "h", "/p"), (200, {"ok": 1}))
        self.assertEqual(len(conns), 3)

    def test_gives_up_after_tries(self):
        patch, conns = self.connect_with([OSError("down")] * 5)
        with patch, self.assertRaises(api.AuthError):
            api.request_json("GET", "h", "/p?secret=1", tries=3)
        self.assertEqual(len(conns), 3)


class Renewal(unittest.TestCase):
    def test_401_renews_once_not_per_thread(self):
        fetched = []

        def token_answer(method, host, path, body=None, headers=None, tries=4):
            fetched.append(1)
            return 200, {"access_token": f"t{len(fetched)}", "expires_in": 3600}

        creds = auth.Credentials("1-x.apps", "s", "r")
        with mock.patch.object(auth, "request_json", token_answer):
            stale = creds.token()
            threads = [threading.Thread(target=creds.renew, args=(stale,)) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(fetched), 2)
        self.assertEqual(creds.token(), "t2")

    def test_api_call_retries_a_401_once(self):
        creds = mock.Mock(token=lambda: "old", renew=mock.Mock(return_value="new"), client_id="")
        answers = [(401, {}), (200, {"id": "x"})]
        with mock.patch.object(api, "request_json", lambda *a, **kw: answers.pop(0)):
            self.assertEqual(api.api_get(creds, "/drive/v3/files/x"), {"id": "x"})
        creds.renew.assert_called_once_with(None)

    def test_refusal_becomes_advice(self):
        creds = mock.Mock(token=lambda: "t", client_id="")
        with mock.patch.object(api, "request_json", lambda *a, **kw: (403, {})), \
                self.assertRaises(api.AuthError):
            api.api_get(creds, "/drive/v3/files/x")


class Hints(unittest.TestCase):
    def test_api_not_enabled_names_the_project(self):
        data = {"error": {"errors": [{"reason": "accessNotConfigured"}], "message": "off"}}
        hint = api.api_hint(403, data, mock.Mock(client_id="123456-abc.apps.googleusercontent.com"), "/p")
        self.assertIn("Google Drive API", hint)
        self.assertIn("project=123456", hint)

    def test_scope(self):
        data = {"error": {"errors": [{"reason": "insufficientPermissions"}],
                          "message": "Request had insufficient authentication scopes."}}
        self.assertIn(api.SCOPE_WRITE, api.api_hint(403, data, mock.Mock(client_id=""), "/p"))

    def test_reason(self):
        self.assertEqual(api.api_reason({"error": "invalid_grant"}), "invalid_grant")
        self.assertIsNone(api.api_reason({}))
        self.assertEqual(api.project_of("123-x.apps"), "123")
        self.assertEqual(api.project_of("abc-x"), "")

    def test_invalid_grant_says_testing(self):
        self.assertIn("Testing", auth.token_error(400, {"error": "invalid_grant"}, "s"))


class ParseCreds(unittest.TestCase):
    def test_console_json(self):
        got = auth.parse_creds('{"installed": {"client_id": "a", "client_secret": "b"}, "refresh_token": "c"}', "s")
        self.assertEqual((got["client_id"], got["client_secret"], got["refresh_token"]), ("a", "b", "c"))

    def test_lines_keep_separators_in_values(self):
        got = auth.parse_creds("# comment\nclient-id: a\nclient_secret = 'b'\nrefresh_token=1//x=y:z,\n", "s")
        self.assertEqual(got, {"client_id": "a", "client_secret": "b", "refresh_token": "1//x=y:z"})

    def test_bad_line(self):
        with self.assertRaises(auth.AuthError):
            auth.parse_creds("just a token", "s")

    def test_half_a_trio_is_an_error(self):
        with self.assertRaises(auth.AuthError) as err:
            auth.from_env({"DRIVE_CLIENT": "a", "DRIVE_SECRET": "b"})
        self.assertIn("DRIVE_REFRESH", str(err.exception))

    def test_nothing_is_none(self):
        self.assertIsNone(auth.from_env({}))

    def test_whole_trio(self):
        creds = auth.from_env({"GDRIVE_CLIENT_ID": "a", "GDRIVE_CLIENT_SECRET": "b",
                               "GDRIVE_REFRESH_TOKEN": "1//tok3n"})
        self.assertEqual((creds.client_id, creds.refresh_token), ("a", "1//tok3n"))
        self.assertNotIn("tok3n", repr(creds))


class Store(unittest.TestCase):
    def test_known_or_die(self):
        self.assertEqual(store.known_or_die("dem-sonny"), "dem-sonny")
        with self.assertRaises(SystemExit):
            store.known_or_die("dem-sony")

    def test_index_newest_wins(self):
        files = [{"id": "old", "name": "a.tif", "size": 1, "raw": {"createdTime": "2026-01-01"}},
                 {"id": "new", "name": "a.tif", "size": 2, "raw": {"createdTime": "2026-02-01"}},
                 {"id": "b", "name": "b.tif", "size": 3, "raw": {"createdTime": "2026-01-15"}}]
        with mock.patch.object(store, "store_id", lambda c, s: "fid"), \
                mock.patch.object(store.folder, "listing", lambda *a, **kw: (files, 0)):
            idx = store.index(None, "dem-sonny")
        self.assertEqual(idx["a.tif"]["id"], "new")
        self.assertEqual(idx["a.tif"]["dupes"], ["old"])
        self.assertEqual(store.latest(idx, suffix=".tif"), "a.tif")
        self.assertEqual(store.latest(idx, prefix="b"), "b.tif")
        self.assertEqual(store.latest(idx, prefix="z"), "")

    def test_missing_store_is_empty(self):
        with mock.patch.object(store, "store_id", lambda c, s: None):
            self.assertEqual(store.index(None, "dem-sonny"), {})


class Cache(unittest.TestCase):
    ITEMS = [{"full_key": "contours-trnavsky-v4-b", "created": "3"},
             {"full_key": "contours-trnavsky-v4-a", "created": "2"},
             {"full_key": "rocks-trnavsky-v2", "created": "1"}]

    def test_exact_first(self):
        self.assertEqual(cache.find(self.ITEMS, "contours-trnavsky-v4-a", ["contours-"]),
                         (self.ITEMS[1], True))

    def test_prefix_takes_the_newest(self):
        self.assertEqual(cache.find(self.ITEMS, "contours-trnavsky-v4-c", ["contours-trnavsky-v4-"]),
                         (self.ITEMS[0], False))

    def test_miss(self):
        self.assertEqual(cache.find(self.ITEMS, "terrain-x", ["terrain-"]), (None, False))

    def test_names(self):
        self.assertEqual(cache.safe("contours-trnavský/v4"), "contours-trnavsk__v4")
        self.assertEqual(cache.entry_key("k.tar.zst"), "k")
        self.assertEqual(cache.entry_key("k.tar.gz"), "k")
        self.assertIsNone(cache.entry_key("notes.txt"))
        self.assertTrue(cache.is_layer("rocks-x"))
        self.assertFalse(cache.is_layer("dem-x"))


if __name__ == "__main__":
    unittest.main()
