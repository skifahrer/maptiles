import base64
import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from load import worker

cloudkit = worker("deploy/cloudkit.py")


def region(name, ts=1, **extra):
    return dict({"name": name, "bbox": [17, 48, 18, 49], "updated_ts": ts,
                 "maps": {"base": {"download": "https://example.invalid/b", "size": 1}}}, **extra)


def catalog():
    return {
        "_updated_ts": 5,
        "slovensko": {"id": "slovakia", "name": "Slovakia", "updated_ts": 3,
                      "maps": {"routing": {"download": "https://example.invalid/r"}},
                      "regions": {"kosicky": region("Košický", id="slovakia-kosicky"),
                                  "presovsky": region("Prešovský", id="slovakia-presovsky")}},
        "usa": {"id": "usa", "name": "United States",
                "regions": {"california": {"id": "usa-california", "name": "California",
                                           "subregions": {"bay": region("Bay Area", id="usa-california-bay")}}}},
        "svet_ground": dict(region("World – ground"), id="world_ground"),
    }


class FakeCloud:
    """The records API over a dict, with change tags."""

    def __init__(self):
        self.records, self.calls, self.tag, self.before_modify = {}, [], 0, None
        self.files = {}

    def upload(self, record_name, data):
        self.files[record_name] = data
        return {"receipt": f"r-{record_name}", "size": len(data), "fileChecksum": "x"}

    def __call__(self, operation, payload):
        self.calls.append(operation)
        if operation == "lookup":
            out = []
            for asked in payload["records"]:
                record = self.records.get(asked["recordName"])
                out.append(copy.deepcopy(record) if record else
                           {"recordName": asked["recordName"], "serverErrorCode": "NOT_FOUND"})
            return {"records": out}
        if self.before_modify:
            hook, self.before_modify = self.before_modify, None
            hook(self)
        out = []
        for op in payload["operations"]:
            record, name = op["record"], op["record"]["recordName"]
            have = self.records.get(name)
            if op["operationType"] == "forceDelete":
                self.records.pop(name, None)
                out.append({"recordName": name, "deleted": True})
                continue
            if (op["operationType"] == "create" and have) or (
                    op["operationType"] == "update" and (not have or have["recordChangeTag"] != record.get("recordChangeTag"))):
                out.append({"recordName": name, "serverErrorCode": "CONFLICT"})
                continue
            self.tag += 1
            self.records[name] = dict(copy.deepcopy(record), recordChangeTag=str(self.tag))
            out.append(self.records[name])
        return {"records": out}

    def field(self, name, field):
        return self.records[name]["fields"][field]["value"]


def quiet(call, *args, **kwargs):
    with redirect_stdout(io.StringIO()):
        return call(*args, **kwargs)


class Tree(unittest.TestCase):
    def test_every_depth_becomes_a_node_under_its_parent(self):
        tree = cloudkit.nodes(catalog())
        self.assertEqual(tree["root"]["children"], ["slovakia", "usa", "world_ground"])
        self.assertEqual(tree["usa-california-bay"]["parent"], "usa-california")
        self.assertEqual(tree["usa-california-bay"]["in"], "subregions")
        self.assertEqual(tree["slovakia-kosicky"]["key"], "kosicky")
        self.assertNotIn("regions", tree["slovakia"]["body"])

    def test_kinds(self):
        tree = cloudkit.nodes(catalog())
        self.assertEqual(tree["slovakia"]["kind"], "both")
        self.assertEqual(tree["usa"]["kind"], "group")
        self.assertEqual(tree["world_ground"]["kind"], "region")
        self.assertEqual(tree["slovakia-kosicky"]["kind"], "region")

    def test_an_id_twice_is_refused(self):
        twice = catalog()
        twice["slovensko"]["regions"]["presovsky"]["id"] = "slovakia-kosicky"
        with self.assertRaises(ValueError):
            cloudkit.nodes(twice)


class Publishing(unittest.TestCase):
    def test_the_first_publish_writes_everything_children_first(self):
        cloud = FakeCloud()
        writes, deletes = quiet(cloudkit.publish, catalog(), cloud, now=100)
        names = [w[0] for w in writes]
        self.assertEqual(len(names), 8)
        self.assertEqual(names[-1], "root")
        self.assertLess(names.index("usa-california-bay"), names.index("usa-california"))
        self.assertEqual(deletes, [])
        kids = json.loads(cloud.field("slovakia", "children"))
        self.assertEqual([k["id"] for k in kids], ["slovakia-kosicky", "slovakia-presovsky"])
        self.assertEqual(kids[0]["subtreeTs"], 100)
        body = json.loads(cloud.field("slovakia-kosicky", "body"))
        self.assertEqual((body["key"], body["held_in"], body["name"]), ("kosicky", "regions", "Košický"))

    def test_a_second_publish_writes_only_the_change_and_its_ancestors(self):
        cloud = FakeCloud()
        quiet(cloudkit.publish, catalog(), cloud, now=100)
        changed = catalog()
        changed["slovensko"]["regions"]["kosicky"]["updated_ts"] = 9
        writes, _ = quiet(cloudkit.publish, changed, cloud, now=200)
        self.assertEqual([w[0] for w in writes], ["slovakia-kosicky", "slovakia", "root"])
        self.assertEqual(cloud.field("usa", "subtreeTs"), 100)
        self.assertEqual(cloud.field("slovakia", "subtreeTs"), 200)
        self.assertEqual(json.loads(cloud.field("root", "children"))[0]["subtreeTs"], 200)

    def test_nothing_changed_writes_nothing(self):
        cloud = FakeCloud()
        quiet(cloudkit.publish, catalog(), cloud, now=100)
        writes, deletes = quiet(cloudkit.publish, catalog(), cloud, now=200)
        self.assertEqual((writes, deletes), ([], []))

    def test_a_delisted_region_goes_with_what_is_below_it(self):
        cloud = FakeCloud()
        quiet(cloudkit.publish, catalog(), cloud, now=100)
        smaller = catalog()
        del smaller["usa"]["regions"]["california"]
        _, deletes = quiet(cloudkit.publish, smaller, cloud, now=200)
        self.assertEqual(sorted(deletes), ["usa-california", "usa-california-bay"])
        self.assertNotIn("usa-california-bay", cloud.records)
        self.assertEqual(json.loads(cloud.field("usa", "children")), [])

    def test_a_record_changed_meanwhile_is_read_again(self):
        cloud = FakeCloud()
        quiet(cloudkit.publish, catalog(), cloud, now=100)
        changed = catalog()
        changed["slovensko"]["name"] = "Slovensko"

        def another_run(fake):
            fake.tag += 1
            fake.records["slovakia"]["recordChangeTag"] = str(fake.tag)
        cloud.before_modify = another_run
        quiet(cloudkit.publish, changed, cloud, now=200)
        self.assertEqual(cloud.field("slovakia", "name"), "Slovensko")
        self.assertEqual(cloud.calls.count("modify"), 3)


    def test_a_body_past_the_record_limit_goes_up_as_an_asset(self):
        cloud = FakeCloud()
        huge = catalog()
        huge["slovensko"]["regions"]["kosicky"]["translations"] = {"x": "a" * 2_000_000}
        quiet(cloudkit.publish, huge, cloud, now=100)
        self.assertEqual(cloud.field("slovakia-kosicky", "body"), "")
        self.assertEqual(cloud.field("slovakia-kosicky", "bodyFile")["receipt"], "r-slovakia-kosicky")
        body = json.loads(cloud.files["slovakia-kosicky"])
        self.assertEqual((body["key"], len(body["translations"]["x"])), ("kosicky", 2_000_000))
        self.assertNotIn("bodyFile", cloud.records["slovakia"]["fields"])

    def test_children_past_the_record_limit_stop_the_publish(self):
        cloud = FakeCloud()
        wide = catalog()
        wide["usa"]["regions"] = {f"r{i}": region("R" * 200, id=f"usa-r{i}") for i in range(4000)}
        with self.assertRaisesRegex(ValueError, "usa"):
            quiet(cloudkit.publish, wide, cloud, now=100)
        self.assertEqual(cloud.records, {})


class NewCountries(unittest.TestCase):
    def test_a_new_country_starts_on_dev_only(self):
        cloud = FakeCloud()
        quiet(cloudkit.publish, catalog(), cloud, now=100)
        self.assertNotIn("features-beta", cloud.records)
        cloud.records["features-prod"] = {"recordName": "features-prod", "recordType": "AppFeatures",
                                          "recordChangeTag": "x",
                                          "fields": {"switches": {"value": '{"gallery": true}'}}}
        bigger = catalog()
        bigger["rakusko"] = {"id": "austria", "name": "Austria", "regions": {"wien": region("Wien", id="austria-wien")}}
        quiet(cloudkit.publish, bigger, cloud, now=200)
        self.assertEqual(json.loads(cloud.field("features-beta", "switches")), {"country:austria": False})
        self.assertEqual(json.loads(cloud.field("features-prod", "switches")),
                         {"gallery": True, "country:austria": False})
        self.assertNotIn("features-dev", cloud.records)

    def test_an_admin_switch_is_never_overwritten(self):
        cloud = FakeCloud()
        cloud.records["features-beta"] = {"recordName": "features-beta", "recordType": "AppFeatures",
                                          "recordChangeTag": "x",
                                          "fields": {"switches": {"value": '{"country:austria": true}'}}}
        with redirect_stdout(io.StringIO()):
            cloudkit.switch_off(cloud, ["austria"])
        self.assertEqual(json.loads(cloud.field("features-beta", "switches")), {"country:austria": True})
        self.assertEqual(json.loads(cloud.field("features-prod", "switches")), {"country:austria": False})


class Signing(unittest.TestCase):
    def test_the_signature_verifies_with_the_public_key(self):
        with tempfile.TemporaryDirectory() as folder:
            private, public = os.path.join(folder, "k.pem"), os.path.join(folder, "p.pem")
            subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", private],
                           check=True, capture_output=True)
            subprocess.run(["openssl", "ec", "-in", private, "-pubout", "-out", public],
                           check=True, capture_output=True)
            body = b'{"records": []}'
            headers = cloudkit.signed("/database/1/x/development/public/records/lookup", body, "kid", private,
                                      date="2026-10-30T10:00:00Z")
            self.assertEqual(headers["X-Apple-CloudKit-Request-KeyID"], "kid")
            digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
            message = os.path.join(folder, "m")
            signature = os.path.join(folder, "s")
            with open(message, "w") as out:
                out.write(f"2026-10-30T10:00:00Z:{digest}:/database/1/x/development/public/records/lookup")
            with open(signature, "wb") as out:
                out.write(base64.b64decode(headers["X-Apple-CloudKit-Request-SignatureV1"]))
            verified = subprocess.run(["openssl", "dgst", "-sha256", "-verify", public, "-signature", signature,
                                       message], capture_output=True)
            self.assertEqual(verified.returncode, 0, verified.stdout)


    def test_a_key_the_secret_mangled_still_signs(self):
        with tempfile.TemporaryDirectory() as folder:
            sec1 = os.path.join(folder, "k.pem")
            subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-out", sec1],
                           check=True, capture_output=True)
            pkcs8 = subprocess.run(["openssl", "pkcs8", "-topk8", "-nocrypt", "-in", sec1],
                                   check=True, capture_output=True).stdout.decode()
            with open(sec1) as handle:
                sec1 = handle.read()
            bare = lambda pem: "".join(ln for ln in pem.splitlines() if "-----" not in ln and ln)
            for secret in (sec1.replace("\n", "\\n"), sec1.replace("\n", " "), sec1.replace("\n", "\r\n"),
                           f'"{pkcs8}"', bare(pkcs8), bare(sec1.split("-----END EC PARAMETERS-----")[1])):
                with mock.patch.dict(os.environ, {"CLOUDKIT_PRIVATE_KEY": secret, "CLOUDKIT_KEY_FILE": ""}):
                    path = cloudkit.key_file()
                try:
                    cloudkit.signed("/p", b"{}", "kid", path)
                finally:
                    os.remove(path)

    def test_a_key_openssl_refuses_says_why(self):
        with tempfile.NamedTemporaryFile("w", suffix=".pem") as broken:
            broken.write("not a key\n")
            broken.flush()
            with self.assertRaisesRegex(RuntimeError, "openssl can't sign with the CloudKit key: .+"):
                cloudkit.signed("/p", b"{}", "kid", broken.name)


class Main(unittest.TestCase):
    def test_without_a_key_nothing_is_published(self):
        with mock.patch.dict(os.environ, {"CLOUDKIT_KEY_ID": "", "CLOUDKIT_PRIVATE_KEY": "",
                                          "CLOUDKIT_KEY_FILE": ""}):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(cloudkit.main(["maps.json"]), 0)
            self.assertIn("not published", out.getvalue())

    def test_the_test_catalog_is_not_published(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cloudkit.main(["maps-test.json"]), 0)
        self.assertIn("not the app's catalog", out.getvalue())


if __name__ == "__main__":
    unittest.main()
