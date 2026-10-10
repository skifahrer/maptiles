import json
import os
import tempfile
import unittest
from unittest import mock

from load import worker

folder = worker("drive/folder.py", name="drive_folder")

ERR_SCOPE = json.dumps({"error": {"errors": [{"reason": "insufficientPermissions"}]}}).encode()
ERR_FULL = json.dumps({"error": {"errors": [{"reason": "storageQuotaExceeded"}]}}).encode()


class Creds:
    def __init__(self):
        self.renewals = 0

    def token(self):
        return f"t{self.renewals}"

    def renew(self, old):
        self.renewals += 1


class Drive:
    """A resumable upload session: keeps the bytes; `faults` script what goes wrong."""

    def __init__(self, size, faults=()):
        self.size, self.got, self.faults = size, b"", list(faults)
        self.puts = []

    def __call__(self, host, method, path, body, headers, timeout=300):
        rng = headers["Content-Range"]
        self.puts.append(rng)
        if rng.startswith("bytes */"):
            if len(self.got) == self.size:
                return self.answer(201, b'{"id": "F"}')
            return self.answer(308, b"", {"Range": f"bytes=0-{len(self.got) - 1}"} if self.got else {})
        fault = self.faults.pop(0) if self.faults else None
        start = int(rng.split()[1].split("-")[0])
        if start != len(self.got):
            return self.answer(400, b"")
        if fault == "drop":
            raise OSError("connection reset")
        if fault == "drop-after-half":
            self.got += body[:len(body) // 2]
            raise OSError("connection reset")
        if fault == "drop-after-all":
            self.got += body
            raise OSError("connection reset")
        if isinstance(fault, tuple):
            return self.answer(*fault)
        self.got += body
        if len(self.got) == self.size:
            return self.answer(201, b'{"id": "F"}')
        return self.answer(308, b"", {"Range": f"bytes=0-{len(self.got) - 1}"})

    @staticmethod
    def answer(status, body, head=None):
        return status, {**(head or {}), "_body": body}, body


class Send(unittest.TestCase):
    DATA = b"0123456789abcdefghij"

    def setUp(self):
        fd, self.path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(self.DATA)
        self.addCleanup(os.remove, self.path)
        for p in (mock.patch.object(folder, "UPLOAD_CHUNK", 8),
                  mock.patch.object(folder.time, "sleep")):
            p.start()
            self.addCleanup(p.stop)

    def send(self, drive, tries=4, creds=None):
        with mock.patch.object(folder, "_request", drive), mock.patch("builtins.print"):
            return folder._send(creds or Creds(), self.path, len(self.DATA), "x",
                                ("upload.example", "/s?id=1"), tries)

    def test_blocks_arrive_in_order(self):
        drive = Drive(len(self.DATA))
        self.assertEqual(self.send(drive), "F")
        self.assertEqual(drive.got, self.DATA)
        self.assertEqual(drive.puts, ["bytes 0-7/20", "bytes 8-15/20", "bytes 16-19/20"])

    def test_a_drop_resumes_where_drive_says(self):
        drive = Drive(len(self.DATA), [None, "drop-after-half"])
        self.assertEqual(self.send(drive), "F")
        self.assertEqual(drive.got, self.DATA)
        self.assertIn("bytes */20", drive.puts)
        self.assertIn("bytes 12-19/20", drive.puts)

    def test_a_drop_after_the_last_byte_still_returns_the_id(self):
        drive = Drive(len(self.DATA), [None, None, "drop-after-all"])
        self.assertEqual(self.send(drive), "F")
        self.assertEqual(drive.puts[-1], "bytes */20")

    def test_an_expired_token_is_renewed_for_the_same_block(self):
        creds = Creds()
        drive = Drive(len(self.DATA), [None, (401, b"")])
        self.assertEqual(self.send(drive, creds=creds), "F")
        self.assertEqual(creds.renewals, 1)
        self.assertEqual(drive.puts.count("bytes 8-15/20"), 2)

    def test_server_errors_give_up_after_the_tries(self):
        drive = Drive(len(self.DATA), [(503, b"")] * 9)
        with self.assertRaisesRegex(RuntimeError, "HTTP 503.*all 3 tries"):
            self.send(drive, tries=3)

    def test_drops_give_up_after_the_tries(self):
        drive = Drive(len(self.DATA), ["drop"] * 9)
        with self.assertRaisesRegex(RuntimeError, "failed on all 2 tries"):
            self.send(drive, tries=2)

    def test_a_refused_write_says_why(self):
        with self.assertRaisesRegex(RuntimeError, folder.auth.SCOPE_WRITE):
            self.send(Drive(len(self.DATA), [(403, ERR_SCOPE)] * 9), tries=1)
        with self.assertRaisesRegex(RuntimeError, "disk is full"):
            self.send(Drive(len(self.DATA), [(403, ERR_FULL)] * 9), tries=1)


class Links(unittest.TestCase):
    def test_folder_id(self):
        fid = "1AbCdEfGhIjK_-"
        self.assertEqual(folder.folder_id(f"https://drive.google.com/drive/folders/{fid}?usp=x"), fid)
        self.assertEqual(folder.folder_id(f"https://drive.google.com/open?id={fid}"), fid)
        self.assertEqual(folder.folder_id(f" {fid} "), fid)
        for bad in ("", "short", "https://example.com/x"):
            with self.assertRaises(SystemExit):
                folder.folder_id(bad)

    def test_id_from_link_reads_what_the_links_write(self):
        self.assertEqual(folder.id_from_link(folder.file_link("F1")), "F1")
        self.assertEqual(folder.id_from_link(folder.download_link("F2")), "F2")
        self.assertEqual(folder.id_from_link("https://example.com"), "")

    def test_resume_from(self):
        self.assertEqual(folder._resume_from({"Range": "bytes=0-99"}, 7), 100)
        self.assertEqual(folder._resume_from({}, 7), 7)
        self.assertEqual(folder._resume_from({"Range": "bytes=0-x"}, 7), 7)


class Clobber(unittest.TestCase):
    def test_the_oldest_id_is_kept_and_twins_deleted(self):
        named = [{"id": "new", "createdTime": "2026-02"}, {"id": "old", "createdTime": "2026-01"}]
        updated, deleted = [], []
        with mock.patch.object(folder, "files_named", lambda c, p, n: list(named)), \
                mock.patch.object(folder, "update", lambda c, path, fid, *a: updated.append(fid)), \
                mock.patch.object(folder, "upload", mock.Mock()) as upload, \
                mock.patch.object(folder.auth, "api_delete", lambda c, fid: deleted.append(fid)), \
                mock.patch("builtins.print"):
            self.assertEqual(folder.upload_clobber(None, "p", "n", "parent"), ("old", 2))
        self.assertEqual((updated, deleted), (["old"], ["new"]))
        upload.assert_not_called()

    def test_a_new_name_is_uploaded(self):
        with mock.patch.object(folder, "files_named", lambda c, p, n: []), \
                mock.patch.object(folder, "upload", lambda *a: "fresh"):
            self.assertEqual(folder.upload_clobber(None, "p", "n", "parent"), ("fresh", 0))


if __name__ == "__main__":
    unittest.main()
