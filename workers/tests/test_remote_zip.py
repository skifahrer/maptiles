import io
import os
import random
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from load import worker
import rangeserver

rz_mod = worker("drive/zip-remote.py")


def archive(zip64=False):
    rnd = random.Random(7)
    members = {"a/readme.txt": b"hello " * 1000,
               "a/N49E019.tif": bytes(rnd.getrandbits(8) for _ in range(300_000)),
               "b/empty.txt": b"",
               "b/stored.bin": bytes(range(256)) * 50}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED if name.endswith(".bin") else zipfile.ZIP_DEFLATED
            with z.open(info, "w", force_zip64=zip64) as f:
                f.write(data)
        z.comment = b"x" * 1000
    return members, buf.getvalue()


class RemoteZip(unittest.TestCase):
    def setUp(self):
        self.members, blob = archive()
        _, blob64 = archive(zip64=True)
        self.server, base = rangeserver.serve({"/dmr5.zip": blob, "/dmr5-64.zip": blob64})
        self.url, self.url64 = base + "/dmr5.zip", base + "/dmr5-64.zip"
        self.size = len(blob)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        p = mock.patch.object(rz_mod.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def open(self, url):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return rz_mod.RemoteZip(url, verbose=False)

    def extract(self, rz, entries):
        got = {}

        def on_file(e, stream):
            got[e["name"]] = stream.read()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rz.extract_span(entries, on_file)
        return got

    def test_directory_without_the_body(self):
        rz = self.open(self.url)
        names = [e["name"] for e in rz.entries()]
        self.assertEqual(names, list(self.members))
        read = sum(int(r.split("-")[1]) - int(r[6:].split("-")[0]) + 1
                   for _, r in rangeserver.Handler.requests if r and r.split("-")[1])
        self.assertLess(read, self.size // 2, "only the tail and the directory were read")

    def test_every_member_unpacked(self):
        for url in (self.url, self.url64):
            with self.subTest(url=url):
                rz = self.open(url)
                self.assertEqual(self.extract(rz, rz.entries()), self.members)

    def test_a_span_reads_only_its_members(self):
        rz = self.open(self.url)
        pick = [e for e in rz.entries() if e["name"].startswith("b/")]
        self.assertEqual(self.extract(rz, pick), {k: v for k, v in self.members.items() if k.startswith("b/")})

    def test_cut_connection_resumes(self):
        rz = self.open(self.url)
        rangeserver.Handler.cut_after["/dmr5.zip"] = 50_000
        self.assertEqual(self.extract(rz, rz.entries())["a/N49E019.tif"], self.members["a/N49E019.tif"])

    def test_no_range_is_refused(self):
        rangeserver.Handler.ranges_off = True
        with self.assertRaises(rz_mod.RemoteZipError):
            self.open(self.url)

    def test_parse_index(self):
        self.assertEqual(rz_mod._parse_index("0-2,5,8-", 10), [0, 1, 2, 5, 8, 9])
        self.assertEqual(rz_mod._parse_index("", 3), [0, 1, 2])
        self.assertEqual(rz_mod._parse_index("2,40", 5), [2])


if __name__ == "__main__":
    unittest.main()
