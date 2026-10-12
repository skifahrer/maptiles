import gzip
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from load import needs, worker


def pmtiles(path, tiles, layers):
    from pmtiles.tile import Compression, TileType, zxy_to_tileid
    from pmtiles.writer import Writer

    with open(path, "wb") as f:
        w = Writer(f)
        for (z, x, y), raw in sorted(tiles.items(), key=lambda t: zxy_to_tileid(*t[0])):
            w.write_tile(zxy_to_tileid(z, x, y), gzip.compress(raw, mtime=0))
        zs = [z for z, _, _ in tiles]
        w.finalize({"tile_type": TileType.MVT, "tile_compression": Compression.GZIP,
                    "min_zoom": min(zs), "max_zoom": max(zs), "center_zoom": min(zs),
                    "min_lon_e7": 0, "min_lat_e7": 0, "max_lon_e7": 10, "max_lat_e7": 10,
                    "center_lon_e7": 5, "center_lat_e7": 5},
                   {"vector_layers": [{"id": n, "fields": {}} for n in layers]})


def tile(**layers):
    import mapbox_vector_tile as mvt
    return mvt.encode([{"name": n, "features": [{"geometry": "POINT(1 1)", "properties": p}]}
                       for n, p in layers.items()])


class AddLayer(unittest.TestCase):
    @needs("pmtiles", "mapbox_vector_tile")
    def test_signs_join_the_base_tiles(self):
        import mapbox_vector_tile as mvt
        from pmtiles.reader import MmapSource, Reader

        add = worker("tiles/add-layer.py")
        d = tempfile.mkdtemp()
        base, signs = os.path.join(d, "r.pmtiles"), os.path.join(d, "s.pmtiles")
        pmtiles(base, {(14, 1, 1): tile(transportation={"class": "minor"}),
                       (15, 2, 2): tile(transportation={"class": "minor"})}, ["transportation"])
        pmtiles(signs, {(14, 1, 1): tile(traffic_sign={"sign": "sk.ts.stop"}, other={"a": 1}),
                        (15, 3, 3): tile(traffic_sign={"sign": "sk.ts.201"})}, ["traffic_sign", "other"])
        for _ in range(2):  # a second run replaces, doesn't double
            argv = ["add-layer.py", f"--into={base}", f"--from={signs}", "--layer=traffic_sign"]
            with mock.patch("sys.argv", argv), redirect_stdout(io.StringIO()):
                self.assertEqual(add.main(), 0)
        with open(base, "rb") as f:
            r = Reader(MmapSource(f))
            got = {zxy: mvt.decode(gzip.decompress(r.get(*zxy)))
                   for zxy in [(14, 1, 1), (15, 2, 2), (15, 3, 3)]}
            meta = r.metadata()
        self.assertEqual(sorted(got[(14, 1, 1)]), ["traffic_sign", "transportation"])
        self.assertEqual(len(got[(14, 1, 1)]["traffic_sign"]["features"]), 1)
        self.assertEqual(sorted(got[(15, 2, 2)]), ["transportation"])
        self.assertEqual(got[(15, 3, 3)]["traffic_sign"]["features"][0]["properties"],
                         {"sign": "sk.ts.201"})
        self.assertEqual([v["id"] for v in meta["vector_layers"]], ["transportation", "traffic_sign"])


class SameLayer(unittest.TestCase):
    def test_the_base_map_and_the_roads_carry_one_sign_layer(self):
        def layer(path):
            with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   path), encoding="utf-8") as f:
                s = f.read()
            start = s.index("  - id: traffic_sign")
            return s[start:s.index("\n\n", start)]
        self.assertEqual(layer("tiles/signs.yml"), layer("transport/transport.yml"))


if __name__ == "__main__":
    unittest.main()
