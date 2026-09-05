#!/usr/bin/env python3
"""Články z Wikipédie ku všetkému, čo v regióne odkazuje na wiki.

Z regionálneho PBF vyberie objekty s odkazom na Wikipédiu alebo Wikidata,
poskladá z nich zoznam článkov a stiahne ich po päťdesiatich na požiadavku do
jedného súboru. Balík z toho robí `deploy/publish-map.py`.

    data/region.osm.pbf
      → osmium tags-filter      len objekty s wiki odkazom
      → osmium cat -f opl       typ, id a tagy každého takého objektu
      → wikidata sitelinks      `Q…` → názov článku (50/req)
      → api.php prop=revisions  celý článok (50/req)
      → wiki-out/articles.ndjson + wiki-out/index.json

Jeden NDJSON, nie súbor na článok – tak to robia aj dumpy Wikimedia
Enterprise. Namerané na 153 článkoch: 149,1 kB proti 101,3 kB v ZIPe, teda
o 32 % menej. ZIP má na každý záznam ~320 B hlavičky a deflate si na každom
súbore začína slovník odznova.

Odkaz má viac podôb a všetky sú v dátach: `wikipedia=sk:Devín (hrad)`,
`wikipedia:sk=…`, celé URL, alebo `wikidata=Q…` cez sitelinks.
`brand:wikipedia` a `operator:wikipedia` sa zámerne neberú – to nie je článok
o tom mieste, ale o firme (podá sa cez `--keys`).

`index.json` hovorí, ktorý článok patrí ktorému OSM objektu – bez neho je to
hromada textov, ktorú sa nemá na čo napojiť. Nestiahnuté články sú v ňom ako
`chybne`, nie zamlčané.

Požiadavky idú sériovo (API:Etiquette), s krátkou pauzou, `User-Agent`,
`maxlag`, a pri 429/503 sa čaká `Retry-After`.

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
import urllib.error
import urllib.parse
import urllib.request

# Kto sme – Wikimedia to vyžaduje a bez toho vracia 403. Odkaz na repozitár je
# tam zámerne: keď niečo robíme zle, je z logu vidieť, komu to napísať.
UA = ("FricoMaps/1.0 (https://github.com/skifahrer/maptiles; "
      "mapy z OSM a DMR 5.0) python-urllib")

# Kľúče, v ktorých hľadáme odkaz. Sú to tie, čo hovoria o TOM objekte –
# `brand:`/`operator:`/`subject:` sa dajú pridať cez `--keys`.
KEYS = ("wikipedia", "wikidata")

# Všetky články v jednom súbore, riadok = článok. Meno drží `index.json`
# v poli `file`, takže kto to číta, nemusí ho poznať dopredu.
NDJSON = "articles.ndjson"

# PLNÝ TEXT SA DÁVKOVAŤ DÁ, ale NIE cez `prop=extracts`. To je celý dôvod,
# prečo sa články berú z `prop=revisions` a prevádzajú sa tu, a nie hotové
# z TextExtracts. Namerané na `sk.wikipedia.org`, 10 názvov v jednej
# požiadavke:
#
#   prop=extracts&explaintext=1&exlimit=20     1 z 10 článkov, a k tomu
#       warning „exlimit was too large for a whole article extracts request,
#       lowered to 1" – ostatných deväť vyzerá ako neexistujúce
#   prop=revisions&rvprop=content&rvslots=main   10 z 10, jedna požiadavka
#
# Strop je 50 názvov na požiadavku (`lowlimit`; s botským právom 500) a nad
# ním API vráti CHYBU `toomanyvalues`, nie ticho zrezanú dávku – takže sa
# nemá ako stať, že by dávka po 60 vrátila 50 a o desiatich mlčala.
CONTENT_BATCH = 50
# `exintro` je jediná podoba extracts, ktorú API dávkuje, a strop je 20.
INTRO_BATCH = 20
WIKIDATA_BATCH = 50

# Namerané (`--format=text`, sk wiki): 153 článkov v 4 požiadavkách za 2,7 s,
# teda 18 ms na článok. Po jednom to bolo 484 ms na článok – 27× viac.
MS_PER_ARTICLE_BATCHED = 20
MS_PER_ARTICLE_SINGLE = 500

# Medzi požiadavkami sa krátko počká. Nie je to strop od Wikimedie, je to
# slušnosť: celý kraj je pri dávkach po 50 rádovo desiatky požiadaviek.
PAUSE_S = 0.2
TRIES = 4
# Nerob to na servery, ktoré práve nestíhajú replikáciu (API:Etiquette).
# Wikimedia na to odpovie 503 s `Retry-After`, čo `Api.get` počká.
MAXLAG = 5


# Číselníky ležia v susednom priečinku (`workers/data`). Priečinok = job,
# súbor = krok, takže hĺbka je vždy jedna úroveň.
_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data")


def jazyky(country, extra, table):
    """Ktoré jazyky sťahovať: angličtina, jazyk krajiny a čo si žiada volajúci.

    ANGLIČTINA VŽDY, lebo je to jediný jazyk, v ktorom je článok skoro o
    všetkom, a mapu s ním možno dať do ruky komukoľvek. K nej JAZYK KRAJINY,
    v ktorej bod leží – to je to, čo číta domáci.

    Krajina sa berie z REGIÓNU, nie z bodu: extrakt kraja je rezaný jeho
    hranicou, takže bod v ňom v tej krajine naozaj leží. Presnejšie by to bolo
    len reverzným geokódovaním hraníc, čo je celá ďalšia pipeline kvôli pár
    bodom pri hranici – a tie sa aj tak chytia inak: jazyk, ktorý si objekt
    píše sám v tagu (`wikipedia=pl:Rysy`), sa sťahuje tiež (viď `odkazy`).
    """
    out = ["en"]
    country = (country or "").strip().lower()
    if country:
        try:
            with open(table, encoding="utf-8") as f:
                tabulka = json.load(f)
        except (OSError, ValueError) as exc:
            log(f"::warning::{table} sa nedá prečítať ({exc}) – ide sa len po "
                f"anglicky a v jazykoch, ktoré si objekty píšu samy.")
            tabulka = {}
        domace = tabulka.get(country)
        if domace:
            out += [str(v).strip().lower() for v in domace if str(v).strip()]
        else:
            log(f"::warning::Krajina „{country}“ nie je vo "
                f"{os.path.basename(table)} – domáci jazyk sa nedoplní. Dopíš "
                f"ju tam, alebo si ho vypýtaj cez voľbu `wiki_langs`.")
    out += [x.strip().lower() for x in (extra or "").split(",") if x.strip()]
    return list(dict.fromkeys(out))


def load(name, path):
    """workers/*.py sa načítavajú cez `importlib` – v priečinku holým menom."""
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


# ---------- 1. čo v regióne odkazuje na wiki ----------

def filter_pbf(pbf, dst, keys):
    """`osmium tags-filter` – z celého regiónu len objekty s wiki odkazom.

    Predfilter je tu na cenu: OPL celého regiónu je stovky megabajtov textu,
    kým odfiltrovaný PBF má rádovo megabajt a ďalšie kroky sú potom sekundy.
    """
    vyrazy = [f"nwr/{k}" for k in keys]
    run(["osmium", "tags-filter", "--overwrite", "-o", dst, pbf, *vyrazy])
    return dst


def objekty(pbf):
    """Objekty s tagmi z OPL – typ, id, tagy a súradnice (pri bodoch).

    OPL, nie `osmium export`: export skladá geometriu a objekt, ktorému ju
    nezloží (relácia bez úplných členov), ZAHODÍ – prišli by sme o článok,
    ktorý v dátach je. OPL je textový výpis KAŽDÉHO objektu; súradnice v ňom
    majú len body, čo je pri článku vedľajšie (poloha je bonus, nie dôvod).
    """
    out = run(["osmium", "cat", "-f", "opl", pbf]).stdout
    for line in out.splitlines():
        if not line:
            continue
        typ, telo = line[0], line[1:]
        if typ not in "nwr":
            continue
        oid = telo.split(" ", 1)[0]
        tags, lat, lon = {}, None, None
        for pole in telo.split(" "):
            if pole.startswith("T") and len(pole) > 1:
                for kv in pole[1:].split(","):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        # OPL escapuje `%XX`; bez odkódovania by v názve
                        # článku ostalo `%20` a stiahlo by sa nič.
                        tags[opl_unescape(k)] = opl_unescape(v)
            elif pole.startswith("x") and len(pole) > 1:
                lon = pole[1:]
            elif pole.startswith("y") and len(pole) > 1:
                lat = pole[1:]
        if tags:
            yield {"typ": {"n": "node", "w": "way", "r": "relation"}[typ],
                   "id": oid, "tags": tags,
                   "lat": float(lat) if lat else None,
                   "lon": float(lon) if lon else None}


def opl_unescape(text):
    """OPL escapuje `%<kód znaku v hexa>%` – teda `%20%` je medzera.

    Uzatvárajúce `%` je POVINNÉ a je to podstatné: bez neho by tento prepis
    zjedol aj percentá z URL (`…/wiki/Dev%C3%ADn` je percentové kódovanie
    UTF-8 bajtov, nie OPL) a z názvu článku by ostala kaša. URL rozkóduje
    `urllib.parse.unquote` na svojom mieste.
    """
    return re.sub(r"%([0-9A-Fa-f]{1,6})%",
                  lambda m: chr(int(m.group(1), 16)), text)


def odkazy(tags, keys, langs):
    """Z tagov objektu vytiahne VŠETKY `(jazyk, názov)`, ktoré si píše sám.

    Vracia `({jazyk: názov}, wikidata_id)`. Jazyk v tagu je zároveň odpoveďou
    na „v akej krajine ten bod leží": `wikipedia=pl:Rysy` na poľskej strane
    hrebeňa dá poľský článok bez toho, aby o Poľsku niekto musel vedieť
    vopred. Zvyšné jazyky (angličtinu a jazyk krajiny) dopĺňa `doplnkove_langs`
    cez `langlinks` – z jedného článku sa dá zistiť, ako sa volá v ostatných.

    Predtým sa bral PRVÝ jazyk, ktorý sedel, a ostatné sa zahodili: objekt
    s `wikipedia=sk:…` tak nikdy nedostal anglický článok, hoci existuje.
    """
    hodnoty = {}
    for k, v in tags.items():
        if not v.strip():
            continue
        if k == "wikipedia" or k.startswith("wikipedia:"):
            lang, nazov = wiki_hodnota(k, v)
            if nazov:
                hodnoty.setdefault(lang, nazov)
    # Odkaz bez jazyka (`wikipedia=Devín`) je v OSM chyba a jazyk z neho nikto
    # nevyčíta. Skúsi sa vo VŠETKÝCH žiadaných jazykoch naraz – stojí to len
    # ďalší názov v dávke, ktorá aj tak ide, a inak by objekt vypadol celý.
    holy = hodnoty.pop("", "")
    if holy:
        for lang in langs:
            hodnoty.setdefault(lang, holy)
    qid = ""
    for k in keys:
        if k.endswith("wikidata") and re.fullmatch(r"Q\d+", tags.get(k, "")):
            qid = tags[k]
            break
    return hodnoty, qid


def wiki_hodnota(key, value):
    """`(jazyk, názov)` z jednej podoby odkazu."""
    value = value.strip()
    # Odkaz na ODDIEL je odkaz na ten istý článok: `sk:Devín (hrad)#Historia`.
    # Bez odrezania kotvy by sa článok hľadal pod menom s `#` a API by ho
    # vyhlásilo za neexistujúci – tichá strata článku, ktorý v dátach je.
    if "#" in value and not value.startswith("http"):
        value = value.split("#", 1)[0].strip()
    if value.startswith("http"):
        # `https://sk.wikipedia.org/wiki/Devín` – jazyk je v hostname.
        u = urllib.parse.urlsplit(value)
        lang = u.netloc.split(".")[0]
        nazov = urllib.parse.unquote(u.path.rsplit("/", 1)[-1]).replace("_", " ")
        # `#Historia` je v URL vo fragmente, ten `urlsplit` oddelí sám; kotva
        # napísaná do cesty ostane, tak ju odrežeme aj tu.
        return lang, nazov.split("#", 1)[0].strip()
    if key.startswith("wikipedia:"):
        return key.split(":", 1)[1], value
    if re.match(r"^[a-z]{2,3}(-[a-z0-9-]+)?:", value):
        lang, nazov = value.split(":", 1)
        return lang, nazov.strip()
    # `wikipedia=Devín` bez jazyka: taký odkaz je nejednoznačný, tak sa berie
    # ako prvý požadovaný jazyk – to je jediné, čo o ňom vieme.
    return "", value


# ---------- 2. sieť ----------
# Sťahovanie a prevod článkov je vo vlastnom module: je to iná otázka („ako sa
# článok dostane k nám") než zvyšok tohto súboru („čo v regióne odkazuje na
# wiki") a spolu to prerástlo strop 800 riadkov.
articles = load("wiki_articles", "articles.py")
Api = articles.Api
wikidata_na_nazvy = articles.wikidata_na_nazvy
doplnkove_langs = articles.doplnkove_langs
nacitaj_cache = articles.nacitaj_cache
stiahni_texty = articles.stiahni_texty
CONTENT_BATCH = articles.CONTENT_BATCH
INTRO_BATCH = articles.INTRO_BATCH
WIKIDATA_BATCH = articles.WIKIDATA_BATCH
MS_PER_ARTICLE_BATCHED = articles.MS_PER_ARTICLE_BATCHED
MS_PER_ARTICLE_SINGLE = articles.MS_PER_ARTICLE_SINGLE
PAUSE_S = articles.PAUSE_S

# ---------- 3. beh ----------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pbf", default="data/region.osm.pbf")
    ap.add_argument("--out", default="wiki-out")
    ap.add_argument("--country", default="",
                    help="`country` regiónu (slovensko) – z neho je DOMÁCI "
                         "jazyk; angličtina ide vždy")
    ap.add_argument("--lang-table", default=os.path.join(_DATA, "wiki-languages.json"),
                    help="číselník krajina → jazyky")
    ap.add_argument("--langs", default="",
                    help="poradie jazykov (prvý, ktorý je, sa berie)")
    ap.add_argument("--keys", default=",".join(KEYS),
                    help="tagy, v ktorých sa hľadá odkaz")
    ap.add_argument("--format", default="text",
                    choices=("text", "wikitext", "intro", "html"),
                    help="`text` celý článok ako čistý text, `wikitext` bez "
                         "prevodu, `intro` len úvod, `html` z REST (po jednom)")
    ap.add_argument("--max", type=int, default=5000,
                    help="strop počtu článkov (0 = bez stropu)")
    ap.add_argument("--cache", default="",
                    help="priečinok cache (articles.ndjson z minulého behu); "
                         "prázdne = necachovať")
    ap.add_argument("--stats", default="", help="kam dopísať meranie (TSV)")
    args = ap.parse_args()

    langs = jazyky(args.country, args.langs, args.lang_table)
    keys = [x.strip() for x in args.keys.split(",") if x.strip()]
    if not os.path.exists(args.pbf):
        print(f"::error::PBF {args.pbf} neexistuje – job `wiki` ho dostáva "
              f"z prípravy ako artefakt `pbf`.")
        return 1
    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()

    maly = filter_pbf(args.pbf, os.path.join(args.out, "wiki.osm.pbf"), keys)
    log(f"Predfilter: {os.path.getsize(args.pbf) / 1e6:.0f} MB → "
        f"{os.path.getsize(maly) / 1e6:.1f} MB")

    # Objekt → názvy jeho článku vo VŠETKÝCH jazykoch, ktoré o sebe vie.
    # Jeden článok má často viac objektov (hrad ako bod aj ako plocha)
    # a sťahovať ho dvakrát netreba, tak sa to nakoniec otočí na
    # `(jazyk, názov) → objekty`.
    veci, bez_odkazu = [], 0
    for o in objekty(maly):
        tituly, qid = odkazy(o["tags"], keys, langs)
        if not tituly and not qid:
            bez_odkazu += 1
            continue
        veci.append({"osm": {"typ": o["typ"], "id": o["id"],
                             "name": o["tags"].get("name"),
                             "lat": o["lat"], "lon": o["lon"]},
                     "titles": tituly, "qid": qid})

    qids = sorted({v["qid"] for v in veci if v["qid"] and not v["titles"]})
    clankov = len({(l, n) for v in veci for l, n in v["titles"].items()})
    log("── Plán ────────────────────────────────────────────")
    log(f"  objektov s odkazom   {len(veci)}"
        + (f" (+{bez_odkazu} s tagom, ktorému nerozumiem)" if bez_odkazu else ""))
    log(f"  článkov priamo       {clankov}")
    log(f"  cez wikidata         {len(qids)}")
    log(f"  jazyky               {', '.join(langs)} (angličtina vždy + jazyk "
        f"krajiny), formát {args.format}")
    # Odhad z NAMERANÉHO: dávkové podoby ~20 ms na článok, `html` ~500 ms
    # (pauza medzi požiadavkami je v oboch číslach). Nech je z plánu dopredu
    # vidieť, či to budú sekundy alebo hodina – job, ktorý spadne na strop
    # času, minie rozpočet a nevyrobí nič.
    # Článkov je pri dvoch jazykoch rádovo dvakrát toľko než objektov – odhad
    # musí rátať s tým, čo sa naozaj stiahne, nie s počtom bodov.
    spolu = clankov + len(qids) * len(langs)
    na_clanok = (MS_PER_ARTICLE_SINGLE if args.format == "html"
                 else MS_PER_ARTICLE_BATCHED)
    odhad = (spolu * na_clanok / 1000.0
             + len(qids) / WIKIDATA_BATCH * (PAUSE_S + 0.4))
    davka = 1 if args.format == "html" else (
        INTRO_BATCH if args.format == "intro" else CONTENT_BATCH)
    log(f"  dávka                {davka} článkov na požiadavku, "
        f"teda ~{-(-spolu // davka)} požiadaviek")
    log(f"  odhad                ~{odhad / 60:.1f} min")
    if args.format == "html":
        log("  ::warning::`html` sa dávkovať nedá (REST vydá jednu stránku "
            "na volanie) – pri stovkách článkov je to desiatky minút. "
            "`text` je z tých istých článkov a ide po päťdesiatich.")
    log("─────────────────────────────────────────────────────")

    api = Api()
    if qids:
        log(f"Dohľadávam články pre {len(qids)} wikidata id…")
        sitelinks = wikidata_na_nazvy(api, qids, langs)
        for v in veci:
            if v["qid"] and not v["titles"]:
                v["titles"] = dict(sitelinks.get(v["qid"], {}))

    # Doplnenie zvyšných jazykov cez `langlinks`: objekt má v tagoch typicky
    # jeden `wikipedia=sk:…` a anglický článok o tom istom mieste sa volá inak.
    chcem = set(langs)
    chyba = {v_id for v_id, v in enumerate(veci) if set(v["titles"]) < chcem}
    if chyba:
        znama = {}
        for v in veci:
            for lang, nazov in v["titles"].items():
                znama.setdefault(lang, []).append(nazov)
        log(f"Dopĺňam jazyky {', '.join(sorted(chcem))} pre {len(chyba)} "
            f"objektov cez prepojenia článkov…")
        prepoj = doplnkove_langs(api, znama, chcem)
        for v in veci:
            for lang, nazov in list(v["titles"].items()):
                for cielovy, cudzi in (prepoj.get((lang, nazov)) or {}).items():
                    if cielovy in chcem:
                        v["titles"].setdefault(cielovy, cudzi)

    kde = {}
    for v in veci:
        for lang, nazov in v["titles"].items():
            kde.setdefault((lang, nazov), []).append(v["osm"])
    if not kde:
        log("::warning::Ani jeden objekt nemá článok v žiadnom zo žiadaných "
            "jazykov – balík by bol prázdny.")

    if args.max and len(kde) > args.max:
        log(f"::warning::Článkov je {len(kde)}, strop je {args.max} – beriem "
            f"prvých {args.max} (podľa počtu objektov, ktoré na ne ukazujú). "
            f"Zdvihni `wiki_max`, ak ich má byť viac.")
        poradie = sorted(kde, key=lambda k: (-len(kde[k]), k))[:args.max]
        kde = {k: kde[k] for k in poradie}

    podla_jazyka = {}
    for lang, nazov in kde:
        podla_jazyka.setdefault(lang, []).append(nazov)

    # Jeden článok má často viac OSM objektov (hrad ako bod aj ako plocha)
    # a viac názvov, ktoré na ten istý článok vedú cez presmerovanie. Preto sa
    # zbiera podľa `key` (`sk:Devín (hrad)`), nie podľa toho, čo bolo v tagu.
    cache = nacitaj_cache(args.cache) if args.cache else None
    clanky, kde_je, chybne_vsetky, z_cache = {}, {}, [], 0
    for lang in sorted(podla_jazyka):
        log(f"Sťahujem {len(podla_jazyka[lang])} článkov ({lang})…")
        hotove, chybne, recyklovane = stiahni_texty(
            api, lang, podla_jazyka[lang], args.format, cache)
        z_cache += recyklovane
        for nazov in podla_jazyka[lang]:
            objekty_odkazu = kde[(lang, nazov)]
            z = hotove.get(nazov)
            if not z:
                chybne_vsetky.append({"title": nazov, "lang": lang,
                                      "osm": objekty_odkazu})
                continue
            clanky.setdefault(z["key"], z).setdefault("asked", [])
            if nazov != z["title"]:
                clanky[z["key"]]["asked"].append(nazov)
            for o in objekty_odkazu:
                # JEDEN OBJEKT MÁ TERAZ VIAC ČLÁNKOV – po jednom na jazyk.
                # Kým tu stálo priradenie, prepísal posledný jazyk všetky
                # predošlé (`sorted` ide en → sk, takže z anglického článku
                # nezostalo v indexe nič, hoci sa stiahol). Kľúče sú preto
                # v mape podľa jazyka.
                zaznam = kde_je.setdefault(f"{o['typ']}/{o['id']}", {
                    "keys": {}, "name": o["name"],
                    "lat": o["lat"], "lon": o["lon"]})
                zaznam["keys"][lang] = z["key"]

    os.remove(maly)
    znakov, index = 0, []
    # NDJSON: riadok = článok. Píše sa priebežne, nie z jedného veľkého
    # reťazca v pamäti – 5000 článkov je rádovo 100 MB textu.
    nd = os.path.join(args.out, NDJSON)
    with open(nd, "w", encoding="utf-8") as f:
        for kluc in sorted(clanky):
            z = dict(clanky[kluc])
            z["asked"] = sorted(set(z.get("asked") or []))
            z["chars"] = len(z["text"])
            znakov += z["chars"]
            # Odsadenie (`offset`) a dĺžka riadka: kto si NDJSON rozbalí, vie
            # skočiť na článok cez `seek` a nemusí prejsť celý súbor.
            offset = f.tell()
            riadok = json.dumps(z, ensure_ascii=False) + "\n"
            f.write(riadok)
            index.append({"key": kluc, "lang": z["lang"], "title": z["title"],
                          "url": z["url"], "chars": z["chars"],
                          "offset": offset, "len": len(riadok.encode())})

    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"_comment": f"Čo je v {NDJSON} a ktorý článok patrí ktorému "
                               f"OSM objektu. Vyrába workers/wiki/collect.py.",
                   "file": NDJSON, "langs": langs, "format": args.format,
                   "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime()),
                   "counts": {"articles": len(index), "osm": len(kde_je),
                              "chybne": len(chybne_vsetky)},
                   # Text článku je v NDJSON a NIE TU (pravidlo 1: jedna
                   # odpoveď na jednom miesto). Tu je len to, čo treba na
                   # nájdenie – kľúč, kde v súbore leží a koľko má.
                   "articles": index,
                   # `<typ>/<id>` → článok. Toto je to, čo mapa potrebuje:
                   # klikneš na objekt, dostaneš kľúč článku.
                   "osm": dict(sorted(kde_je.items())),
                   "chybne": sorted(chybne_vsetky,
                                    key=lambda c: (c["lang"], c["title"]))},
                  f, ensure_ascii=False, indent=1)

    # Kópia pre cache. Je to TEN ISTÝ obsah ako výsledok, a preto sa nemá ako
    # rozísť s tým, čo je v balíku: ďalší beh toho istého regiónu dostane
    # presne tie články, ktoré tu vznikli. Ukladá sa aj vtedy, keď sa nič
    # nezmenilo – inak by záznam pod novým kľúčom (číslo behu) nevznikol
    # a predpona by starla, kým ju `--prune` nezmaže.
    if args.cache:
        os.makedirs(args.cache, exist_ok=True)
        kopia = os.path.join(args.cache, NDJSON)
        if os.path.abspath(kopia) != os.path.abspath(nd):
            shutil.copyfile(nd, kopia)

    took = time.time() - t0
    nd_mb = os.path.getsize(nd) / 1e6
    log(f"Hotovo: {len(index)} článkov ({znakov / 1e6:.1f} M znakov, "
        f"{NDJSON} má {nd_mb:.1f} MB) za {took / 60:.1f} min, "
        f"{api.pocet} požiadaviek na Wikipédiu ({api.bajtov / 1e6:.1f} MB"
        + (f", čakanie na limit {api.cakanie:.0f} s" if api.cakanie else "")
        + f"); odhad bol ~{odhad / 60:.1f} min")
    log(f"  {len(kde_je)} OSM objektov má článok, "
        f"{api.pocet and len(index) / api.pocet:.0f} článkov na požiadavku")
    if cache is not None:
        # Bez tohto riadka sa nedá odlíšiť „cache funguje" od „cache je tam,
        # ale kľúč nesedí a všetko sa ťahá odznova" – a to druhé je zelené
        # a tiché (pravidlo 8), len o desiatky sekúnd dlhšie.
        log(f"  z cache {z_cache} z {len(index)} článkov "
            f"({100 * z_cache / max(1, len(index)):.0f} %), "
            f"stiahnutých {len(index) - z_cache}")
    if chybne_vsetky:
        # NIE JE TO CHYBA BEHU, ale musí to byť napísané: odkaz v OSM môže
        # mieriť na článok, ktorý neexistuje (preklep, premenovaný článok,
        # jazyk bez článku). Zamlčať to by znamenalo „stiahlo sa všetko".
        log(f"::warning::{len(chybne_vsetky)} odkazov nemá článok "
            f"(napr. {', '.join(c['title'] for c in chybne_vsetky[:5])}) – "
            f"sú v index.json v `chybne`, aj s objektmi, ktoré na ne ukazujú.")
    if args.stats:
        with open(args.stats, "a") as f:
            f.write(f"60\tČlánky z Wikipédie\t{int(took)}\t"
                    f"{len(index)} článkov, {nd_mb:.1f} MB, "
                    f"{api.pocet} požiadaviek, "
                    f"{z_cache} z cache, "
                    f"{len(chybne_vsetky)} bez článku\n")
    if not index:
        log("::warning::Ani jeden článok – v regióne nie je objekt s odkazom "
            "na wiki, alebo sa nič nestiahlo. Balík sa nepublikuje.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
