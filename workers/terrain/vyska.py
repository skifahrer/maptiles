#!/usr/bin/env python3
"""
Čo sa zapíše tam, kde výšku NEMÁME – a prečo to nikdy nie je konštanta.

Terrarium je RGB a nemá podobu „hodnota tu nie je": do dlaždice sa niečo
zapísať MUSÍ. Otázky sú dve a `terrain/tiles.py` sa ich pýta v tomto poradí:

  1. KDE MODEL DÁTA NEMÁ (`vypln_nodata`) – fakt o modeli. DMR 5.0 je len
     Slovensko, takže za štátnou hranicou je v ňom diera, a diery bývajú aj
     vnútri (mraky, voda).
  2. KDE SME ZA HRANICOU KRAJA (`pokracuj_okolim`) – naše rozhodnutie. Mapa
     končí na hranici stiahnutého regiónu, takže sa terén za ňou nemá ukázať.

KONŠTANTA ROBÍ STENU, a to je celý dôvod, prečo je tento súbor takýto dlhý.
Hillshade je DERIVÁCIA výšky, takže pokles zo 600 m na konštantu medzi dvoma
pixelmi je preň zvislý útes – nakreslí ho ako ostrú svetlo-tmavú čiaru a v 3D
teréne je z nej múr. Stalo sa to už dvakrát a zakaždým to bola tá istá chyba:

  * `-dstnodata 0` na hranici MODELU: namerané na publikovanom
    `bratislavsky_test4-terrain.pmtiles` 668 m na 407 m/px, čiže 59°;
  * rovina 0 m za hranicou KRAJA: namerané celou pipeline na umelom teréne
    89,4°, kým terén sám mal najviac 17,9°.

Odpoveď je v oboch prípadoch POKRAČOVANIE OKOLÍM – „ďalej nevieme" povedané
tak, aby z toho hillshade nemal čo nakresliť. Algoritmy sú ale dva, lebo tvar
hranice je iný: okraj modelu je rovný (stačí priechod po riadkoch a stĺpcoch),
hranica kraja členitá (treba pyramídu priemerov). Rozpis pri každej funkcii.

ODDELENÉ OD `tiles.py` kvôli stropu 800 riadkov (pravidlo 5 v CLAUDE.md,
stráži `Kontrola · lint workflowov`). Rez je tam, kde bol aj tak: `tiles.py`
je odteraz plán, warp a kódovanie do dlaždíc, tento súbor je práca nad
mriežkou výšok. Nemá pomlčku v mene, takže sa dá `import`-núť normálne.

Použitie ako modul (`terrain/tiles.py`):
    from vyska import NODATA, pokracuj_okolim, vypln_nodata
"""
import numpy as np


# Hodnota, ktorou `gdalwarp` označí „tu model nie je". Musí byť mimo
# rozsahu skutočných výšok (Zem má −430 m až 8849 m) a NESMIE to byť 0:
# nula je platná výška a v terrariu sa nedá odlíšiť od chýbajúcej hodnoty.
NODATA = -9999.0


def vypln_nodata(grid, chyba):
    """Chýbajúce výšky doplní NAJBLIŽŠOU platnou, nie konštantou.

    PREČO VÔBEC NIEČO. Terrarium je RGB a nemá podobu „hodnota tu nie je" –
    do dlaždice sa teda niečo zapísať MUSÍ. Otázka je len čo, a sú dve
    možnosti: konštanta, alebo okolie.

    KONŠTANTA ROBÍ STENU. Tá stena je presne to, čo bolo v mape vidieť ako
    „divný orez": na hranici modelu spadne výška zo 600 m na konštantu, čo je
    pre hillshade (derivácia výšky) zvislý útes, a nakreslí sa ako ostrá
    čiara cez celú mapu. Za ňou je rovina, teda plocha BEZ tieňovania.

    OKOLIE ŽIADNU NEROBÍ: výška za hranicou plynulo pokračuje tou, ktorá je
    na hranici. Nie je to vymyslený terén – je to jediný spôsob, ako povedať
    „ďalej nevieme" bez toho, aby z toho hillshade nakreslil útvar. Presne to
    isté robí `gdal_fillnodata`; tu je to štyrmi priechodmi indexov (O(n)),
    lebo GDAL by kvôli tomu musel súbor prepísať.

    `chyba` je maska „tu nie je hodnota". Vracia doplnenú mriežku; keď nie je
    z čoho dopĺňať (celý pás je bez dát), vracia ju nezmenenú.
    """
    if not chyba.any() or chyba.all():
        return grid
    g = grid
    plati = ~chyba
    # NAJPRV PO RIADKOCH, POTOM PO STĹPCOCH – nie obe osi naraz a to bližšie
    # z nich. Pixel v rohu, ďaleko od okna s dátami, nemá platného suseda ani
    # vo svojom riadku, ani vo svojom stĺpci, takže by z takého porovnania
    # vyšiel nedoplnený – a v dlaždici by ostal sentinel, čiže −9999 m vedľa
    # 600 m: stena stokrát vyššia než tá, ktorú to má odstrániť. Po riadkovom
    # priechode už každý stĺpec, ktorý dáta pretínajú, platné hodnoty MÁ,
    # takže ich stĺpcový priechod roznesie do zvyšku.
    for axis in (1, 0):
        n = g.shape[axis]
        tvar = [1, 1]
        tvar[axis] = n
        idx = np.broadcast_to(np.arange(n).reshape(tvar), g.shape)
        dopredu = np.maximum.accumulate(np.where(plati, idx, -1), axis=axis)
        spat = np.flip(np.minimum.accumulate(
            np.flip(np.where(plati, idx, n), axis=axis), axis=axis), axis=axis)
        d_dop = np.where(dopredu < 0, n + 1, idx - dopredu)
        d_spat = np.where(spat >= n, n + 1, spat - idx)
        v_dop = np.take_along_axis(g, dopredu.clip(0, n - 1), axis)
        v_spat = np.take_along_axis(g, spat.clip(0, n - 1), axis)
        je_dop, je_spat = d_dop <= n, d_spat <= n
        # KEĎ SÚ PLATNÉ OBE STRANY, PRECHÁDZA SA MEDZI NIMI LINEÁRNE, nie
        # skokom na tú bližšiu. Pri diere V MODELI (nie za jeho okrajom) sa
        # totiž výplne z oboch strán stretnú v jej strede a „tá bližšia" tam
        # spraví šev – teda opäť stenu, len menšiu. Namerané na 70 px diere
        # medzi svahmi, ktoré sa líšia o ~300 m: skokom 298 m (36°),
        # lineárne 0 m. Za okrajom modelu je platná len jedna strana, takže
        # tam z toho vyjde presne to isté, čo predtým – rovné pokračovanie.
        sucet = np.where(je_dop, d_dop, 0) + np.where(je_spat, d_spat, 0)
        podiel = np.divide(np.where(je_spat, d_spat, 0), np.maximum(sucet, 1),
                           dtype=np.float64)
        oboje = je_dop & je_spat
        hodnota = np.where(oboje, v_dop * podiel + v_spat * (1.0 - podiel),
                           np.where(je_dop, v_dop, v_spat))
        naslo = je_dop | je_spat
        g = np.where(plati, g, np.where(naslo, hodnota.astype(g.dtype), g))
        plati = plati | naslo
    return g


def _zmensi(v, w):
    """Úroveň pyramídy na polovicu: súčty hodnôt a váh po blokoch 2×2.

    Váha je „koľko známych pixelov do tejto bunky spadlo", takže sa bunka
    s jedným známym pixelom nedostane k slovu rovnako ako plná – a bunka bez
    známeho pixela má váhu 0 a v jemnejšej úrovni nerozhoduje o ničom.
    """
    h, w_ = v.shape
    if h % 2 or w_ % 2:                  # nepárny rozmer sa doplní nulami
        v = np.pad(v, ((0, h % 2), (0, w_ % 2)))
        w = np.pad(w, ((0, h % 2), (0, w_ % 2)))
    v = v.reshape(v.shape[0] // 2, 2, v.shape[1] // 2, 2).sum(axis=(1, 3))
    w = w.reshape(w.shape[0] // 2, 2, w.shape[1] // 2, 2).sum(axis=(1, 3))
    return v, w


def _zvacsi(a, tvar):
    """Úroveň pyramídy nadvakrát, bilineárne (a orezaná na `tvar`).

    Nie `np.repeat` samotné: z toho sú štvorčeky 2×2 a hillshade z ich hrán
    kreslí mriežku – tá istá chyba, akú popisuje hlavička pri prevzorkovaní
    DEM. Jadro 1–2–1 po oboch osiach je jej priemer, teda hladké aj v prvej
    derivácii; okraj sa opakuje, nech sa na ňom nič neutlmí k nule.
    """
    b = np.repeat(np.repeat(a, 2, axis=0), 2, axis=1)
    for axis in (0, 1):
        p1 = np.take(b, [0] + list(range(b.shape[axis] - 1)), axis=axis)
        p2 = np.take(b, list(range(1, b.shape[axis])) + [b.shape[axis] - 1],
                     axis=axis)
        b = 0.25 * p1 + 0.5 * b + 0.25 * p2
    return b[:tvar[0], :tvar[1]]


def _uhlad(a, drz, kolo=4):
    """`kolo` Jacobiho priechodov: neznámy pixel = priemer štyroch susedov.

    ZVÁRA ŠEV. Pyramída sama dá neznámemu pixelu priemer z hrubšej úrovne –
    a ten sa od suseda TESNE ZA hranicou, ktorý si drží skutočnú výšku, môže
    líšiť o desiatky metrov: bez zvárania má p99 švov 42,2° a najhorší 68,1°,
    kým terén sám má p99 20,9° (tabuľka nižšie). Teda opäť stena, len nižšia
    než tá z roviny (89°). Priemerovanie susedov ju rozotrie: doplnená strana
    sa priblíži k tej známej, známa ostáva ako bola.

    Beží na KAŽDEJ úrovni pyramídy, nie len na najjemnejšej – hrubé úrovne
    roznesú hodnotu ďaleko a jemná ju už len dorovná. Preto stačia štyri
    priechody: sto priechodov na jednej úrovni by stálo sto prejdení celej
    mriežky (pás má na z15 aj 33 miliónov pixelov) a spravili by to isté.
    Namerané na umelom teréne (1024², z13; terén sám má v kraji medián sklonu
    7,3°, p99 20,9° a najviac 23,3°) ako sklon na ŠVE medzi známym
    a doplneným pixelom:

        priechodov     0        2        4        8
        medián       7,1°     6,4°     6,3°     6,2°
        p99         42,2°    27,2°    24,8°    20,8°
        najviac     68,1°    49,3°    40,7°    33,1°

    Štyri priechody teda posadia šev na to, čo má terén sám (medián aj p99),
    a ďalšie štyri už len ubíjajú jedno percento najhorších miest.
    """
    for _ in range(kolo):
        sused = np.empty_like(a)
        sused[:] = 0.0
        for axis in (0, 1):
            n = a.shape[axis]
            sused += np.take(a, [0] + list(range(n - 1)), axis=axis)
            sused += np.take(a, list(range(1, n)) + [n - 1], axis=axis)
        a = np.where(drz, a, sused * 0.25)
    return a


def pokracuj_okolim(grid, znam, krok=0.0):
    """Za hranicou kraja pokračuje výška okolím – hladko a bez steny.

    PREČO NIE ROVINA. Kým pixely mimo kraja dostávali výšku 0, bola z hranice
    kraja zvislá stena: hillshade je derivácia výšky, takže pokles zo 600 m na
    nulu medzi dvoma pixelmi je preň útes (namerané na umelom teréne 89,4°
    proti 17,9°, ktoré má terén sám) a v 3D teréne múr po obvode regiónu.
    `--edge` ju posúval pár pixelov za hranicu, kde ju v štýle prekrýva plocha
    `mimo` – lenže schovaná stena je stále stena.

    PREČO NIE `vypln_nodata`. Tá dopĺňa po RIADKOCH a po STĹPCOCH, čo je
    presne to, čo treba za rovným okrajom modelu, ale hranica kraja rovná nie
    je: riadok, ktorý sa kraja ešte dotkne, sa doplní z jeho pixelov, a riadok
    o jeden nižšie už z celkom iného miesta hranice. Namerané na skúšobnom
    behu (z13, členitý polygón): 825 m medzi dvoma susednými riadkami dva
    pixely za hranicou, čiže 89° – stena bola preč a hneď vedľa vyrástla iná.

    ČO SA TEDA ROBÍ: pyramída priemerov (pull-push). Nahor sa nesú súčty
    hodnôt a váh po blokoch 2×2, nadol sa neznáme pixely dopĺňajú z hrubšej
    úrovne, známe si držia svoju hodnotu a na každej úrovni sa šev medzi nimi
    zvarí štyrmi priechodmi priemeru (`_uhlad`). Vyjde z toho pokračovanie,
    ktoré (1) na hranici nadväzuje na terén, lebo o najbližšie pixely sa
    opiera najjemnejšia úroveň, a (2) čím ďalej za hranicou, tým hrubšia
    úroveň o ňom rozhoduje – reliéf teda smerom von slabne (namerané: stredný
    sklon 8,0° v kraji, 7,0° tesne za hranicou, 5,5° stotridsať pixelov za
    ňou). Je to O(n): celá pyramída má 4/3 pixelov originálu.

    `znam` je maska „tu je platná výška" (pixely v kraji aj s rezervou
    `--edge`). Mimo nej sa `grid` prepíše, v nej ostáva nedotknutý.

    `krok` ZAOKRÚHĽUJE DOPLNENÉ VÝŠKY, a to len ich. Zlomkové bity hladkého
    pokračovania sú pre kompresiu šum: dlaždica ich nesie v celej ploche za
    hranicou, hoci je tá výška aj tak vymyslená. Namerané na umelom teréne
    (1024², z13, krok kódovania 1/32 m): 669 kB bez zaokrúhlenia, 444 kB
    s krokom `SLOPE_EPS × pixel`. Ten krok je práve tá hranica, pod ktorou je
    sklon z kvantizácie neviditeľný (`lib/cell.py`) – a odstup troch bitov,
    ktorý si kódovanie drží kvôli pravidelnej mriežke v mape, tu netreba:
    toto je územie ZA hranicou regiónu, ktoré v mape prekrýva plocha `mimo`.
    """
    v = np.where(znam, grid.astype(np.float64), 0.0)
    w = znam.astype(np.float64)
    pyramida = [(v, w)]
    while min(pyramida[-1][0].shape) > 2:
        pyramida.append(_zmensi(*pyramida[-1]))
    v, w = pyramida[-1]
    hore = v / np.maximum(w, 1e-9)
    for v, w in reversed(pyramida[:-1]):
        hore = _zvacsi(hore, v.shape)
        znama = w > 0
        hore = np.where(znama, v / np.maximum(w, 1e-9), hore)
        hore = _uhlad(hore, znama)
    if krok > 0:
        hore = np.rint(hore / krok) * krok
    return np.where(znam, grid, hore.astype(grid.dtype))

