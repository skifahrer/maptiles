#!/usr/bin/env python3
"""Publish `maps.json` to the app's public CloudKit database, one `CatalogNode` per node."""
import argparse
import base64
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

CONTAINER = "iCloud.com.rikimaps.rikimaps.public"
HOST = "https://api.apple-cloudkit.com"
TYPE = "CatalogNode"
ROOT = "root"
# keys that hold children, in the order the app lists them
CHILDREN = ("regions", "subregions", "ranges", "mountains")
LOOKUP_BATCH = 200
WRITE_OPS = 200
WRITE_BYTES = 1_500_000
# a record's fields stop at 1 MB; a body past this goes up as the asset `bodyFile`
BODY_INLINE = 500_000
RECORD_BYTES = 950_000
TRIES = 3
FEATURES = ("features-beta", "features-prod")
COUNTRY_KEY = "country:"


def log(msg):
    print(msg, flush=True)


class Conflict(Exception):
    """Another run wrote a record since we read it."""


def nodes(catalog):
    """`maps.json` as a flat `{id: node}`, the root included."""
    found = {}

    def add(key, value, parent, order, held_in):
        node_id = value.get("id") or (key if parent == ROOT else f"{parent}-{key}")
        if node_id in found:
            raise ValueError(f"{node_id} is in maps.json twice")
        found[node_id] = None
        kids = []
        for container in CHILDREN:
            for child_key, child in (value.get(container) or {}).items():
                if isinstance(child, dict):
                    kids.append(add(child_key, child, node_id, len(kids), container))
        body = {k: v for k, v in value.items() if k not in CHILDREN}
        downloadable = bool(value.get("maps"))
        kind = "both" if kids and downloadable else "group" if kids else "region"
        found[node_id] = {"id": node_id, "key": key, "in": held_in, "parent": parent, "order": order,
                          "name": value.get("name") or key, "kind": kind, "body": body, "children": kids,
                          "version": int(value.get("updated_ts") or 0)}
        return node_id

    top = []
    for key, value in catalog.items():
        if not key.startswith("_") and isinstance(value, dict):
            top.append(add(key, value, ROOT, len(top), ""))
    meta = {k: v for k, v in catalog.items() if k.startswith("_")}
    found[ROOT] = {"id": ROOT, "key": ROOT, "in": "", "parent": "", "order": 0, "name": "Root", "kind": "group",
                   "body": meta, "children": top, "version": int(catalog.get("_updated_ts") or 0)}
    return found


def summary(node):
    """What a parent lists of a child, without its subtree time."""
    out = {k: node[k] for k in ("id", "key", "in", "name", "kind", "version")}
    if node["body"].get("bbox"):
        out["bbox"] = node["body"]["bbox"]
    return out


def digests(tree):
    """A node's own record, its children's summaries included."""
    out = {}
    for node in tree.values():
        own = {k: node[k] for k in ("parent", "kind", "name", "order", "body", "version")}
        own["children"] = [summary(tree[c]) for c in node["children"]]
        out[node["id"]] = hashlib.sha256(json.dumps(own, sort_keys=True).encode()).hexdigest()
    return out


def post_order(tree):
    out = []

    def walk(node_id):
        for child in tree[node_id]["children"]:
            walk(child)
        out.append(node_id)

    walk(ROOT)
    return out


def plan(tree, published, now, force=False):
    """The records to write, children first, and every node's subtree time."""
    digest = digests(tree)
    subtree, dirty = {}, {}
    for node_id in post_order(tree):
        old = published.get(node_id)
        changed = force or old is None or old.get("digest") != digest[node_id]
        dirty[node_id] = changed or any(dirty[c] for c in tree[node_id]["children"])
        subtree[node_id] = now if dirty[node_id] or old is None else int(old.get("subtreeTs") or now)
    writes = []
    for node_id in post_order(tree):
        if not dirty[node_id]:
            continue
        node = tree[node_id]
        kids = [dict(summary(tree[c]), subtreeTs=subtree[c]) for c in node["children"]]
        body = dict(node["body"], key=node["key"], held_in=node["in"]) if node_id != ROOT else node["body"]
        fields = {"parent": node["parent"], "kind": node["kind"], "name": node["name"], "order": node["order"],
                  "body": json.dumps(body, ensure_ascii=False, sort_keys=True),
                  "children": json.dumps(kids, ensure_ascii=False), "version": node["version"],
                  "subtreeTs": subtree[node_id], "digest": digest[node_id]}
        writes.append((node_id, fields, (published.get(node_id) or {}).get("tag")))
    too_big = [n for n, fields, _ in writes
               if len(json.dumps(dict(fields, body="")).encode()) > RECORD_BYTES]
    if too_big:
        raise ValueError(f"children past CloudKit's 1 MB per record, nothing written: {', '.join(too_big)}")
    return writes, subtree


def with_assets(call, writes):
    """A body too big for the record's fields is uploaded and named by `bodyFile`."""
    out = []
    for node_id, fields, tag in writes:
        body = fields["body"].encode()
        if len(body) > BODY_INLINE:
            fields = dict(fields, body="", bodyFile=call.upload(node_id, body))
        out.append((node_id, fields, tag))
    return out


def signed(subpath, body, key_id, key_file, date=None):
    """Apple's server-to-server signature: ECDSA P-256 over date, body hash and path."""
    date = date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
    signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_file],
                               input=f"{date}:{digest}:{subpath}".encode(),
                               capture_output=True, check=True).stdout
    return {"Content-Type": "application/json", "X-Apple-CloudKit-Request-KeyID": key_id,
            "X-Apple-CloudKit-Request-ISO8601Date": date,
            "X-Apple-CloudKit-Request-SignatureV1": base64.b64encode(signature).decode()}


class Cloud:
    """The public database's records API."""

    def __init__(self, key_id, key_file, environment):
        self.key_id, self.key_file, self.environment = key_id, key_file, environment

    def upload(self, record_name, data):
        """Apple's two steps: a signed request for an upload URL, then the bytes to it."""
        tokens = self("upload", {"tokens": [{"recordName": record_name, "recordType": TYPE,
                                             "fieldName": "bodyFile"}]}, kind="assets")["tokens"]
        request = urllib.request.Request(tokens[0]["url"], data=data,
                                         headers={"Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)["singleFile"]

    def __call__(self, operation, payload, kind="records"):
        subpath = f"/database/1/{CONTAINER}/{self.environment}/public/{kind}/{operation}"
        body = json.dumps(payload).encode()
        request = urllib.request.Request(HOST + subpath, data=body,
                                         headers=signed(subpath, body, self.key_id, self.key_file))
        for attempt in range(TRIES):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                said = error.read().decode()[:500]
                if error.code not in (429, 503) or attempt == TRIES - 1:
                    raise RuntimeError(f"{operation}: HTTP {error.code} {said}") from error
                time.sleep(int(error.headers.get("Retry-After") or 2 ** (attempt + 2)))
        raise RuntimeError(f"{operation}: no answer")


def value(record, field):
    return (record.get("fields", {}).get(field) or {}).get("value")


def lookup(call, names, fields):
    """`{name: record}` of those that exist."""
    found = {}
    for start in range(0, len(names), LOOKUP_BATCH):
        answer = call("lookup", {"records": [{"recordName": n} for n in names[start:start + LOOKUP_BATCH]],
                                 "desiredKeys": list(fields)})
        for record in answer.get("records", []):
            if "serverErrorCode" not in record:
                found[record["recordName"]] = record
            elif record["serverErrorCode"] != "NOT_FOUND":
                raise RuntimeError(f"lookup {record.get('recordName')}: {record['serverErrorCode']}")
    return found


def published_state(call, ids):
    records = lookup(call, ids, ("digest", "subtreeTs", "children"))
    return {name: {"digest": value(r, "digest"), "subtreeTs": value(r, "subtreeTs"),
                   "children": [c["id"] for c in json.loads(value(r, "children") or "[]")],
                   "tag": r.get("recordChangeTag")} for name, r in records.items()}


def gone(call, tree, published):
    """Published nodes maps.json no longer has, with everything below them."""
    pending = [c for node in published.values() for c in node["children"] if c not in tree]
    out = []
    while pending:
        out += pending
        below = lookup(call, pending, ("children",))
        pending = [c["id"] for r in below.values() for c in json.loads(value(r, "children") or "[]")
                   if c["id"] not in tree and c["id"] not in out]
    return out


def batches(operations):
    batch, size = [], 0
    for op in operations:
        weight = len(json.dumps(op))
        if batch and (len(batch) >= WRITE_OPS or size + weight > WRITE_BYTES):
            yield batch
            batch, size = [], 0
        batch.append(op)
        size += weight
    if batch:
        yield batch


def modify(call, operations):
    for batch in batches(operations):
        answer = call("modify", {"operations": batch, "atomic": False})
        for record in answer.get("records", []):
            code = record.get("serverErrorCode")
            if code == "CONFLICT":
                raise Conflict(record.get("recordName"))
            if code and code != "NOT_FOUND":
                raise RuntimeError(f"modify {record.get('recordName')}: {code} {record.get('reason', '')}")


def write_operation(node_id, fields, tag):
    record = {"recordName": node_id, "recordType": TYPE,
              "fields": {k: {"value": v} for k, v in fields.items()}}
    if tag:
        record["recordChangeTag"] = tag
    return {"operationType": "update" if tag else "create", "record": record}


def switch_off(call, countries):
    """A country published for the first time starts on Dev only."""
    if not countries:
        return
    records = lookup(call, list(FEATURES), ("switches",))
    operations = []
    for name in FEATURES:
        record = records.get(name)
        switches = json.loads(value(record, "switches") or "{}") if record else {}
        missing = [c for c in countries if COUNTRY_KEY + c not in switches]
        if not missing:
            continue
        switches.update({COUNTRY_KEY + c: False for c in missing})
        fields = {"switches": {"value": json.dumps(switches, sort_keys=True)}}
        made = {"recordName": name, "recordType": "AppFeatures", "fields": fields}
        if record:
            made["recordChangeTag"] = record.get("recordChangeTag")
        operations.append({"operationType": "update" if record else "create", "record": made})
    modify(call, operations)
    log(f"Switched off for Beta and Prod until checked on Dev: {', '.join(countries)}")


def publish(catalog, call, now=None, force=False, dry_run=False):
    tree = nodes(catalog)
    for attempt in range(TRIES):
        published = published_state(call, list(tree))
        writes, _ = plan(tree, published, now or int(time.time()), force)
        deletes = gone(call, tree, published)
        new_countries = ([c for c in tree[ROOT]["children"] if c not in published[ROOT]["children"]]
                         if ROOT in published else [])
        log(f"CloudKit: {len(writes)} of {len(tree)} nodes to write, {len(deletes)} to delete")
        if dry_run:
            return writes, deletes
        try:
            modify(call, [write_operation(*w) for w in with_assets(call, writes)])
            modify(call, [{"operationType": "forceDelete", "record": {"recordName": n}} for n in deletes])
            switch_off(call, new_countries)
            return writes, deletes
        except Conflict as conflict:
            log(f"{conflict} changed while publishing ({attempt + 1} of {TRIES}) – reading again.")
    raise RuntimeError(f"CloudKit kept changing under {TRIES} tries")


def key_file():
    """The key from the environment, as a file openssl reads."""
    if os.environ.get("CLOUDKIT_KEY_FILE"):
        return os.path.expanduser(os.environ["CLOUDKIT_KEY_FILE"])
    pem = os.environ.get("CLOUDKIT_PRIVATE_KEY", "").strip()
    if not pem:
        return ""
    handle, path = tempfile.mkstemp(suffix=".pem")
    with os.fdopen(handle, "w") as out:
        out.write(pem + "\n")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", nargs="?", default="maps.json")
    parser.add_argument("--force", action="store_true", help="write every node again")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if os.path.basename(args.catalog) != "maps.json":
        log(f"CloudKit: {args.catalog} is not the app's catalog – not published.")
        return 0
    key_id, path = os.environ.get("CLOUDKIT_KEY_ID", "").strip(), key_file()
    if not key_id or not path:
        log("CloudKit: no CLOUDKIT_KEY_ID / CLOUDKIT_PRIVATE_KEY – not published.")
        return 0
    environment = os.environ.get("CLOUDKIT_ENV", "").strip() or "development"
    with open(args.catalog, encoding="utf-8") as handle:
        catalog = json.load(handle)
    publish(catalog, Cloud(key_id, path, environment), force=args.force, dry_run=args.dry_run)
    log(f"CloudKit {environment} has {args.catalog} ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
