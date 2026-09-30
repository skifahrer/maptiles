#!/usr/bin/env python3
"""Wikipedia articles for everything in the region that links to a wiki.

    data/region.osm.pbf
      → osmium tags-filter      only objects with a wiki link
      → osmium cat -f opl       type, id and tags of each
      → wikidata sitelinks      `Q…` → article title (50/req)
      → api.php prop=revisions  whole article (50/req)
      → wiki-out/articles.ndjson + wiki-out/index.json

    python3 workers/wiki/collect.py --pbf=data/region.osm.pbf --out=wiki-out
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

# tags about THE object; `brand:`/`operator:` can be added with `--keys`
KEYS = ("wikipedia", "wikidata")

# one file, one article a line – ~32 % smaller zipped than a file per article
NDJSON = "articles.ndjson"

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data")


def languages(country, extra, table):
    """English always, the region's country language, and what the caller asks for."""
    out = ["en"]
    country = (country or "").strip().lower()
    if country:
        try:
            with open(table, encoding="utf-8") as f:
                lookup = json.load(f)
        except (OSError, ValueError) as exc:
            log(f"::warning::{table} can't be read ({exc}) – English only, plus "
                f"the languages objects name themselves.")
            lookup = {}
        local = lookup.get(country)
        if local:
            out += [str(v).strip().lower() for v in local if str(v).strip()]
        else:
            log(f"::warning::Country “{country}” isn't in "
                f"{os.path.basename(table)} – no local language is added. Add "
                f"it there, or ask for it with the `wiki_langs` option.")
    out += [x.strip().lower() for x in (extra or "").split(",") if x.strip()]
    return list(dict.fromkeys(out))


def load(name, path):
    """workers/*.py are loaded with `importlib`, by bare name within the folder."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(os.path.abspath(__file__)), path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def log(msg):
    print(msg, flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def filter_pbf(pbf, dst, keys):
    """`osmium tags-filter` – only objects with a wiki link (OPL of a region is huge)."""
    filters = [f"nwr/{k}" for k in keys]
    run(["osmium", "tags-filter", "--overwrite", "-o", dst, pbf, *filters])
    return dst


def objects(pbf):
    """Objects with tags from OPL – type, id, tags and coordinates (nodes only).

    OPL, not `osmium export`: export drops what it can't assemble, and its article.
    """
    out = run(["osmium", "cat", "-f", "opl", pbf]).stdout
    for line in out.splitlines():
        if not line:
            continue
        kind, body = line[0], line[1:]
        if kind not in "nwr":
            continue
        oid = body.split(" ", 1)[0]
        tags, lat, lon = {}, None, None
        for field in body.split(" "):
            if field.startswith("T") and len(field) > 1:
                for kv in field[1:].split(","):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        tags[opl_unescape(k)] = opl_unescape(v)
            elif field.startswith("x") and len(field) > 1:
                lon = field[1:]
            elif field.startswith("y") and len(field) > 1:
                lat = field[1:]
        if tags:
            yield {"type": {"n": "node", "w": "way", "r": "relation"}[kind],
                   "id": oid, "tags": tags,
                   "lat": float(lat) if lat else None,
                   "lon": float(lon) if lon else None}


def opl_unescape(text):
    """OPL escapes `%<hex code>%`; the closing `%` keeps URL percent-encoding intact."""
    return re.sub(r"%([0-9A-Fa-f]{1,6})%",
                  lambda m: chr(int(m.group(1), 16)), text)


def links(tags, keys, langs):
    """Every `(lang, title)` an object names itself: `({lang: title}, wikidata id)`."""
    values = {}
    for k, v in tags.items():
        if not v.strip():
            continue
        if k == "wikipedia" or k.startswith("wikipedia:"):
            lang, title = wiki_value(k, v)
            if title:
                values.setdefault(lang, title)
    # a link without a language is tried in every wanted language
    bare = values.pop("", "")
    if bare:
        for lang in langs:
            values.setdefault(lang, bare)
    qid = ""
    for k in keys:
        if k.endswith("wikidata") and re.fullmatch(r"Q\d+", tags.get(k, "")):
            qid = tags[k]
            break
    return values, qid


def wiki_value(key, value):
    """`(lang, title)` from one form of the link."""
    value = value.strip()
    # a section link is the same article
    if "#" in value and not value.startswith("http"):
        value = value.split("#", 1)[0].strip()
    if value.startswith("http"):
        # `https://sk.wikipedia.org/wiki/Devín` – the language is in the host
        u = urllib.parse.urlsplit(value)
        lang = u.netloc.split(".")[0]
        title = urllib.parse.unquote(u.path.rsplit("/", 1)[-1]).replace("_", " ")
        return lang, title.split("#", 1)[0].strip()
    if key.startswith("wikipedia:"):
        return key.split(":", 1)[1], value
    if re.match(r"^[a-z]{2,3}(-[a-z0-9-]+)?:", value):
        lang, title = value.split(":", 1)
        return lang, title.strip()
    return "", value


# the network half lives in its own module
articles = load("wiki_articles", "articles.py")
Api = articles.Api
wikidata_to_titles = articles.wikidata_to_titles
other_langs = articles.other_langs
load_cache = articles.load_cache
fetch_texts = articles.fetch_texts
CONTENT_BATCH = articles.CONTENT_BATCH
WIKIDATA_BATCH = articles.WIKIDATA_BATCH
MS_PER_ARTICLE_BATCHED = articles.MS_PER_ARTICLE_BATCHED
PAUSE_S = articles.PAUSE_S

# ---------- 3. beh ----------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pbf", default="data/region.osm.pbf")
    ap.add_argument("--out", default="wiki-out")
    ap.add_argument("--country", default="",
                    help="the region's `country` – gives the LOCAL language; "
                         "English always")
    ap.add_argument("--lang-table", default=os.path.join(_DATA, "wiki-languages.json"),
                    help="lookup country → languages")
    ap.add_argument("--langs", default="",
                    help="language order (the first present is taken)")
    ap.add_argument("--keys", default=",".join(KEYS),
                    help="tags searched for a link")
    ap.add_argument("--max", type=int, default=5000,
                    help="cap on articles (0 = none)")
    ap.add_argument("--cache", default="",
                    help="cache folder (articles.ndjson from the last run); "
                         "empty = no cache")
    ap.add_argument("--stats", default="", help="where to append the measurement (TSV)")
    args = ap.parse_args()

    langs = languages(args.country, args.langs, args.lang_table)
    keys = [x.strip() for x in args.keys.split(",") if x.strip()]
    if not os.path.exists(args.pbf):
        print(f"::error::PBF {args.pbf} doesn't exist – the `wiki` job gets it "
              f"from the plan as the `pbf` artifact.")
        return 1
    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()

    small = filter_pbf(args.pbf, os.path.join(args.out, "wiki.osm.pbf"), keys)
    log(f"Prefilter: {os.path.getsize(args.pbf) / 1e6:.0f} MB → "
        f"{os.path.getsize(small) / 1e6:.1f} MB")

    # object → its article titles in every language it knows
    things, no_link = [], 0
    for o in objects(small):
        titles, qid = links(o["tags"], keys, langs)
        if not titles and not qid:
            no_link += 1
            continue
        things.append({"osm": {"type": o["type"], "id": o["id"],
                               "name": o["tags"].get("name"),
                               "lat": o["lat"], "lon": o["lon"],
                               "qid": qid or None},
                       "titles": titles, "qid": qid})

    qids = sorted({v["qid"] for v in things if v["qid"] and not v["titles"]})
    direct = len({(l, n) for v in things for l, n in v["titles"].items()})
    log("── Plan ────────────────────────────────────────────")
    log(f"  objects with a link  {len(things)}"
        + (f" (+{no_link} with a tag I don't understand)" if no_link else ""))
    log(f"  articles directly    {direct}")
    log(f"  via wikidata         {len(qids)}")
    log(f"  languages            {', '.join(langs)} (English always + the "
        f"country's)")
    total = direct + len(qids) * len(langs)
    estimate = (total * MS_PER_ARTICLE_BATCHED / 1000.0
                + len(qids) / WIKIDATA_BATCH * (PAUSE_S + 0.4))
    log(f"  batch                {CONTENT_BATCH} articles per request, "
        f"so ~{-(-total // CONTENT_BATCH)} requests")
    log(f"  estimate             ~{estimate / 60:.1f} min")
    log("─────────────────────────────────────────────────────")

    api = Api()
    if qids:
        log(f"Looking up articles for {len(qids)} wikidata ids…")
        sitelinks = wikidata_to_titles(api, qids, langs)
        for v in things:
            if v["qid"] and not v["titles"]:
                v["titles"] = dict(sitelinks.get(v["qid"], {}))

    # the other languages via `langlinks` – a tag usually names one
    wanted = set(langs)
    short = {i for i, v in enumerate(things) if set(v["titles"]) < wanted}
    if short:
        known = {}
        for v in things:
            for lang, title in v["titles"].items():
                known.setdefault(lang, []).append(title)
        log(f"Adding languages {', '.join(sorted(wanted))} for {len(short)} "
            f"objects via article links…")
        linked = other_langs(api, known, wanted)
        for v in things:
            for lang, title in list(v["titles"].items()):
                for target, foreign in (linked.get((lang, title)) or {}).items():
                    if target in wanted:
                        v["titles"].setdefault(target, foreign)

    where = {}
    for v in things:
        for lang, title in v["titles"].items():
            where.setdefault((lang, title), []).append(v["osm"])
    if not where:
        log("::warning::No object has an article in any wanted language – "
            "the package would be empty.")

    if args.max and len(where) > args.max:
        log(f"::warning::There are {len(where)} articles, the cap is {args.max} – "
            f"taking the first {args.max} (by how many objects point at them). "
            f"Raise `wiki_max` if there should be more.")
        order = sorted(where, key=lambda k: (-len(where[k]), k))[:args.max]
        where = {k: where[k] for k in order}

    by_lang = {}
    for lang, title in where:
        by_lang.setdefault(lang, []).append(title)

    # gathered by `key`, since redirects lead several titles to one article
    cache = load_cache(args.cache) if args.cache else None
    arts, osm_index, all_failed, from_cache = {}, {}, [], 0
    for lang in sorted(by_lang):
        log(f"Downloading {len(by_lang[lang])} articles ({lang})…")
        done, failed, reused = fetch_texts(api, lang, by_lang[lang], cache)
        from_cache += reused
        for title in by_lang[lang]:
            pointing = where[(lang, title)]
            z = done.get(title)
            if not z:
                all_failed.append({"title": title, "lang": lang,
                                   "osm": pointing})
                continue
            arts.setdefault(z["key"], z).setdefault("asked", [])
            if title != z["title"]:
                arts[z["key"]]["asked"].append(title)
            for o in pointing:
                # one article per language, so keys are per language
                entry = osm_index.setdefault(f"{o['type']}/{o['id']}", {
                    "keys": {}, "name": o["name"],
                    "lat": o["lat"], "lon": o["lon"], "qid": o["qid"]})
                entry["keys"][lang] = z["key"]

    os.remove(small)
    chars, index = 0, []
    # written as it goes – 5000 articles are ~100 MB of text
    nd = os.path.join(args.out, NDJSON)
    with open(nd, "w", encoding="utf-8") as f:
        for key in sorted(arts):
            z = dict(arts[key])
            z["asked"] = sorted(set(z.get("asked") or []))
            z["chars"] = len(z["text"])
            chars += z["chars"]
            # offset and length let a reader `seek` to the article
            offset = f.tell()
            line = json.dumps(z, ensure_ascii=False) + "\n"
            f.write(line)
            index.append({"key": key, "lang": z["lang"], "title": z["title"],
                          "url": z["url"], "chars": z["chars"],
                          "offset": offset, "len": len(line.encode())})

    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"_comment": f"What is in {NDJSON} and which article belongs to "
                               f"which OSM object. Made by workers/wiki/collect.py.",
                   "file": NDJSON, "langs": langs, "format": "text",
                   "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime()),
                   "counts": {"articles": len(index), "osm": len(osm_index),
                              "failed": len(all_failed)},
                   # where each article lies, not its text
                   "articles": index,
                   # `<type>/<id>` → article: tap an object, get its article key
                   "osm": dict(sorted(osm_index.items())),
                   "failed": sorted(all_failed,
                                    key=lambda c: (c["lang"], c["title"]))},
                  f, ensure_ascii=False, indent=1)

    # the cache is the same content, saved even unchanged so the new key exists
    if args.cache:
        os.makedirs(args.cache, exist_ok=True)
        copy = os.path.join(args.cache, NDJSON)
        if os.path.abspath(copy) != os.path.abspath(nd):
            shutil.copyfile(nd, copy)

    took = time.time() - t0
    nd_mb = os.path.getsize(nd) / 1e6
    log(f"Done: {len(index)} articles ({chars / 1e6:.1f} M characters, "
        f"{NDJSON} is {nd_mb:.1f} MB) in {took / 60:.1f} min, "
        f"{api.count} requests to Wikipedia ({api.bytes / 1e6:.1f} MB"
        + (f", waited for the limit {api.waited:.0f} s" if api.waited else "")
        + f"); the estimate was ~{estimate / 60:.1f} min")
    log(f"  {len(osm_index)} OSM objects have an article, "
        f"{api.count and len(index) / api.count:.0f} articles per request")
    if cache is not None:
        # tells "the cache works" from "the key doesn't match"
        log(f"  {from_cache} of {len(index)} articles from cache "
            f"({100 * from_cache / max(1, len(index)):.0f} %), "
            f"{len(index) - from_cache} downloaded")
    if all_failed:
        # not a run failure, but it must be said
        log(f"::warning::{len(all_failed)} links have no article "
            f"(e.g. {', '.join(c['title'] for c in all_failed[:5])}) – "
            f"they are in index.json under `failed`, with the objects pointing at them.")
    if args.stats:
        with open(args.stats, "a") as f:
            f.write(f"60\tWikipedia articles\t{int(took)}\t"
                    f"{len(index)} articles, {nd_mb:.1f} MB, "
                    f"{api.count} requests, "
                    f"{from_cache} from cache, "
                    f"{len(all_failed)} without an article\n")
    if not index:
        log("::warning::No article – no object in the region links to a wiki, "
            "or nothing was downloaded. The package isn't published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
