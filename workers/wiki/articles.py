#!/usr/bin/env python3
"""How a Wikipedia article gets downloaded and turned into text – the network half.

Loaded as a module:
    articles = load("wiki_articles", "articles.py")
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

# Wikimedia returns 403 without our own User-Agent
UA = ("FricoMaps/1.0 (https://github.com/skifahrer/maptiles; "
      "maps from OSM) python-urllib")

# API batch caps
CONTENT_BATCH = 50
WIKIDATA_BATCH = 50

# measured on sk.wikipedia.org
MS_PER_ARTICLE_BATCHED = 20

# politeness, not a limit
PAUSE_S = 0.2
TRIES = 4
# rather be refused than add to lagging replicas
MAXLAG = 5

# the article file name – the cache reads it too
NDJSON = "articles.ndjson"


def log(msg):
    print(msg, flush=True)


class Api:
    """Calls to api.php and REST – serial, polite and measured."""

    def __init__(self, pause=PAUSE_S):
        self.pause = pause
        self.count = 0
        self.bytes = 0
        self.waited = 0.0

    def get(self, url):
        for attempt in range(1, TRIES + 1):
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Encoding": "identity"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = r.read()
                self.count += 1
                self.bytes += len(body)
                time.sleep(self.pause)
                return body
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 503) and attempt < TRIES:
                    # Wikimedia says how long to wait
                    wait = float(exc.headers.get("Retry-After") or 5 * attempt)
                    log(f"  Wikipedia said HTTP {exc.code}, waiting "
                        f"{wait:.0f} s ({attempt} of {TRIES})")
                    self.waited += wait
                    time.sleep(wait)
                    continue
                if exc.code == 404:
                    return None
                if attempt >= TRIES:
                    raise
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= TRIES:
                    raise
                log(f"  network failed ({exc}), retrying "
                    f"({attempt} of {TRIES})")
                time.sleep(2 * attempt)
        return None

    def json(self, url):
        body = self.get(url)
        return json.loads(body) if body else None


def wikidata_to_titles(api, qids, langs):
    """`Q…` → `{lang: title}` from sitelinks, for every wanted language."""
    out = {}
    qids = sorted(set(qids))
    sites = "|".join(f"{lang}wiki" for lang in langs)
    for i in range(0, len(qids), WIKIDATA_BATCH):
        batch = qids[i:i + WIKIDATA_BATCH]
        # `sitefilter` keeps the answer small
        url = ("https://www.wikidata.org/w/api.php?action=wbgetentities"
               "&props=sitelinks&format=json&formatversion=2"
               f"&sitefilter={urllib.parse.quote(sites)}&ids="
               + "|".join(batch))
        data = api.json(url) or {}
        for qid, ent in (data.get("entities") or {}).items():
            links = ent.get("sitelinks") or {}
            found = {}
            for lang in langs:
                sl = links.get(f"{lang}wiki")
                if sl and sl.get("title"):
                    found[lang] = sl["title"]
            if found:
                out[qid] = found
        log(f"  wikidata {min(i + WIKIDATA_BATCH, len(qids))}/{len(qids)} → "
            f"{len(out)} items with a sitelink")
    return out


def other_langs(api, known, wanted):
    """What an article is called in other languages (`langlinks`).

    `known` is `{lang: [titles]}`; returns `{(source lang, title): {lang: title}}`.
    """
    out = {}
    for lang, titles in sorted(known.items()):
        targets = sorted(wanted - {lang})
        if not targets:
            continue
        titles = sorted(set(titles))
        for i in range(0, len(titles), CONTENT_BATCH):
            batch = titles[i:i + CONTENT_BATCH]
            url = (f"https://{lang}.wikipedia.org/w/api.php?action=query"
                   "&format=json&formatversion=2&redirects=1&prop=langlinks"
                   f"&lllimit=500&lllang={urllib.parse.quote('|'.join(targets))}"
                   "&titles=" + urllib.parse.quote("|".join(batch)))
            data = api.json(url) or {}
            query = data.get("query") or {}
            # the answer is under the redirect target, the tag has the asked name: store both
            where = resolve(query)
            back = {}
            for asked, target in where.items():
                back.setdefault(target, []).append(asked)
            for page in query.get("pages") or []:
                if page.get("missing"):
                    continue
                title = page.get("title")
                links = {ll["lang"]: ll["title"]
                         for ll in page.get("langlinks") or []
                         if ll.get("lang") and ll.get("title")}
                if not links:
                    continue
                for key in [title] + back.get(title, []):
                    out[(lang, key)] = links
        log(f"  links from {lang}: {len([1 for k in out if k[0] == lang])} "
            f"articles know themselves in another language")
    return out


TABLE = re.compile(r"\{\|.*?\|\}", re.S)


def to_text(wikitext):
    """Wikitext → plain text; tables cut BEFORE parsing (`strip_code` leaves them)."""
    try:
        import mwparserfromhell
    except ImportError:
        raise SystemExit(
            "::error::`mwparserfromhell` is missing – it turns wikitext into plain "
            "text. Install it (`pip install mwparserfromhell`, "
            "`workers/wiki/build.sh` does it).")
    prev = None
    while prev != wikitext:            # nested tables, inside out
        prev, wikitext = wikitext, TABLE.sub("", wikitext)
    txt = mwparserfromhell.parse(wikitext).strip_code()
    txt = re.sub(r"(?m)^[|!].*$", "", txt)     # leftover table rows
    txt = re.sub(r"\n{3,}", "\n\n", txt)       # three or more blank lines
    return txt.strip()


def resolve(query):
    """`{title we asked for: title the article is under}`, `normalized` then `redirects`."""
    step = {r["from"]: r["to"] for r in query.get("normalized") or []}
    step.update({r["from"]: r["to"] for r in query.get("redirects") or []})
    out = {}
    for source in step:
        target, seen = source, {source}
        while target in step and step[target] not in seen:
            target = step[target]
            seen.add(target)
        out[source] = target
    return out


def load_cache(path):
    """`{article key: record}` from the last run; a half-written line is skipped."""
    out = {}
    if not path:
        return out
    p = os.path.join(path, NDJSON)
    if not os.path.exists(p):
        return out
    broken = 0
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                z = json.loads(line)
            except ValueError:
                broken += 1
                continue
            if z.get("key") and z.get("text") and z.get("revid"):
                out[z["key"]] = z
    log(f"Cache: {len(out)} articles from the last run"
        + (f" ({broken} half-written lines skipped)" if broken else ""))
    return out


def freshness(api, lang, titles):
    """`{title: (title, lastrevid, url)}` – one cheap `prop=info` question per 50 titles."""
    out = {}
    for i in range(0, len(titles), CONTENT_BATCH):
        batch = titles[i:i + CONTENT_BATCH]
        url = (f"https://{lang}.wikipedia.org/w/api.php?action=query"
               f"&prop=info&inprop=url&redirects=1&maxlag={MAXLAG}"
               f"&format=json&formatversion=2&titles="
               + "|".join(urllib.parse.quote(t) for t in batch))
        data = api.json(url) or {}
        query = data.get("query") or {}
        renamed = resolve(query)
        by_title = {p.get("title"): p for p in query.get("pages") or []}
        for title in batch:
            page = by_title.get(renamed.get(title, title))
            if page and not page.get("missing") and page.get("lastrevid"):
                out[title] = (page["title"], page["lastrevid"],
                              page.get("fullurl") or "")
    return out


def fetch_texts(api, lang, titles, cache=None):
    """One language's articles as plain text: `({OSM title: record}, failed, from cache)`."""
    titles = sorted(set(titles))
    done, reused, info = {}, 0, {}
    # on an empty cache the freshness question is pure overhead
    if cache:
        info = freshness(api, lang, titles)
        left = []
        for title in titles:
            if title not in info:
                left.append(title)          # missing → let the download say so
                continue
            real, revid, url = info[title]
            z = cache.get(f"{lang}:{real}")
            if z and z.get("revid") == revid:
                done[title] = dict(z, title=real, url=url or z["url"])
                reused += 1
            else:
                left.append(title)
        log(f"  {lang}: {reused} articles are cached and unchanged, "
            f"{len(left)} to download")
        titles = left
        if not titles:
            return done, [], reused

    new, failed = _in_batches(api, lang, titles)
    done.update(new)
    return done, failed, reused


def _in_batches(api, lang, titles):
    """Wikitext 50 per request, turned into plain text."""
    batch_max = CONTENT_BATCH
    done, failed = {}, []
    for i in range(0, len(titles), batch_max):
        batch = titles[i:i + batch_max]
        props = "&prop=revisions|info&rvprop=content|ids&rvslots=main"
        url = (f"https://{lang}.wikipedia.org/w/api.php?action=query{props}"
               f"&redirects=1&inprop=url&maxlag={MAXLAG}"
               f"&format=json&formatversion=2&titles="
               + "|".join(urllib.parse.quote(t) for t in batch))
        data = api.json(url) or {}
        if data.get("error"):
            # must not turn into 50 "missing" articles
            raise SystemExit(f"::error::Wikipedia ({lang}) refused a batch of "
                             f"{len(batch)} titles: "
                             f"{data['error'].get('code')} – "
                             f"{data['error'].get('info')}")
        query = data.get("query") or {}
        renamed = resolve(query)
        by_title = {p.get("title"): p for p in query.get("pages") or []}
        for title in batch:
            page = by_title.get(renamed.get(title, title))
            record = _record(lang, title, page)
            if record:
                done[title] = record
            else:
                failed.append(title)
        log(f"  {lang}: {min(i + batch_max, len(titles))}/{len(titles)} articles, "
            f"{api.count} requests")
    return done, failed


def _record(lang, title, page):
    """A record from one answer page, or `None` when it holds nothing."""
    if not page or page.get("missing") is True or page.get("invalid"):
        return None
    try:
        wt = page["revisions"][0]["slots"]["main"]["content"]
    except (KeyError, IndexError):
        return None
    text = to_text(wt)
    if not text:
        return None
    real = page.get("title") or title
    return {"key": f"{lang}:{real}", "lang": lang, "title": real,
            "pageid": page.get("pageid"),
            "revid": (page.get("revisions") or [{}])[0].get("revid"),
            "url": page.get("fullurl") or
                   f"https://{lang}.wikipedia.org/wiki/"
                   + urllib.parse.quote(real.replace(" ", "_")),
            "text": text}
