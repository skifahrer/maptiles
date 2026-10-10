import json
import os
import tempfile
import unittest

from load import needs_cmd, worker

tiles = worker("dem/tiles.py")
target = worker("dem/target.py")
coverage = worker("dem/coverage.py")
trust = worker("dem/trust.py")

SOURCES = {"sonny": {"label": "Sonny", "store": "dem-sonny"},
           "dmr5": {"label": "DMR 5.0", "store": "dem-dmr5-v2", "store_area": "dem-ugkk"}}


class Names(unittest.TestCase):
    def test_tile_name_hemispheres(self):
        self.assertEqual(tiles.tile_name(19, 49), "N49E019")
        self.assertEqual(tiles.tile_name(-74, -3), "S03W074")
        self.assertEqual(tiles.tile_name(0, 0), "N00E000")

    def test_degree_of_inverts_tile_name(self):
        for lon, lat in ((19, 49), (-74, -3), (0, 0), (-1, 51)):
            self.assertEqual(coverage.degree_of(tiles.tile_name(lon, lat) + ".tif"), (lon, lat))
        self.assertIsNone(coverage.degree_of("region.tif"))
        self.assertIsNone(coverage.degree_of("NxxE019.tif"))

    def test_tiles_for(self):
        self.assertEqual(target.tiles_for((19.9, 48.5, 21.1, 49.2)),
                         ["N48E019", "N48E020", "N48E021", "N49E019", "N49E020", "N49E021"])

    def test_degrees_box(self):
        self.assertEqual(target.degrees_box((19.9, 48.5, 21.1, 49.2)), (19, 48, 22, 50))

    def test_parse_bbox(self):
        self.assertEqual(target.parse_bbox("1,2,3,4"), (1.0, 2.0, 3.0, 4.0))
        self.assertIsNone(target.parse_bbox(" "))
        with self.assertRaises(SystemExit):
            target.parse_bbox("1,2,3")


class PlanTiles(unittest.TestCase):
    D = 1 / 3600

    def test_covers_bounds_once(self):
        write, partial = tiles.plan_tiles((18.0, 48.0, 21.0, 50.0), None, self.D, self.D)
        names = [w[2] for w in write]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 6)
        self.assertEqual(partial, [])

    def test_thin_overhang_is_not_a_tile(self):
        write, _ = tiles.plan_tiles((18.0, 48.0, 19.0 + self.D / 2, 49.0), None, self.D, self.D)
        self.assertEqual([w[2] for w in write], ["N48E018"])

    def test_window(self):
        # raster reaches 18.5..20, window 19..21: N48E018 overhangs, N48E020 is empty
        write, partial = tiles.plan_tiles((18.5, 48.0, 20.0, 49.0), (19, 48, 21, 49), self.D, self.D)
        self.assertEqual(partial, ["N48E018"])
        self.assertEqual([(w[2], w[3]) for w in write], [("N48E019", True), ("N48E020", False)])


class Target(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(SOURCES, self.tmp)
        self.tmp.close()
        self.env = {k: os.environ.pop(k) for k in ("DEM_STORE", "DMR5_STORE", "UGKK_STORE")
                    if k in os.environ}

    def tearDown(self):
        os.remove(self.tmp.name)
        os.environ.update(self.env)

    def test_area_form(self):
        r = target.target("dmr5", "vysoke_tatry", None, self.tmp.name)
        self.assertEqual((r["form"], r["store"], r["assets"]),
                         ("area", "dem-ugkk", "ugkk-vysoke_tatry.tif"))

    def test_cutout_spelled_as_stored(self):
        self.assertEqual(target.target("dmr5", "cutout_x", None, self.tmp.name)["assets"],
                         "ugkk-vyrez_x.tif")

    def test_whole_is_tiles(self):
        for key in ("whole", "cely", ""):
            r = target.target("dmr5", key, (19.5, 49.1, 20.5, 49.4), self.tmp.name)
            self.assertEqual((r["form"], r["store"], r["degrees"]), ("tiles", "dem-dmr5-v2", "19,49,21,50"))
            self.assertEqual(r["assets"], "N49E019.tif N49E020.tif")

    def test_sonny_never_area(self):
        self.assertEqual(target.target("sonny", "vysoke_tatry", None, self.tmp.name)["form"], "tiles")

    def test_store_from_env(self):
        os.environ["DMR5_STORE"] = "dem-test"
        try:
            self.assertEqual(target.target("dmr5", "whole", None, self.tmp.name)["store"], "dem-test")
        finally:
            del os.environ["DMR5_STORE"]


class Coverage(unittest.TestCase):
    def test_covers_own_degree(self):
        self.assertAlmostEqual(coverage.covers_own_degree((19, 49, 20, 50), (19, 49)), 100)
        self.assertAlmostEqual(coverage.covers_own_degree((19, 49, 19.5, 50), (19, 49)), 50)
        self.assertEqual(coverage.covers_own_degree((21, 49, 22, 50), (19, 49)), 0)

    def test_covered_pct(self):
        self.assertAlmostEqual(coverage.covered_pct((19, 49, 21, 50), [(19, 49, 20, 50)]), 50, delta=0.5)
        self.assertAlmostEqual(coverage.covered_pct((19, 49, 21, 50),
                                                    [(19, 49, 20, 50), (20, 49, 21, 50)]), 100)
        self.assertEqual(coverage.covered_pct((19, 49, 21, 50), []), 0.0)

    def test_empty_stamp(self):
        px = tiles.EMPTY_PX
        self.assertIsNone(coverage.empty_stamp({"size": [3601, 3601]}))
        self.assertEqual(coverage.empty_stamp({"size": [px, px]}), "")
        self.assertEqual(coverage.empty_stamp({"size": [px, px],
                                               "metadata": {"": {tiles.EMPTY_TAG: "v2-presne"}}}),
                         "v2-presne")

    def test_suspects(self):
        index = [f"N49E019.tif:{tiles.EMPTY_MAX_BYTES}", "N49E020.tif:90000000",
                 "N48E019.tif:4000", "junk", "N48E020.tif:x"]
        self.assertEqual(trust.suspects(index, {"N49E019.tif", "N49E020.tif", "N48E020.tif"}),
                         ["N49E019.tif"])


@needs_cmd("gdal_translate", "gdalinfo")
class EmptyTile(unittest.TestCase):
    def test_signed_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = os.path.join(tmp, "N49E019.tif")
            self.assertTrue(tiles.empty_tile(dst, 19, 49, "Float32", None))
            info = coverage.tile_info(dst)
            self.assertEqual(coverage.empty_stamp(info), tiles.EMPTY_CHECK)
            self.assertEqual(coverage.degree_of(dst), (19, 49))
            self.assertAlmostEqual(coverage.covers_own_degree(coverage.extent_of(info), (19, 49)), 100)
            self.assertIsNone(tiles.elevation_range(dst, exact=True))
            self.assertLessEqual(os.path.getsize(dst), tiles.EMPTY_MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
