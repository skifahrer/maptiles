import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from load import worker

collect = worker("wiki/collect.py")
articles = collect.articles
pbf_areas = worker("plan/pbf-areas.py")


class Opl(unittest.TestCase):
    def test_unescape(self):
        for unescape in (collect.opl_unescape, pbf_areas.unesc):
            with self.subTest(unescape=unescape.__module__):
                self.assertEqual(unescape("Nov%20%Mesto"), "Nov Mesto")
                # a percent-encoded URL survives
                self.assertEqual(unescape("a%25%20b"), "a%20b")
                self.assertEqual(unescape("x%2c%y"), "x,y")

    def test_fields_and_tags(self):
        line = "w42 v3 dV c1 t2020-01-01T00:00:00Z i1 utom Tname=Nov%20%Mesto,landuse=forest Nn1,n2"
        fields = pbf_areas.opl_fields(line)
        self.assertEqual(fields["w"], "42")
        self.assertEqual(pbf_areas.tags(fields["T"]),
                         {"name": "Nov Mesto", "landuse": "forest"})
        self.assertEqual(pbf_areas.tags(""), {})


class WikiValue(unittest.TestCase):
    def test_url(self):
        self.assertEqual(collect.wiki_value("wikipedia", "https://sk.wikipedia.org/wiki/Hrad_Dev%C3%ADn"),
                         ("sk", "Hrad Devín"))

    def test_lang_prefix(self):
        self.assertEqual(collect.wiki_value("wikipedia", "sk:Kriváň"), ("sk", "Kriváň"))

    def test_lang_key(self):
        self.assertEqual(collect.wiki_value("wikipedia:de", "Tatra"), ("de", "Tatra"))

    def test_section_dropped(self):
        self.assertEqual(collect.wiki_value("wikipedia", "sk:Kriváň#Výstup"), ("sk", "Kriváň"))
        self.assertEqual(collect.wiki_value("wikipedia", "https://sk.wikipedia.org/wiki/Krivá%C5%88#V"),
                         ("sk", "Kriváň"))

    def test_bare(self):
        self.assertEqual(collect.wiki_value("wikipedia", "Kriváň"), ("", "Kriváň"))


class Links(unittest.TestCase):
    def test_bare_title_in_every_language(self):
        values, qid = collect.links({"wikipedia": "Kriváň"}, collect.KEYS, ["en", "sk"])
        self.assertEqual(values, {"en": "Kriváň", "sk": "Kriváň"})
        self.assertEqual(qid, "")

    def test_language_wins_over_bare(self):
        tags = {"wikipedia": "sk:Kriváň", "wikipedia:en": "Kriváň (mountain)"}
        values, _ = collect.links(tags, collect.KEYS, ["en", "sk"])
        self.assertEqual(values, {"sk": "Kriváň", "en": "Kriváň (mountain)"})

    def test_wikidata(self):
        self.assertEqual(collect.links({"wikidata": "Q123"}, collect.KEYS, ["en"])[1], "Q123")
        self.assertEqual(collect.links({"wikidata": "Q12x"}, collect.KEYS, ["en"])[1], "")
        self.assertEqual(collect.links({"wikidata": "123"}, collect.KEYS, ["en"])[1], "")


class Articles(unittest.TestCase):
    def test_is_not_text(self):
        for title, expected in (("Súbor:x.jpg", True), ("Kategória:Hory", True),
                                ("File:x.png", True), ("Kriváň", False),
                                ("Vysoké Tatry: história", False)):
            with self.subTest(title=title):
                self.assertEqual(articles.is_not_text(SimpleNamespace(title=title)), expected)

    def test_resolve_normalized_then_redirect(self):
        query = {"normalized": [{"from": "krivan", "to": "Krivan"}],
                 "redirects": [{"from": "Krivan", "to": "Kriváň"}]}
        self.assertEqual(articles.resolve(query), {"krivan": "Kriváň", "Krivan": "Kriváň"})

    def test_resolve_cycle_ends(self):
        query = {"redirects": [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}]}
        self.assertEqual(articles.resolve(query), {"A": "B", "B": "A"})


class FakeApi:
    """Answers `prop=info` from `revids` and `prop=revisions` with a page per title."""

    def __init__(self, revids):
        self.revids = revids
        self.count = 0
        self.asked = []

    def json(self, url):
        self.count += 1
        titles = [t for t in self.revids if t in url]
        kind = "info" if "&prop=info&" in url else "content"
        self.asked.append((kind, sorted(titles)))
        pages = [{"title": t, "pageid": i, "lastrevid": self.revids[t],
                  "fullurl": f"https://sk.wikipedia.org/wiki/{t}",
                  "revisions": [{"revid": self.revids[t],
                                 "slots": {"main": {"content": f"text {t}"}}}]}
                 for i, t in enumerate(titles)]
        return {"query": {"pages": pages}}


class FetchTexts(unittest.TestCase):
    def setUp(self):
        self._to_text = articles.to_text
        articles.to_text = lambda wt: wt

    def tearDown(self):
        articles.to_text = self._to_text

    def fetch(self, api, cache):
        with redirect_stdout(io.StringIO()):
            return articles.fetch_texts(api, "sk", ["Alfa", "Beta"], cache)

    def test_cache_unchanged_and_changed(self):
        cache = {"sk:Alfa": {"key": "sk:Alfa", "revid": 1, "text": "old alfa", "url": "u"},
                 "sk:Beta": {"key": "sk:Beta", "revid": 1, "text": "old beta", "url": "u"}}
        api = FakeApi({"Alfa": 1, "Beta": 2})
        done, failed, reused = self.fetch(api, cache)
        self.assertEqual(reused, 1)
        self.assertEqual(failed, [])
        self.assertEqual(done["Alfa"]["text"], "old alfa")
        self.assertEqual(done["Beta"]["text"], "text Beta")
        self.assertEqual(api.asked, [("info", ["Alfa", "Beta"]), ("content", ["Beta"])])

    def test_empty_cache_skips_freshness(self):
        api = FakeApi({"Alfa": 1, "Beta": 2})
        done, failed, reused = self.fetch(api, {})
        self.assertEqual((sorted(done), failed, reused), (["Alfa", "Beta"], [], 0))
        self.assertEqual([kind for kind, _ in api.asked], ["content"])

    def test_missing_page_fails(self):
        api = FakeApi({"Alfa": 1})
        done, failed, _ = self.fetch(api, {})
        self.assertEqual((sorted(done), failed), (["Alfa"], ["Beta"]))


if __name__ == "__main__":
    unittest.main()
