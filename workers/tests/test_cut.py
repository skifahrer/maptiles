import gzip
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from load import needs, worker
from test_add_layer import pmtiles


def tile(layers):
    import mapbox_vector_tile as mvt
    return mvt.encode([{"name": n, "features": [{"geometry": "POINT(1 1)", "properties": p}
                                                for p in props]}
                       for n, props in layers.items()])


def read(path):
    import mapbox_vector_tile as mvt
    from pmtiles.reader import MmapSource, Reader, all_tiles
    with open(path, "rb") as f:
        r = Reader(MmapSource(f))
        return ({zxy: mvt.decode(gzip.decompress(d)) for zxy, d in all_tiles(r.get_bytes)},
                [v["id"] for v in r.metadata()["vector_layers"]])


class Cut(unittest.TestCase):
    @needs("pmtiles", "mapbox_vector_tile")
    def test_every_feature_lands_in_one_package(self):
        cut = worker("tiles/cut.py")
        d = tempfile.mkdtemp()
        src = os.path.join(d, "r.pmtiles")
        pmtiles(src, {
            (14, 1, 1): tile({
                "landcover": [{"class": "wood"}],
                "poi": [{"class": "shop"}],
                "transportation": [{"class": "primary"}, {"class": "path", "subclass": "footway"},
                                   {"class": "pedestrian"}, {"class": "rail"},
                                   {"class": "aerialway"}, {"class": "track"}],
                "traffic_sign": [{"sign": "a", "way": "path"}, {"sign": "b", "way": "road"}],
                "place": [{"class": "village"}],
                "housenumber": [{"housenumber": "1"}],
            }),
            (15, 2, 2): tile({"water": [{"class": "lake"}], "boundary": [{"admin_level": 2}]}),
        }, ["landcover", "poi", "transportation", "traffic_sign", "place", "housenumber",
            "water", "boundary"])
        with redirect_stdout(io.StringIO()):
            written = cut.cut(src, os.path.join(d, "r"))

        def classes(package, layer, key="class"):
            got = read(written[package])[0]
            return sorted(f["properties"].get(key) for t in got.values()
                          for f in t.get(layer, {}).get("features", []))

        self.assertEqual(classes("roads", "transportation"), ["primary", "track"])
        self.assertEqual(classes("paths", "transportation"), ["path", "pedestrian"])
        self.assertEqual(classes("railways", "transportation"), ["aerialway", "rail"])
        self.assertEqual(classes("paths", "traffic_sign", "sign"), ["a"])
        self.assertEqual(classes("roads", "traffic_sign", "sign"), ["b"])
        self.assertEqual(classes("landscape", "landcover"), ["wood"])
        self.assertEqual(classes("points", "poi"), ["shop"])
        self.assertEqual(classes("settlements", "place"), ["village"])
        self.assertEqual(read(written["roads"])[1],
                         ["transportation", "traffic_sign", "housenumber"])
        self.assertEqual(sorted(read(written["water"])[0]), [(15, 2, 2)])
        # tags stay readable after the split
        paths = read(written["paths"])[0][(14, 1, 1)]["transportation"]["features"]
        self.assertIn({"class": "path", "subclass": "footway"}, [f["properties"] for f in paths])

    @needs("pmtiles", "mapbox_vector_tile")
    def test_a_layer_no_package_takes_stops_the_cut(self):
        cut = worker("tiles/cut.py")
        d = tempfile.mkdtemp()
        src = os.path.join(d, "r.pmtiles")
        pmtiles(src, {(14, 1, 1): tile({"mystery": [{"a": 1}]})}, ["mystery"])
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            cut.cut(src, os.path.join(d, "r"))


if __name__ == "__main__":
    unittest.main()
