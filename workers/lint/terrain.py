#!/usr/bin/env python3
"""
Tieňovanie nesmie ticho stratiť presnosť, ktorou stojí a padá.

PREČO TO EXISTUJE. Výškové dlaždice vyzerali roky správne a neboli: výška sa
zaokrúhľovala na celé metre (`B = 0`) a na maxzoome sa DEM zväčšoval
priemerom, ktorý pri zväčšovaní zdegeneruje na najbližšieho suseda. Hillshade
je derivácia výšky, takže z metrových plošiniek a zo štvorčekov po najbližšom
susedovi spravil PRAVIDELNÚ TKANINU cez celú mapu. Nič nespadlo, nič nezčervenalo
– dlaždice vznikli, mapa sa nasadila a bolo to vidieť len okom. Presne to,
čo je v CLAUDE.md pravidlo 8.

Oprava je v troch číslach a každé z nich sa dá „zjednodušiť" späť bez toho,
aby to čokoľvek povedalo. Preto sa strážia:

  1. ZVISLÝ KROK IDE ZA PIXELOM, A S ODSTUPOM. `frac_bits` musí pre každý zoom
     vrátiť toľko bitov, aby krok kódovania ostal `FRAC_BITS_MARGIN` bitov pod
     `SLOPE_EPS × pixel` – kým sa nenarazí na `MAX_FRAC_BITS`. Bez toho je krok
     na vysokých zoomoch znova metrový; a keď sedí presne NA tej hranici,
     falošný sklon z kvantizácie ostane na každom zoome tesne pod hranicou
     viditeľnosti – lenže je PRAVIDELNÝ, takže ho oko číta ako mriežku. To bolo
     na mape vidieť aj po prvej oprave.
  2. PRIEMERUJE SA, AŽ KEĎ JE ČO PRIEMEROVAŤ. `resampling` smie vrátiť
     `average` iba vtedy, keď je pixel dlaždice aspoň `AVERAGE_RATIO`× hrubší
     než bunka modelu. Nielen pri zväčšovaní, ale aj v pásme tesne nad bunkou
     z neho vypadnú plošinky – a mriežku bolo na mape vidieť aj potom, čo sa
     opravilo samotné zväčšovanie.
  3. WARP MUSÍ NIESŤ ZLOMOK. `-ot Int16` vo `warp_level` by zlomok zahodil
     ešte pred kódovaním a body 1 a 2 by boli zbytočné – krok by bol metrový
     bez ohľadu na to, koľko bitov mu potom dáme. A `terrarium` musí zlomok
     ZAOKRÚHLIŤ na krok, nie orezať maskou spodných bitov: maska je `floor`,
     čiže posun každej výšky nadol – systematický, teda nie šum, ale schod
     na hranici zoomov.

  4. A ŠTVRTÁ, INÁ VEC: podoba kódovania je v mene assetu v sklade
     (`workers/terrain/build.sh`) aj v kľúči cache
     (`workers/plan/cache-keys.sh`). Sú to dve miesta a jedna otázka („sú
     tieto hotové dlaždice ešte tie, ktoré by dnes vznikli?"). Keď sa rozídu,
     build si z jedného z nich vytiahne staré dlaždice a bude zelený.

Spustiť sa dá aj lokálne: `python3 workers/lint/terrain.py`.
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
# Rozhodovanie („aký krok, ktorý resampling") sa SPÚŠŤA, nie číta zo zdrojáku –
# a preto býva vo `lib/cell.py`, ktoré nemá numpy. Lintovací job má len
# `checkout` a holý `python3`: `terrain/tiles.py` by sa tu naimportovať nedalo
# (numpy) a kontrola by sa musela ticho preskakovať. To, čo je nad poľami
# (kódovanie do RGB), sa preto kontroluje na texte, tak ako `-ot Int16`.
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
import cell  # noqa: E402

# Zoomy, na ktorých tieňovanie naozaj beží: `terrain/build.sh` púšťa
# `tiles.py` od z5 a `terrain_maxzoom: auto` dá najviac z16.
ZOOMS = range(5, 17)


def main():
    bad = []
    t = cell

    # ---------- 1. zvislý krok ide za pixelom ----------
    # BEZ ÚĽAVY NA `MAX_FRAC_BITS`: ten strop je poistka proti nezmyselne
    # jemnému kroku (1/64 m je pod šumom každého modelu), nie povolenie
    # nechať krok hrubý. Na zoomoch, ktoré tieňovanie používa, sa naň nemá
    # ako naraziť – a keby ho niekto stiahol dole „na ušetrenie bajtov",
    # mriežka sa vráti a nikto to nepovie.
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
        # A NIELEN POD ŇU, ALE S ODSTUPOM. Krok presne na hranici viditeľnosti
        # nechá falošný sklon na každom zoome tesne pod ňou – a keďže je
        # PRAVIDELNÝ, oko ho aj tak číta ako mriežku. Presne to ostalo na mape
        # vidieť po prvej oprave. Strop `MAX_FRAC_BITS` je legitímny dôvod
        # nedosiahnuť plný odstup, tak sa naň neplače.
        s_margin = strop / (2 ** t.FRAC_BITS_MARGIN)
        if krok > s_margin and bits < t.MAX_FRAC_BITS:
            bad.append(f"z{z}: krok {krok:g} m je len tesne pod hranicou "
                       f"viditeľnosti ({strop:.3f} m). Kvantizácia robí "
                       f"falošný sklon PRAVIDELNE, takže má byť "
                       f"{t.FRAC_BITS_MARGIN} bitov pod ňou, teda najviac "
                       f"{s_margin:.4f} m – `frac_bits` dala {bits} bitov.")
    # A druhá strana toho istého: na hrubých zoomoch sa nemá platiť za nič.
    if t.frac_bits(t.tile_m_per_px(5)) != 0:
        bad.append("z5: taký hrubý pixel znesie celý meter, ale `frac_bits` "
                   "si pýta zlomkové bity – to je bajt navyše na dlaždicu "
                   "za presnosť, ktorú tam nikto neuvidí.")

    # ---------- 2. priemeruje sa, až keď je čo priemerovať ----------
    # Hranica NIE JE `pixel >= bunka`. `average` je box filter cez prekryté
    # bunky, takže tesne nad bunkou mu padne raz jedna, raz dve – striedavo
    # najbližší sused a priemer dvojice, čiže rytmus plošiniek a z neho tá istá
    # mriežka ako pri zväčšovaní. Namerané čísla sú pri `AVERAGE_RATIO`
    # vo `lib/cell.py`.
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
    # A hlavne: v pásme tesne nad bunkou sa `average` vrátiť NESMIE. Je to tá
    # istá chyba ako pri zväčšovaní a práve tú bolo vidieť na mape aj potom,
    # čo sa opravilo zväčšovanie.
    if t.resampling(25.0, 20.0) == "average":
        bad.append("Pixel 25 m nad bunkou 20 m (z12 pri Sonnym) sa prevzorkúva "
                   "`average` – nameraných 5,45 proti 4,07 pri `cubicspline` "
                   "(a 5,36 proti 0,53 na samotnom warpe). To je tá mriežka, "
                   "ktorú bolo vidieť na mape aj po oprave zväčšovania, "
                   "a `cubicspline` je tu zadarmo.")
    # Bez známej mriežky sa nesmie hádať – ostáva doterajšie správanie.
    if t.resampling(10.0, 0.0) != "average":
        bad.append("Bez známej mriežky modelu musí `resampling` ostať pri "
                   "`average` – to je doterajšie správanie a pri zmenšovaní "
                   "je správne.")

    # ---------- 3. warp musí niesť zlomok ----------
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

    # ---------- 3b. kóduje sa zaokrúhlením, nie orezaním ----------
    # Maskovanie spodných bitov (`v >> k << k`) je o riadok kratšie a je to
    # `floor`: posunulo by KAŽDÚ výšku nadol až o celý krok. Systematicky,
    # takže nie ako šum, ale ako schod na hranici zoomov – v 3D teréne by terén
    # pri priblížení nadskočil. Kontroluje sa na texte, lebo `terrarium` počíta
    # nad poľom a numpy tu nie je (viď hlavičku).
    enc = src[src.index("def terrarium"):]
    enc = enc[:enc.index("\ndef ", 1)] if "\ndef " in enc[1:] else enc
    if re.search(r">>\s*\(?\s*8\s*-\s*bits", enc):
        bad.append("`terrarium` reže zlomok maskou (`>> (8 - bits)`), a to je "
                   "`floor` – každá výška klesne až o celý krok. Musí sa "
                   "zaokrúhliť NA krok (`np.rint(… / krok) * krok`).")
    elif "np.rint" not in enc:
        bad.append("`terrarium` nezaokrúhľuje (`np.rint`); bez toho sa zlomok "
                   "oreže nadol a výšky sa systematicky posunú.")

    # ---------- 4. podoba kódovania: sklad aj cache ----------
    build = open(BUILD).read()
    keys = open(KEYS).read()
    # Verzia je v `build.sh` premenná (`ENC_VER`) a NIE napísané číslo. Kým
    # napísaná bola, boli z nej dve: `asset_name` skladalo `-v4` a `sed`, ktorý
    # sklad prehľadáva, hľadal `-v3`. Uložené dlaždice sa teda nenašli nikdy
    # a tieňovanie sa počítalo v každom behu odznova – zelené a pomalé. Preto
    # sa kontroluje oboje: že premenná je, a že vedľa nej nezostalo napísané
    # číslo verzie, ktoré by sa od nej mohlo odchýliť.
    v_asset = set(re.findall(r"^ENC_VER=v(\d+)\s*$", build, re.M))
    # Komentáre sa vyhadzujú – tie o verzii HOVORIA a majú ju smieť menovať;
    # zakázané je len napísať ju do kódu, ktorý meno naozaj skladá.
    kod = "\n".join(r for r in build.splitlines()
                    if not r.lstrip().startswith("#"))
    napisane = set(re.findall(r"-v(\d+)\\?\.pmtiles", kod))
    v_cache = set(re.findall(r'echo "terrain=terrain-v(\d+)-', keys))
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
                   "`terrain=` – bez nej vráti cache staré dlaždice.")
    elif v_asset != v_cache:
        bad.append(f"Podoba kódovania sa rozišla: sklad hovorí v{v_asset.pop()}, "
                   f"cache v{v_cache.pop()}. Jedno z tých dvoch miest vráti "
                   f"dlaždice spočítané po starom a build bude zelený.")
    else:
        print(f"  ✓ podoba kódovania v{v_cache.pop()} v sklade aj v cache")

    # ---------- 5. tieňovanie končí na hranici kraja ----------
    # PREČO. Dlaždicový orez (`--poly`) hrubší byť nemôže, než je dlaždica:
    # ktorá sa kraja dotkne, vyrobí sa CELÁ. Namerané na Prešovskom kraji
    # (10 184 km²) ako plocha vyrobených dlaždíc proti ploche kraja: z8 6,2×,
    # z10 2,2×, z12 1,4×. To je ten „dvakrát väčší tieň než kraj", ktorý bolo
    # v mape vidieť – a v behu sa neohlásil ničím, lebo dlaždice vznikli a mapa
    # sa nasadila. Zastaví ho až orez po PIXELOCH (`pixel_mask`): za hranicou
    # kraja sa výška DOPĹŇA OKOLÍM a dlaždica, v ktorej nie je ani jeden pixel
    # kraja, sa nezapíše. Zrovnať to tam na rovinu sa NESMIE – z hrany terénu
    # a roviny je zvislá stena (89,4° proti 17,9°, ktoré má terén sám) a v 3D
    # múr po obvode regiónu.
    #
    # Obe polovice sa dajú „zjednodušiť" preč bez toho, aby to čokoľvek
    # povedalo (vrstva bude, len bude zase väčšia než región), tak sa strážia
    # textom – `tiles.py` sa tu naimportovať nedá, numpy v lintovacom jobe nie
    # je (viď hlavičku).
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
    # ROVINA ZA HRANICOU SA NESMIE VRÁTIŤ. Bola to zvislá stena po obvode
    # regiónu: hillshade je derivácia výšky, takže pokles zo 600 m na nulu
    # medzi dvoma pixelmi je preň útes (namerané na umelom teréne 89,4° proti
    # 17,9°, ktoré má terén sám) a v 3D múr. `--edge` ju posúval za hranicu,
    # kde ju prekrýva plocha `mimo` – lenže to je schovanie, nie odstránenie.
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
    if "def pixel_mask" not in open(MASK).read():
        bad.append("`workers/lib/region-mask.py` už nemá `pixel_mask` – "
                   "na to, ktoré PIXELY ležia v kraji, je jedna odpoveď "
                   "a býva vedľa tej dlaždicovej, nie druhýkrát v `tiles.py`.")
    # A rezerva okolo hranice musí ostať. Tieňovanie sa počíta zo susedných
    # pixelov a klient si dlaždicu ešte prevzorkuje, takže s `--edge 0` by
    # pixel NA hranici kraja mal susedov už z doplneného okolia – tieňovanie
    # v mape by na poslednom prúžku stálo na výplni namiesto terénu.
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
