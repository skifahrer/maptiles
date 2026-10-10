import gzip
import importlib.util
import os
import tempfile
import unittest

from load import needs, worker


@needs("shapely", "mapbox_vector_tile", "pmtiles")
class ClipTiles(unittest.TestCase):
    Z, X, Y = 10, 567, 355

    @classmethod
    def setUpClass(cls):
        cls.c = worker("lib/clip-tiles.py")

    def tile(self, features, compressed=True):
        import mapbox_vector_tile
        raw = mapbox_vector_tile.encode([{"name": "poi", "features": features}],
                                        default_options={"extents": 4096, "y_coord_down": True})
        return gzip.compress(raw) if compressed else raw

    def clip(self, features, compressed=True):
        import mapbox_vector_tile
        from shapely.geometry import box
        w, s, e, n = self.c.tile_bounds(self.Z, self.X, self.Y)
        west_half = box(w, s, (w + e) / 2, n)
        out = self.c.clip_tile(self.tile(features, compressed), west_half, self.Z, self.X, self.Y, compressed)
        if out is None:
            return None
        raw = gzip.decompress(out) if compressed else out
        return mapbox_vector_tile.decode(raw, default_options={"y_coord_down": True})

    def test_tile_bounds(self):
        w, s, e, n = self.c.tile_bounds(1, 0, 0)
        self.assertEqual((w, e), (-180, 0))
        self.assertAlmostEqual(n, 85.0511, places=3)
        self.assertAlmostEqual(s, 0, places=9)

    def test_outside_dropped_inside_kept(self):
        got = self.clip([{"geometry": "POINT(1000 2000)", "properties": {"name": "in"}},
                         {"geometry": "POINT(3000 2000)", "properties": {"name": "out"}}])
        self.assertEqual([f["properties"]["name"] for f in got["poi"]["features"]], ["in"])

    def test_nothing_left_is_none(self):
        self.assertIsNone(self.clip([{"geometry": "POINT(3000 2000)", "properties": {}}]))

    def test_line_across_the_edge_is_cut(self):
        got = self.clip([{"geometry": "LINESTRING(1000 2000, 3000 2000)", "properties": {}}], compressed=False)
        xs = [p[0] for p in got["poi"]["features"][0]["geometry"]["coordinates"]]
        self.assertEqual(min(xs), 1000)
        self.assertAlmostEqual(max(xs), 2048, delta=2)

    def test_polygon_stays_a_polygon(self):
        got = self.clip([{"geometry": "POLYGON((1000 1000, 3000 1000, 3000 3000, 1000 3000, 1000 1000))",
                          "properties": {"kind": "lake"}}])
        geom = got["poi"]["features"][0]["geometry"]
        self.assertEqual(geom["type"], "Polygon")
        self.assertAlmostEqual(max(p[0] for p in geom["coordinates"][0]), 2048, delta=2)

    def test_same_kind_drops_crumbs(self):
        from shapely.geometry import GeometryCollection, LineString, Point, Polygon
        mixed = GeometryCollection([Polygon([(0, 0), (1, 0), (1, 1)]), LineString([(5, 5), (6, 6)]), Point(9, 9)])
        self.assertEqual(self.c._same_kind(mixed, "Polygon").geom_type, "Polygon")
        self.assertEqual(self.c._same_kind(mixed, "MultiLineString").geom_type, "LineString")
        self.assertIsNone(self.c._same_kind(LineString([(0, 0), (1, 1)]), "Polygon"))


@needs("pmtiles", "mapbox_vector_tile")
class DropLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = worker("tiles/drop-layer.py")

    def encode(self, names):
        import mapbox_vector_tile
        return mapbox_vector_tile.encode(
            [{"name": n, "features": [{"geometry": f"POINT({i * 10} {i * 20})", "properties": {"n": n * 50}}]}
             for i, n in enumerate(names, start=1)])

    def test_drops_one_and_leaves_the_rest_byte_identical(self):
        import mapbox_vector_tile
        whole = self.encode(["water", "contours", "poi"])
        out = self.d.bez_vrstiev(whole, {"contours"})
        self.assertEqual(sorted(mapbox_vector_tile.decode(out)), ["poi", "water"])
        self.assertEqual(len(whole) - len(out), len(self.encode(["contours"])))
        self.assertEqual(self.d.bez_vrstiev(whole, set()), whole)

    def test_layer_name(self):
        raw = self.encode(["water"])
        _, i = self.d.varint(raw, 0)
        n, i = self.d.varint(raw, i)
        self.assertEqual(self.d.layer_name(raw[i:i + n]), "water")

    def test_varint_and_skip(self):
        self.assertEqual(self.d.varint(bytes([0xAC, 0x02]), 0), (300, 2))
        self.assertEqual(self.d.varint(bytes([0x01]), 0), (1, 1))
        self.assertEqual(self.d.skip(bytes([0xAC, 0x02, 9]), 0, 0), 2)
        self.assertEqual(self.d.skip(bytes([0x82, 0x01]) + bytes(130), 0, 2), 132)
        self.assertEqual(self.d.skip(bytes(8), 0, 1), 8)
        self.assertEqual(self.d.skip(bytes(4), 0, 5), 4)
        with self.assertRaises(ValueError):
            self.d.skip(b"", 0, 3)


@needs("pmtiles")
class TerrainPack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = worker("terrain/pack.py")

    def test_collect(self):
        from pmtiles.tile import zxy_to_tileid
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ("3/4/2.png", "3/4/3.webp", "2/1/1.png", "2/1/notes.txt", "2/1/x.png", "maxzoom.txt"):
                path = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").close()
            got = [(t[1], t[2], t[3]) for t in self.p.collect(tmp)]
            ids = [t[0] for t in self.p.collect(tmp)]
        self.assertEqual(sorted(got), [(2, 1, 1), (3, 4, 2), (3, 4, 3)])
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(ids[0], zxy_to_tileid(2, 1, 1))

    def test_tile_bounds_agree_with_clip_tiles(self):
        clip = worker("lib/clip-tiles.py") if importlib.util.find_spec("shapely") else None
        for zxy in ((0, 0, 0), (10, 567, 355), (14, 9000, 5685)):
            w, s, e, n = self.p.tile_bounds(*zxy)
            self.assertLess(w, e)
            self.assertLess(s, n)
            if clip:
                for a, b in zip((w, s, e, n), clip.tile_bounds(*zxy)):
                    self.assertAlmostEqual(a, b, places=9)


if __name__ == "__main__":
    unittest.main()
