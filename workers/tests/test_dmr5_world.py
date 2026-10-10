import io
import json
import math
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from load import WORKERS, needs, worker

dmr5 = worker("drive/dmr5.py")
cut = dmr5.cut
raster = dmr5.raster
smooth = worker("contours-rocks/smooth-shapes.py")
glyphs = worker("world/glyphs.py")


class Blocks(unittest.TestCase):
    def test_snapped_cover_without_overlap(self):
        box = (100003.7, 50001.2, 140010.0, 61005.5)
        parts, (nx, ny) = cut.blocks(box, 5.0, jobs=4)
        self.assertEqual(len(parts), nx * ny)
        self.assertGreaterEqual(len(parts), 4)
        for bw, bs, be, bn in parts:
            for v in (bw, bs, be, bn):
                self.assertEqual(v % 5.0, 0)
            self.assertLessEqual((be - bw) / 5.0, 4096)
        area = sum((be - bw) * (bn - bs) for bw, bs, be, bn in parts)
        w, s = math.floor(box[0] / 5) * 5, math.floor(box[1] / 5) * 5
        e, n = math.ceil(box[2] / 5) * 5, math.ceil(box[3] / 5) * 5
        self.assertEqual(area, (e - w) * (n - s))

    def test_small_window_isnt_split_for_jobs(self):
        parts, _ = cut.blocks((0, 0, 1000, 1000), 5.0, jobs=8)
        self.assertEqual(len(parts), 1, "under 512 px a block isn't worth splitting")


class Pyramid(unittest.TestCase):
    INFO = {"size": [40000, 40000], "bands": [{"overviews": [
        {"size": [20000, 20000]}, {"size": [10000, 10000]}, {"size": [5000, 5000]}, {}]}]}

    def test_coarsest_overview_still_finer(self):
        self.assertEqual(cut.pyramid_level(self.INFO, 1.0, 5.0), (1, 4.0))
        self.assertEqual(cut.pyramid_level(self.INFO, 1.0, 8.0), (2, 8.0))
        self.assertEqual(cut.pyramid_level(self.INFO, 1.0, 1.0), (None, 1.0))

    def test_read_args(self):
        args, why = cut.read_args(5.0, 5.0, 3)
        self.assertEqual(args, ["-ovr", "3"])
        self.assertIn("without resampling", why)
        args, _ = cut.read_args(5.0, 4.0, 1)
        self.assertEqual(args[args.index("-r") + 1], "cubicspline", "1.25× is no case for a mean")
        args, _ = cut.read_args(5.0, 1.0, None)
        self.assertEqual((args[:2], args[args.index("-r") + 1]), (["-ovr", "NONE"], "average"))


class Raster(unittest.TestCase):
    INFO = {"geoTransform": [1000, 1, 0, 2000, 0, -1], "size": [500, 400]}

    def test_clamp(self):
        log = []
        self.assertEqual(raster.clamp_to_raster((1100, 1700, 1200, 1800), self.INFO, 4, log.append),
                         (1096, 1696, 1204, 1804))
        self.assertEqual(raster.clamp_to_raster((900, 1500, 2000, 2500), self.INFO, 4, log.append),
                         (1000, 1600, 1500, 2000))
        self.assertTrue(log)
        with self.assertRaises(SystemExit):
            raster.clamp_to_raster((5000, 5000, 6000, 6000), self.INFO, 4, log.append)

    def test_resolve_area(self):
        areas = os.path.join(WORKERS, "data", "areas.json")
        self.assertEqual(raster.resolve_area("cele_slovensko", areas), ("whole country", None))
        self.assertEqual(raster.resolve_area("20,49,20.5,49.5", areas)[1], (20, 49, 20.5, 49.5))
        with open(areas) as f:
            key = next(k for k in json.load(f) if not k.startswith("_"))
        name, bbox = raster.resolve_area(key, areas)
        self.assertEqual(len(bbox), 4)
        for bad in ("1,2,3", "neznama_oblast"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                raster.resolve_area(bad, areas)

    def test_degrees_per_metre(self):
        dx, dy = raster.degrees_per_metre(60)
        self.assertAlmostEqual(dx, 2 / 111320)
        self.assertAlmostEqual(dy, 1 / 110540)


class State(unittest.TestCase):
    def test_round_trip_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                dmr5.load_state(tmp)
            dmr5.log("planned")
            dmr5.save_state(tmp, {"stage": "plan"})
            got = dmr5.load_state(tmp)
        self.assertEqual(got["stage"], "plan")
        self.assertIn("planned", got["log"])


@needs("yaml")
class Variant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = worker("world/variant.py")

    def test_pick(self):
        self.assertEqual(self.v.pick("plna"), self.v.pick("full"))
        with self.assertRaises(SystemExit):
            self.v.pick("tiny")

    def test_schema_keeps_only_used_sources(self):
        doc = {"sources": {"a": {}, "b": {}}, "layers": [
            {"id": "x", "features": [{"source": "a"}]}, {"id": "y", "features": [{"source": "b"}]}]}
        out, sources = self.v.schema_for(["x"], doc)
        self.assertEqual(([l["id"] for l in out["layers"]], list(out["sources"]), sources), (["x"], ["a"], ["a"]))
        with self.assertRaises(SystemExit):
            self.v.schema_for(["z"], doc)

    def test_real_variants_fit_the_schema(self):
        for name, spec in self.v.variants().items():
            with self.subTest(variant=name):
                out, _ = self.v.schema_for(spec["layers"])
                self.assertEqual(sorted(l["id"] for l in out["layers"]), sorted(spec["layers"]))
                self.assertTrue(self.v.map_layers(spec["layers"]))

    def test_map_layers_order_and_once(self):
        raw = {"_names": {"water": ["water"], "lakes": ["water", "lakes"], "places": ["names"]}}
        self.assertEqual(self.v.map_layers(["lakes", "water"], raw), ["water", "lakes"])


class Glyphs(unittest.TestCase):
    def test_ranges_from_names_only(self):
        with tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False, encoding="utf-8") as f:
            json.dump({"features": [{"properties": {"name": "Žilina", "name:ru": "Жилина",
                                                    "name:zh": "日本", "kind": "Ωmega", "rank": 3}}]}, f)
        self.addCleanup(os.remove, f.name)
        self.assertEqual(glyphs.ranges_in_geojson(f.name), {0, 1, 4})


class Smooth(unittest.TestCase):
    def test_line_ends_stay(self):
        line = [(0, 0), (10, 0), (10, 10), (20, 10)]
        out = smooth.curve_line(line, 0.1)
        self.assertEqual((out[0], out[-1]), ((0, 0), (20, 10)))
        self.assertGreater(len(out), len(line))
        self.assertEqual(smooth.curve_line([(0, 0), (1, 1)], 0.1), [(0, 0), (1, 1)])

    def test_ring_closed_and_inside_the_corners(self):
        ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        out = smooth.curve_ring(ring, 0.05)
        self.assertEqual(out[0], out[-1])
        self.assertNotIn((10, 10), out)
        self.assertTrue(all(0 <= x <= 10 and 0 <= y <= 10 for x, y in out))

    def test_finer_tolerance_more_points(self):
        ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        self.assertGreater(len(smooth.curve_ring(ring, 0.001)), len(smooth.curve_ring(ring, 1)))

    def test_geometry_and_count(self):
        geom = {"type": "MultiPolygon", "coordinates": [[[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]]}
        out = smooth.smooth_geometry(geom, 0.1)
        self.assertEqual(out["type"], "MultiPolygon")
        self.assertGreater(smooth.count_points(out), 5)
        self.assertEqual(smooth.smooth_geometry({"type": "Point", "coordinates": [1, 2]}, 1)["coordinates"], [1, 2])

    def test_tolerance_units(self):
        deg, _ = smooth.tolerance("EPSG:4326", False, 14, 2)
        metres, _ = smooth.tolerance("EPSG:3035", True, 14, 2)
        self.assertAlmostEqual(deg * smooth.cell.M_PER_DEG_LAT, metres)
        merc, _ = smooth.tolerance("EPSG:3857", True, 14, 2)
        self.assertGreater(merc, metres)


if __name__ == "__main__":
    unittest.main()
