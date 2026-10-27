import unittest

from load import worker

urls = worker("lib/extract-urls.py")
BASE = "https://x/extracts"
REGIONS = {
    "slovensko": {"osmfr": {"dir": "europe", "slugs": ["slovakia-latest", "slovakia"]}},
    "bratislavsky": {"osmfr": {"dir": "europe/slovakia", "slugs": ["bratislavsky-latest"],
                               "parent": "slovensko"}},
    "vlastny": {},
}


class Urls(unittest.TestCase):
    def test_a_region_needs_its_parent_and_every_name_of_it(self):
        self.assertEqual(urls.region("bratislavsky", REGIONS, BASE),
                         [f"{BASE}/europe/slovakia-latest.osm.pbf {BASE}/europe/slovakia.osm.pbf"])

    def test_a_country_needs_itself(self):
        self.assertEqual(urls.region("slovensko", REGIONS, BASE),
                         urls.region("bratislavsky", REGIONS, BASE))

    def test_a_region_without_osmfr_needs_nothing(self):
        self.assertEqual(urls.region("vlastny", REGIONS, BASE), [])
        self.assertEqual(urls.region("unknown", REGIONS, BASE), [])

    def test_a_routing_area_needs_each_of_its_extracts(self):
        areas = {"sk_cz": {"pbf": ["europe/slovakia", "europe/czech_republic"]}}
        self.assertEqual(urls.routing("sk_cz", areas, BASE),
                         [f"{BASE}/europe/slovakia-latest.osm.pbf",
                          f"{BASE}/europe/czech_republic-latest.osm.pbf"])


if __name__ == "__main__":
    unittest.main()
