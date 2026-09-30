#!/usr/bin/env python3
"""
Ako sa článok z Wikipédie stiahne a prevedie na text – celá sieťová polovica.

PREČO ZVLÁŠŤ od `collect.py`. Ten sa pýta „ČO v regióne odkazuje na wiki a ktoré
články to teda sú"; tu je odpoveď na „AKO sa taký článok dostane k nám".
Sú to dve otázky s dvoma úplne inými dôvodmi, prečo sú napísané tak, ako sú:
tam OSM tagy a jazyky, tu dávky po päťdesiatich, `lastrevid`, presmerovania
a prevod wikitextu. Spolu to prerástlo strop 800 riadkov (pravidlo 5
v CLAUDE.md) a v jednom súbore sa už nedalo rýchlo nájsť, čo sa zmenilo.

Načítava sa ako modul, nie z príkazovej riadky:
    articles = load("wiki_articles", "articles.py")
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

# Wikimedia chce vedieť, kto sa pýta – bez vlastného User-Agenta vracia 403.
UA = ("FricoMaps/1.0 (https://github.com/skifahrer/maptiles; "
      "mapy z OSM) python-urllib")

# stropy dávok v API
CONTENT_BATCH = 50
WIKIDATA_BATCH = 50

# namerané na sk.wikipedia.org
MS_PER_ARTICLE_BATCHED = 20

# Pauza medzi požiadavkami a počet pokusov. Nie je to limit, je to slušnosť –
# Wikipédia je zadarmo a nie je naša.
PAUSE_S = 0.2
TRIES = 4
# `maxlag` je zdvorilostný parameter Wikimedie: keď sú repliky pozadu, radšej
# nech nás odmietnu, než aby sme im to zhoršili. Chodí v každom volaní API.
MAXLAG = 5

# Meno súboru s článkami – čítať ho vie aj cache, tak stojí pri sťahovaní.
NDJSON = "articles.ndjson"


def log(msg):
    print(msg, flush=True)


class Api:
    """Volania na api.php a REST – sériovo, so slušnosťou a s meraním."""

    def __init__(self, pause=PAUSE_S):
        self.pause = pause
        self.pocet = 0
        self.bajtov = 0
        self.cakanie = 0.0

    def get(self, url):
        for pokus in range(1, TRIES + 1):
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Encoding": "identity"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    telo = r.read()
                self.pocet += 1
                self.bajtov += len(telo)
                time.sleep(self.pause)
                return telo
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 503) and pokus < TRIES:
                    # Wikimedia povie, koľko čakať – tak sa to počká, a nie
                    # háda. Bez toho by opakovanie útočilo do toho istého.
                    cakaj = float(exc.headers.get("Retry-After") or 5 * pokus)
                    log(f"  Wikipedia povedala HTTP {exc.code}, čakám "
                        f"{cakaj:.0f} s ({pokus}. z {TRIES})")
                    self.cakanie += cakaj
                    time.sleep(cakaj)
                    continue
                if exc.code == 404:
                    return None
                if pokus >= TRIES:
                    raise
            except (urllib.error.URLError, TimeoutError) as exc:
                if pokus >= TRIES:
                    raise
                log(f"  sieť zlyhala ({exc}), skúšam znova "
                    f"({pokus}. z {TRIES})")
                time.sleep(2 * pokus)
        return None

    def json(self, url):
        telo = self.get(url)
        return json.loads(telo) if telo else None


def wikidata_na_nazvy(api, qids, langs):
    """`Q…` → `{jazyk: názov}` podľa sitelinks – VŠETKY žiadané jazyky.

    `sitefilter` drží odpoveď malú: bez neho príde tristo jazykov na položku.
    Predtým sa bral prvý sediaci jazyk a ostatné sa zahodili – objekt, ktorý má
    len `wikidata`, tak dostal jeden článok namiesto angličtiny aj domáceho.
    """
    out = {}
    qids = sorted(set(qids))
    sites = "|".join(f"{lang}wiki" for lang in langs)
    for i in range(0, len(qids), WIKIDATA_BATCH):
        davka = qids[i:i + WIKIDATA_BATCH]
        url = ("https://www.wikidata.org/w/api.php?action=wbgetentities"
               "&props=sitelinks&format=json&formatversion=2"
               f"&sitefilter={urllib.parse.quote(sites)}&ids="
               + "|".join(davka))
        data = api.json(url) or {}
        for qid, ent in (data.get("entities") or {}).items():
            links = ent.get("sitelinks") or {}
            najdene = {}
            for lang in langs:
                sl = links.get(f"{lang}wiki")
                if sl and sl.get("title"):
                    najdene[lang] = sl["title"]
            if najdene:
                out[qid] = najdene
        log(f"  wikidata {min(i + WIKIDATA_BATCH, len(qids))}/{len(qids)} → "
            f"{len(out)} položiek so sitelinkom")
    return out


def doplnkove_langs(api, znama, chcem):
    """Z článku v jednom jazyku zistí, ako sa volá v ostatných (`langlinks`).

    `znama` je `{jazyk: [názvy]}`, `chcem` množina jazykov, ktoré chceme mať.
    Vracia `{(zdrojový jazyk, názov): {jazyk: názov}}`.

    BEZ TOHTO BY DRUHÝ JAZYK NEVZNIKOL. Objekt má v tagoch typicky jeden
    `wikipedia=sk:…`; anglický článok o tom istom mieste existuje, len sa volá
    inak a nikto ho z tagu neuhádne. Je to jedna dávková otázka na tie isté
    články, ktoré aj tak sťahujeme.
    """
    out = {}
    for lang, nazvy in sorted(znama.items()):
        ciele = sorted(chcem - {lang})
        if not ciele:
            continue
        nazvy = sorted(set(nazvy))
        for i in range(0, len(nazvy), CONTENT_BATCH):
            davka = nazvy[i:i + CONTENT_BATCH]
            url = (f"https://{lang}.wikipedia.org/w/api.php?action=query"
                   "&format=json&formatversion=2&redirects=1&prop=langlinks"
                   f"&lllimit=500&lllang={urllib.parse.quote('|'.join(ciele))}"
                   "&titles=" + urllib.parse.quote("|".join(davka)))
            data = api.json(url) or {}
            query = data.get("query") or {}
            # `rozuzli` vracia „čo sme pýtali → kde to leží"; tu potrebujeme
            # oboje. Odpoveď je pod menom CIEĽA presmerovania (`Devín (hrad)`),
            # kým objekt má v tagu meno, ktoré sme PÝTALI (`Devínsky hrad`) –
            # a práve pod tým sa to bude hľadať. Zapíše sa preto pod obe mená;
            # bez toho sa prepojenie našlo a ticho zahodilo, takže anglický
            # článok o hrade sa nikdy nestiahol.
            kam = rozuzli(query)
            spat = {}
            for pytane, ciel in kam.items():
                spat.setdefault(ciel, []).append(pytane)
            for page in query.get("pages") or []:
                if page.get("missing"):
                    continue
                titul = page.get("title")
                pre = {ll["lang"]: ll["title"]
                       for ll in page.get("langlinks") or []
                       if ll.get("lang") and ll.get("title")}
                if not pre:
                    continue
                for kluc in [titul] + spat.get(titul, []):
                    out[(lang, kluc)] = pre
        log(f"  prepojenia z {lang}: {len([1 for k in out if k[0] == lang])} "
            f"článkov vie o sebe v inom jazyku")
    return out


TABULKA = re.compile(r"\{\|.*?\|\}", re.S)


def na_text(wikitext):
    """Wikitext → čistý text. Tabuľky sa odstrihnú PRED parsovaním.

    `mwparserfromhell.strip_code()` tabuľky nerozoberá – nechá ich ako text,
    takže v článku ostanú riadky `| align=center` a `|-`. Namerané na ôsmich
    článkoch sk wiki: bez tohto krokov 102 zvyškov `| param=`, s ním jeden
    jediný (neuzavretá šablóna v jednom článku).

    Čo tým NESTRATÍME: proti hotovému textu z `prop=extracts` má takto
    prevedený článok 92–144 % dĺžky (medián ~106 %) – teda o nič, čo by
    v článku bolo, neprichádzame.
    """
    # hláška s návodom, nie `ModuleNotFoundError` v tretej minúte sťahovania
    try:
        import mwparserfromhell
    except ImportError:
        raise SystemExit(
            "::error::Chýba `mwparserfromhell` – prevádza wikitext na čistý "
            "text. Doinštaluj ho (`pip install mwparserfromhell`, robí to "
            "`workers/wiki/build.sh`).")
    prev = None
    while prev != wikitext:            # vnorené tabuľky, zvnútra von
        prev, wikitext = wikitext, TABULKA.sub("", wikitext)
    txt = mwparserfromhell.parse(wikitext).strip_code()
    txt = re.sub(r"(?m)^[|!].*$", "", txt)     # zvyšky riadkov tabuliek
    txt = re.sub(r"\n{3,}", "\n\n", txt)       # tri a viac prázdnych riadkov
    return txt.strip()


def rozuzli(query):
    """`{názov, ktorý sme si vypýtali: názov, pod ktorým článok leží}`.

    API vracia dve mapy a MÔŽU SA ZARETIAZIŤ: `normalized` opraví prvé veľké
    písmo a podčiarkovníky (`devín_hrad` → `Devín hrad`), `redirects` potom
    presmeruje na cieľ (`Devín` → `Devín (hrad)`). Kto by prešiel len jednu,
    stratí článok, ktorý sa pritom stiahol – text by v balíku bol a index by
    ho k objektu nepriradil.
    """
    krok = {r["from"]: r["to"] for r in query.get("normalized") or []}
    krok.update({r["from"]: r["to"] for r in query.get("redirects") or []})
    out = {}
    for zdroj in krok:
        ciel, videne = zdroj, {zdroj}
        while ciel in krok and krok[ciel] not in videne:
            ciel = krok[ciel]
            videne.add(ciel)
        out[zdroj] = ciel
    return out


def nacitaj_cache(cesta):
    """`{kľúč článku: záznam}` z minulého behu, alebo prázdno.

    NEDOPÍSANÝ RIADOK SA PRESKOČÍ, nie odmietne: cache sa ukladá aj zo behu,
    ktorý niekto zrušil v polovici zápisu, a jeden pokazený riadok na konci
    nesmie znamenať, že sa zahodí aj tých 900 článkov pred ním.
    """
    out = {}
    if not cesta:
        return out
    p = os.path.join(cesta, NDJSON)
    if not os.path.exists(p):
        return out
    zlych = 0
    with open(p, encoding="utf-8") as f:
        for riadok in f:
            try:
                z = json.loads(riadok)
            except ValueError:
                zlych += 1
                continue
            if z.get("key") and z.get("text") and z.get("revid"):
                out[z["key"]] = z
    log(f"Cache: {len(out)} článkov z minulého behu"
        + (f" ({zlych} nedopísaných riadkov preskočených)" if zlych else ""))
    return out


def sviezost(api, lang, nazvy):
    """`{názov: (titul, lastrevid, url)}` – jedna otázka na 50 názvov.

    `prop=info` povie `lastrevid` a rozuzlí presmerovania, takže sa z nej dá
    rozhodnúť, ČO NETREBA sťahovať. Namerané na sk wiki, tých istých 50
    názvov: `prop=info` 19,9 kB, `prop=revisions` s obsahom 197,4 kB – teda
    desatina, a k tomu odpadne prevod wikitextu. `lastrevid` z `info` sedí
    s `revid` obsahu (overené).
    """
    out = {}
    for i in range(0, len(nazvy), CONTENT_BATCH):
        davka = nazvy[i:i + CONTENT_BATCH]
        url = (f"https://{lang}.wikipedia.org/w/api.php?action=query"
               f"&prop=info&inprop=url&redirects=1&maxlag={MAXLAG}"
               f"&format=json&formatversion=2&titles="
               + "|".join(urllib.parse.quote(t) for t in davka))
        data = api.json(url) or {}
        query = data.get("query") or {}
        prezvane = rozuzli(query)
        podla_nazvu = {p.get("title"): p for p in query.get("pages") or []}
        for nazov in davka:
            page = podla_nazvu.get(prezvane.get(nazov, nazov))
            if page and not page.get("missing") and page.get("lastrevid"):
                out[nazov] = (page["title"], page["lastrevid"],
                              page.get("fullurl") or "")
    return out


def stiahni_texty(api, lang, nazvy, cache=None):
    """Články jedného jazyka ako čistý text. Vracia `({názov z OSM: záznam}, chybné, z cache)`."""
    nazvy = sorted(set(nazvy))
    hotove, recyklovane, info = {}, 0, {}
    # na prázdnej cache je otázka na sviežosť čistá režija
    if cache:
        info = sviezost(api, lang, nazvy)
        zostava = []
        for nazov in nazvy:
            if nazov not in info:
                zostava.append(nazov)          # neexistuje → nech to povie sťahovanie
                continue
            titul, revid, url = info[nazov]
            z = cache.get(f"{lang}:{titul}")
            if z and z.get("revid") == revid:
                hotove[nazov] = dict(z, title=titul, url=url or z["url"])
                recyklovane += 1
            else:
                zostava.append(nazov)
        log(f"  {lang}: {recyklovane} článkov je v cache a nezmenilo sa, "
            f"{len(zostava)} treba stiahnuť")
        nazvy = zostava
        if not nazvy:
            return hotove, [], recyklovane

    nove, chybne = _po_davkach(api, lang, nazvy)
    hotove.update(nove)
    return hotove, chybne, recyklovane


def _po_davkach(api, lang, nazvy):
    """Wikitext po 50 na požiadavku, prevedený na čistý text."""
    davka_max = CONTENT_BATCH
    hotove, chybne = {}, []
    for i in range(0, len(nazvy), davka_max):
        davka = nazvy[i:i + davka_max]
        dotaz = "&prop=revisions|info&rvprop=content|ids&rvslots=main"
        url = (f"https://{lang}.wikipedia.org/w/api.php?action=query{dotaz}"
               f"&redirects=1&inprop=url&maxlag={MAXLAG}"
               f"&format=json&formatversion=2&titles="
               + "|".join(urllib.parse.quote(t) for t in davka))
        data = api.json(url) or {}
        if data.get("error"):
            # Dávka po 50 nemá ako naraziť na `toomanyvalues`, ale keby áno
            # (alebo na iný `error`), nesmie z toho byť 50 „neexistujúcich"
            # článkov – to je presne tichý omyl, ktorý sa potom hľadá v mape.
            raise SystemExit(f"::error::Wikipedia ({lang}) odmietla dávku "
                             f"{len(davka)} názvov: "
                             f"{data['error'].get('code')} – "
                             f"{data['error'].get('info')}")
        query = data.get("query") or {}
        prezvane = rozuzli(query)
        podla_nazvu = {p.get("title"): p for p in query.get("pages") or []}
        for nazov in davka:
            page = podla_nazvu.get(prezvane.get(nazov, nazov))
            zaznam = _zaznam(lang, nazov, page)
            if zaznam:
                hotove[nazov] = zaznam
            else:
                chybne.append(nazov)
        log(f"  {lang}: {min(i + davka_max, len(nazvy))}/{len(nazvy)} článkov, "
            f"{api.pocet} požiadaviek")
    return hotove, chybne


def _zaznam(lang, nazov, page):
    """Z jednej stránky odpovede spraví záznam, alebo `None` keď z nej nič nie je."""
    if not page or page.get("missing") is True or page.get("invalid"):
        return None
    try:
        wt = page["revisions"][0]["slots"]["main"]["content"]
    except (KeyError, IndexError):
        return None
    text = na_text(wt)
    if not text:
        return None
    titul = page.get("title") or nazov
    return {"key": f"{lang}:{titul}", "lang": lang, "title": titul,
            "pageid": page.get("pageid"),
            "revid": (page.get("revisions") or [{}])[0].get("revid"),
            "url": page.get("fullurl") or
                   f"https://{lang}.wikipedia.org/wiki/"
                   + urllib.parse.quote(titul.replace(" ", "_")),
            "text": text}

