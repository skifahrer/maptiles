#!/usr/bin/env python3
"""Copy MVT layers from one `.pmtiles` into another's tiles of the same zoom and place."""
import argparse
import gzip
import importlib.util
import os
import sys

from pmtiles.reader import MmapSource, Reader, all_tiles
from pmtiles.tile import Compression, zxy_to_tileid
from pmtiles.writer import Writer

_spec = importlib.util.spec_from_file_location(
    "drop_layer", os.path.join(os.path.dirname(os.path.abspath(__file__)), "drop-layer.py"))
drop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drop)


def layers_of(raw, names):
    """The bytes of layers `names` in a tile, each a whole field."""
    out = bytearray()
    i = 0
    while i < len(raw):
        start = i
        key, i = drop.varint(raw, i)
        end = drop.skip(raw, i, key & 7)
        if key == (3 << 3 | 2):
            n, j = drop.varint(raw, i)
            if drop.layer_name(raw[j:j + n]) in names:
                out += raw[start:end]
        i = end
    return bytes(out)


def read(path):
    """`(header, metadata, {(z, x, y): raw tile})`."""
    with open(path, "rb") as f:
        r = Reader(MmapSource(f))
        header, metadata = r.header(), r.metadata()
        gz = header["tile_compression"] == Compression.GZIP
        tiles = {zxy: gzip.decompress(d) if gz else d for zxy, d in all_tiles(r.get_bytes)}
    return header, metadata, tiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--into", required=True, help="the `.pmtiles` that gains the layers")
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--layer", action="append", required=True)
    a = ap.parse_args()
    names = set(a.layer)

    header, metadata, tiles = read(a.into)
    _, src_meta, src_tiles = read(a.src)
    added = 0
    for zxy, raw in src_tiles.items():
        extra = layers_of(raw, names)
        if extra:
            # a layer of the same name from an earlier run goes first
            tiles[zxy] = drop.bez_vrstiev(tiles.get(zxy, b""), names) + extra
            added += 1
    gz = header["tile_compression"] == Compression.GZIP
    layers = [v for v in metadata.get("vector_layers") or [] if v.get("id") not in names]
    layers += [v for v in src_meta.get("vector_layers") or [] if v.get("id") in names]
    if "vector_layers" in metadata:
        metadata["vector_layers"] = layers

    tmp = a.into + ".tmp"
    with open(tmp, "wb") as f:
        w = Writer(f)
        for (z, x, y), raw in sorted(tiles.items(), key=lambda t: zxy_to_tileid(*t[0])):
            # mtime=0, or equal tiles hash apart and lose deduplication
            w.write_tile(zxy_to_tileid(z, x, y), gzip.compress(raw, 9, mtime=0) if gz else raw)
        w.finalize(header, metadata)
    os.replace(tmp, a.into)
    print(f"{a.into}: {', '.join(sorted(names))} in {added} tiles from {a.src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
