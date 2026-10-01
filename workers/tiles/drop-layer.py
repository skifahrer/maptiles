#!/usr/bin/env python3
"""Drop MVT layers from tiles below a zoom and rewrite the `.pmtiles`."""
import argparse
import gzip
import os
import sys

from pmtiles.reader import MmapSource, Reader, all_tiles
from pmtiles.tile import Compression, zxy_to_tileid
from pmtiles.writer import Writer


def varint(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def skip(b, i, wire):
    if wire == 0:
        return varint(b, i)[1]
    if wire == 1:
        return i + 8
    if wire == 2:
        n, i = varint(b, i)
        return i + n
    if wire == 5:
        return i + 4
    raise ValueError(f"wire type {wire}")


def layer_name(body):
    i = 0
    while i < len(body):
        key, i = varint(body, i)
        if key == (1 << 3 | 2):
            n, i = varint(body, i)
            return body[i:i + n].decode()
        i = skip(body, i, key & 7)
    return None


def bez_vrstiev(raw, names):
    """The same tile without layers `names`; other bytes stay untouched."""
    out = bytearray()
    i = 0
    while i < len(raw):
        start = i
        key, i = varint(raw, i)
        end = skip(raw, i, key & 7)
        if key == (3 << 3 | 2):
            n, j = varint(raw, i)
            if layer_name(raw[j:j + n]) in names:
                i = end
                continue
        out += raw[start:end]
        i = end
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--layer", action="append", required=True)
    ap.add_argument("--below", type=int, required=True,
                    help="the layer stays from this zoom up")
    args = ap.parse_args()
    names = set(args.layer)
    before = os.path.getsize(args.src)

    with open(args.src, "rb") as f:
        r = Reader(MmapSource(f))
        header = r.header()
        metadata = r.metadata()
        gz = header["tile_compression"] == Compression.GZIP
        tiles = []
        for (z, x, y), data in all_tiles(r.get_bytes):
            if z < args.below:
                raw = gzip.decompress(data) if gz else data
                new = bez_vrstiev(raw, names)
                if len(new) != len(raw):
                    # mtime=0, or equal tiles hash apart and lose deduplication
                    data = gzip.compress(new, 9, mtime=0) if gz else new
            tiles.append((zxy_to_tileid(z, x, y), data))
    tiles.sort(key=lambda t: t[0])
    layers = []
    for layer in metadata.get("vector_layers") or []:
        if layer.get("id") in names:
            if args.below > header["max_zoom"]:
                continue
            layer["minzoom"] = max(layer.get("minzoom", 0), args.below)
        layers.append(layer)
    if "vector_layers" in metadata:
        metadata["vector_layers"] = layers

    tmp = args.dst + ".tmp"
    with open(tmp, "wb") as f:
        w = Writer(f)
        for tid, data in tiles:
            w.write_tile(tid, data)
        w.finalize(header, metadata)
    os.replace(tmp, args.dst)
    after = os.path.getsize(args.dst)
    print(f"{args.dst}: no {', '.join(sorted(names))} below z{args.below}, "
          f"{after / 1048576:.1f} MB (was {before / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
