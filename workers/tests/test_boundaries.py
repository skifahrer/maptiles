import os
import unittest

from load import WORKERS, needs

BOUNDARIES = os.path.join(WORKERS, "boundaries")
REGIONAL = ("boundary", "boundary_line", "boundary_label", "place")


def schema(name):
    import yaml
    with open(os.path.join(BOUNDARIES, f"{name}.yml"), encoding="utf-8") as f:
        return {layer["id"]: layer for layer in yaml.safe_load(f)["layers"]}


def filter_rules(name):
    """`{(kind, key): {values}}` of an `osmium tags-filter` expressions file; no value is any."""
    rules = {}
    with open(os.path.join(BOUNDARIES, name), encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            kinds, expr = line.split("/", 1)
            key, _, values = expr.partition("=")
            for kind in kinds:
                rules.setdefault((kind, key), set()).update(values.split(",") if values else {"*"})
    return rules


def wanted(include):
    """Every `(key, value)` an `include_when` asks for."""
    if isinstance(include, list):
        return [kv for part in include for kv in wanted(part)]
    out = []
    for key, value in include.items():
        if key in ("__all__", "__any__"):
            out += wanted(value)
        else:
            out += [(key, v) for v in (value if isinstance(value, list) else [value])]
    return out


@needs("yaml")
class RangeSchema(unittest.TestCase):
    def test_a_range_keeps_the_regional_layers(self):
        regional, ranged = schema("boundaries"), schema("range")
        for layer in REGIONAL:
            with self.subTest(layer=layer):
                self.assertEqual(ranged[layer]["features"][:len(regional[layer]["features"])],
                                 regional[layer]["features"])

    def test_settlement_parts_and_nature_are_in(self):
        ranged = schema("range")
        levels = [v for f in ranged["boundary"]["features"] for k, v in wanted(f["include_when"])
                  if k == "admin_level"]
        self.assertIn("11", levels)
        self.assertTrue({"nature_area", "nature_label", "ridge", "valley"} <= set(ranged))

    def test_the_prefilter_lets_through_what_the_schema_wants(self):
        rules = filter_rules("range-filter.txt")
        for layer in schema("range").values():
            for feature in layer["features"]:
                for key, value in wanted(feature["include_when"]):
                    if key == "admin_level":
                        continue
                    kinds = {"r", "w"} if feature["geometry"] != "point" else {"n"}
                    with self.subTest(layer=layer["id"], tag=f"{key}={value}"):
                        self.assertTrue(any(value in rules.get((kind, key), ()) or "*" in rules.get((kind, key), ())
                                            for kind in kinds), f"{key}={value} isn't in range-filter.txt")


class RangeBuild(unittest.TestCase):
    def test_the_range_schema_makes_a_file_of_its_own(self):
        with open(os.path.join(BOUNDARIES, "build.sh"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("range) FILTER=workers/boundaries/range-filter.txt; SUFFIX=range-boundaries", src)
        self.assertIn('OUT="_site/tiles/${REGION_KEY}-${SUFFIX}.pmtiles"', src)


if __name__ == "__main__":
    unittest.main()
