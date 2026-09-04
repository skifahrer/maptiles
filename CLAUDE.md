# CLAUDE.md

Pipeline na vektorové mapy Slovenska (OSM ─► PMTiles). `workers/` = kroky
pipeline (priečinok = job, súbor = krok), `.github/workflows/` = CI,
`poc/web/` = webový viewer, `docs/` = návrhy a rozbory.

Podrobne: `workers/README.md`.

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
