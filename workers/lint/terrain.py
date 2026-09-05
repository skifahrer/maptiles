#!/usr/bin/env python3
"""Tieňovanie nesmie ticho stratiť presnosť, ktorou stojí a padá.

Výška sa kedysi zaokrúhľovala na celé metre a DEM sa na maxzoome zväčšoval
priemerom – hillshade z toho spravil pravidelnú tkaninu cez celú mapu a nič
nespadlo. Oprava je v troch číslach, ktoré sa dajú „zjednodušiť" späť, tak sa
strážia:

  1. zvislý krok ide za pixelom a s odstupom `FRAC_BITS_MARGIN` (krok presne
     na hranici viditeľnosti dá pravidelný, teda viditeľný, falošný sklon);
  2. `average` až keď je pixel aspoň `AVERAGE_RATIO`× hrubší než bunka;
  3. warp musí niesť zlomok (`-ot Int16` by ho zahodil) a `terrarium` musí
     zaokrúhľovať, nie orezávať maskou (maska je `floor`, teda schod).

A štvrtá, iná vec: podoba kódovania je v mene assetu aj v kľúči cache – keď sa
rozídu, build si vytiahne staré dlaždice a bude zelený.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
TILES = os.path.join(_WORKERS, "terrain", "tiles.py")
BUILD = os.path.join(_WORKERS, "terrain", "build.sh")
KEYS = os.path.join(_WORKERS, "plan", "cache-keys.sh")
MASK = os.path.join(_WORKERS, "lib", "region-mask.py")
# práca nad mriežkou výšok leží vo vyska.py – kontrola sa pozerá do oboch
VYSKA = os.path.join(_WORKERS, "terrain", "vyska.py")
# rozhodovanie sa spúšťa, nie číta zo zdrojáku, a preto býva v lib/cell.py,
# ktoré nemá numpy: lintovací job má len holý python3. Čo je nad poľami, sa
# kontroluje na texte.
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
import cell  # noqa: E402

# zoomy, na ktorých tieňovanie naozaj beží
ZOOMS = range(5, 17)


def main():
    bad = []
    t = cell

    # 1. zvislý krok ide za pixelom
    # bez úľavy na `MAX_FRAC_BITS`: ten strop je poistka proti nezmyselne
    # jemnému kroku, nie povolenie nechať krok hrubý
    for z in ZOOMS:
        px = t.tile_m_per_px(z)
        bits = t.frac_bits(px)
        krok = 2.0 ** -bits
        strop = t.SLOPE_EPS * px
        if krok > strop:
            bad.append(f"z{z}: pixel {px:.1f} m znesie krok najviac "
                       f"{strop:.3f} m, ale `frac_bits` dala {bits} bitov, "
                       f"teda {krok:g} m"
                       + (f" (zaráža strop MAX_FRAC_BITS={t.MAX_FRAC_BITS})"
                          if bits >= t.MAX_FRAC_BITS else "")
                       + ". Z plošiniek spraví hillshade pravidelnú tkaninu.")
        # a s odstupom: krok presne na hranici nechá pravidelný falošný sklon,
        # ktorý oko číta ako mriežku
        s_margin = strop / (2 ** t.FRAC_BITS_MARGIN)
        if krok > s_margin and bits < t.MAX_FRAC_BITS:
            bad.append(f"z{z}: krok {krok:g} m je len tesne pod hranicou "
                       f"viditeľnosti ({strop:.3f} m). Kvantizácia robí "
                       f"falošný sklon PRAVIDELNE, takže má byť "
                       f"{t.FRAC_BITS_MARGIN} bitov pod ňou, teda najviac "
                       f"{s_margin:.4f} m – `frac_bits` dala {bits} bitov.")
    # a druhá strana: na hrubých zoomoch sa nemá platiť za nič
    if t.frac_bits(t.tile_m_per_px(5)) != 0:
        bad.append("z5: taký hrubý pixel znesie celý meter, ale `frac_bits` "
                   "si pýta zlomkové bity – to je bajt navyše na dlaždicu "
                   "za presnosť, ktorú tam nikto neuvidí.")

    # 2. priemeruje sa, až keď je čo priemerovať
    # hranica nie je `pixel >= bunka`: tesne nad bunkou padne do box filtra raz
    # jedna, raz dve, čiže rytmus plošiniek. Čísla pri `AVERAGE_RATIO`.
    for mriezka in (1.0, 5.0, 10.0, 20.0, 31.0):
        for z in ZOOMS:
            px = t.tile_m_per_px(z)
            r = t.resampling(px, mriezka)
            if px < t.AVERAGE_RATIO * mriezka and r == "average":
                bad.append(f"model {mriezka:g} m, z{z} (pixel {px:.1f} m): pixel "
                           f"nie je ani {t.AVERAGE_RATIO:g}× hrubší než bunka, "
                           f"ale prevzorkúva sa `average` – ten tu prekryje raz "
                           f"jednu bunku, raz dve, a z tých plošiniek spraví "
                           f"hillshade mriežku.")
            if px >= t.AVERAGE_RATIO * mriezka and r != "average":
                bad.append(f"model {mriezka:g} m, z{z} (pixel {px:.1f} m): DEM sa "
                           f"zmenšuje aspoň {t.AVERAGE_RATIO:g}×, tam sa musí "
                           f"priemerovať (`average`), nie `{r}`.")
    # v pásme tesne nad bunkou sa `average` vrátiť nesmie
    if t.resampling(25.0, 20.0) == "average":
        bad.append("Pixel 25 m nad bunkou 20 m (z12 pri Sonnym) sa prevzorkúva "
                   "`average` – nameraných 5,45 proti 4,07 pri `cubicspline` "
                   "(a 5,36 proti 0,53 na samotnom warpe). To je tá mriežka, "
                   "ktorú bolo vidieť na mape aj po oprave zväčšovania, "
                   "a `cubicspline` je tu zadarmo.")
    # bez známej mriežky sa nesmie hádať
    if t.resampling(10.0, 0.0) != "average":
        bad.append("Bez známej mriežky modelu musí `resampling` ostať pri "
                   "`average` – to je doterajšie správanie a pri zmenšovaní "
                   "je správne.")

    # 3. warp musí niesť zlomok
    src = open(TILES).read()
    warp = src[src.index("def warp_level"):]
    warp = warp[:warp.index("\ndef ")] if "\ndef " in warp[1:] else warp
    if re.search(r'"-ot",\s*"Int16"', warp):
        bad.append("`warp_level` warpuje do Int16 – zlomok výšky sa zahodí "
                   "ešte pred kódovaním a zvislý krok je metrový bez ohľadu "
                   "na `frac_bits`.")
    elif not re.search(r'"-ot",\s*"Float32"', warp):
        bad.append("`warp_level` nemá `-ot Float32`; skontroluj, či zlomok "
                   "výšky prežije až po kódovanie.")

    # 3b. kóduje sa zaokrúhlením, nie orezaním: maskovanie spodných bitov je
    # `floor`, teda schod na hranici zoomov. Na texte, lebo numpy tu nie je.
    enc = src[src.index("def terrarium"):]
    enc = enc[:enc.index("\ndef ", 1)] if "\ndef " in enc[1:] else enc
    if re.search(r">>\s*\(?\s*8\s*-\s*bits", enc):
        bad.append("`terrarium` reže zlomok maskou (`>> (8 - bits)`), a to je "
                   "`floor` – každá výška klesne až o celý krok. Musí sa "
                   "zaokrúhliť NA krok (`np.rint(… / krok) * krok`).")
    elif "np.rint" not in enc:
        bad.append("`terrarium` nezaokrúhľuje (`np.rint`); bez toho sa zlomok "
                   "oreže nadol a výšky sa systematicky posunú.")

    # 4. podoba kódovania: sklad aj cache
    build = open(BUILD).read()
    keys = open(KEYS).read()
    # verzia je premenná (`ENC_VER`), nie napísané číslo – kým napísaná bola,
    # skladalo sa `-v4` a hľadalo `-v3`, takže sa uložené dlaždice nenašli nikdy
    v_asset = set(re.findall(r"^ENC_VER=v(\d+)\s*$", build, re.M))
    # komentáre o verzii ju smú menovať; zakázané je číslo v kóde
    kod = "\n".join(r for r in build.splitlines()
                    if not r.lstrip().startswith("#"))
    napisane = set(re.findall(r"-v(\d+)\\?\.pmtiles", kod))
    # kľúč tieňovania sa skladá v `T_NASTAVENIA`
    v_cache = set(re.findall(r'^T_NASTAVENIA="terrain-v(\d+)-', keys, re.M))
    if len(v_asset) != 1:
        bad.append(f"Vo `workers/terrain/build.sh` sa nedá prečítať `ENC_VER=v<číslo>` "
                   f"(našlo sa {sorted(v_asset)}). Podoba kódovania musí byť "
                   f"premenná na JEDNOM mieste – meno assetu sa skladá aj pri "
                   f"hľadaní v sklade, aj pri ukladaní, a obe musia hovoriť "
                   f"to isté.")
    elif napisane:
        bad.append(f"Vo `workers/terrain/build.sh` je verzia kódovania napísaná "
                   f"číslom ({sorted('v' + v for v in napisane)}) popri `ENC_VER`. "
                   f"Práve tak sa rozišli `-v4` v mene assetu a `-v3` v `sed`-e, "
                   f"ktorý sklad prehľadáva: uložené dlaždice sa nenašli nikdy "
                   f"a tieňovanie sa počítalo v každom behu znova. Použi "
                   f"`${{ENC_VER}}`.")
    elif not v_cache:
        bad.append("V `workers/plan/cache-keys.sh` nie je verzia v kľúči "
                   "tieňovania (`T_NASTAVENIA=\"terrain-v<číslo>-…\"`) – bez "
                   "nej vráti cache staré dlaždice.")
    elif v_asset != v_cache:
        bad.append(f"Podoba kódovania sa rozišla: sklad hovorí v{v_asset.pop()}, "
                   f"cache v{v_cache.pop()}. Jedno z tých dvoch miest vráti "
                   f"dlaždice spočítané po starom a build bude zelený.")
    else:
        print(f"  ✓ podoba kódovania v{v_cache.pop()} v sklade aj v cache")

    # 5. tieňovanie končí na hranici kraja
    # Dlaždicový orez (`--poly`) nemôže byť jemnejší než dlaždica, takže tieň
    # vychádzal až 6× väčší než kraj. Zastaví to až orez po pixeloch
    # (`pixel_mask`). Zrovnať to na rovinu sa nesmie – z hrany terénu a roviny
    # je zvislá stena. Obe polovice sa strážia textom (numpy tu nie je).
    if "--poly=data/region.geojson" not in build:
        bad.append("`workers/terrain/build.sh` nepodáva `tiles.py` polygón "
                   "kraja (`--poly=data/region.geojson`) – dlaždice sa vyrobia "
                   "na celom obdĺžniku bboxu a tieňovanie bude siahať ďaleko "
                   "za región (pri Prešovskom kraji 37 % plochy navyše).")
    strip = src[src.index("def main("):]
    if "pixel_mask(" not in strip:
        bad.append("`terrain/tiles.py` sa nepýta, ktoré PIXELY ležia v kraji "
                   "(`pixel_mask`). Sám dlaždicový orez hrubší než dlaždica "
                   "byť nemôže, takže tieňovanie zase presiahne za hranicu "
                   "regiónu – na z10 na dvojnásobok jeho plochy, a build bude "
                   "zelený.")
    if "pokracuj_okolim(" not in strip:
        bad.append("`terrain/tiles.py` nedopĺňa výšku za hranicou kraja "
                   "okolím (`pokracuj_okolim`). Bez toho tam ostane terén, "
                   "ktorý mal orez schovať – a zrovnať sa to tam nesmie, "
                   "z roviny je na hranici stena.")
    # rovina za hranicou sa nesmie vrátiť – bola to zvislá stena po obvode
    # regiónu; `--edge` ju len schovával pod plochu `mimo`
    if re.search(r"grid\[~keep\]\s*=", strip):
        bad.append("`terrain/tiles.py` zase zrovnáva pixely mimo kraja na "
                   "rovinu (`grid[~keep] = …`). Hrana terénu a roviny je pre "
                   "hillshade zvislá stena (89,4° proti 17,9°, ktoré má terén "
                   "sám) a v 3D múr po obvode regiónu – výška za hranicou má "
                   "pokračovať okolím.")
    if not re.search(r"keep\[[^\]]*\][^\n]*\.any\(\)", strip):
        bad.append("`terrain/tiles.py` nevynecháva dlaždicu, v ktorej nie je "
                   "ani jeden pixel kraja. Odkedy sa za hranicou dopĺňa "
                   "okolím, nie je taká dlaždica rovina a `je_rovina` ju "
                   "nezachytí – tieňovanie by rástlo do dlaždíc, ktoré s "
                   "krajom nemajú spoločné nič.")
    if "def pokracuj_okolim" not in open(VYSKA).read():
        bad.append("`workers/terrain/vyska.py` už nemá `pokracuj_okolim` – "
                   "to je to, čím výška za hranicou kraja pokračuje okolím "
                   "namiesto roviny, ktorá tam robila stenu.")
    if "def pixel_mask" not in open(MASK).read():
        bad.append("`workers/lib/region-mask.py` už nemá `pixel_mask` – "
                   "na to, ktoré PIXELY ležia v kraji, je jedna odpoveď "
                   "a býva vedľa tej dlaždicovej, nie druhýkrát v `tiles.py`.")
    # rezerva okolo hranice musí ostať: s `--edge 0` by pixel na hranici mal
    # susedov už z doplneného okolia
    edge = re.search(r'"--edge",\s*type=int,\s*default=(\d+)', src)
    if not edge:
        bad.append("`terrain/tiles.py` nemá prepínač `--edge` (koľko pixelov "
                   "skutočného terénu ostáva ešte za hranicou kraja).")
    elif int(edge.group(1)) < 1:
        bad.append("`--edge` má predvolene 0 pixelov: dopĺňanie okolím začne "
                   "presne na hranici kraja, takže posledný prúžok tieňovania "
                   "V MAPE sa počíta z výplne a nie z terénu. Rezerva ho "
                   "posunie za hranicu, kde je v štýle aj tak plocha `mimo`.")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print("Tieňovanie: zvislý krok ide za pixelom, priemeruje sa len nadol, "
          "warp nesie zlomok, za hranicou kraja terén pokračuje okolím ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
