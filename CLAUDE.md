# CLAUDE.md

Pipeline na vektorové mapy Slovenska (OSM ─► PMTiles). `workers/` = kroky
pipeline (priečinok = job, súbor = krok), `.github/workflows/` = CI,
`poc/web/` = webový viewer, `docs/` = návrhy a rozbory.

Podrobne: `workers/README.md`.

## Pull requesty: merge až na zelenom

**Nemerguj PR, kým kontroly nie sú zelené a pipeline naozaj neprebehla.**

- `Kontrola · lint workflowov` musí byť zelená na HLAVIČKE PR, nie na
  niektorom staršom commite vetvy.
- Žiadny konflikt s `master`.
- Kontrola musela naozaj zbehnúť: beh bez jobu neoveril nič, a zelená
  z iného commitu nehovorí o tomto.

Lint sa spúšťa len na zmenu v `.github/workflows/**`, `workers/**` a
`poc/web/**`. Commit do `maps.json` ho nespustí, takže posledný výsledok na
`master` môže byť starý aj o dni. Keď na tom záleží, pusti workflow ručne
(`workflow_dispatch`), alebo lokálne: `workers/lint/*.py` a `workers/lint/*.mjs`.

Červenú kontrolu treba opraviť, alebo pri PR napísať, prečo nie je jeho.
Test ani lint sa kvôli zelenej nevypína.

## Komentáre: čo najmenej slov

**Toto je tvrdé pravidlo. Komentár má mať pár slov, nie odsek.**

- Jeden riadok. Ak nestačí, väčšinou netreba komentár, ale lepší názov.
- Píš **prečo**, nikdy nie **čo** – to je vidieť z kódu.
- Žiadne eseje, história rozhodnutí, čísla z meraní, príklady behov,
  zoznamy alternatív ani „PREČO NIE …" state. To patrí do `docs/`
  alebo do commit message, nie nad funkciu.
- Docstring: jedna veta. Žiadne sekcie `Použitie:`, `Args:`, `Pozor:`.
- Nekomentuj samozrejmosti, zakomentovaný kód maž.
- Slovensky, malé písmená, bez dekoratívnych oddeľovačov (`# ---`, `# ===`).

Dobre:

```python
# GDAL zaokrúhľuje nadol, preto +1
zoom = floor(z) + 1
```

Zle:

```python
# ZAOKRÚHĽOVANIE. GDAL pri prepočte rozlíšenia zaokrúhľuje nadol, čo
# znamená, že pri hranici 1,4 m/px vyjde o úroveň menej, než čakáme.
# Skúšali sme to riešiť aj cez ...
```

Výnimka: direktívy (`# noqa`, `# shellcheck disable=…`), shebang, licenčné
hlavičky a `yaml`/`workflow` kľúče, kde komentár nesie hodnotu.
