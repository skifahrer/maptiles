#!/usr/bin/env python3
"""Čo sa zapíše tam, kde výšku nemáme alebo nechceme.

Diera v modeli sa dopĺňa okolím (`vypln_nodata`), za hranicou kraja je rovina
(`zarovnaj_za_hranicou`) – tieňovanie ani skaly nesmú siahať mimo kraja.
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


def vyska_okraja(grid, znam):
    """Medián výšky na okraji kraja – rovina za hranicou, nech je stena čo najnižšia."""
    vnutro = znam.copy()
    vnutro[1:, :] &= znam[:-1, :]
    vnutro[:-1, :] &= znam[1:, :]
    vnutro[:, 1:] &= znam[:, :-1]
    vnutro[:, :-1] &= znam[:, 1:]
    okraj = grid[znam & ~vnutro]
    if not okraj.size:
        okraj = grid[znam]
    return float(np.median(okraj)) if okraj.size else 0.0


def zarovnaj_za_hranicou(grid, znam, vyska):
    """Mimo kraja jedna výška pre celý beh – rovina nemá sklon, tak sa netieňuje."""
    return np.where(znam, grid, np.asarray(vyska, dtype=grid.dtype))
