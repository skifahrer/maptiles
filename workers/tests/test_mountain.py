import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from load import WORKERS, needs, needs_cmd, worker

ROOT = os.path.dirname(WORKERS)
plan = worker("mountain/plan.py")
manifest = worker("mountain/manifest.py")
aerial = worker("mountain/aerial.py")
outline = worker("mountain/outline.py")
names = worker("deploy/names.py")
catalog = worker("deploy/catalog.py")

CLEAR = {k: "" for k in ("REGION_KEY", "AREA_KEY", "CUSTOM_PBF_URL", "CUSTOM_NAME",
                         "TEST_KM2", "MAP_LAYERS", "MOUNTAIN_COUNTRY")}


def env(**kw):
    return mock.patch.dict(os.environ, {**CLEAR, **kw})


def registry(name):
    with open(os.path.join(WORKERS, "data", name), encoding="utf-8") as f:
        return json.load(f)


class Registry(unittest.TestCase):
    def test_every_mountain_has_a_country_and_a_cut_out(self):
        areas, regions = registry("areas.json"), registry("regions.json")
        for key, entry in registry("mountains.json").items():
            if key.startswith("_"):
                continue
            self.assertEqual(regions[entry["country"]]["admin_level"], 2, key)
            self.assertIn(entry["area"], areas, key)

    def test_the_form_offers_every_mountain(self):
        import yaml
        with open(os.path.join(ROOT, ".github", "workflows", "mountain.yml")) as f:
            flow = yaml.safe_load(f)
        on = flow.get("on") or flow.get(True)
        offered = on["workflow_dispatch"]["inputs"]["mountain"]["options"]
        known = [k for k in registry("mountains.json") if not k.startswith("_")]
        self.assertEqual(sorted(offered), sorted(known))

    def test_a_range_has_contours_every_five_metres(self):
        import yaml
        with open(os.path.join(ROOT, ".github", "workflows", "mountain.yml")) as f:
            options = yaml.safe_load(f)["env"]["MOUNTAIN_OPTIONS"].split()
        self.assertIn("contour_interval=5", options)

    def test_exaggeration_is_the_styles(self):
        with open(os.path.join(ROOT, "poc", "web", "themes.js"), encoding="utf-8") as f:
            found = re.search(r"DEFAULT_TERRAIN_EXAGGERATION = ([\d.]+)", f.read())
        self.assertEqual(float(found.group(1)), manifest.TERRAIN_EXAGGERATION)


class Plan(unittest.TestCase):
    def test_a_range_resolves_to_its_country_and_cut_out(self):
        got = plan.plan("vysoke_tatry")
        self.assertEqual((got["key"], got["country"], got["area"], got["area_key"]),
                         ("vysoke_tatry", "slovensko", "vysoke_tatry", "vysoke_tatry"))
        self.assertEqual(got["name"], "Vysoké Tatry")
        self.assertEqual(got["bbox"], "19.9,49.09,20.32,49.32")
        self.assertEqual(got["bboxkey"], "19_9_49_09_20_32_49_32")

    def test_a_test_never_shares_keys_with_the_real_one(self):
        got = plan.plan("vysoke_tatry", test_km2=4)
        self.assertEqual((got["key"], got["area_key"]), ("vysoke_tatry_test4", "vysoke_tatry_test4"))
        self.assertEqual(names.strip_test(got["key"]), "vysoke_tatry")
        self.assertLess(float(got["km2"]), 5)

    def test_unknown_range(self):
        with self.assertRaises(SystemExit):
            plan.plan("alpy")

    def test_outline_is_the_bbox(self):
        ring = plan.outline([1, 2, 3, 4])["features"][0]["geometry"]["coordinates"][0]
        self.assertEqual(ring, [[1, 2], [3, 2], [3, 4], [1, 4], [1, 2]])

    def test_poly_closes_the_bbox_for_osmium(self):
        lines = plan.poly(plan.outline([1, 2, 3, 4])).splitlines()
        self.assertEqual(lines[:2], ["mountain", "1"])
        self.assertEqual(lines[2].split(), lines[6].split())
        self.assertEqual(lines[-2:], ["END", "END"])

    def test_poly_marks_a_hole(self):
        square = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
        hole = [[1, 1], [2, 1], [2, 2], [1, 1]]
        fc = {"features": [{"geometry": {"type": "Polygon", "coordinates": [square, hole]}}]}
        lines = plan.poly(fc).splitlines()
        self.assertIn("!2", lines)

    def test_the_high_tatras_follow_the_parks(self):
        drawn = plan.shape("vysoke_tatry", [19.9, 49.09, 20.32, 49.32])
        rings = plan.rings(drawn)
        self.assertEqual([hole for _, hole in rings], [False])
        self.assertGreater(len(rings[0][0]), 100, "the parks' edge, not the box's four corners")
        lons = [x for x, _ in rings[0][0]]
        lats = [y for _, y in rings[0][0]]
        self.assertTrue(19.9 <= min(lons) and max(lons) <= 20.32 and 49.09 <= min(lats)
                        and max(lats) <= 49.32, "inside the box")

    def test_an_outline_has_a_key_of_its_own(self):
        got = plan.plan("vysoke_tatry")
        self.assertTrue(got["shapekey"].startswith(got["bboxkey"] + "_o"))
        self.assertEqual(plan.plan("nizke_tatry")["shapekey"], plan.plan("nizke_tatry")["bboxkey"])
        self.assertEqual(plan.plan("vysoke_tatry", test_km2=4)["shapekey"],
                         plan.plan("vysoke_tatry", test_km2=4)["bboxkey"], "a test square is a box")

    def test_the_high_tatras_end_where_the_lidar_does(self):
        got = plan.plan("vysoke_tatry")
        self.assertEqual(got["countries"], "SK")
        self.assertEqual(got["osm"].split(),
                         ["https://download.openstreetmap.fr/extracts/europe/slovakia-latest.osm.pbf"])
        rings = plan.rings(plan.shape("vysoke_tatry", [19.9, 49.09, 20.32, 49.32]))
        lats_at_morskie_oko = [y for x, y in rings[0][0] if abs(x - 20.071) < 0.01]
        self.assertTrue(lats_at_morskie_oko and max(lats_at_morskie_oko) < 49.195,
                        "the border runs south of Morskie Oko, so the range does too")

    def test_every_range_crossing_the_border_has_an_outline(self):
        for key in ("vysoke_tatry", "zapadne_tatry", "pieniny"):
            self.assertIsNotNone(plan.outline_file(key), key)
        self.assertIsNone(plan.outline_file("nizke_tatry"), "wholly in Slovakia, its box")

    def test_a_range_without_extracts_takes_its_countrys(self):
        mountains = {"x": {"country": "slovensko", "area": "pieniny"}}
        self.assertEqual(plan.plan("x", mountains=mountains)["osm"],
                         "https://download.openstreetmap.fr/extracts/europe/slovakia-latest.osm.pbf")

    def test_every_range_names_its_countries_and_extracts(self):
        for key, entry in registry("mountains.json").items():
            if key.startswith("_"):
                continue
            self.assertIn("SK", entry["countries"], key)
            self.assertEqual(len(entry["osm"]), len(entry["countries"]), key)


class Manifest(unittest.TestCase):
    def site(self, *kinds):
        site = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, site)
        os.makedirs(os.path.join(site, "tiles"))
        for kind in kinds:
            open(os.path.join(site, "tiles", f"vysoke_tatry-{kind}.pmtiles"), "wb").close()
        return site

    def test_says_what_the_layers_really_are(self):
        site = self.site("contours", "rocks", "terrain")
        with env(REGION_KEY="vysoke_tatry", AREA_BBOX="19.9,49.09,20.32,49.25",
                 CONTOUR_INTERVAL="2.5", CONTOURS_MAXZOOM="16", ROCKS_MAXZOOM="16",
                 ROCK_SLOPE="50", ROCKS_SOURCE="dmr5", CONTOURS_SOURCE="dmr5",
                 TERRAIN_MAXZOOM="16", TERRAIN_SOURCE="dmr5", MOUNTAIN_NAME="Vysoké Tatry"):
            got = manifest.manifest(site)
        reg = got["regions"]["vysoke_tatry"]
        self.assertEqual(reg["contour_interval"], 2.5)
        self.assertEqual(reg["bbox"], [19.9, 49.09, 20.32, 49.25])
        self.assertEqual(reg["contours"], "tiles/vysoke_tatry-contours.pmtiles")
        self.assertEqual((got["dem"], got["dem_maxzoom"], got["terrain_3d"]),
                         ("tiles/vysoke_tatry-terrain.pmtiles", 16, True))
        self.assertEqual(catalog.tiles_paths(got, reg)["terrain"], "tiles/vysoke_tatry-terrain.pmtiles")

    def test_borders_and_nature_are_the_boundaries_package(self):
        site = self.site("range-boundaries")
        with env(REGION_KEY="vysoke_tatry", AREA_BBOX="19.9,49.09,20.32,49.32", BOUNDARIES_MAXZOOM="14"):
            got = manifest.manifest(site)
        reg = got["regions"]["vysoke_tatry"]
        self.assertEqual((reg["boundaries"], reg["boundaries_maxzoom"]),
                         ("tiles/vysoke_tatry-range-boundaries.pmtiles", 14))
        self.assertEqual(catalog.tiles_paths(got, reg)["boundaries"],
                         "tiles/vysoke_tatry-range-boundaries.pmtiles")

    def test_the_app_gets_the_outline(self):
        site = self.site("terrain")
        with env(REGION_KEY="vysoke_tatry", AREA_BBOX="19.9,49.09,20.32,49.32"):
            reg = manifest.manifest(site)["regions"]["vysoke_tatry"]
        self.assertEqual(len(reg["outline"]), 1, "one polygon")
        self.assertGreater(len(reg["outline"][0][0]), 100)
        with env(REGION_KEY="nizke_tatry", AREA_BBOX="19.05,48.83,20.2,49.08"):
            self.assertNotIn("outline", manifest.manifest(site)["regions"]["nizke_tatry"])

    def test_roads_paths_and_photos(self):
        site = self.site("transport", "paths")
        with open(os.path.join(site, "tiles", "vysoke_tatry-aerial_summer.pmtiles"), "wb") as f:
            f.write(b"PMTiles\x03" + bytes(92) + bytes([8, 17]))
        open(os.path.join(site, "tiles", "vysoke_tatry-roadsigns.png"), "wb").close()
        for kind in ("trails", "water", "points"):
            open(os.path.join(site, "tiles", f"vysoke_tatry-{kind}.pmtiles"), "wb").close()
        with env(REGION_KEY="vysoke_tatry", AREA_BBOX="1,2,3,4", TRANSPORT_MAXZOOM="14",
                 COUNTRIES="SK,PL", WATER_MAXZOOM="14"):
            reg = manifest.manifest(site)["regions"]["vysoke_tatry"]
        self.assertNotIn("trails", reg, "a range's Paths draw its trails")
        self.assertEqual((reg["water"], reg["water_maxzoom"]), ("tiles/vysoke_tatry-water.pmtiles", 14))
        self.assertEqual((reg["points"], reg["points_maxzoom"]), ("tiles/vysoke_tatry-points.pmtiles", 15))
        self.assertEqual(reg["countries"], ["SK", "PL"])
        self.assertEqual((reg["transport"], reg["paths_maxzoom"]),
                         ("tiles/vysoke_tatry-transport.pmtiles", 14))
        self.assertEqual(reg["road_sign_sprite"], ["tiles/vysoke_tatry-roadsigns.png"])
        self.assertEqual((reg["aerial_summer"], reg["aerial_summer_maxzoom"]),
                         ("tiles/vysoke_tatry-aerial_summer.pmtiles", 17))
        self.assertNotIn("aerial_winter", reg)

    def test_a_missing_layer_is_left_out(self):
        site = self.site("contours")
        with env(REGION_KEY="vysoke_tatry", AREA_BBOX="1,2,3,4", CONTOUR_INTERVAL="5"):
            got = manifest.manifest(site)
        self.assertNotIn("rocks", got["regions"]["vysoke_tatry"])
        self.assertNotIn("dem", got)
        self.assertEqual(got["regions"]["vysoke_tatry"]["contour_interval"], 5)

    def test_nothing_to_package_fails(self):
        site = self.site()
        with env(REGION_KEY="vysoke_tatry", AREA_BBOX="1,2,3,4"), \
                redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            manifest.main([site])


class Names(unittest.TestCase):
    def test_drive_folder_is_in_the_mountains_category(self):
        with env(REGION_KEY="vysoke_tatry", AREA_KEY="whole", MOUNTAIN_COUNTRY="slovensko"):
            self.assertEqual(names.drive_path({}), ["mountains", "vysoke_tatry"])
            self.assertEqual(names.file_name("contours"), "vysoke_tatry-contours.zip")

    def test_a_test_gets_its_own_node(self):
        with env(REGION_KEY="vysoke_tatry_test4", AREA_KEY="whole", TEST_KM2="4",
                 MOUNTAIN_COUNTRY="slovensko"):
            parts = names.drive_path({})
            self.assertEqual(parts, ["mountains", "vysoke_tatry"])
            self.assertEqual(names.catalog_path(parts)[-1], "vysoke_tatry_test4km2")
            self.assertEqual(names.file_name("rocks"), "vysoke_tatry-test4km2-rocks.zip")

    def test_a_region_is_untouched(self):
        with env(REGION_KEY="presovsky", AREA_KEY="whole"):
            self.assertEqual(names.drive_path({"presovsky": {"country": "slovensko"}}),
                             ["slovensko", "presovsky"])


class Catalog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.path = os.path.join(self.tmp, "maps.json")
        self.regions = registry("regions.json")
        with open(self.path, "w") as f:
            json.dump({"slovensko": {"name": "Slovakia", "regions": {"presovsky": {"maps": {}}}}}, f)

    def write(self, parts, man, uploaded, **kw):
        with redirect_stdout(io.StringIO()):
            catalog.write_catalog(self.path, parts, self.regions, uploaded, man,
                                  owns=[k for k, *_ in uploaded], **kw)
        with open(self.path) as f:
            return json.load(f)

    def mountain(self):
        man = {"default_region": "vysoke_tatry", "dem": "tiles/vysoke_tatry-terrain.pmtiles",
               "dem_maxzoom": 16, "dem_source": "dmr5",
               "regions": {"vysoke_tatry": {"bbox": [19.9, 49.09, 20.32, 49.25],
                                            "contours": "tiles/vysoke_tatry-contours.pmtiles",
                                            "contours_maxzoom": 16, "contour_interval": 2.5}}}
        uploaded = [("contours", "vysoke_tatry-contours.zip", 10, "id1", "zip", "a" * 64),
                    ("terrain", "vysoke_tatry-terrain.zip", 20, "id2", "zip", "b" * 64)]
        with env(MOUNTAIN_COUNTRY="slovensko"):
            return self.write(["mountains", "vysoke_tatry"], man, uploaded)

    def test_a_mountain_sits_in_its_own_category(self):
        data = self.mountain()
        self.assertEqual((data["mountains"]["id"], data["mountains"]["name"]),
                         ("mountains", "Mountains"))
        node = data["mountains"]["ranges"]["vysoke_tatry"]
        self.assertEqual((node["id"], node["name"]), ("mountains-vysoke_tatry", "Vysoké Tatry"))
        self.assertEqual((node["country"], node["drive"]), ("slovensko", "mountains/vysoke_tatry"))
        self.assertNotIn("mountains", data["slovensko"])
        self.assertEqual(node["contour_interval"], 2.5)
        self.assertEqual(node["terrain_maxzoom"], 16)
        self.assertEqual(sorted(node["maps"]), ["contours", "terrain"])
        self.assertNotIn("area_bbox", node)
        self.assertNotIn("vysoke_tatry", data["slovensko"]["regions"])

    def test_a_country_build_keeps_its_mountains(self):
        self.mountain()
        man = {"default_region": "slovensko", "regions": {"slovensko": {"bbox": [16, 47, 23, 50]}}}
        data = self.write(["slovensko"], man, [("", "slovensko.zip", 5, "id3", "zip", "c" * 64)])
        self.assertIn("vysoke_tatry", data["mountains"]["ranges"])
        self.assertIn("presovsky", data["slovensko"]["regions"])

    def test_a_mountain_under_its_country_moves_to_the_category(self):
        with open(self.path, "w") as f:
            json.dump({"slovensko": {"name": "Slovakia", "regions": {},
                                     "mountains": {"pieniny": {"name": "Pieniny", "maps": {}}}}}, f)
        data = self.mountain()
        self.assertEqual(sorted(data["mountains"]["ranges"]), ["pieniny", "vysoke_tatry"])
        self.assertEqual(data["mountains"]["ranges"]["pieniny"]["country"], "slovensko")
        self.assertNotIn("mountains", data["slovensko"])


class Publish(unittest.TestCase):
    def test_a_mountain_publishes_its_layers_and_no_base_map(self):
        site = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, site)
        os.makedirs(os.path.join(site, "tiles"))
        for kind in ("contours", "rocks", "terrain", "transport", "paths", "water", "points",
                     "aerial_summer"):
            with open(os.path.join(site, "tiles", f"vysoke_tatry-{kind}.pmtiles"), "wb") as f:
                f.write(b"x")
        with open(os.path.join(site, "tiles", "manifest.json"), "w") as f:
            json.dump({"default_region": "vysoke_tatry", "regions": {"vysoke_tatry": {}}}, f)
        run = subprocess.run(
            ["python3", os.path.join(WORKERS, "deploy", "publish-map.py"),
             f"--site={site}", "--maps=", "--dry-run"],
            capture_output=True, text=True,
            env={**os.environ, **CLEAR, "REGION_KEY": "vysoke_tatry", "AREA_KEY": "whole",
                 "MOUNTAIN_COUNTRY": "slovensko"})
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        listed = re.findall(r"^\s+(vysoke_tatry\S*\.zip) .* \d+ files", run.stdout, re.M)
        self.assertIn("vysoke_tatry-aerial_winter.zip", run.stdout)
        self.assertEqual(sorted(listed), ["vysoke_tatry-aerial_summer.zip",
                                          "vysoke_tatry-contours.zip", "vysoke_tatry-paths.zip",
                                          "vysoke_tatry-points.zip", "vysoke_tatry-roads.zip",
                                          "vysoke_tatry-rocks.zip", "vysoke_tatry-terrain.zip",
                                          "vysoke_tatry-water.zip"])
        self.assertRegex(run.stdout, r"vysoke_tatry-trails\.zip .* NOT IN THIS BUILD",
                         "the old trails package is deleted, not left behind")
        self.assertIn("mountains/vysoke_tatry", run.stdout)


OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
{}
</osm>
"""
NODE = '<node id="{}" version="1" timestamp="2026-01-01T00:00:00Z" lat="{}" lon="{}"/>'


@needs_cmd("osmium", "curl")
class Extracts(unittest.TestCase):
    def extract(self, folder, name, nodes):
        xml = os.path.join(folder, name + ".osm")
        with open(xml, "w") as f:
            f.write(OSM.format("\n".join(NODE.format(*n) for n in nodes)))
        pbf = os.path.join(folder, name + ".osm.pbf")
        subprocess.run(["osmium", "cat", "-o", pbf, xml], check=True)
        return "file://" + pbf

    def test_extracts_are_cut_to_the_box_and_merged_once(self):
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work)
        # node 2 lies on the border and is in both countries' extracts
        sk = self.extract(work, "sk", [(1, 49.15, 20.1), (2, 49.2, 20.1), (5, 48.0, 20.1)])
        pl = self.extract(work, "pl", [(2, 49.2, 20.1), (3, 49.3, 20.0)])
        run = subprocess.run(["bash", os.path.join(WORKERS, "mountain", "pbf.sh")], cwd=work,
                             capture_output=True, text=True,
                             env={**os.environ, "OSM_URLS": f"{sk} {pl}",
                                  "MOUNTAIN_BBOX": "19.9,49.09,20.32,49.32"})
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        ids = subprocess.run(["osmium", "cat", "-f", "opl", os.path.join(work, "data", "region.osm.pbf")],
                             capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(sorted(i for i in ids if i.startswith("n")), ["n1", "n2", "n3"])


@needs("shapely")
class Outline(unittest.TestCase):
    def square(self, w, s, e, n):
        return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}

    def test_two_parks_become_one_edge_inside_the_box(self):
        parks = [self.square(19.8, 49.0, 20.1, 49.25), self.square(20.1, 49.1, 20.4, 49.3),
                 self.square(20.2, 49.299, 20.201, 49.3)]
        got = outline.outline(parks, [19.9, 49.09, 20.32, 49.32], [1, 2, 3])
        geom = got["features"][0]["geometry"]
        self.assertEqual(geom["type"], "Polygon", "joined, the islet dropped")
        lons = [x for x, _ in geom["coordinates"][0]]
        self.assertEqual((min(lons), max(lons)), (19.9, 20.32))
        self.assertEqual(got["features"][0]["properties"]["osm_relations"], [1, 2, 3])

    def test_nothing_in_the_box_stops(self):
        with self.assertRaises(SystemExit):
            outline.outline([self.square(10, 10, 11, 11)], [19.9, 49.09, 20.32, 49.32], [1])

    def test_a_range_ends_where_its_model_does(self):
        slovakia = self.square(19.0, 48.0, 20.2, 49.25)
        got = outline.outline([], [19.9, 49.09, 20.32, 49.32], [], coverage=slovakia)
        lons = [x for x, _ in got["features"][0]["geometry"]["coordinates"][0]]
        lats = [y for _, y in got["features"][0]["geometry"]["coordinates"][0]]
        self.assertEqual((max(lons), max(lats)), (20.2, 49.25))
        self.assertEqual(got["features"][0]["properties"]["model"], "dmr5")

    def test_a_box_wholly_in_its_model_is_kept(self):
        slovakia = self.square(19.0, 48.0, 21.0, 50.0)
        self.assertIsNone(outline.outline([], [19.9, 49.09, 20.32, 49.32], [], coverage=slovakia))


class Aerial(unittest.TestCase):
    def test_every_tile_over_the_box_shallow_first(self):
        got = aerial.wanted([20.16, 49.17, 20.17, 49.175], 14, 15)
        self.assertEqual(got[0][0], 14)
        self.assertEqual({z for z, _x, _y in got}, {14, 15})
        self.assertEqual(len(got), len(set(got)))

    def test_a_tile_inside_the_box_is_whole(self):
        x, y = (int(v) for v in aerial.lonlat_to_tile(20.1, 49.2, 14))
        self.assertIsNone(aerial.window([19.9, 49.09, 20.32, 49.32], 14, x, y, 256))

    def test_a_tile_on_the_edge_keeps_only_the_box(self):
        left, top, right, bottom = aerial.window([19.9, 49.09, 20.32, 49.32], 8, 142, 87, 256)
        self.assertTrue(0 < left < right < 256 and 0 < top < bottom < 256)

    @needs("PIL")
    def test_beyond_the_box_is_clear(self):
        from PIL import Image
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        bbox = [19.9, 49.09, 20.32, 49.32]
        jpeg = os.path.join(tmp, "t.jpg")
        Image.new("RGB", (256, 256), (40, 90, 40)).save(jpeg, "JPEG")
        x, y = (int(v) for v in aerial.lonlat_to_tile(20.1, 49.2, 14))
        self.assertEqual(aerial.cut(jpeg, bbox, 14, x, y), jpeg)
        left, top, right, bottom = aerial.window(bbox, 8, 142, 87, 256)
        with Image.open(aerial.cut(jpeg, bbox, 8, 142, 87)) as got:
            self.assertEqual(got.format, "WEBP")
            alpha = got.getchannel("A")
            self.assertEqual(alpha.getpixel((0, 0)), 0)
            self.assertEqual(alpha.getpixel(((left + right) // 2, (top + bottom) // 2)), 255)

    @needs("PIL")
    def test_photos_follow_the_outline(self):
        from PIL import Image
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        bbox = [19.9, 49.09, 20.32, 49.32]
        rings = aerial._mask.rings_from_geojson(
            os.path.join(WORKERS, "data", "outlines", "vysoke_tatry.geojson"))
        jpeg = os.path.join(tmp, "t.jpg")
        Image.new("RGB", (256, 256), (40, 90, 40)).save(jpeg, "JPEG")
        gerlach = (int(v) for v in aerial.lonlat_to_tile(20.134, 49.164, 14))
        self.assertEqual(aerial.cut(jpeg, bbox, 14, *gerlach, rings), jpeg)
        zdiar = (int(v) for v in aerial.lonlat_to_tile(20.27, 49.275, 15))
        self.assertIsNone(aerial.cut(jpeg, bbox, 15, *zdiar, rings), "in the box, beyond the parks")
        with Image.open(aerial.cut(jpeg, bbox, 8, 142, 87, rings)) as got:
            alpha = got.getchannel("A")
            px = lambda lon, lat: tuple(int((v - o) * 256) for v, o in
                                        zip(aerial.lonlat_to_tile(lon, lat, 8), (142, 87)))
            self.assertEqual(alpha.getpixel(px(20.134, 49.164)), 255)
            self.assertEqual(alpha.getpixel(px(20.27, 49.275)), 0)

    def test_summer_has_a_source(self):
        self.assertTrue(aerial.season("summer")["url"].endswith("{z}/{x}/{y}.jpg"))

    def test_the_archive_is_jpeg_with_its_zooms(self):
        try:
            from pmtiles.reader import MmapSource, Reader
        except ImportError:
            self.skipTest("pmtiles isn't installed")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        jpeg = os.path.join(tmp, "t.jpg")
        with open(jpeg, "wb") as f:
            f.write(b"\xff\xd8\xff" + bytes(20))
        out = os.path.join(tmp, "x-aerial_summer.pmtiles")
        aerial.write(out, {(8, 145, 89): jpeg, (9, 290, 178): jpeg}, [20, 49, 20.3, 49.2],
                     8, 9, "x-aerial_summer")
        with open(out, "rb") as f:
            reader = Reader(MmapSource(f))
            head = reader.header()
            self.assertEqual((head["min_zoom"], head["max_zoom"]), (8, 9))
            self.assertEqual(head["tile_type"].name, "JPEG")
            self.assertEqual(reader.get(9, 290, 178)[:3], b"\xff\xd8\xff")
        self.assertEqual(manifest.pmtiles_zooms(out), (8, 9))


if __name__ == "__main__":
    unittest.main()
