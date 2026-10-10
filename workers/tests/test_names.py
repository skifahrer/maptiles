import os
import unittest
from unittest import mock

from load import worker

names = worker("deploy/names.py")

REGIONS = {
    "presovsky": {"country": "slovakia", "admin_level": 4},
    "slovakia": {"country": "slovakia", "admin_level": 2},
}
CLEAR = {k: "" for k in ("REGION_KEY", "AREA_KEY", "CUSTOM_PBF_URL",
                         "CUSTOM_NAME", "TEST_KM2", "MAP_LAYERS")}


def env(**kw):
    return mock.patch.dict(os.environ, {**CLEAR, **kw})


class Safe(unittest.TestCase):
    def test_folds_diacritics(self):
        self.assertEqual(names.safe("Prešovský kraj"), "presovsky_kraj")

    def test_slash_becomes_underscore(self):
        self.assertEqual(names.safe("a/b c"), "a_b_c")

    def test_empty_is_unnamed(self):
        self.assertEqual(names.safe("  "), "unnamed")
        self.assertEqual(names.safe("///"), "unnamed")


class StripTest(unittest.TestCase):
    def test_strips_suffix(self):
        self.assertEqual(names.strip_test("presovsky_test4"), "presovsky")

    def test_strips_stacked(self):
        self.assertEqual(names.strip_test("presovsky_test4_test2"), "presovsky")

    def test_keeps_lookalikes(self):
        self.assertEqual(names.strip_test("presovsky_tester"), "presovsky_tester")
        self.assertEqual(names.strip_test("presovsky_test"), "presovsky_test")


class CountryFromUrl(unittest.TestCase):
    def test_extract(self):
        url = "https://download.openstreetmap.fr/extracts/europe/austria/tirol-latest.osm.pbf"
        self.assertEqual(names.country_from_url(url), "austria")

    def test_unknown(self):
        self.assertEqual(names.country_from_url("region.osm.pbf"), "other")


class DrivePath(unittest.TestCase):
    def test_region(self):
        with env(REGION_KEY="presovsky"):
            self.assertEqual(names.drive_path(REGIONS), ["slovakia", "presovsky"])

    def test_test_suffix_is_not_a_folder(self):
        with env(REGION_KEY="presovsky_test4"):
            self.assertEqual(names.drive_path(REGIONS), ["slovakia", "presovsky"])

    def test_country_has_no_region_folder(self):
        with env(REGION_KEY="slovakia"):
            self.assertEqual(names.drive_path(REGIONS), ["slovakia"])

    def test_whole_adds_no_folder(self):
        # fix 1334: packages landed in a `cely` folder
        for key in ("cely", "whole", "cely_test2"):
            with self.subTest(key=key), env(REGION_KEY="slovakia", AREA_KEY=key):
                self.assertEqual(names.drive_path(REGIONS), ["slovakia"])

    def test_area_is_appended(self):
        with env(REGION_KEY="presovsky", AREA_KEY="Vysoké Tatry"):
            self.assertEqual(names.drive_path(REGIONS),
                             ["slovakia", "presovsky", "vysoke_tatry"])

    def test_custom_pbf(self):
        url = "https://download.openstreetmap.fr/extracts/europe/austria/tirol-latest.osm.pbf"
        with env(CUSTOM_PBF_URL=url):
            self.assertEqual(names.drive_path(REGIONS), ["austria", "tirol-latest"])
        with env(CUSTOM_PBF_URL=url, CUSTOM_NAME="Tirol"):
            self.assertEqual(names.drive_path(REGIONS), ["austria", "tirol"])


class FileName(unittest.TestCase):
    def test_stable_across_runs(self):
        with env(REGION_KEY="presovsky_test4", AREA_KEY="tatry"):
            first = names.file_name("trails")
            self.assertEqual(first, names.file_name("trails"))
        self.assertEqual(first, "presovsky-tatry-trails.zip")

    def test_quick_test_never_overwrites_the_map(self):
        with env(REGION_KEY="presovsky", TEST_KM2="4"):
            self.assertEqual(names.file_name(fmt="aar"), "presovsky-test4km2.aar")
            self.assertEqual(names.catalog_path(["slovakia", "presovsky"]),
                             ["slovakia", "presovsky_test4km2"])


if __name__ == "__main__":
    unittest.main()
