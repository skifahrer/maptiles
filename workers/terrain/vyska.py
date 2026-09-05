#!/usr/bin/env python3
"""Čo sa zapíše tam, kde výšku nemáme – nikdy konštanta.

Terrarium je RGB a nemá podobu „hodnota tu nie je", takže sa niečo zapísať
musí. Konštanta robí stenu: hillshade je derivácia výšky, takže skok zo 600 m
na konštantu je preň zvislý útes. Odpoveď je pokračovanie okolím. Algoritmy sú
dva, lebo okraj modelu je rovný (`vypln_nodata`), hranica kraja členitá
(`pokracuj_okolim`). Oddelené od tiles.py kvôli stropu 800 riadkov.
"""
import numpy as np


# `gdalwarp` sentinel; nesmie byť 0 – nula je platná výška
NODATA = -9999.0


def vypln_nodata(grid, chyba):
    """Chýbajúce výšky doplní najbližšou platnou, nie konštantou.

    Štyri priechody indexov (O(n)) namiesto `gdal_fillnodata`, ktorý by musel
    prepísať súbor. `chyba` je maska „tu nie je hodnota".
    """
    if not chyba.any() or chyba.all():
        return grid
    g = grid
    plati = ~chyba
    # najprv po riadkoch, potom po stĺpcoch – nie obe osi naraz a bližšia
    # z nich: pixel v rohu nemá platného suseda ani v riadku, ani v stĺpci
    # a ostal by so sentinelom v dlaždici
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
        # medzi dvomi platnými stranami sa prechádza lineárne, nie skokom na
        # bližšiu – v diere v modeli by sa výplne stretli v strede a spravili šev
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

    Váha = koľko známych pixelov do bunky spadlo.
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

    Nie `np.repeat`: z toho sú štvorčeky 2×2 a hillshade z ich hrán kreslí mriežku.
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

    Zvára šev medzi doplnenou a známou stranou. Beží na každej úrovni
    pyramídy, preto stačia štyri priechody.
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

    Rovina 0 m aj `vypln_nodata` tu robia stenu: hranica kraja nie je rovná,
    takže riadkové dopĺňanie berie susedné riadky z celkom iných miest.
    Namiesto toho pyramída priemerov (pull-push) so zváraním švov na každej
    úrovni; reliéf smerom von slabne. O(n).

    `znam` je maska platných výšok (kraj aj s rezervou `--edge`); mimo nej sa
    `grid` prepíše. `krok` zaokrúhľuje len doplnené výšky – ich zlomkové bity
    sú pre kompresiu šum.
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
