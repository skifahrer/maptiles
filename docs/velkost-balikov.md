# Prečo sú balíky veľké a čo sa z nich dá vyhodiť

Analýza balíkov (`.zip` / `.aar`), ktoré si mobilná aplikácia sťahuje z Drive.
Čísla sú z `maps.json` (stav 2026-08-23) a z premerania zdrojov, z ktorých
pipeline balíky skladá.

## Čo dnes vážia balíky

| región | mapa (zip) | vrstevnice-skaly | tienovanie | search |
|---|---|---|---|---|
| bratislavsky | 130,9 MB | 26,7 MB | 71,5 MB | 6,1 MB |
| presovsky | 218,8 MB | 139,7 MB | 112,9 MB | 6,5 MB |
| trnavsky | 141,0 MB | 45,7 MB | 49,1 MB | 4,0 MB |

## Z čoho je základná mapa

`zaklad_subory()` v `workers/deploy/publish-map.py` berie **celý `_site`**
okrem vrstevníc, skál a tieňovania. V `_site` pritom leží aj to, čo mapa
nepotrebuje.

Rozpis pre `bratislavsky.zip` (fonty premerané presne, `search` z katalógu,
dlaždice dopočítané ako zvyšok):

| položka | v ZIPe | podiel |
|---|---|---|
| **fonty (`_site/fonts`)** | **61,2 MB** | **47 %** |
| dlaždice `.pmtiles` (mapa, trasy, prvky, cesty) | ~62 MB | 47 % |
| `search-index.db` | 6,1 MB | 5 % |
| sprity + viewer + `region.geojson` | ~1,5 MB | 1 % |

Fonty sú v každom regióne rovnaké, takže tých 61,2 MB je konštanta vo
**všetkých** balíkoch.

## Nález 1 – fonty: 60 MB znakov, ktoré mapa nikdy nevykreslí ✅ opravené

> Opravené v `workers/assets/glyphs.sh`: rozsahy sa orežú na
> `GLYPHS_KEEP_RANGES` (predvolene latinka, gréčtina, cyrilika,
> interpunkcia). Zmerané na origináli balíka: zo 768 súborov ostane 51,
> z 61,2 MB v ZIPe ostane 1,7 MB. Zvyšok tejto sekcie popisuje stav pred
> opravou.

`workers/assets/glyphs.sh` skopíroval z `noto-sans.zip` celé fontstacky:

```bash
copy_matching '^Noto Sans (Regular|Bold|Italic)$'   # cp -r "$d" _site/fonts/
```

`cp -r` vezme adresár **so všetkými 256 rozsahmi** – vrátane CJK, arabčiny,
hebrejčiny, thajčiny, dévanágarí a emoji. Premerané na origináli:

| variant | súborov | RAW | v ZIPe |
|---|---|---|---|
| všetko (dnešný stav) | 768 | 99,7 MB | **61,2 MB** |
| bezpečný výber | 48 | 3,4 MB | **1,7 MB** |
| minimum (latinka + cyrilika + interpunkcia) | 24 | 2,3 MB | 1,1 MB |

Štýl používa tri fontstacky (`REG`, `BOLD`, `ITAL` v `poc/web/themes.js`),
takže vyhodiť sa nedá ani jeden – ale rozsahy nad U+2000 áno. Mapa je
`--languages=sk,en`; čínsky názov v nej nie je z čoho vzniknúť.

**Úspora: 59,5 MB z každého balíka mapy.**

Kontrola v `workers/deploy/check.sh` overuje len existenciu
`$SITE/fonts/$stack/0-255.pbf` a smoke test siaha na ten istý súbor, takže
orezanie rozsahov ani jednému neprekáža.

Vedľajší efekt, ktorý oprava rieši spolu s tým: `BUDGET_ASSETS_MB: "40"`
v `build-map-region.yml` počítal s tým, že fonty a ikonky majú 40 MB. Mali 100 MB,
takže rozpočet na dlaždice bol o ~60 MB optimistickejší, než aká bola
skutočnosť. Po oreze sa do tých 40 MB zmestia s veľkou rezervou.

Pozor na cache: kľúč `assets-…` v `build-map-region.yml` `workers/assets/glyphs.sh`
neobsahoval, takže samotná zmena zoznamu rozsahov by sa neprejavila – cache by
vrátila staré (širšie) fonty. Preto je skript teraz v `hashFiles(...)`.

## Nález 2 – `search-index.db` je v balíku dvakrát ✅ opravené, potom prehodnotené

> Opravené v `workers/deploy/publish-map.py`: `hladanie_subory()` sa počíta
> raz a to isté pole išlo aj do `vylucit` základnej mapy. Overené na
> zabalených ZIPoch – index bol potom práve v jednom balíku.
>
> **A práve to sa ukázalo ako zlá odpoveď na správny nález.** Dvakrát v balíku
> bola chyba; vlastný balík ale nie je jej jediná oprava a je to tá horšia
> z dvoch. Odstránené je odteraz to ZDVOJENIE (index je v balíku raz),
> a je v tom, ktorý si človek naozaj stiahne – v ZÁKLADNEJ MAPE. Balík
> `-search` zanikol (`ZRUSENE`), starý sa na Drive maže a `maps.json` má
> veľkosť indexu pod balíkom `mapa` v `casti.search.raw_size`. Tým istým
> spôsobom sa do mapy dostal aj navigačný graf Valhally – a **pri ňom to
> neplatí a je to zmerané**: graf kraja váži 170–190 MB a mapa s ním 283 MB,
> čiže dve tretiny „základnej mapy". To nie sú percentá, to je ten istý
> prípad ako vrstevnice a tieňovanie, takže má odteraz vlastný balík
> `-navigacia.zip` a v katalógu vlastnú položku (`maps.navigacia`), nie
> `casti`. Rozdiel oproti indexu je práve to číslo, nie iná úvaha –
> `docs/navigation.md` §7a.
>
> Dôvod je v poslednom odseku tejto sekcie a v čísle: úspora 4–6,5 MB na
> balíku, ktorý má 65–152 MB, je 4–8 %. Za to sa kúpila mapa, v ktorej
> hľadanie nefunguje, a to bez jediného slova – aplikácia sa na druhý balík
> nepýta a v katalógu ho nikto nehľadá. Kde tá úvaha platí ďalej, sú
> vrstevnice, skaly a tieňovanie: tie vážia toľko čo mapa sama (tabuľka
> vyššie), takže tam je „nechcem to sťahovať" naozaj o polovicu sťahovania,
> nie o percentách.

```python
vrstvy_pack = vrstvy_subory(args.site, man)
tien_pack   = tienovanie_subory(args.site, man)
baliky = [
    ("", "…", args.site, zaklad_subory(args.site, vrstvy_pack + tien_pack)),
    …
    ("search", "…", args.site, hladanie_subory(args.site, man)),
]
```

Zo základnej mapy sa vynímajú `vrstvy_pack` a `tien_pack`, ale **nie**
`hladanie_subory`. `_site/tiles/search-index.db` je preto aj v
`<región>.zip`, aj v `<región>-search.zip`. Ten balík vznikol práve preto, aby
sa index sťahovať nemusel.

**Úspora: 4,0 – 6,5 MB podľa regiónu.**

Katalóg ani `manifest.json` o indexe nevedeli – appka ho hľadá skenovaním
stiahnutého priečinka na `.db` so slovom „search" v mene. Vybratie zo
základnej mapy teda nič nerozbilo; kto chcel hľadanie, stiahol si `-search`,
presne ako pri vrstevniciach. **Bola to ale zmena správania:** kto si stiahol
len základnú mapu, hľadanie mal; po oprave ho nemal, kým si nestiahol aj druhý
balík – a nemal sa to ako dozvedieť. Presne táto veta bola dôvod, prečo sa
delenie vrátilo späť: mlčanie tu neznamená „nemáš to zapnuté", ale „mapa je
pokazená". Katalóg o indexe odvtedy vie (`casti.search`), takže sa jeho
veľkosť dá prečítať bez toho, aby sa musel oddeliť do vlastného súboru.

## Nález 3 – dlaždice sú stavané na maximálny detail

`workers/tiles/build.sh` prepisuje tri Planetiler prepínače proti ich
predvoleným hodnotám (overené cez `planetiler --help`):

| prepínač | default | v repozitári |
|---|---|---|
| `min_feature_size_at_max_zoom` | 0.0625 | **0** |
| `simplify_tolerance_at_max_zoom` | 0.0625 | **0** |
| `building_merge_z13` | true | **false** |

Je to zámer – viewer prezoomováva z16 až na z20, takže sa na z16 nič
nezahadzuje ani nezjednodušuje. Ale je to zároveň jediný väčší zdroj
veľkosti dlaždíc, ktorý je pod kontrolou repozitára. Stojí za A/B beh
s defaultmi; bežne to býva 10–25 %.

Druhá vec: štýl kreslí `housenumber` od `minzoom: 17`, ale dlaždice končia na
z16. Súpisné čísla sú teda v dátach z14–z16 (OpenMapTiles ich tam dáva) a na
obrazovku sa dostanú len prezoomovaním. Na turistickej mape je to vrstva,
ktorá sa dá vypnúť bez toho, aby niekomu chýbala.

## Otázka 2 – zlúčiť vrstevnice a skaly do základnej mapy?

**Nie. Nezmenší to nič a zdraží to sťahovanie.**

### Na bajtoch sa nezíska

Zmeral som to na syntetických MVT dlaždiciach (`gzip` po dlaždiciach + réžia
PMTiles adresárov), štyri scenáre:

| scenár | dva `.pmtiles` | jeden `.pmtiles` | rozdiel |
|---|---|---|---|
| husté vrstevnice z16 (hory) | 23,6 MB | 23,7 MB | −0,38 % |
| riedke vrstevnice z12 (nížina) | 1,2 MB | 1,2 MB | +0,37 % |
| malé dlaždice, skaly všade | 1,0 MB | 1014 KB | +3,58 % |
| stredné, skaly v polovici | 5,9 MB | 6,0 MB | −0,49 % |

Dôvod: PMTiles komprimuje **každú dlaždicu zvlášť**. Zlúčenie ušetrí jednu
hlavičku (127 B) a jeden adresár (~3 B na dlaždicu), ale gzip stream navyše
stojí ~18 B na dlaždicu – to sa navzájom vyruší. Zisk je merateľný len tam,
kde sú dlaždice tak malé, že réžia streamu prevažuje, a to práve vrstevnice
na z16 nie sú.

### Na sťahovaní sa stratí

To podstatné je, že dnes si vrstevnice a skaly stiahnuť **nemusíš**:

| región | základná mapa | +vrstevnice-skaly | zlúčené (povinne) |
|---|---|---|---|
| bratislavsky | 130,9 MB | 26,7 MB | 157,6 MB |
| presovsky | 218,8 MB | 139,7 MB | **358,5 MB** |
| trnavsky | 141,0 MB | 45,7 MB | 186,7 MB |

Pri Prešovskom kraji by sa základná mapa zväčšila o 64 %. Delenie na balíky
je presne to, čo veľkosť sťahovania rieši – a hlavička `publish-map.py` to
takto aj popisuje.

## Čo z toho vyjde

Nálezy 1 a 2 sú čistý zisk – nič sa v mape nezmení, len sa prestane baliť to,
čo sa nepoužíva:

| región | pôvodne | po oprave 1 (+2 ako zdvojenie) |
|---|---|---|
| bratislavsky | 130,9 MB | ~71 MB (−46 %) |
| presovsky | 218,8 MB | ~159 MB (−27 %) |
| trnavsky | 141,0 MB | ~82 MB (−42 %) |

(Index je v tých číslach ZAPOČÍTANÝ raz – v základnej mape, kde je odteraz aj
navigačný graf. Zmizlo len to, čo tam bolo dvakrát.)

**Pozor na aritmetiku vyššie.** Medzitým pribudlo (`d0f4dfd`, mimo tejto
analýzy), že glyfy a viewer sa do balíka nebalia vôbec, keď na ne manifest
odkazuje absolútnou adresou na Pages. Kde to platí, je fontov v balíku 0 MB
a úspora z nálezu 1 sa v tom balíku už neprejaví druhýkrát – orez rozsahov
tam šetrí Pages a mapu sveta, nie sťahovanie do mobilu. Tabuľka platí pre
balík, ktorý si glyfy nesie (manifest s relatívnym odkazom).

Nález 3 je kompromis medzi detailom a veľkosťou – ten sa oplatí zmerať A/B
skôr, než sa o ňom rozhodne.

Čo naopak **nemá zmysel** riešiť: sprity (všetky tri sady majú v zdroji dokopy
~380 KB) a viewer (`poc/web` má 576 KB). Sú to promile.
