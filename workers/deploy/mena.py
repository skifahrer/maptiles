#!/usr/bin/env python3
"""Ako sa balík volá a kam patrí.

Meno súboru na Drive a cesta k nemu sú SĽUB: sú stále, takže ďalší build ten
istý súbor prepíše (`presovsky-tienovanie.zip` je vždy tieňovanie Prešovského
kraja) a katalóg sa na ne dá odkázať. Preto sú tu na jednom mieste, a nie
rozpísané po `publish-map.py`, `catalog.py` a workflowoch – dve odpovede na
otázku „ako sa to volá" znamenajú dva rôzne súbory na Drive, z ktorých jeden
nikto nikdy neprepíše.

Číta ich `publish-map.py` (a cez neho aj job, čo dobalí `.aar`). Sem sa dostali
pri delení `publish-map.py`, ktorý prerástol strop 800 riadkov (pravidlo 5).

Použitie: `mena = load("deploy_mena", "mena.py")`, potom `mena.meno("tienovanie")`.
"""
import os


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def safe(text):
    """Kus mena súboru: bez diakritiky, medzier a lomítok."""
    prevod = {"á": "a", "ä": "a", "č": "c", "ď": "d", "é": "e", "í": "i",
              "ĺ": "l", "ľ": "l", "ň": "n", "ó": "o", "ô": "o", "ŕ": "r",
              "š": "s", "ť": "t", "ú": "u", "ý": "y", "ž": "z"}
    out = []
    for ch in text.strip().lower():
        ch = prevod.get(ch, ch)
        out.append(ch if (ch.isalnum() and ch.isascii()) or ch in "._-" else "_")
    return "".join(out).strip("_") or "bez_mena"


def bez_testu(key):
    """`presovsky_test4` → `presovsky`.

    Kľúč výrezu aj regiónu nesie pri rýchlom teste príponu `_test<N>`, aby si
    testovací výsledok nesadol na miesto ostrého. Do CESTY ale patrí to
    pohorie, o ktoré ide – že je to test, povie meno súboru.
    """
    base = key
    while True:
        cut = base.rfind("_test")
        if cut < 0 or not base[cut + 5:].replace(".", "").isdigit():
            return base
        base = base[:cut]



# ---------- kam to patrí ----------

def krajina_z_url(url):
    """Krajina z odkazu na osm.fr export.

    `…/extracts/europe/austria/tirol-latest.osm.pbf` → `austria`. Vlastný PBF
    je jediný prípad, keď región nie je v `workers/data/regions.json`, takže sa
    krajina nemá odkiaľ inak dozvedieť. Keď sa z odkazu vyčítať nedá, ide to
    do `ostatne` – nie do `slovensko`, kde nepatrí.
    """
    cesta = url.split("/extracts/", 1)[-1] if "/extracts/" in url else url
    kusy = [k for k in cesta.split("/") if k]
    if len(kusy) >= 2:
        return safe(kusy[-2])
    return "ostatne"


def cesta(regions):
    """Priečinky pod koreňom: [krajina, kraj?, výsek?]."""
    region_key = bez_testu(env("REGION_KEY"))
    custom_url = env("CUSTOM_PBF_URL")
    area_key = bez_testu(env("AREA_KEY"))

    if custom_url:
        # Vlastný PBF: v `regions.json` nie je, kraj je to, čo si človek
        # pomenoval sám (alebo slug z odkazu).
        kraj = safe(env("CUSTOM_NAME") or region_key
                    or custom_url.rsplit("/", 1)[-1].split(".")[0])
        parts = [krajina_z_url(custom_url), kraj]
    else:
        r = regions.get(region_key) or {}
        krajina = safe(r.get("country") or region_key or "ostatne")
        parts = [krajina]
        # Celá krajina nemá nadradený kraj – `admin_level` 2 je štát.
        if r.get("admin_level") != 2 and region_key:
            parts.append(safe(region_key))
    # `cely` znamená „celý región", teda žiadny výrez – vlastnú úroveň
    # nedostane, inak by v každom kraji ležal priečinok `cely`.
    if area_key and area_key != "cely":
        parts.append(safe(area_key))
    return parts


def cesta_katalog(parts):
    """Kam to patrí v KATALÓGU – to isté, len rýchly test má vlastný uzol.

    Na Drive ležia balíky testu v tom istom priečinku ako ostrá mapa (odlíši
    ich meno – `…-test4km2.zip`), ale v katalógu na jej miesto sadnúť NESMÚ:
    terén je v nich na pár km² a čitateľ by si podľa nich stiahol „mapu
    kraja". Zapisovať sa ale majú – bez toho o nich nevie nikto, kto nemá
    otvorený Drive, a to je presne to, načo `maps.json` je. Uzol preto dostane
    tú istú príponu, akú nesú súbory: `vysoke_tatry_test4km2`.
    """
    test_km2 = env("TEST_KM2", "0")
    if test_km2 in ("", "0"):
        return parts
    return parts[:-1] + [f"{parts[-1]}_test{safe(test_km2)}km2"]


# ---------- ako sa to volá ----------

def vrstvy():
    """Kúsky mena, ktoré hovoria, čo je v mape a z čoho.

    Vrstva sa do mena zapíše aj vtedy, keď v mape NIE JE (`bez_vrstevnic`).
    Mlčanie by sa dalo čítať dvoma spôsobmi – „nie sú" aj „zabudlo sa to
    dopísať" – a to je presne ten rozdiel, kvôli ktorému sa mená píšu.

    `MAP_LAYERS` je pre pipeline, ktorá NEROBÍ mapu kraja a tento zoznam
    vrstiev na ňu nesadá – zatiaľ mapa sveta (`world-map.yml`). Bez toho by
    o sebe napísala „bez_vrstevnic, bez_skal, bez_tienovania", čo je pri mape,
    ktorá nemá ani cesty, mätúce: znie to ako mapa kraja s vypnutým terénom.
    Podáva sa prostredím a nie prepínačom zámerne – ten istý zoznam potrebuje
    aj job, čo dobalí `.aar` (položku katalógu prepisuje navrch), a env stojí
    v oboch jobov na tom istom mieste vo workflowe.
    """
    vlastne = env("MAP_LAYERS")
    if vlastne:
        return [safe(k) for k in vlastne.split(",") if k.strip()]

    out = []
    if env("CONTOURS_ENABLED") == "true":
        interval = env("CONTOUR_INTERVAL", "10")
        out.append(f"vrstevnice_{safe(env('CONTOURS_SOURCE', '?'))}_{safe(interval)}m")
    else:
        out.append("bez_vrstevnic")

    if env("ROCKS_ENABLED") == "true":
        out.append(f"skaly_{safe(env('ROCKS_SOURCE', '?'))}")
    else:
        out.append("bez_skal")

    if env("TERRAIN_ENABLED") == "true":
        out.append(f"tienovanie_{safe(env('TERRAIN_SOURCE', '?'))}")
    else:
        out.append("bez_tienovania")

    # Trasy a prvky sa píšu, len keď sú – nie sú to vrstvy z výškového modelu
    # a meno by bez toho narástlo o dve „bez_" na každom behu.
    if env("TRAILS_ENABLED") == "true":
        out.append("trasy")
    if env("FEATURES_ENABLED") == "true":
        out.append("prvky")
    if env("TRANSPORT_ENABLED") == "true":
        out.append("doprava")
    if env("BOUNDARIES_ENABLED") == "true":
        out.append("hranice")
    if env("WATER_ENABLED") == "true":
        out.append("vodstvo")
    return out


def zaklad():
    """Stále meno bez prípony: `<kraj>[-<výsek>][-testNkm2]`.

    Zoom, vrstvy, ich zdroje, dátum ani číslo behu v ňom NIE SÚ – práve preto
    je stále a ďalší build ten istý súbor prepíše. Všetko to nesie `obsah.json`
    vnútri balíka.
    """
    region = bez_testu(env("REGION_KEY")) or "mapa"
    area = bez_testu(env("AREA_KEY"))
    kusy = [safe(region)]
    if area and area != "cely":
        kusy.append(safe(area))
    test_km2 = env("TEST_KM2", "0")
    if test_km2 not in ("", "0"):
        # Rýchly test má terén len na pár km². Bez tohto by mapa vyzerala ako
        # ostrá, chýbala by jej väčšina – a PREPÍSALA by tú ostrú.
        kusy.append(f"test{safe(test_km2)}km2")
    return "-".join(kusy)


# Prípony podľa formátu. `.aar` je Apple Archive – to, čo iOS a macOS vedia
# rozbaliť SYSTÉMOVO (framework AppleArchive), bez tretej knižnice v aplikácii
# a s dekompresiou LZFSE, ktorá je na Apple hardvéri rýchlejšia než deflate.
# ZIP ostáva, lebo ten otvorí čokoľvek; `.aar` je navyše, nie namiesto.
PRIPONY = {"zip": ".zip", "aar": ".aar"}


def meno(kind="", fmt="zip"):
    """Meno balíka: základ + druh (`` = celá mapa) + prípona formátu."""
    return zaklad() + (f"-{kind}" if kind else "") + PRIPONY[fmt]
