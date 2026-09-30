#!/usr/bin/env python3
"""
Reading a remote ZIP over HTTP Range – without downloading all of it.

ÚGKK's DMR 5.0 is one ~198 GB archive and a runner has ~60 GB free. A ZIP ends
in a central directory with exact offsets, so with HTTP Range one can read the
tail, then the directory, then only one member's bytes, unpacked on the fly.
ZIP64 is required: at 198 GB offsets exceed 4 GB.

    # what is in the archive (no content downloaded)
    python3 workers/drive/zip-remote.py list URL --limit=50
    python3 workers/drive/zip-remote.py list URL --json=manifest.json

    # unpack chosen members into a directory
    python3 workers/drive/zip-remote.py extract URL --out=dir --index=0-99

As a library:

    rz = RemoteZip(url)
    for e in rz.entries():
        ...
    rz.extract_span(entries, on_file=lambda name, stream: ...)
"""
import argparse
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib

# the probe's User-Agent – some CDNs refuse an empty client
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.4 Safari/605.1.15")

EOCD_SIG = b"PK\x05\x06"
EOCD64_SIG = b"PK\x06\x06"
EOCD64_LOC_SIG = b"PK\x06\x07"
CDIR_SIG = b"PK\x01\x02"
LFH_SIG = b"PK\x03\x04"

# the directory end is the last 22 bytes + comment (max 64 kB); 128 kB fits ZIP64 too
TAIL = 128 * 1024


class RemoteZipError(RuntimeError):
    pass


def _open(url, headers, timeout):
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


class RemoteZip:
    """A ZIP at the end of an HTTP link; downloads only what is asked for."""

    def __init__(self, url, timeout=60, retries=5, verbose=True):
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self.verbose = verbose
        self._entries = None
        self.size = self._probe_size()

    def _log(self, msg):
        if self.verbose:
            print(msg, flush=True)

    def _probe_size(self):
        """The file size, checking the server really does Range (a 206 for one byte)."""
        last = None
        for attempt in range(self.retries):
            try:
                with _open(self.url, {"User-Agent": UA, "Range": "bytes=0-0"},
                           self.timeout) as r:
                    code = r.getcode()
                    cr = r.headers.get("Content-Range", "")
                    r.read(1)
                if code != 206 or "/" not in cr:
                    raise RemoteZipError(
                        f"the server can't do HTTP Range (HTTP {code}, "
                        f"Content-Range: {cr or '—'}). Without it a 198 GB "
                        f"archive can't be processed.")
                total = cr.rsplit("/", 1)[1].strip()
                if not total.isdigit():
                    raise RemoteZipError(f"unreadable Content-Range: {cr}")
                return int(total)
            except RemoteZipError:
                raise
            except Exception as exc:              # network, 5xx, timeout
                last = exc
                time.sleep(min(2 ** attempt, 30))
        raise RemoteZipError(f"{self.url} doesn't answer: {last}")

    def _stream(self, start, end):
        """Open the answer to `bytes=start-end` (both inclusive)."""
        hdr = {"User-Agent": UA, "Range": f"bytes={start}-{end}"}
        last = None
        for attempt in range(self.retries):
            try:
                r = _open(self.url, hdr, self.timeout)
                if r.getcode() != 206:
                    r.close()
                    raise RemoteZipError(
                        f"a Range got HTTP {r.getcode()} – the server would "
                        f"send the whole file ({self.size} B)")
                return r
            except RemoteZipError:
                raise
            except urllib.error.HTTPError as exc:
                if exc.code in (416,):
                    raise RemoteZipError(f"invalid range {start}-{end}") from exc
                last = exc
                time.sleep(min(2 ** attempt, 30))
            except Exception as exc:
                last = exc
                time.sleep(min(2 ** attempt, 30))
        raise RemoteZipError(f"range {start}-{end} couldn't be opened: {last}")

    def get(self, start, length):
        """Read exactly `length` bytes from `start` into memory."""
        end = min(start + length, self.size) - 1
        buf = bytearray()
        want = end - start + 1
        while len(buf) < want:
            r = self._stream(start + len(buf), end)
            try:
                while len(buf) < want:
                    part = r.read(min(1 << 20, want - len(buf)))
                    if not part:
                        break
                    buf += part
            finally:
                r.close()
            if len(buf) < want:
                # the transfer broke – resume where it ended
                self._log(f"  … the transfer broke at {len(buf)}/{want} B, "
                          f"resuming")
        return bytes(buf)

    def reader(self, start, end):
        """A byte stream `start..end` (inclusive) that resumes itself."""
        return _ResumableReader(self, start, end)

    def _find_directory(self):
        tail_len = min(TAIL, self.size)
        tail = self.get(self.size - tail_len, tail_len)
        pos = tail.rfind(EOCD_SIG)
        if pos < 0:
            raise RemoteZipError(
                "the file doesn't end in a central directory end (PK\\x05\\x06) – "
                "either it isn't a ZIP, or the server sent an error page.")
        cd_count, cd_size, cd_off = struct.unpack_from("<2xHII", tail, pos + 8)
        base = self.size - tail_len

        # ZIP64: 0xFFFF/0xFFFFFFFF means "the real number is elsewhere", always at 198 GB
        loc = tail.rfind(EOCD64_LOC_SIG, 0, pos)
        if loc >= 0 and (cd_count == 0xFFFF or cd_size == 0xFFFFFFFF
                         or cd_off == 0xFFFFFFFF):
            (eocd64_off,) = struct.unpack_from("<Q", tail, loc + 8)
            if base <= eocd64_off < self.size:
                rec = tail[eocd64_off - base:]
            else:
                rec = self.get(eocd64_off, 56)
            if rec[:4] != EOCD64_SIG:
                raise RemoteZipError(
                    f"the ZIP64 record at offset {eocd64_off} doesn't start with PK\\x06\\x06")
            cd_count, cd_size, cd_off = struct.unpack_from("<QQQ", rec, 32)
        return cd_off, cd_size, cd_count

    def entries(self):
        """The archive's members (read once, then from memory)."""
        if self._entries is not None:
            return self._entries
        cd_off, cd_size, cd_count = self._find_directory()
        self._log(f"Central directory: {cd_count} members, "
                  f"{cd_size / 1048576:.1f} MB at offset {cd_off}")
        blob = self.get(cd_off, cd_size)
        out, p = [], 0
        while p + 46 <= len(blob) and blob[p:p + 4] == CDIR_SIG:
            (flags, method, _t, _d, crc, csize, usize, nlen, elen, clen,
             _disk, _ia, _ea, hoff) = struct.unpack_from("<8xHHHHIIIHHHHHII", blob, p)
            name = blob[p + 46:p + 46 + nlen].decode("utf-8", "replace")
            extra = blob[p + 46 + nlen:p + 46 + nlen + elen]
            csize, usize, hoff = _zip64_fix(extra, csize, usize, hoff)
            out.append({
                "i": len(out), "name": name, "method": method, "flags": flags,
                "crc": crc, "csize": csize, "usize": usize, "offset": hoff,
                "nlen": nlen,
            })
            p += 46 + nlen + elen + clen
        if len(out) != cd_count:
            self._log(f"::warning::the directory has {len(out)} members, the "
                      f"header says {cd_count}")
        self._entries = out
        return out

    def head(self, entry, want=65536):
        """The start of one member – only as many compressed bytes as needed."""
        take = min(entry["csize"], max(want, 1 << 16))
        raw = self.get(entry["offset"], 30 + entry["nlen"] + 4096 + take)
        if raw[:4] != LFH_SIG:
            raise RemoteZipError(f"{entry['name']}: the local header is missing")
        nlen, elen = struct.unpack_from("<HH", raw, 26)
        data = raw[30 + nlen + elen:30 + nlen + elen + take]
        if entry["method"] == 0:
            return data[:want]
        dec = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            return dec.decompress(data, want)
        except zlib.error as exc:
            raise RemoteZipError(f"{entry['name']}: can't be unpacked ({exc})")

    def extract_span(self, entries, on_file, hard_limit=None):
        """Unpack members in ONE transfer (one request instead of one a file)."""
        # `on_file(entry, stream)` gets the unpacked stream; unread rest is skipped
        if not entries:
            return 0
        ents = sorted(entries, key=lambda e: e["offset"])
        start = ents[0]["offset"]
        # the end: the last member's data + room for its header and a data descriptor
        last = ents[-1]
        end = min(last["offset"] + 30 + last["nlen"] + 4096 + last["csize"] + 24,
                  self.size) - 1
        span = end - start + 1
        if hard_limit and span > hard_limit:
            raise RemoteZipError(
                f"the span has {span / 1048576:.0f} MB, the cap is "
                f"{hard_limit / 1048576:.0f} MB")
        self._log(f"Span {start}–{end} ({span / 1048576:.1f} MB), "
                  f"{len(ents)} members")

        rd = self.reader(start, end)
        done = 0
        for e in ents:
            rd.skip_to(e["offset"])
            head = rd.read_exact(30)
            if head[:4] != LFH_SIG:
                raise RemoteZipError(
                    f"no local header at offset {e['offset']} "
                    f"({e['name']}) – did the archive change meanwhile?")
            nlen, elen = struct.unpack_from("<HH", head, 26)
            rd.read_exact(nlen + elen)
            on_file(e, _EntryStream(rd, e))
            rd.drain_entry(e)
            done += 1
        rd.close()
        return done


def _zip64_fix(extra, csize, usize, hoff):
    """Fill the real sizes/offset from the ZIP64 extra field (ID 0x0001)."""
    p = 0
    while p + 4 <= len(extra):
        tag, ln = struct.unpack_from("<HH", extra, p)
        body = extra[p + 4:p + 4 + ln]
        if tag == 0x0001:
            q = 0
            # a fixed order: ONLY the fields that overflowed outside are there
            if usize == 0xFFFFFFFF and q + 8 <= len(body):
                usize = struct.unpack_from("<Q", body, q)[0]; q += 8
            if csize == 0xFFFFFFFF and q + 8 <= len(body):
                csize = struct.unpack_from("<Q", body, q)[0]; q += 8
            if hoff == 0xFFFFFFFF and q + 8 <= len(body):
                hoff = struct.unpack_from("<Q", body, q)[0]; q += 8
        p += 4 + ln
    return csize, usize, hoff


class _ResumableReader:
    """Sequential reading of a range surviving a broken transfer (it remembers its position)."""

    def __init__(self, rz, start, end):
        self.rz = rz
        self.pos = start
        self.end = end
        self.r = None
        self.fails = 0

    def _ensure(self):
        if self.r is None:
            self.r = self.rz._stream(self.pos, self.end)

    def read(self, n):
        if self.pos > self.end or n <= 0:
            return b""
        n = min(n, self.end - self.pos + 1)
        while True:
            try:
                self._ensure()
                part = self.r.read(n)
                if not part:
                    # an early end – try again from the current position
                    raise IOError("the stream ended too early")
                self.pos += len(part)
                self.fails = 0
                return part
            except Exception as exc:
                self._reset()
                self.fails += 1
                if self.fails > self.rz.retries:
                    raise RemoteZipError(
                        f"reading from {self.pos} failed {self.fails}×: {exc}")
                time.sleep(min(2 ** self.fails, 30))

    def read_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            part = self.read(n - len(buf))
            if not part:
                raise RemoteZipError(f"{n - len(buf)} B missing at the span's end")
            buf += part
        return bytes(buf)

    def skip(self, n):
        while n > 0:
            part = self.read(min(n, 1 << 20))
            if not part:
                return
            n -= len(part)

    def skip_to(self, abs_pos):
        if abs_pos < self.pos:
            raise RemoteZipError(
                f"can't go back ({self.pos} → {abs_pos}); members must "
                f"go by offset")
        self.skip(abs_pos - self.pos)

    def drain_entry(self, e):
        """Read the rest of a member's data so the stream sits on the next header."""
        left = e.get("_left", 0)
        if left:
            self.skip(left)
            e["_left"] = 0

    def _reset(self):
        if self.r is not None:
            try:
                self.r.close()
            except Exception:
                pass
            self.r = None

    def close(self):
        self._reset()


class _EntryStream:
    """One member's unpacked content as a file stream (`read` only)."""

    def __init__(self, rd, entry):
        self.rd = rd
        self.e = entry
        entry["_left"] = entry["csize"]
        if entry["method"] == 0:
            self.dec = None
        elif entry["method"] == 8:
            self.dec = zlib.decompressobj(-zlib.MAX_WBITS)
        else:
            raise RemoteZipError(
                f"{entry['name']}: compression {entry['method']} isn't supported "
                f"(we know 0 = stored and 8 = deflate)")
        self.buf = bytearray()
        self.eof = False

    def _fill(self):
        """Fill the output buffer by at least one network read."""
        while not self.buf and not self.eof:
            if self.e["_left"] <= 0:
                if self.dec is not None:
                    self.buf += self.dec.flush()
                self.eof = True
                break
            raw = self.rd.read(min(1 << 20, self.e["_left"]))
            if not raw:
                self.eof = True
                break
            self.e["_left"] -= len(raw)
            self.buf += raw if self.dec is None else self.dec.decompress(raw)

    def read(self, n=-1):
        if n is None or n < 0:
            out = bytearray()
            while True:
                self._fill()
                if not self.buf:
                    return bytes(out)
                out += self.buf
                del self.buf[:]
        self._fill()
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def __iter__(self):
        """Lines – handy for text elevation points."""
        rest = b""
        while True:
            chunk = self.read(1 << 20)
            if not chunk:
                if rest:
                    yield rest
                return
            rest += chunk
            lines = rest.split(b"\n")
            rest = lines.pop()
            for ln in lines:
                yield ln


def _parse_index(spec, n):
    """\"0-99,150,200-\" → a list of indices."""
    if not spec:
        return list(range(n))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            out.extend(range(int(a or 0), (int(b) if b else n - 1) + 1))
        else:
            out.append(int(part))
    return [i for i in out if 0 <= i < n]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("cmd", choices=["list", "extract"])
    ap.add_argument("url")
    ap.add_argument("--limit", type=int, default=40, help="how many to print")
    ap.add_argument("--json", default="", help="where to save the manifest")
    ap.add_argument("--index", default="", help="which members (0-9,20)")
    ap.add_argument("--out", default="out", help="where to unpack")
    ap.add_argument("--timeout", type=float, default=60)
    args = ap.parse_args(argv)

    rz = RemoteZip(args.url, timeout=args.timeout)
    print(f"Archive size: {rz.size / 1e9:.1f} GB ({rz.size} B)")
    ents = rz.entries()
    total_c = sum(e["csize"] for e in ents)
    total_u = sum(e["usize"] for e in ents)
    print(f"Members: {len(ents)}, compressed {total_c / 1e9:.1f} GB, "
          f"unpacked {total_u / 1e9:.1f} GB")

    if args.cmd == "list":
        for e in ents[:args.limit]:
            print(f"  [{e['i']:6d}] {e['name']}  "
                  f"{e['csize'] / 1048576:.2f} → {e['usize'] / 1048576:.2f} MB")
        if len(ents) > args.limit:
            print(f"  … and {len(ents) - args.limit} more")
        if args.json:
            with open(args.json, "w") as f:
                json.dump({"url": args.url, "size": rz.size, "entries": ents},
                          f, ensure_ascii=False)
            print(f"Manifest: {args.json}")
        return 0

    pick = [ents[i] for i in _parse_index(args.index, len(ents))]
    os.makedirs(args.out, exist_ok=True)

    def write(e, stream):
        dest = os.path.join(args.out, os.path.basename(e["name"]) or f"e{e['i']}")
        with open(dest, "wb") as f:
            while True:
                b = stream.read(1 << 20)
                if not b:
                    break
                f.write(b)
        print(f"  ✓ {e['name']} → {dest}")

    n = rz.extract_span(pick, write)
    print(f"Members unpacked: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
