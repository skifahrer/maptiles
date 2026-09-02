# fricomaps

All-in-one mapová aplikácia. Vektorové mapy Slovenska z OSM dát – jedna
pipeline, jeden formát (PMTiles), spoločné štýly pre web aj mobil.

## Štruktúra monorepa

```
app/ios/       iOS aplikácia (SwiftUI + MapLibre Native)
backend/       NestJS backend (API – regióny, budúce užívateľské veci)
poc/web/       proof-of-concept web viewer (MapLibre GL JS + PMTiles)
               + developer mode na ladenie štýlu priamo v prehliadači
workers/       pipeline: regióny, výškové dlaždice, značené trasy, generátor
               štýlov, SDF sprite, vzory do spritu, zápis úprav štýlu,
               skaly zo sklonu DEM aj z tmavých plôch v tieňovaní
docs/          návrhy (iOS / multiplatform), podrobný popis pipeline
.github/workflows/  CI pipeline (výškový model + build mapy + deploy Pages
                    + pokusné skaly z tieňovaných dlaždíc)
```

> Podrobne – čo robí každý krok, aké formáty medzi sebou putujú a prečo –
> je v [docs/pipeline.md](../docs/pipeline.md).

## Ako funguje pipeline

```
Mapa · Build map             deväť jobov, tie dlhé bežia súbežne:
(manuálne, výber regiónu)      plan     región + PBF z osm.fr exportov
                               tiles    Planetiler ─► {región}.pmtiles
                               contours vrstevnice + skaly z DEM
                               terrain  tieňovanie a 3D ako raster .pmtiles
                               trails   značené trasy z OSM relácií
                               assets   SDF sprity a glyfy
                               deploy   zloží _site ─► GitHub Pages
                               apple-archive  balíky ešte raz ako .aar
                                        (macOS runner – nástroj `aa`)

Mapa · Build wiki            objekty regiónu s `wikipedia`/`wikidata`
(manuálne, ten istý región)  ─► články (NDJSON, dávky po 50)
                             ─► {región}-wikipedia.zip na Drive
                             ▲ na Pages NEJDE – do `_site` z toho nič
                             ▲ vlastná pipeline: iná sieť, iná životnosť

Mapa · Build svet            základná mapa CELÉHO sveta – podklad pod výber
(manuálne, raz za dlho)      „ktorý kus si stiahnuť":
                               vodstvo z pobrežných čiar OSM
                               hranice štátov a jazerá z Natural Earth
                               regióny sťahovania z indexu Geofabriku
                             ─► svet.zip a svet.aar na Drive
                             ▲ NIE z planet.osm.pbf (80 GB sa na runner nezmestí)
                             ▲ cesty, sídla ani terén v nej nie sú

Dáta · výškové modely        Sonny 20m / ÚGKK DMR 3.5 ─► rezanie
(sám, keď terén chýba)       na 1° dlaždice ─► sklad `dem-sonny`:
                             N49E019.tif + meta.json
                             ▲ Build map ho zavolá automaticky, keď v sklade
                               nie je pre jeho územie ani jedna dlaždica

Dáta · DMR 5.0               145 GB BigTIFF + 43 GB pyramíd na Google Drive,
(toto si volá Build map)     čítané cez HTTP Range – berie sa len to, čo
                             výrez pretína:
                               výrez (1 m)          ─► `dem-ugkk` ┐ jeden zdroj
                               1° dlaždice (5 m)    ─► `dem-dmr5` ┘ `dmr5`
                             ▲ výšky sú elipsoidické, prevádzajú sa cez EGM2008
                             ▲ toto je zdroj pre skaly v plnom rozlíšení
                             ▲ Build map ju volá DVOMA jobmi (výrez + dlaždice),
                               lebo model má dve podoby a chýbať môžu naraz


Dáta · tieňované skaly       POKUS: hillshade JPG z freemap.sk ─► tmavé
(pokus, na jedno pohorie)    plochy ─► polygóny ─► sklad `dem-rocks-img`
                             ▲ Build map si ich vypýta výberom
                               rock_source: tienovanie

Mapa · úpravy štýlu          style-overrides.json z developer módu
(po doladení mapy)           ─► kontrola + prečistenie
                             ─► poc/web/style-overrides.json v repozitári
```

- **Výber regiónu:** celé Slovensko alebo ktorýkoľvek z 8 krajov. Zdroj je
  [osm.fr](https://download.openstreetmap.fr/extracts/europe/slovakia/)
  (rezané po skutočných administratívnych hraniciach, denne aktualizované);
  mapovanie a presné bboxy z osm.fr rezacích polygónov sú vo
  [workers/data/regions.json](data/regions.json). **Kraj sa REŽE z rodiča** –
  stiahne sa `slovakia-latest.osm.pbf` (373 MB) a `osmium extract -s smart
  -S types=multipolygon,boundary --polygon` z neho vyreže kraj po jeho `.poly`
  (~30 s; rozpis [workers/plan/pbf.sh](plan/pbf.sh), stráži
  [workers/lint/pbf-source.py](lint/pbf-source.py)). Cache nesie dátum, takže
  sa v rámci dňa sťahuje raz.

  **Hotový `{kraj}-latest.osm.pbf` z osm.fr sa nepoužíva, hoci existuje**
  (36 MB, rezaný po tej istej hranici): nie je referenčne úplný. Ploche, ktorá
  pokračuje do susedného kraja, v ňom chýbajú členské cesty a Planetiler ju
  zahodí **celú** – aj tú časť, čo v kraji leží. Namerané na Bratislavskom
  kraji: z 3075 plošných relácií malo 250 chýbajúceho člena, z toho 49
  krajinnej pokrývky a ochrany prírody – chýbala CHKO Malé Karpaty, CHKO
  Záhorie, CHKO Dunajské luhy, NPR Aluvium Moravy, les Záhoria (relácia s 1011
  členmi) aj Zdrž Hrušov. Po reze z rodiča ostane päť a všetky sú na rakúskej
  hranici (ich členovia nie sú ani v slovenskom extrakte). Koľko ich v behu
  naozaj je, počíta [workers/plan/pbf-areas.py](plan/pbf-areas.py) a píše to do
  logu aj do súhrnu behu.
- **Ľubovoľný región Európy/sveta:** pri spúšťaní workflowu vyplň
  `custom_pbf_url` (URL na `.osm.pbf` z osm.fr extracts stromu, napr.
  `https://download.openstreetmap.fr/extracts/europe/austria.osm.pbf`)
  a `custom_name`. Bbox sa prečíta z PBF hlavičky (alebo zadaj `custom_bbox`).
- **Typy máp:** [poc/web/map-types.js](../poc/web/map-types.js) – **turistická,
  lyžiarska, cestná, historická** a základná („všetko"). Typ mapy hovorí, *čo*
  mapa ukazuje; téma len to, *ako* to vyzerá. Viď
  [Typy máp](#typy-máp--čo-ktorá-mapa-ukazuje).
- **Témy a štýlovanie:** [poc/web/themes.js](../poc/web/themes.js) – 4 farebné
  témy (Svetlá, Tmavá, Outdoor, Retro/Pastel), ~140 vrstiev pokrývajúcich celú
  OpenMapTiles schému: krajinná pokrývka, využitie územia, voda a vodné toky,
  budovy (od z16 v 3D), cesty vrátane chodníkov/cyklotrás/schodov, mosty a
  tunely, železnice, lanovky, hranice až po obce, súpisné čísla, vrcholy hôr,
  letiská a POI s ikonkami zo spritu osm-liberty (maki). Všetky nápisy majú
  jemný obrys (`textHalo`), aby zostali čitateľné nad ľubovoľným podkladom;
  pohoria, hrebene a geografické oblasti sa od nízkych zoomov kreslia
  kurzívou a verzálkami, aby sa nepliedli so sídlami.
  Ten istý generátor vyrába statické `styles/{region}-{typ mapy}-{tema}.json`
  pre iOS (predvolený typ aj pod starým menom `{region}-{tema}.json`).
- **Značené trasy:** turistické chodníky, cyklotrasy, bežky, ferraty
  a jazdecké trasy z OSM relácií – ako farebné pásiky **vedľa** cesty,
  s názvom pozdĺž trasy.
  Viď [Značené trasy](#značené-trasy-turistika-cyklo-bežky).
- **Krajinné prvky mimo schémy:** násypy, zárezy, múry, ploty, elektrické
  vedenia, prieseky, pramene, jaskyne, rozhľadne, parkoviská a zjazdovky.
  Schéma OpenMapTiles ich nemá vôbec, takže majú vlastné dlaždice.
  Viď [Krajinné prvky](#krajinné-prvky-čo-openmaptiles-nemá).
- **Ikonky bez podkladov, s farbou:** hotové sprity kreslia symboly na
  podklade (osm-liberty v bielom koliesku, osm-bright so svetlým halom) a
  farbu im meniť nejde. Pipeline z každého zdroja vyrobí vlastný **SDF sprite**
  ([workers/assets/sprite.mjs](assets/sprite.mjs)), kde je len
  samotný symbol a dá sa mu nastaviť `icon-color` aj `icon-halo-color`.
- **Tri sady ikoniek** ([poc/web/icon-sources.js](../poc/web/icon-sources.js)) sa
  nasadzujú všetky naraz, takže sa dajú v developer móde prepínať naživo.
- **Developer mode:** ladenie mapy priamo v prehliadači – viď nižšie.

## Nadmorská výška, vrstevnice a skaly

**OpenStreetMap výškové dáta neobsahuje.** Má len bodový tag
[`ele`](https://wiki.openstreetmap.org/wiki/Key:ele) na vrcholoch, sedlách,
prameňoch či staniciach — žiadny terénny model, a vrstevnice sa doň zámerne
nenahrávajú. Každá OSM mapa s reliéfom (OpenTopoMap, OpenAndroMaps, Waymarked
Trails) preto kombinuje OSM s externým DEM. Robíme to rovnako:

| čo | zdroj | kde sa berie |
|---|---|---|
| výšky vrcholov | OSM tag `ele` | už v dlaždiciach, vrstva `mountain_peak` |
| **vrstevnice a skaly** | **Sonny's LiDAR DTM, model 20m** | náš sklad `dem-sonny` na Drive (napĺňa ho workflow *Dáta · výškové modely*) |
| **tieňovanie reliéfu, 3D terén** | **ten istý Sonny DEM** | vlastný raster `.pmtiles` (terrarium PNG vnútri), uložený v sklade `dem-terrain` |
| tieňovanie a 3D – záloha | AWS Terrain Tiles (Terrarium) | [registry.opendata.aws](https://registry.opendata.aws/terrain-tiles/), keď sa vlastné nevyrobia |

Tieňovanie reliéfu je **predvolene vypnuté** – na farebnej mape prekrýva
odtiene plôch a pri malých mierkach z nej robí hnedý šum. Zapína sa
prepínačom v paneli ⚙ (a takto zapnuté sa aj zapečie do štýlu pre iOS).

### Zdroj výšok: Sonny's LiDAR DTM, model **20m**

[Sonny's LiDAR DTM](https://sonny.4lima.de/) je **model terénu z LiDARu** –
na rozdiel od Copernicus GLO-30, ktorý je *DSM*, teda model povrchu vrátane
stromov a striech. V lese preto vrstevnice sedia na zemi, nie na korunách, a
skalné steny nie sú rozmazané vegetáciou. Práve preto je predvoleným zdrojom.

Sonny ponúka pre Slovensko dva použiteľné modely a **berieme 20m**:

| model | formát | vodorovne | **zvisle** |
|---|---|---|---|
| **20m** | GeoTIFF | 20 × 20 m | **0,1 m** |
| 1″ | `.hgt` | 20,3 × 30,9 m | 1 m |

Rozhoduje ten zvislý krok. Z metrových schodov vychádza schodíkovitý sklon,
ktorý súvislú skalnú stenu roztrhá na kopu falošných úlomkov – namerané na
tom istom území Vysokých Tatier:

| zvislé rozlíšenie | skalných plôch | plocha skál | bodov na obrys |
|---|---|---|---|
| 0,1 m (20m model) | 2 138 | 4 218 ha | 195 |
| 1 m (1″ `.hgt`) | 5 293 | 4 223 ha | 101 |

Rovnaká celková plocha skál, ale z metrových dát je z nej **2,5× viac
polámaných kúskov s hrubším obrysom**. Viac polygónov tu teda neznamená viac
detailu, ale viac šumu.

Vidno to aj na jednom bode: v dlaždici `N49E020` vyjde Gerlachovský štít
**2 646 m** oproti oficiálnym 2 654,4 m (−8,4 m), kým DMR 5.0 cez pipeline dá
2 653,92 m (−0,5 m). Bunka 20 × 31 m vrchol jednoducho zroluje.

**1″ model sa dá zvoliť** – je vo výberoch ako `sonny1` (sklad `dem-sonny1`,
[priečinok na Drive](https://drive.google.com/drive/folders/1FCXPutDU6DvnTEA4PY6iFOQKiuVd11j4)).
Predvolený nie je a podľa tabuľky vyššie ani nemá byť: na skaly je `sonny`
lepší a `dmr5` ešte lepší. Zmysel dáva tam, kde 20m model nesiaha, alebo keď
si chceš to porovnanie zopakovať. Doplní sa ako ktorýkoľvek iný zdroj – buď
sám (`Build map` si ho vypýta), alebo ručne cez *Dáta · výškové modely* so
`what: sonny1`.

**Čo v tom priečinku naozaj je** (prečítané 2026-08-11, nie odhadnuté): 15
dlaždíc `N47E017` … `N49E022`, každá ako `<dlaždica>.zip` s jedným
`<dlaždica>.hgt` s 25 934 402 B = 3601 × 3601 × int16 (čiže 1″), spolu ~146 MB
na stiahnutie. K tomu `_Readme.txt` a mapka pokrytia `_Region.jpg`. Výšky sú
nad morom v národnom systéme (Bpv), nie elipsoidické, takže sa neprepočítavajú.

Dve veci, ktoré z toho readme stoja za zapamätanie. Priečinok sa volá
„…1asec **v1**", ale readme v ňom je od **verzie 2** – meno priečinka o verzii
nehovorí. A **zdroj tých dát je DMR 5.0**: readme uvádza „ÚGKK: DTM v5.0
(1 Meter)", prevzorkované na 1″ a zaokrúhlené na celé metre. Na Slovensku je
`sonny1` teda ten istý LiDAR, aký si pipeline berie priamo z Drive v 1 m
(výrez) alebo 5 m (región) – len zahodený. Za hranicou je výplň zo SRTM v3
alebo Viewfinder Panoramas, čiže nie LiDAR.

**Chce prihlásenie na Drive**, a nie kvôli limitu: všetkých 15 dlaždíc je
v priečinku ako **skratka** (shortcut) na súbor inde. Verejné
`uc?export=download` na skratku odpovie „Only the owner and editors can
download this file", hoci cieľ zdieľaný je, a `gdown --folder` na tom padne –
stiahne len readme a mapku. Skratky rozuzľuje `workers/drive/folder.py`
(funkcia `rozuzli`) cez Drive API a bez tokenu krok skončí hláškou, ktorá to
povie rovno, namiesto aby posielal riešiť práva, ktoré sú v poriadku.

Sonny distribuuje dáta cez **Google Drive**, z ktorého sa v každom builde
sťahovať nedá (nemá stabilné priame URL a pri väčšom počte stiahnutí vracia
limit). Preto je medzi tým **zrkadlo v releasi**:

```
Google Drive (priečinok krajiny)
  → workers/drive/folder.py   stiahne celý priečinok, prihlásene cez Drive API
                              (bez tokenu gdown a s varovaním o limite)
  → 7z / unzip         rozbalí .zip
  → workers/dem/tiles.py   GeoTIFF (aj celá krajina v metrickej projekcii)
                           → dlaždice 1°×1° N49E019.tif vo WGS84
     (.hgt sa prevádza priamo – je to už 1° dlaždica, len bez hlavičky)
  → sklad `dem-sonny` + meta.json
```

Rezanie na dlaždice je potrebné preto, že 20m model môže byť **jeden GeoTIFF
na celú krajinu a v metrickej projekcii**, kým build mapy chce sťahovať len
dlaždice pre svoj bbox a lepiť ich `gdalbuildvrt`-om (ten rôzne projekcie
v jednom VRT neunesie). Jeden sklad = jeden model; miešať 20m a 1″ v jednom
sklade nemá zmysel, dlaždice sa volajú rovnako.

Build mapy si potom vypýta **len tie dlaždice, ktoré pokrývajú jeho bbox**.
Bbox je obdĺžnik, ale produkt pokrýva krajinu – rohové bunky za hranicou
(u Slovenska napr. `N47E016` v Maďarsku) v ňom nikdy nebudú. Chýbajúce
dlaždice sú preto **varovanie so zoznamom**, nie chyba: tam jednoducho nebude
terén. Build zlyhá až vtedy, keď pre dané územie nie je **ani jedna**.

> **Copernicus GLO-30 ako záloha je zámerne vypnutý.** Je to model *povrchu*:
> vrstevnice by v lese viedli po korunách stromov a skaly by vychádzali
> z vegetácie. Keby sa ním chýbajúce dlaždice ticho dopĺňali, časť mapy by
> klamala a nikde by nebolo vidieť, ktorá. Radšej nech build povie, že terén
> chýba. Zapnúť sa dá vrátením sťahovania z `copernicus-dem-30m.s3.amazonaws.com`
> do kroku *Vrstevnice a skaly z DEM*.

Licencia Sonny's DTM je CC BY 4.0, zdroj sa uvádza v atribúcii mapy.

### Vrstevnice

Počítajú sa v pipeline a končia vo **vlastnom `.pmtiles`**, takže fungujú na
webe aj na iOS cez ten istý `style.json`:

```
DEM (1°×1° dlaždice pre bbox: dem-sonny, doplnené Copernicusom)
  → gdalwarp   orez na bbox (zjemnenie DEM je predvolene vypnuté – vrstevnice
               sa trasujú z plného rozlíšenia; `contour_smoothing` v oblúkových
               sekundách ho vie zapnúť, 2 = pôvodné hladenie)
  → gdalwarp   vyhladí DEM: priemer v okne 2 m (`-r average` na hrubšiu
               mriežku a `-r cubicspline` späť na pôvodnú). Pri hrubom modeli
               vyjde okno na jednu bunku a nerobí sa nič
  → gdal_contour -i 10
  → ogr2ogr    dopočíta `level`: major (100 m) / mid (50 m) / minor (10 m)
               a `-simplify` zmaže schodíky po hranách buniek DEM
               (tolerancia: štvrtina bunky)
  → smooth-shapes.py  zaoblí rohy, čo po zjednodušení ostali ostré
                      (limitná krivka, vzorkovaná podľa mriežky dlaždice)
  → planetiler generate-custom --schema=workers/contours-rocks/contours.yml
  → {región}-contours.pmtiles
```

**Zubatosť robí mikroreliéf v modeli, nie mriežka – a preto sa hladí DEM, nie
len čiara.** `gdal_contour` interpoluje priesečník na hrane bunky, takže
z hladkého poľa výšok vyjde hladká čiara aj bez akýchkoľvek úprav. Čo ju krčí,
je to, čo je v LiDARovom DTM naozaj: kry, balvany, šum merania na úrovni
decimetrov. Zaoblenie čiary to vlnenie len **zaokrúhli**, neodstráni.

**Lenže v tom okne nie je len šum – a práve tým sa vrstevnice zaoblili
priveľmi.** Rebro, žľab či terasa široká pár metrov sú tvary, ktoré v teréne
naozaj sú, a priemer v okne 5×5 ich zmazal spolu s krami: čiara potom nebola
zubatá, ale ani sa nedržala terénu. Merané na simulovanom teréne, ktorý má
okrem šumu (σ = 0,15 m na 1 m mriežke) aj **reálne tvary** s vlnovou dĺžkou
60, 25 a 12 m; „odchýlka" je vzdialenosť od izolínie toho istého terénu **bez**
šumu, posledné dva stĺpce hovoria, koľko z tvaru na čiare ostalo:

| postup | bodov | priemerný lom | lomov > 30° | odchýlka | tvar 25 m | tvar 12 m |
|---|--:|--:|--:|--:|--:|--:|
| izolínia terénu bez šumu (referencia) | 1420 | 5,6° | 4,1 % | 0,04 m | 99 % | 98 % |
| bez vyhladenia, 1/4 bunky, 1× Chaikin (do augusta) | 1908 | 31,3° | 43,4 % | 0,86 m | 100 % | 93 % |
| okno 5×5, 1/2 bunky, 2× Chaikin (august) | 436 | 10,6° | 4,1 % | 1,52 m | 75 % | **27 %** |
| okno 3×3, 1/2 bunky, 2× Chaikin | 604 | 10,7° | 4,2 % | 0,95 m | 90 % | 52 % |
| **okno 3×3, 1/4 bunky (dnešné okno a tolerancia)** | **860** | **8,2°** | **1,6 %** | **0,70 m** | **93 %** | **63 %** |
| okno 7×7, 1/2 bunky, 2× Chaikin | 336 | 10,8° | 3,0 % | 2,23 m | 58 % | **5 %** |

Meria to [`workers/contours-rocks/measure-smoothing.py`](contours-rocks/measure-smoothing.py) – nie
je to časť pipeline, nevolá to žiadny workflow a stačí naň numpy, takže sa
tabuľka dá kedykoľvek zopakovať (`python3 workers/contours-rocks/measure-smoothing.py`).

(Zaoblenie bolo v čase toho merania ešte Chaikinovo – o tom je tabuľka
o kus nižšie; okna a tolerancie sa tá zmena netýka.)

Kľúčové je porovnanie tretieho a piateho riadku: **menšie okno nie je ústupok
zubatosti**. Priemerný lom je menší (8,2° oproti 10,6°), ostrých lomov je
1,6 % namiesto 4,1 % a odchýlka od skutočnej izolínie klesla z 1,52 na 0,70 m –
čiara je zároveň hladšia **aj** vernejšia. Platí sa **bodmi**: 860 namiesto
436, stále však o 55 % menej než pred augustom.

Okno sa zadáva **v metroch** (`CONTOUR_DEM_LOWPASS`, default 2 m), nie
v bunkách – a to je celé, prečo sa smie zapnúť predvolene. Okno je vždy
nepárny násobok bunky, takže dva metre sú na 1 m LiDARe okno 3×3, kým na 5 m
dlaždiciach DMR 5.0, na DMR 3.5 (10 m) aj na Sonnyho 20 m vyjde jedna bunka
a nevyhladzuje sa nič. Hrubý model mikroreliéf neobsahuje – je v ňom
spriemerovaný už zo zdroja – a okno „3×3 buniek" by v ňom zmazalo desiatky
metrov terénu. Priemer robia dva `gdalwarp`y (zmenšenie s `-r average`,
zväčšenie späť s `-r cubicspline`), takže sa gigabajtový raster nemusí ťahať
cez pamäť.

**Až potom sa upratuje čiara.** `-simplify` zmaže schodíky po hranách buniek,
po ňom ostanú **ostré rohy** – a tie sa zaoblia. Zjednodušenie je na
**štvrtine** bunky, nie na polovici, a je to tá istá otázka ako veľkosť okna:
samo čiaru oblou nerobí, ale predlžuje segmenty, a zaoblenie potom reže rohy
dlhé štvrtinu segmentu – čím dlhší segment, tým väčší kus tvaru sa odreže (pri
1/2 bunky prežije z 12 m tvaru 52 %, pri 1/4 bunky 63 %).

**Zaobľuje sa LIMITNOU KRIVKOU, nie dvoma prechodmi Chaikina** – a to je tá
oprava, kvôli ktorej boli vrstevnice „vyhladené, ale v pravidelných intervaloch
zubaté". Chaikinovo orezávanie rohov ku kvadratickému B-splinu len konverguje
a robí to **lokálne**: jeden prechod roh rozpolí, dva ho zmenšia na štvrtinu,
takže zo 120° rohu ostane vyše 30°. Tie zvyšky sedia presne tam, kde nechal
vrcholy Douglas–Peucker, čiže sú **pravidelne rozostupené** – na hotovej mape
(Bratislavský kraj, `bratislavsky-contours.pmtiles`, 3 220 km čiar) ich bolo
**14,7 na kilometer**, jeden každých ~68 m. Tretí prechod ich dorovná, ale
zdvojnásobí počet bodov, a to je horšie než zuby (viď mriežku dlaždice nižšie).

Limitná krivka sa preto vyhodnotí rovno a vzorkuje sa podľa **priehybu
tetivy**: oblúk medzi vrcholmi a–b–c má od tetivy priehyb |2b − a − c| / 8
a rozdelenie na `n` dielov ho zmenší n²-krát, takže `n = ⌈√(priehyb /
tolerancia)⌉`. Tolerancia je **pol kroku mriežky dlaždice** na maxzoome tej
vrstvy – presne toľko, koľko spraví aj samotné zaokrúhlenie do dlaždice, takže
sa neplatí bodmi za detail, ktorý sa tam aj tak nezmestí. Rovná časť čiary
dostane jeden bod, zákruta toľko, koľko treba.

Merané na tom istom teréne (okno 3×3, 1/4 bunky, maxzoom z16); „zub/km" sú
ostré lomy **tvaru** – čiara sa pred meraním prevzorkuje rovnomerne, inak by
sa porovnávala hustota bodov a nie zubatosť:

| nastavenie | bodov | zub/km | tvar 12 m | zub/km po mriežke z16 |
|---|--:|--:|--:|--:|
| bez zaoblenia | 215 | 72,7 | 71 % | 68,8 |
| 1× Chaikin | 430 | 31,9 | 65 % | 32,9 |
| 2× Chaikin (do teraz) | 860 | 10,0 | 63 % | 11,0 |
| 3× Chaikin | 1720 | 4,0 | 63 % | 5,0 |
| **limitná krivka, priehyb 1/2 mriežky (default)** | **586** | **5,0** | **62 %** | **8,1** |

A to isté celou cestou cez skutočný `gdal_contour` (5 m model, 89 čiar,
`-simplify` ¼ bunky): 2× Chaikin dá 56 792 bodov a 0,7 zuba/km po mriežke z16,
limitná krivka 56 421 bodov a 0,1 – **sedemkrát menej zubov za rovnaký počet
bodov**. Štvrtinový priehyb je pri takom hrubom modeli o 35 % viac bodov za
rovnaký počet zubov, a väčšia vrstva nie je len väčšia: rozpočet stránky by jej
mohol zobrať celý zoom, čo je proti zubatosti oveľa horšie.

Ovláda to `CONTOUR_DEM_LOWPASS`, `CONTOUR_SIMPLIFY` a `CONTOUR_SMOOTH` v `env:`
build-map.yml: okno v metroch (`0` = nehladiť DEM), záporné číslo = koľko
**štvrtín** bunky DEM (`-1` = štvrtina), `0` = presná čiara, kladné číslo =
tolerancia v metroch; `CONTOUR_SMOOTH: 0` zaoblenie vypne. Všetky tri sú aj
v kľúči cache, takže po ich zmene sa vrstevnice naozaj prepočítajú.

**Pri max zoome nerozhoduje čiara, ale mriežka dlaždice.** Vektorová dlaždica
má súradnice v celých číslach na mriežke `extent` (4096) a Planetiler ju meniť
nevie, takže krok mriežky určuje maxzoom vrstevníc – pri z14 je to 0,391 m,
pri z16 0,098 m. Nad svojím maxzoomom sa dlaždice už len naťahujú, a práve to
zaokrúhlenie vidno pri najväčšom priblížení ako schodíky: čiara, ktorá má sama
1,6 % ostrých lomov, ich má po mriežke z14 rovných **11,5 %**, po z15 4,3 %
a po z16 2,1 %. Dočistiť hotovú čiaru nepomáha (zhoršuje to) – jediné dve páky
sú maxzoom a to, aby sa čiara nevzorkovala jemnejšie, než mriežka unesie
(preto je tolerancia zaoblenia zlomkom jej kroku).

Preto si vrstevnice zoom **hľadajú oboma smermi**: keď sa `.pmtiles` nezmestí
do svojho podielu rozpočtu stránky, ide o úroveň nižšie (ako doteraz), a keď
v rozpočte ostalo miesto aspoň na dvojnásobok, skúsi sa o úroveň vyššie – až
po 16. Celý kraj tak ostane na z14 (187 MB), kým výrez jedného pohoria vyjde
na z16 a pri max zoome je hladký. Voľba `contour_maxzoom` je teda želanie, od
ktorého sa začína, nie strop.

Vrstevnice sa trasujú z **plného rozlíšenia DEM** a do dlaždíc idú na
najvyššom zoome bez zjednodušovania geometrie
(`--simplify_tolerance_at_max_zoom=0`) a bez zahadzovania drobných prvkov
(`--min_feature_size_at_max_zoom=0`) – malé uzavreté krúžky na kopčekoch a
v jamách teda ostávajú. Nižšie zoomy si Planetiler zjednodušuje sám, inak by
z vrstevníc bola čierna plocha.

`level` riadi, čo je vidieť kedy: hlavné vrstevnice od **z11**, polovičné od
z12, základné od z13, popisky výšky pozdĺž hlavných od z13. To je celé to
„zjednodušene na malých mierkach": od z11 do z12 je v mape **len jedna trieda**
(hlavná vrstevnica, pri intervale 5 m po 50 m) a Planetiler ju má na každom
zoome zjednodušenú podľa veľkosti pixela.

**Pod z11 nie sú vrstevnice v mape vôbec – ani sa nedláždia.** Kedysi šla hlavná
trieda až od z1 („tvar pohoria je čitateľný aj z prehľadu"), lenže na tej mierke
sa nedá prečítať ani jedna čiara, z celej vrstvy je sivý závoj a dlaždice s ním
si prehliadač aj tak stiahne. To isté dno má aj vrstva skál. Číslo je na dvoch
miestach – `min_zoom` v [`contours-rocks/contours.yml`](contours-rocks/contours.yml)
(čo sa vyrobí) a `minzoom` vrstvy v `poc/web/themes.js` (čo sa nakreslí) – a keď
sa rozídu, nikto nič nepovie: buď platíme dlaždice, ktoré nikto nevidí, alebo je
v mape diera. Stráži to [`lint/zoom-floor.py`](lint/zoom-floor.py).

Výsledok je nacacheovaný podľa bboxu, zdroja výšok a intervalu — vrstevnice
závisia len od územia, takže sa pri ďalšom builde mapy nepočítajú znova.

Ovládanie vo workflowe: `contours` (zap/vyp), `contour_interval` (default
5 m; zvýrazňuje sa každá 10. čiara ako hlavná a každá 5. ako polovičná, čiže
pri 5 m sú to 50 a 25 m), `contour_maxzoom` (default 14) a
`contour_smoothing` (default 0 = bez zjemnenia). Bez zjemnenia je terén detailnejší, ale vrstevníc je viac – a keď
prekročia 40 % rozpočtu stránky, pipeline im sama zníži maxzoom.

### Tieňovanie reliéfu a 3D terén

MapLibre nevie čítať výšky z GeoTIFFu – potrebuje pyramídu PNG dlaždíc, kde je
výška zakódovaná do farby (*terrarium*). Robia sa z výškového modelu, ktorý
vyberá **`shading_source`** ([workers/terrain/tiles.py](terrain/tiles.py)),
takže 3D reliéf nedvíha koruny stromov, kým vrstevnice vedú po zemi.

- **Áno, dá sa aj z DMR 5.0** – `shading_source: dmr5`. Tieňovanie sa robí
  vždy na celý región, takže `dmr5` tu vyjde na svoju **5 m** dlaždicovú
  podobu (metrová existuje len na výrez, viď „jeden zdroj, dve podoby").
- **Každý zoom sa prevzorkuje z DEM nanovo**, nezmenšujú sa hotové dlaždice:
  priemerovať sa musí *výška*, nie zakódovaná farba. **Ktorým resamplingom,
  rozhoduje pomer pixela a bunky**: `-r average` až od dvojnásobku bunky
  (`AVERAGE_RATIO`), pod ním `-r cubicspline`. Na maxzoome sa zväčšuje vždy
  (viď bod nižšie o `auto`) a `average` tam degeneruje na najbližšieho suseda –
  z každej bunky modelu vypadne štvorček rovnakých pixelov. **A tesne nad
  bunkou je to to isté, len slabšie**: box filter prekryje raz jednu bunku,
  raz dve, takže z toho vypadne rytmus plošiniek – preto hranica nie je
  „pixel hrubší než bunka", ale jej dvojnásobok.
- **Zvislý krok kódovania ide za vodorovným pixelom** (`krok ≤ 2 % pixelu`,
  zaokrúhlené na mocninu dvojky, a ešte o `FRAC_BITS_MARGIN` bitov nižšie):
  do z8 celý meter, z12 šestnástina, z13 tridsaťdvatina. Kým bol krok vždy
  metrový (`B = 0`), bol terén rozrezaný na metrové plošinky – a hillshade,
  ktorý je *derivácia* výšky, z hrany každej z nich spravil čiaru. Spolu
  s tými štvorčekmi z toho bola v mape **pravidelná tkanina**.
  A keď sa krok postavil presne na hranicu viditeľnosti (`SLOPE_EPS × pixel`),
  ostala z nej **slabšia, ale stále pravidelná mriežka** – lebo pravidelný
  falošný sklon oko číta aj tesne pod tou hranicou. Preto je krok o tri bity
  nižšie. Dlaždice sú za to ~2,2× väčšie a platí sa to len tam, kde je pixel
  jemný; namerané čísla sú v hlavičke [`terrain/tiles.py`](terrain/tiles.py)
  a pri `FRAC_BITS_MARGIN` v [`lib/cell.py`](lib/cell.py), strážia to
  `workers/lint/terrain.py` a v mene assetu aj v kľúči cache prípona `v4`.
- **Dlaždica bez reliéfu nevznikne.** Kde nikde nie je sklon nad tými 2 %
  (hladina, rovina), by hillshade nakreslil rovnú plochu a 3D terén rovinu –
  teda presne to, čo klient dostane aj z rodičovskej dlaždice o zoom nižšie
  (MapLibre ju hľadá sám, `TerrainSourceCache.getSourceTile`). Nižný kraj tak
  neplatí štvornásobkom dlaždíc za každý ďalší zoom nad rovinou a rozpočet
  ostane horám. Minzoom sa nevynecháva nikdy – je to koreň tej pyramídy.
- **Kde model dáta nemá, sa nevyrobí hladina mora.** Terrarium je RGB a nemá
  podobu „hodnota tu nie je“, takže sa do dlaždice niečo zapísať MUSÍ – a dlho
  to bola nula (`gdalwarp -dstnodata 0`). Tým sa „model tu nemáme“ zmenilo na
  „nula metrov nad morom“ a hillshade (derivácia výšky) z toho na hranici dát
  nakreslil **stenu**: namerané na publikovanom
  `bratislavsky_test4-terrain.pmtiles` skok 668 m na 407 m/px, čo je sklon
  **59°** – ostrá svetlo-tmavá čiara cez mapu na mieste, kde o žiadnu hranicu
  nejde. Za ňou bola rovina, čiže plocha **bez tieňovania**: na z5 malo 99,6 %
  dlaždice presne 0 m, na z9 43 %, na z10 35 %.

  Odteraz je `NODATA` sentinel mimo rozsahu skutočných výšok (−9999),
  chýbajúce hodnoty dopĺňa `vypln_nodata` **najbližšou platnou** – to isté, čo
  robí `gdal_fillnodata`, len štyrmi priechodmi indexov, aby sa kvôli tomu
  nemusel prepisovať súbor. Konštanta by stenu nezrušila, len znížila; okolím
  doplnená výška za hranicou plynulo pokračuje tou, ktorá je na hranici, takže
  z nej hillshade nemá čo nakresliť (namerané na napodobenine dlaždice:
  57–68° → 6°, platné výšky nedotknuté). Dlaždica bez jediného platného pixela
  sa **nezapíše vôbec** – nie je to rovina, je to územie, o ktorom model nič
  nehovorí. Stráži to [workers/lint/terrain-nodata.py](lint/terrain-nodata.py).
- **Rozsah v hlavičke `.pmtiles` je bbox behu**, nie zjednotenie dlaždíc
  (`pack.py --clip-bbox`). Zjednotenie je totiž rozsah tej NAJVÄČŠEJ dlaždice
  a tá na z5 má 11,25°, takže sa pyramída nad jedným krajom vykázala ako pol
  Európy: hlavička hovorila `11,25 / 40,98 / 22,50 / 48,92`, kým mapa bola
  `17,167 / 48,321 / 17,195 / 48,340` – **182 751× väčšia plocha**, než akú
  archív popisuje. Klientovi to neuberie ani jednu dlaždicu: MapLibre porovnáva
  `bounds` s dlaždicou prienikom, takže tá z5, do ktorej kraj padne, ostáva
  v rozsahu.
- **Zoom je `auto`** (`terrain_maxzoom`): najnižší, na ktorom je pixel
  dlaždice jemnejší než bunka modelu – Sonny (20 m) → **z13**, DMR 3.5 (10 m)
  → **z14**, DMR 5.0 (5 m) → **z15**. Pevná trinástka tu bola dovtedy, kým bol
  Sonny jediný zdroj, a znamenala, že si síce vyberieš DMR 5.0, ale reliéf
  vyzerá ako zo Sonnyho: pixel z13 má 12,5 m, takže sa 5 m model nemá ako
  prejaviť.
- **Každý zoom navyše je štvornásobok dlaždíc**, takže z13 → z15 je
  šestnásťnásobok. Preto má tieňovanie svoj podiel rozpočtu stránky
  (`BUDGET_TERRAIN_PCT`, 12 %) a `terrain/tiles.py` sa do neho zmestí sám:
  vypíše plán, počíta zoomy odspodu a ten, ktorý by rozpočet prekročil, ani
  nezačne – povie to warningom a čo s tým (menšie územie, vyšší
  `size_limit_mb`). Jemný reliéf celého kraja sa teda nedá dostať zadarmo,
  ale výrez alebo rýchly test ho majú.
- **Ukladajú sa do skladu `dem-terrain`** ako jeden `.pmtiles` na región,
  model a maxzoom. Meno nesie **skutočne vyrobený** maxzoom, nie želaný –
  a ďalší build si zo skladu vezme najvyšší uložený zoom, ktorý nie je vyšší
  než ten želaný, takže sa to isté nepočíta druhýkrát. `terrain_rebuild: áno`
  ich vynúti prepočítať nanovo.
- Keď sa nevyrobia, štýl padá späť na AWS Terrain Tiles.

### Skaly (najstrmšie úseky terénu)

Kde sú vrstevnice husté, je stena. Hustota čiar je ale len **obraz sklonu** –
a závisí od intervalu vrstevníc aj od zoomu. Skaly sa preto nepočítajú z
hotových vrstevníc, ale rovno **zo sklonu terénu**, z toho istého DEM:

```
DEM
  → gdalwarp -t_srs EPSG:3035     do metrickej projekcie (v stupňoch by sklon
                                  vyšiel skreslený – 1° po dĺžke je u nás
                                  o tretinu kratší než 1° po šírke),
                                  mriežka `rock_res` (auto = najjemnejšia,
                                  ktorá sa zmestí do času a má pri danom
                                  DEM ešte zmysel)
  → gdaldem slope                 sklon v stupňoch
  → gdal_translate -ot Int16      sklon v stotinách ° na disk (mozaika celého
                                  územia sa vo Float32 nezmestí)
  → gdalbuildvrt                  mozaika sklonu, a až nad ňou NARAZ:
  → gdal_contour -p -fl …         izolínia sklonu ako PLOCHY
                                  (hladší okraj než polygonizácia po pixeloch)
  → -explodecollections           samostatné skaly
  → ST_BuildArea(ST_ExteriorRing) PLNÉ plochy – von ide len vonkajší prstenec
  → filter najmenšej plochy
  → -simplify                     preč so schodíkmi po hranách buniek
  → smooth-shapes.py              zaoblenie rohov, ktoré po zjednodušení
                                  ostali ostré (limitná krivka podľa mriežky
                                  dlaždice); ten istý skript zaobľuje
                                  aj vrstevnice
  → vrstva `rock` v {región}-rocks.pmtiles  – VLASTNÉ dlaždice, vlastný maxzoom
```

**Tvar plôch je tvar terénu.** Obrys je izolínia sklonu, teda presne tá čiara,
kde svah prekročí prah – členitý pás pod hrebeňom, oblúk okolo žľabu, ostrov
brala v suti. Žiadna mriežka štvorčekov (tá tu bola do augusta 2026 a je
preč).

**Obrys je zaoblený, nie zubatý.** Samotná izolínia zubatá nie je (priemerný
lom medzi segmentmi 4,6°) – zubatou ju robilo až zjednodušenie, ktoré tie
státisíce bodov zredukuje (28,5°). Preto sa po zjednodušení rohy ešte zaoblia –
tým istým skriptom a tou istou limitnou krivkou ako vrstevnice, vzorkovanou
podľa mriežky dlaždice na `rock_maxzoom`. Čísla a neúspešné pokusy
(vyhladzovanie rastra sklonu plochy rozbíja: 326 → 1668) sú
v `workers/contours-rocks/smooth-shapes.py`.

**Jedna trieda, jedna sivá.** Skala je v mape jedna plocha v jednej sivej bez
priehľadnosti — žiadna plocha vnútri inej. Priehľadnosť by totiž znamenala,
že každý prekryv je vidieť — dve plochy cez seba vyjdú tmavšie než jedna,
a stačí na to plocha rozseknutá hranicou bloku alebo `cliff` ležiaci v diere
`steep`u. Plná farba to rieši na úrovni kreslenia a plochy sa nemusia ani
zlepovať, ani strážiť proti sebe.

Predtým to boli dve polopriehľadné triedy (`steep` ≥ 50°, `cliff` ≥ 65°).
Vrátiť sa to dá: `options: rock_plne=0`, prípadne `rock_img_options=plne=0`
pre skaly z tieňovania.

**Diery v plochách ostávajú** — tam, kde je vnútri steny miesto pod prahom
(polica, terasa, zarastený stupeň). Krátko sa zapĺňali spolu s tým prechodom
na jednu triedu a bola to chyba: zo skál boli súvislé klaksy, v ktorých nebolo
vidieť žiaden tvar. `options: rock_zapln_diery=1` to vráti, ak by to niekto
naozaj chcel.

**Skaly majú vlastné dlaždice.** `{región}-rocks.pmtiles`, oddelene od
vrstevníc — a to kvôli maxzoomu: každý `.pmtiles` má len jeden a tie dve
vrstvy ho chcú úplne iný. Vrstevnice sú čiary cez celý kraj a rozpočet
stránky minú okolo z14; skaly sú plochy len tam, kde je terén strmý, takže sa
do z16 (tvrdý strop Planetilera) zmestia. Kým boli v jednom súbore, museli sa
obe uskromniť na to nižšie — a na skalách to bolo vidieť, lebo práve pri
priblížení sa pozerá, či obrys sedí na terén. Nad maxzoomom sa dlaždice
naťahujú overzoomom, takže sú skaly vidieť **až do maximálneho zoomu mapy**.
Vo viewri majú vlastný prepínač, takže sa dajú zapnúť aj bez vrstevníc.

**Vektorizuje sa naraz nad celým územím – a je to nutné.** Sklon sa pre kraj
nedá spočítať jedným rasterom (pri 2 m je to vyše 3 miliárd buniek), takže sa
počíta po častiach. Vektorizovať po častiach sa ale nedá: diera prerezaná
hranicou časti sa zmení na zárez v okraji a späť sa nezlepí ani cez
`ST_Union`. Namerané na syntetickom teréne (prstencová terasa v kuželi):

| postup | plôch | dier |
|---|--:|--:|
| celý raster naraz (referencia) | 2 | 2 |
| po častiach + `ST_Union` | 4 | **0** |
| **sklon po častiach, vektorizácia naraz** | **2** | **2** |

Preto sa po častiach počíta **len raster sklonu**, uloží sa na disk ako `Byte`
s krokom 0,5° (vo `Float32` by mala mozaika kraja ~13 GB) a `gdal_contour` ide
jedným priechodom nad celou mozaikou. Výsledok potom nezávisí od toho, na
koľko častí sa počítalo – overené pri 1, 12 aj 60 častiach je zhodný do
posledného m².

**Skaly sú vidieť všade, kde sú** – vrstva ide do dlaždíc od **z1** a štýl ich
odtiaľ aj kreslí. Nízke zoomy pritom nič nestoja: Planetiler na každom zoome
zjednoduší obrys podľa veľkosti pixela a zahodí všetko menšie než pixel, takže
z prehľadu ostane len tvar veľkých stien – a dlaždíc je tam rádovo menej (z1
je jedna na celý región, z10 ich je tisíc). S približovaním pribúdajú detaily.

#### Aký je to detail

| vec | hodnota |
|---|---|
| mriežka, na ktorej sa obrys počíta | **auto** (`rock_res`) – najjemnejšia, ktorá sa zmestí do času a má pri danom DEM zmysel |
| krok sklonu v mozaike | **0,01°** (Int16) – hrubší krok robil obrys zubatý |
| zjednodušenie obrysu | štvrtina mriežky (`ROCK_SIMPLIFY: -1`) – zmaže schodíky |
| zaoblenie rohov | **limitná krivka** (`ROCK_SMOOTH: 2` = priehyb pol kroku mriežky dlaždice) – priemerný lom 28,5° → 7,7° |
| bunka zdrojového DEM (Sonny 20 m) | ~20 m → **strop skutočného detailu** |
| najmenšia ponechaná plocha | jedna bunka mriežky: **4 m²** pri 2 m, **1 m²** pri 1 m |
| filter drobných prvkov v dlaždiciach | vypnutý na najvyššom zoome |

Presné čísla za konkrétny beh (počet plôch, najmenšia/priemerná/najväčšia
plocha, koľko km² skál, koľko plôch má dieru a koľko km² diery vykrojili) píše
build do **Summary** – viď [Súhrn buildu](#súhrn-buildu).

**Mriežku vyberá `auto` a vypíše prečo.** Prejde rebríček 0,5 / 1 / 1,5 / 2 /
3 / 4 / 5 / 8 / 10 / 15 / 20 m a zoberie najjemnejšiu, ktorá sa zmestí do
rozpočtu času (`ROCK_BUDGET_MIN`) a nie je jemnejšia než desatina bunky
zdrojového DEM. Pri Sonnym (20 m) z toho vždy vyjde **2 m** – jemnejšia
mriežka by len interpolovala medzi tými istými výškami, stála 4× viac času a
nepridala ani jeden nový tvar terénu. Skutočný skok v detaile prinesie až
`rock_source: dmr5` s výrezom (1 m LiDAR), kde auto ide na 0,5 m. Zadať sa dá aj číslo
natvrdo (`options: rock_res=1`).

> **Mriežka nie je to isté ako detail.** Mriežka 2 m hovorí, ako jemne je
> obrys odkrokovaný. Skutočný detail je ale stropený zdrojom: Sonny má pre
> Slovensko bunku ~20 m, takže tvary pod 20 m sú **dopočítané, nie merané** –
> interpolácia dá hladší a presnejšie umiestnený obrys, novú informáciu však
> nepridá. Jemnejšie by vedel len 1 m LiDAR
> ([ÚGKK DMR 5.0](https://www.geoportal.sk/)); ten sa z geoportálu sťahuje cez
> interaktívny export, takže by sa musel najprv nazrkadliť do releasu rovnako
> ako Sonnyho DTM.

#### Druhá cesta k skalám: tmavé plochy v tieňovaní (pokus)

Všetko vyššie počíta skaly **zo sklonu DEM**. Existuje aj druhá, pokusná
cesta, ktorá sa výšok vôbec nedotkne: vezme hotový **hillshade** z freemap.sk
a hľadá v ňom **tmavé plochy**. Robí to workflow **Skaly z tieňovaných
dlaždíc** ([`workers/rocks-shading/build.py`](rocks-shading/build.py)):

```
XYZ dlaždice sk-hires-shading.tiles.freemap.sk/{z}/{x}/{y}.jpg
  → mozaika odtieňov šedej v EPSG:3857   dlaždice sú v ňom natívne, takže
                                         sa nič neprevzorkúva: 1 px = 1 px
  → raster „tmavosti"                    o koľko je pixel pod referenciou
  → gdal_contour -p -fl 0,5 -fl …        izolínia tmavosti ako PLOCHY,
                                         s dierami – ten istý nástroj aj tá
                                         istá sémantika ako u skál z DEM
  → -explodecollections + filter plôch a dier
  → -simplify + smooth-shapes.py       rovnaké zaoblenie ako pri DEM
  → rock.gpkg  ─► sklad `dem-rocks-img`  +  sklad `vysledky` (na pozretie)
```

**Prečo to môže fungovať:** tieňovanie je obraz sklonu a hires vrstva
freemap.sk je robená z 1 m LiDARu – pri z18 vyjde jeden pixel na **~0,4 m**
terénu. To je jemnejšie, než na čo si sklon vieme rozumne spočítať sami.

**Prečo to klame:** hillshade je osvetlený z jednej strany. Rovnako strmá
stena otočená k slnku je na ňom **najsvetlejšia zo všetkého**. Táto cesta
teda systematicky nájde severozápadné steny a systematicky prehliadne
juhovýchodné. Preto je to jedna z možností vo výbere `rock_source`
(`tienovanie`) a nie náhrada skál počítaných zo sklonu.

**Najtenšie vlákna siete skala nie sú.** Prah nájde aj vlásočnicové ryhy
a mikrotiene cez celý svah. Vektorizáciou sa z nich stane jeden prepojený
polygón cez celý výrez a v mape z neho pri z14 a nižšie nie je sieť, ale
**rovnomerná sivá deka**. Zahadzuje ich `open` (default 3 m) – podľa ŠÍRKY,
nie podľa plochy, lebo celá sieť je jeden veľký útvar a `min_area` na ňu
nesiaha. Namerané pri Gerlachu: 21,6 % plochy bez neho, **9,5 %** s ním.

**Prah nie je jedno číslo.** Celý zatienený svah je tmavý bez toho, aby bol
skala; stena v presvetlenej doline býva svetlejšia než tráva vedľa. Prah sa
preto skladá z troch:

| input | čo znamená |
|---|---|
| `dark` (125) | nad touto šedou nie je skala **nikdy** |
| `dark_always` (70) | pod touto šedou je skala **vždy**, nech je okolo čokoľvek |
| `rel` (18) | medzi tým: koľko musí byť pixel pod **miestnym pozadím** |

Miestne pozadie nie je obyčajný priemer, ale priemer **svetlejších** pixelov
v okne (`local`, default 1500 m na zemi) – odpoveď na „ako svetlý je tu
osvetlený terén" sa nesmie dať stiahnuť dole tým, čo práve hľadáme. Dolný
strop `dark_always` tam nie je pre ozdobu: bez neho sa veľká súvislá stena
nenájde, lebo sa okno pozadia zmestí celé dovnútra nej a ostane z nej len
prstenec (namerané na skúšobných dátach).

**Svetlé miesto vnútri tmavej plochy ostane dierou** – polica, sneh,
kosodrevina. Presne ako pri skalách z DEM, a z toho istého dôvodu: pásmo
`gdal_contour -p` má vnútorné prstence tam, kde hodnota klesla pod prah.
Zahadzujú sa len dierky menšie než `min_hole` (default 10 m²), čo je zrno
JPEGu, nie polica.

##### Čo ukázala skutočná dlaždica

Predvolené hodnoty nie sú odhad – sú namerané na výreze z tej vrstvy
(1260×1933 px, Vysoké Tatry):

- **Je to farebný hillshade, nie šedý.** Žltozelený nádych, tiene ťahajú do
  modra (sýtosť ~34, `B−R` od −95 do +50). Čítame ho ako jas (luma 601), kde
  modrý kanál váži najmenej – modré tiene sa tým ešte prehĺbia, čo nám
  vyhovuje. Farba ako druhý, nezávislý signál zatiaľ použitá **nie je**.
- **Rozloženie jasu:** medián 176, 20. percentil 135, 10. percentil 107.
  Prah `dark = 125` z toho odkrojí ~16 % plochy a sedí na skalnatý terén.
- **Tmavé nie je plocha, ale sieť.** Tmavé miesta nie sú súvislé steny, ale
  hustá sieť žliabkov, ryhiek a mikrotieňov v rozčlenenom teréne. Táto jemná
  štruktúra je to, čo chceme – nie vyplnená klaksa. Kto chce súvislé plochy,
  zapne `options: fill=40` (spriemeruje tmavosť v okne 40 m); štandardne je
  to **vypnuté**.
- **Sieť je pospájaná**, takže počet útvarov neexploduje – 16 útvarov pokrylo
  15 % výrezu. Explodujú **body**: pri z18 to vyšlo na ~2 MB GeoPackage na km²
  skalnatého terénu. Toto číslo píše beh do súhrnu (`MB na km² skál`), lebo
  práve ono rozhoduje, či sa vrstva zmestí do rozpočtu mapy.
- **Odtiaľ sú predvolené filtre.** Merané na tom istom výreze:

  | nastavenie | plôch | dier | dáta |
  |---|--:|--:|--:|
  | `min_area 200`, `min_hole 50`, simplify ½ px, jemné zaoblenie | 16 | 89 | 3,95 MB/km² |
  | **`min_area 50`, `min_hole 10`, simplify 1 px, hrubšie zaoblenie** | **78** | **392** | **1,97 MB/km²** |

  Jemnejšie filtre a hrubšie zjednodušenie dali **súčasne viac štruktúry aj
  polovičné dáta**: pol pixela a jemnejšie zaoblenie leštili obrys, ktorý
  aj tak nikto nerozozná, zatiaľ čo `min_area 200` zmazal práve tie drobné
  útvary, o ktoré ide. Predvolené `min_area` je preto dnes **7 m²** – ~11
  pixelov na z17, teda blízko hranice, pod ktorou je už len zrno JPEGu.
  Tabuľka ostáva pri nameraných 200 a 50. `min_hole` sa neuplatňuje, kým sú
  plochy plné (diery sa nekreslia vôbec).

**Prvý beh je ladiaci.** Predvolené prahy sú kvalifikovaný odhad, nie
nameraná hodnota – tá dlaždicová vrstva sa nedá ochutnať dopredu. Beh preto
odloží do skladu `vysledky` na Drive súbor `nahlad-…` s PNG **mozaika vedľa
nájdených plôch** (vľavo tieňovanie, vpravo to isté s červenou maskou)
a histogramom odtieňov. Podľa nich sa `dark` / `dark_always` / `rel` doladia
za jeden pohľad.

**Každý request vyzerá ako iný prehliadač.** Hlavičky sa berú z deviatich
profilov skutočných prehliadačov (Chrome, Firefox, Safari, Edge; Windows,
macOS, Linux, iOS, Android) a vyberajú sa náhodne na každý request. Profil je
celý – `User-Agent`, `Sec-CH-UA`, platforma aj `Accept-Language` sedia
dokopy, lebo Chrome, ktorý o sebe v `Sec-CH-UA` tvrdí, že je Firefox, nie je
maskovanie, ale rozbitá hlavička.

> Stojí za to vedieť, čo to robí: berie to freemap.sk možnosť rozoznať dávku
> od človeka, a je to dobrovoľnícky server. Slušnosť preto musí zabezpečiť
> objem – `jobs` ostáva na 12 a dlaždice sa cachujú, takže druhý beh nestiahne
> ani jednu. `options: ua=project` vráti pôvodnú hlavičku, ktorá sa priznáva
> menom projektu; `ua=…` pošle čokoľvek vlastné.

**Efektivita.** Dlaždice sa sťahujú paralelne (`jobs`, default 12 – je to
dobrovoľnícka služba) s trvalým spojením, ukladajú sa do cache behu a pri
opakovanom ladení prahov sa už neťahajú. `zoom: auto` skúsi najvyšší zoom,
ktorý server dá a ktorý sa zmestí do stropu 60 000 dlaždíc. Vektorizuje sa **po blokoch**
(`options: block_tiles=8`, teda 2048 px; menší blok = menej pamäte a jemnejšie
pokračovanie). Nad celou mozaikou to totiž nedobehlo: `gdal_contour -p`
skladá uzavreté prstence a v zrnitom JPEGu ich je toľko, že to rastie
rýchlejšie než lineárne — 3,62 mld. pixelov bežalo 2 h 41 min a nedopočítalo
sa, pričom pamäť ostala na 0,7 GB.

Plocha cez hranicu bloku vypadne ako dva kusy; tie sa na konci zlepia cez
`ST_Union` (spatialite), a to len tie, ktoré sa hranice naozaj dotýkajú.
Keď spatialite chýba **alebo únia stratí plochu**, beh pokračuje s pôvodnými
kusmi a povie to — v skalách budú vidieť rovné rezy. To druhé nie je
teoretické: `ST_Union` nad neplatnou geometriou skončí ÚSPECHOM a napíše
prázdny súbor, takže bez prepočítania plochy zmizli všetky skaly na hraniciach
blokov (beh 31434520563) a mapa bola zelená a bez skál.

Obe cesty ku skalám — zo sklonu (`contours-rocks/rock-areas.py`) aj
z tieňovania (`rocks-shading/vector.py`) — robia toto isté, a preto to robia
**jedným kódom**: `workers/lib/contour-blocks.py` (obrysy po blokoch, značenie
a zlepovanie švov, kontrola metrických súradníc). Kým to boli dve kópie,
oprava prázdnej únie aj zhrnutie varovania o SRS skončili len v jednej z nich.

**Zoom vyberá `auto` a nie je to štvornásobok na zoom.** Sťahovanie áno, ale
obrysy nie — a tie sú to drahé. Namerané na Vysokých Tatrách:

| zoom | dlaždice | mozaika | obrysy |
|---|--:|--:|---|
| z17 | 13 815 | 0,91 mld. px | ~50 min (odhad) |
| z18 | 55 260 | 3,62 mld. px | **2 h 41 min a nedopočítalo sa** (sťahovanie pritom 12 min) |

Preto má `auto` okrem stropu na dlaždice aj rozpočet času (`options:
budget_min=…`, default 100) a zíde pod neho sám — na Vysokých Tatrách teda
zvolí z17. Nad rozpočtom sa výpočet zastaví s hláškou namiesto toho, aby
bežal do timeoutu celého jobu.

**Jedna trieda, jedna sivá.** Výstupom je jedno pásmo, teda žiadna plocha
vnútri inej (`options: plne=0` vráti pôvodné dve pásma). Diery **ostávajú** —
sú to medzery medzi vláknami siete žliabkov a práve ony sú tá štruktúra;
`options: zapln_diery=1` ich zaplní a detail tým zmizne.
V mape sa kreslí plnou farbou bez priehľadnosti, takže sa prekryv nikde
neprejaví a plochy sa nemusia ani zlepovať. Vedľajší efekt, ktorý sa počíta:
jedno pásmo namiesto dvoch je polovica prstencov na obtiahnutie, a to je tá
najdrahšia fáza celého behu.

**Zoom dlaždíc končí na 17** (~0,8 m na pixel). Na z18 sú to štvornásobne
dlaždice a obrysy rastú ešte rýchlejšie — 3,62 mld. pixelov bežalo 2 h 41 min
a nedopočítalo sa. Mapa z toho nemá nič: skaly sa zobrazujú do maximálneho
zoomu tak či tak, z vyššieho zdroja by bol ostrejší tvar, nie väčší rozsah.

**Sú z toho tri joby**, nie jeden — strop času totiž platí na job:

| job | strop | čo robí | čo po ňom ostane |
|---|--:|---|---|
| Stiahnuť dlaždice | 2 h | JPG z freemap.sk | cache + `dlazdice-tienovania-…` v sklade |
| Obrysy po blokoch | 3 h | raster tmavosti, `gdal_contour` po blokoch | cache s rozrobeným + `nahlad-…` v sklade |
| Skaly z tieňovania | 1 h | zlepenie blokov, švy, filter, vyhladenie | polygóny do skladu, čísla |

Sťahovanie býva desiatky minút a obrysy ďalšiu hodinu — dokopy sa to do
jedného rozpočtu zmestiť nemusí, a keď čas dôjde, padne aj to, čo už bolo
hotové. Rozdelené má každá časť celý svoj rozpočet a v Actions je vidieť,
na ktorej beh práve je. Vedľajší efekt, ktorý stojí za to: **každý job odloží
svoj výsledok hneď**, takže obrázky aj náhľad sú po ruke aj vtedy, keď to za
nimi ešte nedobehlo. A zmena `min_area` je odteraz posledný job (minúty), nie
celý výpočet odznova.

Dáta si joby podávajú cache: dlaždice pod vlastným kľúčom, rozrobené pod
druhým (takže sa gigabajty JPEGov neukladajú dvakrát). Zvolený zoom ide
z prvého jobu ďalej ako výstup, takže sa pri `auto` nehádá trikrát.

**Testovací režim** (switch `test`) vyreže zo stredu výrezu štvorec so 4 km²
a počíta na ňom celý beh — vrstevnice, skaly a tieňovanie aj samotnú mapu
(orezáva sa aj PBF). Ladenie prahov je potom minúty namiesto hodín
— a beh do súhrnu vypíše obrázok s okolím (červený štvorec = testované
územie), súradnice a odkaz, ktorý otvorí hotovú mapu presne tam.

**Čo je hotové, sa nepočíta znova.** Rozrobené leží v cache dlaždíc, ktorá
sa ukladá aj po páde a po timeoute:

| checkpoint | čo ušetrí |
|---|---|
| stiahnuté dlaždice | celé sťahovanie |
| pásy rastra tmavosti | pás po páse |
| `bloky/b00000…` | **obrysy, blok po bloku** |
| `bands.geojsonl`, `rock.geojsonl` | zlepenie a filter |

Takže aj beh, ktorý sa nezmestí do troch hodín, sa dá dotiahnuť opakovaným
spustením — každé ďalšie nadviaže tam, kde predošlé skončilo. Po úspechu sa
rozrobené maže; `options: fresh=1` ho zahodí dopredu.

**Ako to dostať do mapy:** stačí **Build map** s `area: vysoke_tatry`
a `rock_source: tienovanie`. Nič sa dopredu púšťať nemusí – build si tú
pipeline zavolá sám, rovnako ako si sám dopĺňa chýbajúce výškové modely.
V behu z toho pribudnú do skladu `vysledky` na Drive dva balíky:
`dlazdice-tienovania-…` so stiahnutými JPG dlaždicami (to sú tie obrázky,
z ktorých sa skaly hľadali) a `nahlad-…` s mozaikou, maskou a histogramom na
doladenie prahov.

| chcem | ako |
|---|---|
| skaly z tieňovania, nech to trvá koľko chce | `rock_source: tienovanie` |
| iný zoom dlaždíc | `options: rock_img_zoom=18` |
| iné prahy / vyplnenie | `options: rock_img_options="fill=40 min_hole=5"` |
| aj najtenšie ryhy ako skalu (sivá deka pri z14) | `options: rock_img_options="open=0"` |
| len výrazné steny | `options: rock_img_options="open=6"` |
| presne ten asset, čo som si doladil ručne | `options: rock_img_asset=rockimg-…gpkg.zst` (vtedy sa nič nepočíta nanovo) |
| len rýchlo overiť, či to vôbec niečo nájde | switch `test` (predvolene odškrtnutý, viď nižšie) |

### Rýchly test: pár km² namiesto celého pohoria

Switch **`test`** vyreže **zo stredu zvoleného výrezu štvorec so 4 km²**
a na ňom spočíta CELÝ beh — vrstevnice, skaly a tieňovanie aj samotnú mapu.
Z desiatok minút sú minúty, čiže sa dá prah alebo interval overiť za jeden beh
a nie za jeden obed.

**Orezáva sa aj PBF, takže mapa je tiež len tie 4 km².** Dlaždice, značené
trasy, krajinné prvky aj ZIP vyjdú zo štvorca; `bbox` behu sa rovná
`dem_bbox` a orez robí ten istý `osmium extract`, aký robí `crop_bbox`
(namerané na Bratislavskom kraji: 37 MB PBF → 237 kB). Kým sa mapa nechávala
celá, bol test polovičný: kraj sa aj tak stiahol, prehnal Planetilerom, zabalil
a nahral, takže sa okolo štvorca s pár km² terénu viezol celý kraj. Dôvod,
prečo to tak bolo — „nech tie skaly nevisia nad prázdnom" — nesie obrázok
„kde to je" ([workers/plan/test-map.py](plan/test-map.py)) a mapa sveta pod
výberom; na to celý kraj netreba. **Celý kraj s terénom len v jednom pohorí sa
dá stále postaviť:** switch `test` odškrtnúť a `area` prepnúť na pohorie.

`-s smart -S types=multipolygon,boundary` je pri tom reze nutné: zo štvorca so
4 km² vytŕča skoro každá plocha, takže bez dopĺňania členov by v testovacej
mape nebol les ani chránené územie takmer nikde (namerané: bez `-S types=`
zmizli „Záhorie (vojenský obvod)" a „Turecký vrch", s ním neostala ani jedna
zahodená plocha).

**Predvolene je zapnutý.** Ostrý build na celý výrez ho chce odškrtnúť.
Opačné poradie znamenalo, že sa každé ladenie prahu platilo desiatkami minút,
kým si niekto spomenul dopísať voľbu do textového poľa — a to je práve tá
vec, ktorá sa preklikáva pri každom behu. Veľkosť štvorca sa naopak mení
zriedka, tak ostala voľbou (`options: test_km2=5`). Za miesto vo formulári
zaplatila mriežka `rock_res`, ktorá sa prestavuje len s iným zdrojom výšok;
je z nej tiež voľba (`options: rock_res=1`).

**Mapa sa otvorí rovno na tom štvorci.** Manifest nesie pri regióne okrem
`bbox` aj `test_bbox` a viewer sa pri štarte nastaví na ten druhý. Odkedy je
mapa orezaná tiež, sú to tie isté súradnice — `test_bbox` ostáva, lebo z neho
viewer aj súhrn behu vedia, že to JE test. Polohu z adresy (`#map=…`) viewer
zahodí, len keď mieri mimo nasadeného regiónu, aby `F5` ani starý odkaz
neotvorili mapu nad cudzím krajom. V paneli je napísané, že vrstevnice, skaly
a tieňovanie sú len na tých 4 km² — nech kraj bez skál nevyzerá ako pokazený
build. Tieňovanie má navyše v štýle `bounds` toho štvorca, takže sa jeho
dlaždice mimo neho ani nepýtajú.

Kľúč dostane príponu `_test4`, takže si testovací beh **nesadne do tej istej
cache ani na tie isté uložené výsledky** ako ostrý.

**Pri `area: cely_region` tá prípona nie je** – kľúč ostáva `cely`, lebo je to
sentinel („žiadny výrez") a prípona by prepla podobu DMR 5.0 z dlaždíc na výrez
v plnom rozlíšení (rozpis v [`plan/area.py`](plan/area.py)). Cache to nemieša
(v jej kľúči je bbox výpočtu, teda bbox štvorca), ale **sklad hotových skál by
áno**: meno `rock-presovsky-cely-…gpkg.zst` by nieslo skaly zo 4 km² a ostrý
beh by si ich stiahol ako hotové skaly celého kraja. Testovací beh preto do
skladu skál ani sklonu **nesiaha** – ani neukladá, ani neberie
([`contours-rocks/build.sh`](contours-rocks/build.sh)). Je to tá istá vec ako
dlaždica, ktorá sľubuje celý stupeň: meno musí hovoriť, čo v súbore naozaj je.

**Testovací beh pregenerúva vždy všetko**, aj keď je `rebuild: nic`. Ladíš
ním prah, interval alebo kód – a keby sa výsledok vrátil z cache, videl by si
to, čo vyšlo naposledy, a ladil by si ducha. Kľúč cache síce nesie nastavenia
aj otlačok skriptov, ale nie všetko, a pár km² prepočítať stojí minúty, kým
jedno takto stratené kolo ladenia stojí viac. Cache ostrého behu je pritom
v bezpečí: v kľúči terénových vrstiev je bbox výpočtu a ten je pri teste
bboxom testovacieho štvorca.
Platí to aj pre skaly z tieňovania – tá podpipeline dostane `fresh=1`, takže
nenadviaže na rozrobené obrysy z minulého behu. Zo stiahnutých **vstupov**
(PBF, DEM dlaždice, JPG dlaždice tieňovania, Planetiler, glyfy) sa nezahadzuje
nič: nie sú to výsledky a v kľúči majú dátum alebo otlačok zdroja.

Beh do súhrnu vypíše, kde ten štvorec je:

- **obrázok** s okolím (podklad je tieňovanie, červený štvorec = testované
  územie, modrý = celý výrez) — nasadí sa spolu so stránkou, takže ho súhrn
  ukáže priamo;
- **súradnice** stredu aj bbox;
- **odkaz do hotovej mapy** na tie súradnice, plus OSM a Freemap na porovnanie.

Bez toho je totiž „nenašlo ani jednu skalu" nečitateľné: nevie sa, či sú
prísne prahy, alebo len štvorec padol na lúku pod lesom.

| chcem | ako |
|---|---|
| iná veľkosť | `options: test_km2=5` |
| ostrý beh na celom výreze | odškrtnúť switch `test` |
| iné miesto než stred výrezu | `options: test_at=20.30,49.24` (`lon,lat`) |
| to isté v samostatnom workflowe so skalami z tieňovania | výber `test: 2` v „Dáta · tieňované skaly“ (tam je to počet km², nie switch) |

Dlaždice majú vlastnú cache podľa výrezu a zoomu, takže druhý build z
dobrovoľníckeho servera freemap.sk neťahá nič. Tieňovanie na **celý región**
build odmietne hneď v príprave – dlaždice sú cudzie a na kraj by ich boli
státisíce.

Keby v sklade aj tak nič nebolo (napr. keď ten job spadol), build to povie
a **nespadne späť na skaly z DEM** – tichá zámena jedného zdroja za druhý by
bola horšia než zastavenie.

Vrstva je tá istá `rock` v tých istých dlaždiciach (`{región}-rocks.pmtiles`),
takže štýl netreba meniť. Líši sa len atribút: skaly z DEM majú `slope`
(stupne sklonu), skaly z obrázka `dark` (o koľko stupňov šedej pod
referenciou). V manifeste je `rock_source`, takže je v mape vidieť, odkiaľ
tie plochy sú.

#### Zdroj výšok sa vyberá zvlášť pre každú vrstvu

Tri výbery vo formulári – `contour_source` (vrstevnice), `rock_source`
(skaly) a `shading_source` (tieňovanie a 3D terén). Ponúkajú tie isté modely:

| hodnota | model | mriežka | pokrytie | stav |
|---|---|--:|---|---|
| **`sonny`** (default) | Sonny's LiDAR DTM | 20 m | celý región | overené |
| **`dmr35`** | ÚGKK DMR 3.5 (otvorené dáta) | **10 m** | celý región | **overené** ✓ |
| **`dmr5`** | ÚGKK DMR 5.0 (LiDAR) | **1 m** s výrezom, **5 m** na celý región | oboje | naplniť *Dáta · DMR 5.0* ✓ |
| `ziadne` | – | – | – | vrstva sa negeneruje |

Navyše: `rock_source: tienovanie` neberie výšky vôbec – vezme hotové polygóny
z workflowu *Dáta · tieňované skaly*.

Vrstvy môžu mať **rôzny model naraz** – napríklad vrstevnice zo `sonny`
a skaly z `dmr5`. Build vtedy stiahne oba (každý do `dem/<zdroj>/`) a v mape
je pri každej vrstve atribúcia toho modelu, z ktorého naozaj je.

**`dmr5` má dve podoby a rozhoduje rozsah, nie ďalší výber.** S vyplneným
výrezom (`area`) si vezme `ugkk-<vyrez>.tif` z releasu `dem-ugkk` v **plnom
metrovom rozlíšení**; bez neho dlaždice `N49E019.tif` z `dem-dmr5` na **5 m**.
Je to ten istý LiDAR – pri 1 m má jedna 1°×1° dlaždica ~48 GB a strop assetu
je 2 GB, takže celý región v metri sa nemá kam uložiť. To je fyzika, nie
voľba, tak sa na ňu formulár nepýta.

> Boli to dva zdroje, `dmr5` a `ugkk`. Praktický rozdiel bol len ten, že sa
> dalo zadať `ugkk` bez výrezu a beh spadol na strážcovi – alebo `dmr5` na
> pohorie a build ticho vzal 5 m tam, kde bol k dispozícii meter.

Oba sklady plní jediný workflow – [*DMR 5.0 z
Drive*](#dmr-50-z-drive-145-gb-cez-http-range) (ETRS89 verzia, **toto si
`Build map` volá sám**, a to dvoma jobmi, lebo model má dve podoby). Záloha
z archívu ÚGKK (198 GB ZIP so sekvenčným čítaním) bola zrušená – Drive púšťa
spoľahlivo a Range na ľubovoľnom offsete je rádovo lacnejší.

**`dmr35` funguje a je to najlepší model, ktorý vieme vziať priamo
v pipeline.** Overené behom
[31125042584](https://github.com/skifahrer/fricomaps/actions/runs/31125042584):
2319 MB ZIP z `opendata.skgeodesy.sk` stiahnutý, v archíve jeden raster
42 692×20 429, mriežka **presne 10,0×10,0 m**, CRS S-JTSK / Krovak East
North. Rozrezané na 15 dlaždíc (1315 MB) a nahraté do releasu `dem-dmr35`.

Ten hostiteľ je iný stroj než ten, na ktorom je DMR 5.0 — statické úložisko,
nie ArcGIS za mapovým klientom — a odpovedal na prvý pokus, kým `zbgis.` aj
`zbgisws.` timeoutujú aj pri 30 s.

Model je starší a redší než 1 m LiDAR, ale **dvakrát jemnejší než Sonny**, a
mriežka zdroja je jediné, čo stropuje skutočný detail skál. `rock_res: auto`
si to zoberie sám: dolný strop je desatina bunky DEM, takže z 2 m spadne na
1 m — v `contours-rocks/rock-areas.py` netreba meniť nič.

Dlaždice majú tú istú pomenúvaciu schému ako Sonny (`N49E019.tif`), takže sa
sťahujú tou istou cestou — `sonny` a `dmr35` sa líšia len menom releasu
(`dem-sonny` vs. `dem-dmr35`).

Platí pre **vrstevnice, skaly aj tieňovanie** – všetko sa počíta z toho istého
modelu, nech obrys skaly, priebeh vrstevnice a tieň pod nimi sedia na tom istom
teréne. (Pri `dmr5` s vyplneným výrezom to platí tiež, len tieňovanie sa robí
na celý región, takže tam vyjde jeho 5 m podoba.)

> **Dlaždice sú vo WGS84, nie v S-JTSK.** Zdrojový ZIP je v *S-JTSK / Krovak
> East North* — to hlási súhrn ako „CRS zdroja“ — ale `dem/fetch-open.py` ho
> pri krájaní prepočíta (`gdalwarp -t_srs EPSG:4326`). Overené na hotovej
> dlaždici z releasu: `N49E017.tif`, `GEOGCRS["WGS 84"]`, roh presne
> 17°E/50°N, 8826×8826 px, Float32, výšky 383–782 m.

### DMR 5.0 z Drive: 145 GB cez HTTP Range

Tá istá dátová sada, ale **ETRS89 verzia a bez ZIPu** — dva holé BigTIFFy na
Google Drive:

```
dmr5_etrs89.tif      156 108 150 990 B = 145,39 GiB   423 518 × 207 589 px, 1 m
dmr5_etrs89.tif.ovr   46 550 149 948 B =  43,35 GiB   pyramídy 2 … 256 m
```

**To, že nie sú v ZIPe, mení všetko.** V archíve ÚGKK je raster jedným
deflate prúdom a v deflate sa nedá skočiť dopredu — dá sa doň len rozbaliť od
začiatku, takže výrez na juhu Slovenska stojí prechod celým súborom. Tu má
každá dlaždica (128×128) vlastnú kompresiu a HTTP Range funguje na
ľubovoľnom offsete (overené na 20 GB aj 145 GB). **Číta sa len to, čo výrez
pretína** — Vysoké Tatry stoja rovnako ako Slovenský kras.

Georeferencia je priamo v GeoTIFF tagoch, nič sa nedopočítava:

| | |
|---|---|
| CRS | **EPSG:3046** — ETRS89 / TM zone N34 (cm 21° E, k₀ 0,9996, FE 500 000) |
| origin | X **191 148,0**, Y **5 497 220,0** (ľavý horný roh) |
| bunka | 1,0 × 1,0 m, Float32, nodata 3,4e38, LZW |

**Dve veci, ktoré to komplikujú, a ako sú vyriešené:**

1. **Drive klame o veľkosti.** Na `HEAD` vracia `content-length: 0`, takže
   GDAL súbor odmietne (`GetFileSize()=0` → „not recognized as a supported
   file format"). Na `Range` GET pritom odpovedá správne. Rieši to
   [`workers/drive/serve.py`](drive/serve.py) — malý HTTP server na
   localhoste, ktorý tú jednu hlavičku opraví a Range requesty prepája ďalej.
   Podáva **oba** súbory pod jedným menom, takže si GDAL nájde `.ovr` ako
   sidecar sám: `gdalinfo` potom vypíše všetkých 8 úrovní, otvorenie 145 GiB
   trvá **8 s** a stojí 9 požiadaviek / 0,3 MB.

2. **Limituje latencia, nie šírka pásma.** Jeden Range request trvá rádovo
   0,1–1 s bez ohľadu na veľkosť. Zmerané na 48 náhodných výrezoch po 400 kB:
   1 vlákno 1 143 ms/req, 8 vlákien 147 ms/req, 24 vlákien 68 ms/req. Preto
   sa okno **krája na bloky prichytené na cieľovú mriežku** a číta sa
   súbežne (`jobs`, default 12). Výrez 5,2 × 5,6 km pri 1 m: **1,2 min,
   0,11 GB, 697 požiadaviek.**

**Číta sa prihlásený ako vlastník dát, a inak sa nečíta vôbec.** Model leží
v **priečinku** na Drive (`FOLDER_ID` vo [`workers/drive/dmr5.py`](drive/dmr5.py))
a súbory sa v ňom hľadajú podľa mena — presun modelu inam je tak zmena jedného
čísla. Čo v priečinku je, ale povie len Drive API prihlásenému účtu, takže
verejný odkaz (s denným limitom sťahovania, ktorý zdieľajú všetci, kto naň
siahnu) tu už nie je náhradná cesta. Token vlastníka v repository secrete
**`GDRIVE_CREDENTIALS`** má navyše ten limit rádovo vyšší; číta sa cez Drive
API s `Authorization: Bearer`.

Vyrobí sa raz, na vlastnom počítači:

```bash
python3 workers/drive/auth.py --login --client-id=… --client-secret=…
# vypísaný JSON → Settings → Secrets and variables → Actions → GDRIVE_CREDENTIALS
python3 workers/drive/dmr5.py --auth-check      # ktorým účtom sa číta a či naň vidí
```

Klient je typu *Desktop app* z Google Cloud Console, rozsah práv `drive` —
pipeline z Drive nielen číta, ale aj ukladá cache buildu (viď nižšie), a na to
`drive.readonly` nestačí. **Publishing status appky musí
byť „In production"** — v „Testing" platí refresh token 7 dní a pipeline by
raz do týždňa spadla; pri type *Internal* (Workspace) to neplatí.

**Bez počítača** to spraví workflow *Údržba · prihlásenie Drive*
([`drive-login.yml`](../.github/workflows/drive-login.yml)): prehliadač je
telefón, shell je runner. Token sa v ňom **nikde nevypíše** — log public
repozitára vidí ktokoľvek — ide zo súboru rovno do secretu `DRIVE_REFRESH`.
Prihlásenie sa dá podať aj po kusoch — `client_id` ako repository **variable**
`DRIVE_CLIENT` (nie je to tajné) a secrety `DRIVE_SECRET`, `DRIVE_REFRESH`,
lebo `client_secret` Google druhýkrát neukáže; nekompletná dvojica secretov
je chyba a `Kontrola · lint workflowov` ju zachytí.

Bez secretu beh spadne hneď a s návodom — nie po pol dni na vyčerpanom
limite. Podrobne (aj kam všade sa ten secret musí dostať, aj postup z telefónu)
v [`docs/pipeline.md`](../docs/pipeline.md#prihlásenie-ako-vlastník-dát-secret-gdrive_credentials).

**Výšky sú elipsoidické, nie Bpv.** Maximum v súbore je 2 697,03 m, kým
Gerlachovský štít má 2 654,4 m n. m. — tých **+42,6 m je geoidová undulácia**.
Workflow ich preto predvolene prevádza cez EGM2008; kontrola na Gerlachu dá
po prevode 2 653,92 m, čiže rozdiel 0,5 m na 1 m mriežke. Na skaly a
tieňovanie by to bolo jedno (sklon sa geoidom nemení), na vrstevnice nie.

To je workflow **Dáta · DMR 5.0**
([`dmr5-drive.yml`](../.github/workflows/dmr5-drive.yml)), jeden job:

```
area: <pohorie>       ─► out/ugkk-<pohorie>.tif  ─► sklad dem-ugkk
                          ▲ Build map: vrstevnice a skaly s rovnakým `area`
area: <bbox stupňov>  ─► out/N49E019.tif …       ─► sklad dem-dmr5
  + tiles: true           ▲ Build map: tieňovanie a 3D terén
area: cele_slovensko  ─► out/N49E019.tif …       ─► sklad dem-dmr5
                          ▲ to isté, ale rovno na celú krajinu
```

Výstup je **presne ten istý formát**, aký `workers/dem/fetch.sh` čaká už
dávno, takže Build map sa nemení ani o riadok.

**Nespúšťaš to ručne.** Workflow je volateľný a `Build map` si ho zavolá sám
(joby `Doplniť DMR 5.0 (výrez…)` a `Doplniť DMR 5.0 (dlaždice)`), keď mu
v sklade chýba to, čo si vypýtal. Dva joby preto, že `dmr5` má dve podoby
a chýbať môžu naraz: vrstevnice a skaly čítajú výrez v plnom rozlíšení,
tieňovanie 1° dlaždice na 5 m – to sa robí na celý región, kde 1 m verzia
neexistuje.

Dlaždice sa dopĺňajú **po celých stupňoch**: meno `N49E020.tif` je sľub o celom
stupni a build si ju podľa mena hľadá, takže polovičná dlaždica by v ďalšom
behu prešla kontrolou a tieňovanie by ticho skončilo v polovici mapy. Stojí to
rádovo pol hodiny a ~2 GB z Drive na stupeň – ale raz.

##### Ako sa ten sľub raz porušil (a čím sa to drží)

Prevod do WGS84 okno **vydúva**: z okna `21,49…22,50` v EPSG:3046 vyšel raster
`21.000,48.996 … 22.013,49.628`, takže doň spadli aj tri cudzie stupne po pár
set metroch. Krájanie sa vtedy riadilo rozsahom rastra, takže z nich vyrobilo
dlaždice a do skladu `dem-dmr5` išli ako `N48E021.tif` (6 MB), `N48E022.tif`
(5 MB) a `N49E020.tif` (5 MB) – vedľa poctivej `N49E021.tif` (253 MB). Mená
tvrdili celé stupne.

Ďalší beh na celý Prešovský kraj potom videl „dlaždíc pre bbox 8, v sklade 6 →
doplniť: false", zlepil mozaiku, ktorá pokrývala **48 % kraja**, a vrstevnice
aj tieňovanie z nej vyšli v jednom štvorci (`lon 20,0–22,0`, `lat 49,0–49,5`).
Beh bol zelený a v súhrne stálo „Vrstevnice: áno". Behy
[31476448895](https://github.com/skifahrer/fricomaps/actions/runs/31476448895)
→ [31484544154](https://github.com/skifahrer/fricomaps/actions/runs/31484544154).

Držia to teraz tri veci, každá na inom mieste:

| kde | čo |
|---|---|
| [`dem/tiles.py`](dem/tiles.py) `--window` | ukladá LEN stupne, ktoré volajúci prečítal celé; stupeň v okne bez výšok uloží **prázdny** (záznam „pozerali sme sa a nič tu nie je") |
| [`dem/check.sh`](dem/check.sh) | pri `dmr5` dopĺňa **každú** chýbajúcu dlaždicu, nie „až keď nie je ani jedna" – a pýta si obálku chýbajúcich stupňov, nie celý bbox |
| [`dem/coverage.py`](dem/coverage.py) | pri sťahovaní meria **rozsah** dlaždíc oproti územiu; nepoctivú dlaždicu vymaže zo skladu (ďalší beh ju doplní celú) a pod 95 % pokrytia vráti „tento model pre toto územie nemáme" (kód 3) namiesto polovičnej mapy |

Prečo rozsah a nie počet platných buniek: poctivá dlaždica má rozsah presne
celého stupňa aj vtedy, keď je v nej terén len na pätine plochy (pohraničný
stupeň alebo prázdna dlaždica). Lož má rozsah pár pixelov. Rozsah teda tie dva
prípady oddelí presne, kým „koľko je v nej nodaty" ich zlieva.

##### A ako sa porušil druhý raz: prázdny stupeň, ktorý prázdny nebol

Bratislavský kraj (beh
[31526268289](https://github.com/skifahrer/maptiles/actions/runs/31526268289))
vyšiel s vrstevnicami, skalami aj tieňovaním **odrezanými rovnou líniou na 17.
poludníku** – na Devíne, Devínskej Kobyle a celom Záhorí nebolo nič. Beh bol
zelený, pokrytie hlásilo `100.0 %` a v sklade ležali obe dlaždice, ktoré kraj
potrebuje. Len tá západná mala **500 bajtov**:

```
  ○ N48E016 (prečítaný celý, výšky v ňom nie sú)
  ✓ N48E017
  N48E016.tif   0 MB      N48E017.tif   548 MB
```

Terén v tom stupni pritom je. Rozhodovalo o tom `gdalinfo -approx_stats`, ktoré
číta len **každý n-tý blok** (n ≈ √počet blokov) – v štvorcovej dlaždici teda
prejde po uhlopriečke. Stupeň `N48E016` je od 16° do 17° v. d., ale Slovensko
v ňom leží len v páse pri východnom okraji (16,83–17,0), čo je **7,8 % plochy**.
Uhlopriečka cez 5041 blokov trafila samé rakúske; GDAL povedal „no valid pixels
found in sampling", `elevation_range()` z toho urobilo `None` a hotová dlaždica
s 25 miliónmi platných buniek sa zahodila a nahradila prázdnou.

Overené na napodobenine (18 084² px, ten istý pás): `-approx_stats` nenájde nič
na GDAL 3.8 aj 3.10, presný priechod nájde výšky – a `dem/tiles.py` z pred
opravy z toho napíše tých istých 500 bajtov, po oprave 6 MB dlaždicu.

A bolo to **doživotné**: prázdna dlaždica je legitímna odpoveď („pozerali sme
sa a nič tu nie je“), takže má poctivý rozsah celého stupňa, pokrytie ju počíta
a `dem/check.sh` ju v sklade vidí podľa mena. Ten stupeň by už nikto nikdy
neprečítal.

| kde | čo sa zmenilo |
|---|---|
| [`dem/tiles.py`](dem/tiles.py) `has_elevations()` | vzorkovanie smie povedať len „výšky SÚ“; jeho „nie sú“ (= zahodiť hotovú dlaždicu) sa vždy overí **presným** priechodom. Platí sa len za dlaždice, ktoré vyzerajú prázdne |
| [`dem/tiles.py`](dem/tiles.py) `empty_tile()` | prázdna dlaždica sa **podpíše** verziou kontroly (`EMPTY_CHECK` v metadátach GDALu) – odpoveď z pravidiel, ktorým už neveríme, sa nesmie tváriť ako dnešná |
| [`dem/coverage.py`](dem/coverage.py) | nepodpísaná (alebo staro podpísaná) prázdna dlaždica je **lož ako každá iná** → zmaže sa zo skladu a ďalší beh ten stupeň prečíta znova. Sklad sa tým vylieči sám, len to chce dva behy |
| [`dem/fetch.sh`](dem/fetch.sh) | prázdne stupne sa vypisujú **vždy**, aj keď je pokrytie 100 % – inak sa „prečo tam nie sú vrstevnice“ hľadá v mape a nie v logu |
| [`dem/trust.py`](dem/trust.py) | kontrola skladu sa pýta **to isté, čo sťahovanie**: podozrivo malý súbor (`tiles.EMPTY_MAX_BYTES`) otvorí a podpis posúdi `coverage.empty_stamp` – teda tá istá funkcia. Otvárajú sa LEN malé súbory, skutočná dlaždica má stovky MB |
| [`lint/dem-empty.py`](lint/dem-empty.py) | stráží, že o prázdnote nerozhoduje vzorkovanie, že sa podpis naozaj píše, že `coverage.py` má o prázdnej dlaždici tú istú predstavu ako `tiles.py` a že `check.sh` sa pýta cez `trust.py` |

**Kým sa kontrola pýtala len na meno, vylieči sa to až po páde.** Sklad síce
nepoctivú dlaždicu zahodí sám, ale robí to `coverage.py` – teda až v jobe,
ktorý si model vypýtal. Beh 31781263921 na tom zomrel: `dem-dmr5` mal
`N48E016.tif` s nulovou veľkosťou (prázdna dlaždica ešte od kontroly „v1"),
`check-dem` povedal „2 z 2 → doplniť: false", doplnenie sa nespustilo a
tieňovanie o minútu neskôr napočítalo pokrytie 75,8 %, prešlo na Sonnyho a
spadlo (jeho sklad je prázdny). Odvtedy sa na to isté pýta už aj kontrola –
`dem/trust.py` – takže sa chýbajúci stupeň doplní hneď na začiatku behu.

Skál sa to netýkalo: pri `rock_source: dmr5` si sklon číta
[`contours-rocks/slope-chunks.py`](contours-rocks/slope-chunks.py) z Drive po
častiach a dlaždicovú podobu vôbec nepoužíva.

#### Výstup je vstup pre Build map

Toto je celý zmysel workflowu — čo z neho vypadne, z toho vie `Build map`
počítať **vrstevnice, skaly aj tieňovanie**:

| `area` | mriežka | výsledok | sklad | v Build map |
|---|--:|---|---|---|
| `cele_slovensko` | 5 m | dlaždice `N49E019.tif` | `dem-dmr5` | `dmr5` vo výbere vrstevníc/skál/tieňovania |
| pohorie | **1 m** | `ugkk-<pohorie>.tif` | `dem-ugkk` | `dmr5` vo výbere vrstevníc/skál + rovnaké `area` |

Pomenúvacia schéma aj formát sú tie isté ako u Sonnyho a DMR 3.5, takže
[`workers/dem/fetch.sh`](dem/fetch.sh) sa pri čítaní vôbec nevetví —
rozhoduje len meno releasu. Build mapy sa nemusí učiť nič nové. Presné
nastavenia vypíše workflow do súhrnu behu, aby sa nemuseli hádať.

**Licencia ÚGKK:** voľné použitie vrátane komerčného pri uvedení zdroja
(ÚGKK SR) — atribúcia je v [`poc/web/themes.js`](../poc/web/themes.js).

**Spúšťaš len jednu pipeline.** `Build map` sa sám pozrie, čo mu v sklade
chýba, a doplnenie si spustí ako svoju úlohu. Ručne netreba spúšťať nič –
vrátane `dmr5`, ktorý sa dopĺňa cez `Dáta · DMR 5.0` (číta cez HTTP Range len
to, čo územie pretína, takže to nie je „prekvapenie na osem hodín", ako keby sa
mal sťahovať celý model).

```
Build map
  └─ check-dem        čo chýba pre vrstevnice / skaly / tieňovanie?
       ├─ (výrez chýba)    → Doplniť DMR 5.0 (výrez)    ← spustí sa sám
       │                       Dáta · DMR 5.0, area: <pohorie>
       │                       → ugkk-<pohorie>.tif do dem-ugkk
       ├─ (dlaždice chýbajú) → Doplniť DMR 5.0 (dlaždice)  ← spustí sa sám
       │                       Dáta · DMR 5.0, area: <bbox stupňov>,
       │                       tiles: true → N49E020.tif do dem-dmr5
       ├─ contours    stiahne výrez z releasu a počíta
       └─ terrain     stiahne dlaždice z releasu a tieňuje
```

Ktorý sklad a ktoré súbory ktorá vrstva potrebuje, hovorí jediné miesto –
[`workers/dem/target.py`](dem/target.py). Pýta sa doň aj kontrola
(`workers/dem/check.sh`), aj sťahovanie (`workers/dem/fetch.sh`); kým to bolo
napísané dvakrát, rozišlo sa to a build kontroloval jeden sklad, kým sťahoval
z druhého ([beh 31307163093](https://github.com/skifahrer/fricomaps/actions/runs/31307163093)).

> **Zrkadlo skúša štyri cesty a v každej sa tvári ako prehliadač.**
> Geoportály za WAF-om bežne zahadzujú požiadavky, ktoré nevyzerajú ako
> prehliadač – a nezahadzujú ich chybou, ale **tichom**, čo v logu vyzerá
> presne ako výpadok siete. V behu
> [30997189220](https://github.com/skifahrer/fricomaps/actions/runs/30997189220)
> to bol práve timeout, takže to stálo za skúšku.
>
> | # | cesta | poznámka |
> |--:|---|---|
> | 1 | priame URL (`ugkk_urls`) | čo si zadal ručne |
> | 2 | **metadátový katalóg RPI** | dá *skutočné* URL služieb namiesto uhádnutých názvov – a je to iný hostiteľ |
> | 3 | ArcGIS `exportImage` | kandidáti + čo sa nájde v adresári služieb |
> | 4 | WCS `GetCoverage` | |
>
> Každá požiadavka ide postupne ako **Safari 17 → Chrome 124 → ArcGIS Pro →
> fricomaps**, a keď neprejde ani jeden, ešte raz cez **`curl` s HTTP/2** –
> lebo časť WAF-ov blokuje podľa TLS odtlačku spojenia, nie podľa hlavičiek,
> a curl má iný TLS stack než Python.
>
> **Prvý krok zrkadla je diagnostika**, ktorá to celé zmeria a napíše do
> Summary maticu hostiteľ × profil:
>
> ```
>    zbgis.skgeodesy.sk                     URL!      URL!      URL!      URL!       000
>    rpi.gov.sk                             URL!      URL!      URL!      URL!       000
>    pypi.org                                200       200       200       200       200
>                                         Safari    Chrome    ArcGIS  fricomaps      curl
> ```
>
> Riadok `pypi.org` je kontrolný: keď je 200 a ÚGKK riadky nie, problém je na
> ich strane. Keď nie je 200 ani pypi, je rozbitá sieť runnera. Bez tohto sa
> „nefunguje to" nedá odlíšiť od „nefunguje to takto".

#### Ako to dopadlo: z GitHub runnera sa k ÚGKK dostať nedá

Zmerané, nie odhadnuté. Diagnostický workflow prehľadal širokú sadu vstupných
bodov, čo našiel to stiahol a všetko vyhodil ako artefakt. Tri behy
([31072215798](https://github.com/skifahrer/fricomaps/actions/runs/31072215798),
[31075806874](https://github.com/skifahrer/fricomaps/actions/runs/31075806874),
[31096745697](https://github.com/skifahrer/fricomaps/actions/runs/31096745697))
dali zakaždým to isté:

| hostiteľ | výsledok |
|---|---|
| `zbgis.skgeodesy.sk` | `Connection timed out` — aj pri 30 s |
| `zbgisws.skgeodesy.sk` | `Connection timed out` — aj pri 30 s |
| `geoportal.sk` aj `www.geoportal.sk` | chyba certifikátu, ich cert nesedí ani na jedno meno |
| `mapy.geoportal.sk` | neexistuje, DNS ho nepozná (bol to náš tip) |
| `data.slovensko.sk`, `data.gov.sk`, `rpi.gov.sk`, `inspire.gov.sk`, `www.skgeodesy.sk` | **HTTP 200** |

Posledný riadok je dôležitý: **nie je to geoblok na Slovensko.** Mŕtve sú
presne tie dva stroje, na ktorých sú dáta.

Vyčerpali sme adresár služieb, správne meno služby, dvoch rôznych hostiteľov,
WMS, WCS, národný katalóg otvorených dát aj INSPIRE. Že mechanika je v poriadku,
dokázalo české ČÚZK — tá istá cesta (`exportImage`) odtiaľ vrátila skutočné
GeoTIFFy.

Vedľajší nález: **správne meno služby je `LLS_DMR5`**, nie žiadne zo šiestich,
ktoré sme hádali. Vrátilo ho vyhľadávanie ArcGIS Online ako „DMR 5.0 (Web
Mercator)“, vlastník `UGKK_SR`. Nepomohlo to — na mŕtvy hostiteľ sa nedostaneš
ani so správnym menom — ale keby sa cesta niekedy otvorila, toto je meno,
ktorým začať.

**Prakticky:** `dmr5` **s výrezom** (teda plné metrové rozlíšenie) funguje len
vtedy, keď je ten výrez už v releasi `dem-ugkk`. Dostane sa tam **workflowom
[*Dáta · DMR 5.0*](#dmr-50-z-drive-145-gb-cez-http-range)** (`area:
<pohorie>`) – to si build spúšťa sám – alebo jednorazovým exportom zo
ZBGIS Mapového klienta (Terén → Export údajov → DMR 5.0, do 400 km²)
a nahratím ako `ugkk-<vyrez>.tif`. Inak build spadne späť na Sonnyho a napíše
to.

> **Dodatok (august 2026): tá cesta sa našla, dokonca dvakrát.** Všetko nižšie
> o mŕtvom `zbgis.skgeodesy.sk` platí – ale to isté DMR 5.0 leží aj na
> `opendata.skgeodesy.sk` ako jeden 198 GB ZIP, a jeho ETRS89 verzia na Google
> Drive ako dva holé BigTIFFy. Odtiaľ sa vziať dá. Viď [DMR 5.0 z
> Drive](#dmr-50-z-drive-145-gb-cez-http-range).

Build to preto **neskúša naslepo**: `dem/fetch-ugkk.py` sa najprv spýta na
dostupnosť hostiteľa a keď neodpovedá, ImageServer ani WCS už nerozbieha —
všetky sú na tej istej doméne a každý z nich stojí štyri profily prehliadača
plus curl.

**1 m sa dá len na výrez.** Celý kraj má pri 1 m 16 miliárd buniek, čo je 64 GB
vo Float32 – a to sa nezmestí na runner (voľných má ~60 GB).
Preto si `dmr5` podobu vyberá podľa rozsahu: s vyplneným `area` ide plné 1 m,
bez neho dlaždice na 5 m. Nie je to teda čo zakázať, ale čo dopočítať:

| výrez | plocha | 1 m raster (Float32) |
|---|--:|--:|
| Belianske Tatry | 177 km² | ~0,7 GB |
| Vysoké Tatry | 541 km² | ~2,2 GB (COG ~0,6 GB) |
| celý kraj | 16 103 km² | ~64 GB → **odmietne** |

#### Testovací výrez – vrstevnice aj skaly len na pohorí

Terén je najdrahšia časť buildu. Pri ladení prahu, mriežky, zdroja alebo
farieb nemá zmysel čakať polhodinu na celý kraj, keď ťa zaujíma jedno pohorie
– na to je input **`area`**. Platí na **vrstevnice aj skaly**:

| `area` | územie | plocha | terén trvá |
|---|---|--:|--:|
| *(prázdne)* | celý región | 16 103 km² | ~30 min |
| `tatry` | Západné + Vysoké + Belianske | 1 032 km² | ~2 min |
| `vysoke_tatry` | Vysoké Tatry | 541 km² | ~1 min |
| `belianske_tatry` | Belianske Tatry | 177 km² | <1 min |
| `slovensky_raj` | Slovenský raj | 424 km² | ~1 min |
| `20.0,49.1,20.2,49.2` | vlastný bbox | 161 km² | <1 min |

*(plochy sú po orezaní na Prešovský kraj)*

Pomenované výrezy sú vo [`workers/data/areas.json`](data/areas.json) – zatiaľ
Tatry (celé aj po častiach), Nízke Tatry, Slovenský raj, Pieniny, Malá aj
Veľká Fatra, Súľovské skaly, Slovenský kras, Muránska planina, Vihorlat,
Strážovské vrchy a Malé Karpaty. Namiesto názvu sa dá zadať aj bbox
`west,south,east,north`.

Výrez sa vždy **pretne s bboxom regiónu** – čo je mimo, sa nepočíta (nie je
tam ani DEM, ani mapa). Keď sa neprekrývajú vôbec (napr. `mala_fatra`
s Prešovským krajom), build to povie rovno a zastaví sa, namiesto aby
polhodinu počítal prázdno.

> **Vo zvyšku regiónu potom nie sú ani vrstevnice, ani skaly.** Mapa a
> tieňovanie sú za celý región – toto je beh na testovanie, nie na nasadenie. Build to hlási ako
> `::warning::` aj v súhrne, aby sa taký beh omylom nenasadil ako finálny.
> Výrez je aj v mene uloženého assetu (`rock-{región}-{výrez}-…`) a v kľúči
> cache, takže sa skaly z Tatier nikdy nevydávajú za skaly celého kraja.

#### Koľko to bude trvať sa povie dopredu

Skaly sa **nezačnú počítať, kým sa nevypíše plán**: čo sa ide robiť, nad čím,
za koľko a s akými stropmi (`ROCK_BUDGET_MIN`, default 30 min):

```
── Plán výpočtu skál ────────────────────────────────
  územie          208×111 km (obdĺžnik v EPSG:3035)
  mriežka         1 m
  buniek          19.60 mld.
  častí           144 z 170 (26 mimo územia sa preskočí), po 12.2×11.1 km
  odhad sklon     1:04:02
  odhad obrysy    1:33:19
  odhad SPOLU     2:37:21  (rozpočet 0:30:00)
  mozaika na disk ~1.0 GB
  špička pamäte   ~13.4 GB
─────────────────────────────────────────────────────
::warning::Vektorizácia … potrvá odhadom ~1:33:19, čo je nad rozpočet
30 min – NEZASTAVUJEM ju, nechávam dobehnúť. Keď to má byť rýchlejšie:
hrubší sklad (rock_res) alebo menší výrez (area).
```

**Rozpočet je odhad, nie vypínač.** Nad ním sa to povie a počíta sa ďalej –
zastaviť vektorizáciu nemá čo zachrániť: je to jeden nedeliteľný priechod nad
celou mozaikou (kvôli dieram), takže zabitý `gdal_contour` nenechá ani
neúplný výstup. Zastavenie znamenalo to isté ako timeout jobu, len skôr, a
k tomu bez šance, že by beh dobehol. Stropy, ktoré platia, sú timeout jobu
`rocks` (3 h) a pamäť.

Presne z toho istého odhadu ale vyberá `rock_res: auto` mriežku – zoberie
najjemnejšiu so ✓ (zdola stropenú desatinou bunky DEM), takže cesta, ako sa
do rozpočtu zmestiť, je tá automatická.

| územie | `rock_res` | buniek | odhad | |
|---|--:|--:|--:|---|
| Prešovský kraj | 1 m | 19,60 mld. | 2:37:21 | ✗ auto ho nezvolí |
| Prešovský kraj | **2 m (auto pri Sonnym)** | 5,27 mld. | 0:42:18 | ✓ |
| Prešovský kraj | 3 m | 2,57 mld. | 0:20:38 | ✓ |
| Tatry | 1 m | 1,34 mld. | 0:10:46 | ✓ |
| Vysoké Tatry | 1 m | 0,71 mld. | 0:05:44 | ✓ |
| Belianske Tatry | 1 m | 0,23 mld. | 0:01:49 | ✓ |

Konštanty odhadu sú **namerané na runneri**, nie odhadnuté: sklon
5,1 mil. buniek/s, obrysy 121 tis. zdrojových buniek/s. Keď sa beh s tou
druhou rozíde viac než 3×, povie to na konci sám – vtedy sa má prepísať.

#### Počas výpočtu je vidieť, čo sa deje

```
  [12/144] sklon – 0:07:41 za sebou, zostáva ~0:24:26, mozaika 96 MB
── Vektorizácia sklonu (gdal_contour -p) ────────────
  vstup           slope-chunks/slope-r2.vrt
  číta sa         5.27 mld. buniek skladu (2 m) – toto rozhoduje o čase
  trasuje sa      3.37 mld. buniek na 2 m
  prahy           sklon ≥ 50° (raster je v stotinách stupňa)
  odhad           ~0:25:05 pri 121 tis. buniek/s (rozpočet 30 min)
  stropy          pamäť 12 GB; čas NEOBMEDZENÝ – jeden priechod sa nedá
                  prerušiť a nadviazať, tak beží, kým nie je hotový
  postup          percentá po 2,5 % + tep každých 30 s
─────────────────────────────────────────────────────
▶ gdal_contour: gdal_contour -p -fl 5000.0 -amin smin -amax smax -f GPKG …
… gdal_contour: 30 % (beží 0:07:14, tempo 4.1 %/min, zostáva ~0:16:53 (koniec ~14:23))
… gdal_contour: beží 0:07:30, 32.5 %, zostáva ~0:15:35 (koniec ~14:23),
  pamäť 2.4 GB (špička 2.4 GB, strop 12.0 GB), CPU 99 % (priemer 97 %),
  disk 4210/640 MB (+8.1/+1.2 MB/s), výstup 1129 MB (+2.1 MB/s)
✔ gdal_contour: hotovo za 0:24:29, výstup 612 MB, špička pamäte 2.4 GB,
  CPU 0:23:51 (97 %), disk 4210 MB čítania / 640 MB zápisu
```

Pri sklone ide riadok po každej časti s odpracovaným časom a odhadom zvyšku.
`gdal_contour` hlási percentá **po 2,5 %** (bodky medzi desiatkami sú tri,
takže pri hodinovom behu je to správa každé tri minúty namiesto každých
dvanástich) a nezávisle od oboch beží **tep** každých 30 s
(`ROCK_HEARTBEAT_S`): kde to je, kedy skončí, pamäť aj jej špička, CPU teraz
aj v priemere, koľko číta a zapisuje a ako rastie výstup. `CPU 99 %` znamená
„počíta, pomôže len menej práce", `CPU 0 %` znamená, že problém je inde.
Riadok `✔` na konci nesie namerané čísla – z nich, a nie z odhadu, sa opravujú
konštanty.

Keď pamäť prekročí `ROCK_MAX_RSS_GB` (12 GB), tep výpočet zastaví s hláškou –
to je lepšie než tiché zabitie runnera na OOM, po ktorom v logu nie je nič.
**Čas takú poistku nemá** a je to zámer: strop času by zahodil hodiny práce
a nenechal ani neúplný výsledok.

**Časti mimo územia sa preskočia.** EPSG:3035 je pootočená voči poludníkom,
takže obdĺžnik opísaný bboxu je v metroch väčší než región – pri Prešovskom
kraji 208×111 km namiesto 200×82 km. Čo do bboxu nezasahuje, sa nepočíta
(26 zo 170 častí pri 1 m).

#### Veľkosť plôch určuje prah sklonu, nie mriežka

Súvislá stena nad prahom je jedna plocha, nech ju počítaš na akejkoľvek
mriežke – jemnejšia mriežka dá presnejší *obrys*, nie menšie plochy. Namerané
na výreze Vysokých Tatier (mriežka 2 m):

| prah | plôch | plocha spolu | priemerná | najväčšia |
|---|---|---|---|---|
| 40° | 1 299 | 2 931 ha | 22 567 m² | **428 ha** |
| 45° | 1 019 | 1 710 ha | 16 788 m² | 82 ha |
| **50° (default)** | **719** | **884 ha** | **12 295 m²** | **38 ha** |
| 55° | 402 | 389 ha | 9 698 m² | 30 ha |
| 60° | 208 | 131 ha | 6 301 m² | 18 ha |

Pri 40° je najväčšia súvislá plocha 428 ha – to už nie je skala, ale celý
strmý svah. Preto je predvolený prah **50°**; kto chce drobnejšie a ostrejšie
vymedzené skaly, dá 55° alebo 60°.

**Počíta sa po častiach.** Bbox kraja má pri 2 m vyše 3 miliardy buniek, čo je
~13 GB na jeden raster – viac, než má runner miesta aj pamäte. Územie sa preto
krája (`ROCK_CHUNK_CELLS`, default 150 mil. buniek na kus), každá časť sa
spracuje a hneď upratá; sklon sa počíta s presahom a plochy sa orežú presne na
hranicu časti, takže susedné kusy na seba nadväzujú bez medzery ani prekryvu.
Čas rastie lineárne – merané ~2,5 mil. buniek/s, teda kraj pri 2 m okolo
30 minút. **Mriežka 1 m sa oplatí len na `crop_bbox`; pre kraj by to boli
~2 hodiny.**

Ovládanie vo workflowe: `rock_source` (z ktorého modelu – alebo `ziadne`,
čím sa skaly vypnú) a `rock_slope` (od akého sklonu je terén skala, default
50°); mriežka obrysu je voľba `options: rock_res=…` (číslo v metroch alebo
`auto`, default `auto`).
Ostatné ladenie je v `env:` na začiatku
[build-map.yml](../.github/workflows/build-map.yml): `ROCK_SIMPLIFY` (0 = presný
obrys), `ROCK_SMOOTH` (priehyb zaoblenia v štvrtinách kroku mriežky
dlaždice, 0 = vypnúť),
`ROCK_CLIFF_PLUS` (o koľko ° nad prahom začína trieda `cliff`),
`ROCK_CHUNK_CELLS` (koľko buniek naraz pri počítaní sklonu), `ROCK_ALGO`
(verzia algoritmu v mene uloženého assetu).

V mape z toho sú **tmavšie sivohnedé plochy** (#8a8578, farba papierovej
horskej mapy) kreslené *pod* tieňovaním aj *pod*
vrstevnicami. Poradie je zámerné a v tomto poradí: skala je tvar terénu, takže
cez ňu musí prejsť tieňovanie (inak je práve stena v mape plochá škvrna bez
reliéfu), a vrstevnica musí prejsť cez oboje (inak nie sú výšky tam, kde je
terén najstrmší). Farba `Skalné plochy (plná výplň)` je v palete v skupine
**Vrstevnice a skaly**, takže sa dá v developer móde doladiť ako čokoľvek iné.

**Hotové skaly sa neprepočítavajú.** Uložia sa do releasu `dem-rocks` pod
menom, ktoré nesie región aj nastavenia
(`rock-{región}-s{prah}-g{mriežka}-{algo}.gpkg.zst`), takže ďalší build s tými istými
nastaveniami ich len stiahne – sekundy namiesto desiatok minút. Iné nastavenia
dajú iné meno súboru, takže sa nikdy nepomiešajú. Ako to prepočítať nanovo,
hovorí [Pregenerovanie](#pregenerovanie).

Hotové skaly a vrstevnice si každý build odloží aj do **skladu `vysledky`**
(`teren-{región}-s{prah}-g{mriežka}-{dátum}-r{beh}.tar.zst`) – aj s GPKG
geometriou, takže sa dajú stiahnuť a pozrieť v QGISe bez ďalšieho buildu.
Kedysi to bol artefakt behu s 90-dňovou lehotou; do GitHubu sa už nepublikuje
nič a sklad na Drive prerieďuje na tých istých 90 dní workflow *Údržba · týždenné upratovanie*.

Podiel plochy nad prahom (merané pri 40°, teda hornom odhade):

| územie | podiel plochy nad 40° |
|---|---|
| Vysoké Tatry (hrebeň, doliny) | 8,0 % |
| Malá Fatra (lesnaté hory) | 0,7 % |
| Považie pri Trenčíne (kopce) | 0,7 % |

### Pregenerovanie

Nič sa nepočíta dvakrát: vrstevnice, skaly aj tieňovanie sa berú z cache
(a skaly navyše z releasu `dem-rocks`, tieňovanie z `dem-terrain`). Keď sa
zmenia nastavenia, zmení sa aj kľúč a prepočíta sa to samo. Keď chceš to isté
prepočítať **nanovo aj pri rovnakých nastaveniach**, spusť *Build map*
so zaškrtnutým inputom:

| `rebuild` | čo pregeneruje |
|---|---|
| `vrstevnice` | vrstevnice **aj skaly** – zmaže cache `contours-…` a trasuje z DEM odznova |
| `skaly` | skaly – zmaže cache aj súbor v sklade `dem-rocks` (vrstevnice sa prepočítajú s nimi, sú lacné) a pri `rock_source: tienovanie` zahodí aj rozrobené obrysy podpipeline (`fresh=1`) |
| `tienovanie` | tieňovanie a 3D terén – zmaže cache aj súbor v sklade `dem-terrain` |
| `clanky` | články z Wikipédie – **obíde cache** `wiki-…` a stiahne ich odznova |
| `vsetko` | všetko z tejto tabuľky |

Prečo to musí najprv mazať: **existujúci záznam cache sa nedá prepísať.**
Kľúč, ktorý raz existuje, si drží starý obsah, takže bez zmazania by sa
prepočítaná verzia zahodila a ďalší build by dostal späť tú starú. Preto každý
`*_rebuild` začne tým, že príslušný záznam zmaže (aj jeho variant `-rocks`,
lebo skaly majú vlastný job a tým aj vlastný záznam).

**Články sú jediná výnimka z toho mazania a nie je to nedôslednosť:** ich kľúč
má na konci číslo behu (`wiki-v1-…-<run_id>`), takže nový záznam vždy vznikne
a ďalší beh si cez predponu vezme najnovší – čiže ten čerstvý. `rebuild:
clanky` preto len **preskočí obnovenie**: nesťahuje z Drive nič, čo by potom
zahodil.

**Kedy to naozaj treba.** Cache článkov sa neplatí kalendárom, ale `lastrevid`
(viď kapitolu o jobe `wiki`), takže zmenu na Wikipédii zachytí sama – na to
`rebuild: clanky` netreba. Treba ho na ten druhý prípad: **zmenil sa zberač**
(pribudla podoba odkazu, iný prevod wikitextu, iné jazyky). Vtedy je
`lastrevid` ten istý, cache sadne a vrátila by články spracované po starom –
zelený beh so starým obsahom, čiže pravidlo 8.

**Testovací beh články NEpregenerúva**, hoci terén áno. Nezávisia od
testovacieho štvorca ani od prahov, ktoré sa ním ladia – job `wiki` číta celý
regionálny PBF tak či tak – a sťahovať pri každom kole ladenia terénu tisíc
článkov odznova by bola len daň za to, že sa ladí niečo iné.

Ostatné cache (PBF, Planetiler, DEM dlaždice, glyfy a sprity) sa
nepregenerúvajú vôbec – sú to stiahnuté dáta, nie výpočet, a majú v kľúči buď
dátum, alebo otlačok zdroja.

### Vrstvy z DEM sa počítajú na KRAJ, nie na jeho obdĺžnik

Vrstevnice, skaly a tieňovanie sa počítali na **bboxe** regiónu. Bbox
Prešovského kraja je obdĺžnik ~199×82 km, teda 16 107 km², kým kraj má
10 184 km² – **37 % práce padalo mimo kraj**, do susedných krajov a za hranicu.
A nie je to len práca navyše: **DMR 5.0 je len Slovensko**, takže za hranicou je
v modeli nodata, a hranica dát a nodaty je pre `gdaldem slope` zvislá stena so
sklonom 90°.

| región | kraj | bbox | mimo kraj |
|---|--:|--:|--:|
| Prešovský | 10 184 km² | 16 107 km² | **37 %** |
| Žilinský | 7 706 km² | 13 068 km² | 41 % |
| Bratislavský | 2 142 km² | 3 773 km² | 43 % |

**Polygón sa nekreslí ani sa neťahá z OSM – berie sa ten istý `.poly`, ktorým
je orezaný náš PBF** (openstreetmap.fr ich zverejňuje vedľa extraktov, pri kraji
je to ~3,5 kB a 249 bodov). Mapa a jej výškové vrstvy tak majú **rovnakú**
hranicu; druhá definícia by sa raz rozišla s prvou. Vyrába ho
[`workers/plan/region-poly.py`](plan/region-poly.py) v jobe `plan` a ostatné
joby ho dostanú **artefaktom** – keby si ho ťahal každý sám a jednému by sa to
nepodarilo, rezal by na bboxe, kým ostatní na kraji.

**Pol dlaždice smie prečnievať.** Dlaždica tieňovania sa berie, keď sa jej okno
zväčšené o pol svojej strany dotýka kraja
([`workers/lib/region-mask.py`](lib/region-mask.py)). Bez tej rezervy by vrstva
končila presne na hranici a v mape by bola rovná hrana tam, kde ešte má byť
terén. Namerané na Prešovskom kraji: z11 sa vynechá 7 % dlaždíc, z13 27 %,
**z14 31 %**.

**Lenže dlaždica je nedeliteľná, tak sa tieňovanie orezáva aj PO PIXELOCH.**
Ktorá sa kraja dotkne, tá sa vyrobí CELÁ – a na nízkych zoomoch je obrovská,
takže tieňovaný reliéf pokračoval ďaleko za hranicu stiahnutého regiónu.
Namerané na Prešovskom kraji ako plocha vyrobených dlaždíc proti ploche kraja:

| zoom | z8 | z9 | z10 | z11 | z12 | z13 | z14 |
|---|--:|--:|--:|--:|--:|--:|--:|
| pred | 6,2× | 3,8× | **2,2×** | 1,7× | 1,4× | 1,2× | 1,11× |
| po | 1,07× | 1,04× | **1,02×** | 1,00× | 1,00× | 1,00× | 1,00× |

Ktoré pixely dlaždice sú ešte kraj, povie `pixel_mask` v tom istom súbore –
a za nimi sa výška **dopĺňa okolím** ([`terrain/vyska.py`](terrain/vyska.py) —
je tam aj výplň dier v modeli; obe odpovede na „tu výšku nemáme" bývajú vedľa
seba, a `tiles.py` je plán, warp a kódovanie).
V mape to dovtedy zakrývala až plocha `mimo` zo štýlu, čiže to bola tichá
chyba: vrstva bola dvakrát väčšia než región a bolo to vidieť, len keď sa
maska nekreslila (a v 3D pod iným uhlom).

**Rovina za hranicou bola stena.** Kým tam bola výška 0, spadol terén medzi
dvoma pixelmi zo 600 m na nulu – a to je pre hillshade (derivácia výšky)
zvislý útes, v 3D doslova múr po obvode regiónu. Namerané celou pipeline na
umelom teréne (z13, 12,5 m/px, členitý polygón kraja; terén sám má v kraji
najväčší sklon 17,9° a stredný 8,0°):

| orez | najväčší 1–4 px za | najväčší 5–12 px za | stredný 1–8 px za | stredný 33–128 px za |
|---|--:|--:|--:|--:|
| rovina 0 m | **89,4°** | 89,4° | **79,2°** | 0,0° |
| pokračovanie okolím | **30,6°** | 22,8° | **7,0°** | 5,5° |

`--edge` (2 px) stenu len **posúval** za hranicu, kde ju plocha `mimo`
prekrýva – lenže schovaná stena je stále stena a v 3D, pri prevýšení a všade,
kde sa maska nekreslí, ju bolo vidieť. Pokračovanie stenu nepostaví nikde;
`--edge` ostáva, ale s inou úlohou: koľko pixelov skutočného terénu sa nechá
ešte za hranicou, nech tieňovanie NA hranici stojí na okolí a nie na výplni.

Dopĺňa sa **pyramídou priemerov** (pull-push), nie po riadkoch a stĺpcoch ako
`vypln_nodata` za okrajom modelu: tá je stavaná na rovný okraj a na členitej
hranici kraja spraví vlastnú stenu (namerané 825 m medzi dvoma susednými
riadkami dva pixely za hranicou, čiže 89°). Šev medzi doplneným a skutočným
sa na každej úrovni zvarí štyrmi priechodmi priemeru – bez nich má p99 švov
42,2°, s nimi 24,8°, čo je p99 terénu (20,9°).

Cenou je, že tieňovanie za hranicou nekončí skokom, ale slabne (8,0° v kraji
→ 5,5° stotridsať pixelov za hranicou). Ten pás je celý ZA hranicou pod
plochou `mimo` a ďalej než o kúsok sa nedostane: **dlaždica, v ktorej nie je
ani jeden pixel kraja, sa nezapíše vôbec** – to isté, čo predtým robila rovina
cez `je_rovina`, len sa to pýta priamo masky. Dlaždíc je preto rovnako veľa
ako s rovinou a sú o pár percent väčšie (kraj na 54 % bboxu: 202 dlaždíc
a 8,7 MB proti 203 a 8,2 MB) – doplnené výšky sa preto zaokrúhľujú na
`SLOPE_EPS × pixel`, čo je krok, pod ktorým je sklon z kvantizácie
neviditeľný (669 kB → 444 kB na skúšobnej mriežke). Podoba kódovania ide
z `v5` na **`v6`** (meno assetu v sklade aj kľúč cache), inak by build vrátil
staré dlaždice a oprava by sa na už spočítanom regióne neprejavila.

Maska je rastrová a **bez shapely** – tá istá úvaha ako v `dem/coverage.py`: pri
mriežke 2048 buniek je bunka ~100 m, kým dlaždica na z14 má ~1,5 km. Vrstevnice
a skaly dostanú polygón ako `-cutline` do gdalwarpu (bez `-crop_to_cutline` –
okno má ostať bboxom, nech sa kľúče cache nemenia).

### Dlaždica DEM musí mať aj DÁTA, nie len rozsah

Pokrytie sa meralo z **rozsahov** dlaždíc („mozaika sa dotýka celého bboxu") a to
prejde aj vtedy, keď je dlaždica takmer prázdna. V behu **31635772047** mala
v sklade `dem-dmr5` dlaždica `N49E020.tif` – Vysoké Tatry, čiže **stred**
Prešovského kraja – **5 MB**, kým susedná `N49E021.tif` 265 MB. Kontrola
vypísala „Pokrytie územia 100.0 % z 8 dlaždíc" a beh pokračoval:

* **tieňovanie** skončilo rovnou hranou na 21° (prázdny model = biele dlaždice),
* **skalám** z hrany dát vyšlo **13 403 km²** „skalnej plochy" (bbox má 16 107),
  zlepovanie švov to nedalo dokopy (`z 13403.21 km² ostalo 0.00 km²`) a spadlo
  na náhradné riešenie s 375 nezlepenými plochami – v mape teda skaly len na
  kúsku.

`coverage.py --data-pct` preto pri každej dlaždici vypíše podiel skutočných
výšok (`STATISTICS_VALID_PERCENT`, presný priechod – nie vzorkovanie, to už raz
odrezalo pol kraja) aj jej veľkosť, a pod prahom (2 %) to **ohlási varovaním**
s návodom: keď ten stupeň má byť plný, zmazať zo skladu a nechať doplniť znova.
Nie je to pád – stupeň celý za hranicou Slovenska je prázdny právom.

### Hotové dáta ležia v sklade na Google Drive, nie v releasoch

Do GitHubu nejde nič, čo má prežiť beh — **ani release, ani artefakt**. Osem
druhov drahých medzivýsledkov kedysi ležalo v releasoch (`dem-sonny`,
`dem-dmr35`, `dem-dmr5`, `dem-ugkk`, `dem-terrain`, `dem-rocks`,
`dem-rocks-img`, `dem-slope`) a medzivýsledky na pozretie v artefaktoch
s 30- až 90-dňovou retenciou. Oboje je teraz v **sklade na Google Drive** —
na tom istom účte, ktorý drží DMR 5.0, cache buildu aj hotové mapy.

```
<koreň>/dem-dmr5/N49E020.tif             <koreň> = `fricomaps-sklad`
<koreň>/dem-ugkk/ugkk-vysoke_tatry.tif   v My Drive vlastníka tokenu
<koreň>/vysledky/teren-…-r73.tar.zst
         sklad     meno — to isté, aké mal asset releasu
```

Prečo: release má na jeden asset **strop 2 GB**, ktorý pipeline tvaroval
zvonku, a hotové dáta v releasoch verejného repozitára vyzerajú ako vydanie
softvéru, ktorým nikdy neboli. Ten strop teda odpadol — **dve podoby DMR 5.0
však ostávajú**, tie nedržal release, ale runner: jedna 1°×1° dlaždica má
v metri ~48 GB a voľných je ~60 GB.

Čo sa tým **nezmenilo**: mená súborov (`N49E020.tif` ďalej hovorí „tento celý
stupeň je tu"), ani to, ktorý sklad ktorá vrstva hľadá. Celý rozpis je vo
[`workers/drive/store.py`](drive/store.py).

Krátkodobé artefakty (`site-*`, `steps-*` s `retention-days: 1`) ostávajú a nie
sú publikovanie — sú to prepravky, ktorými si joby jedného behu podávajú kusy
`_site`. Čokoľvek s dlhšou retenciou ide do skladu `vysledky` cez
[`workers/deploy/publish-results.sh`](deploy/publish-results.sh) a *Kontrola · lint workflowov* to
kontroluje. Staré releasy, ich tagy aj artefakty zmaže *Údržba · týždenné upratovanie*
([`cleanup.yml`](../.github/workflows/cleanup.yml)) v režime
`releasy_a_artefakty`.

### Cache leží na Google Drive

GitHubová cache má na repozitár **10 GB** a keď sa naplní, nič nepovie — ticho
vyhodí najstaršie záznamy. Jeden výrez do nej pritom ukladá desiatky GB (DEM
dlaždice, sklad častí sklonu, vrstevnice, tieňovanie, dlaždice tieňovania),
takže si záznamy vyhadzovali navzájom a hodinové výpočty sa rátali odznova bez
toho, aby bolo na čom to vidieť — build je zelený, len trvá hodinu namiesto
minút.

Preto záznamy ležia na Google Drive, na tom istom účte, ktorý drží DMR 5.0.
Kroky vo workflowoch vyzerajú rovnako ako predtým (`.github/actions/cache-restore`
a `cache-save` namiesto `actions/cache/*`) a **sémantika je tá istá**:
`cache-hit` len pri presnej zhode kľúča, `restore-keys` ako predpony, existujúci
kľúč sa neprepisuje. Celý rozpis je vo
[`workers/drive/cache.py`](drive/cache.py).

Dve veci, ktoré z toho plynú:

- **Token na Drive musí vedieť zapisovať** (rozsah `drive`, nie
  `drive.readonly`). `python3 workers/drive/cache.py --check` povie, či vie —
  aj koľko miesta na účte ešte je.
- **Nič sa nemaže samo.** GitHub staré záznamy vyhadzoval sám, Drive nie.
  Preriedi ich workflow *Údržba · týždenné upratovanie*
  ([`cleanup.yml`](../.github/workflows/cleanup.yml)) — raz za týždeň, alebo
  ručne. Ten istý workflow vyprázdni aj GitHub cache, ktorú už nikto nehľadá,
  a preriedi sklad `vysledky`. Kým to boli dva workflowy, mali dva plány
  posunuté o pol hodiny, aby si nelezli do cesty.

### Hotová mapa ide aj na Drive – tri ZIPy so stálym menom

Okrem GitHub Pages sa každý build publikuje do priečinka na Google Drive.
Priečinok hovorí, čoho sa mapa týka, a čo chýba, sa vyrobí:

```
<koreň>/slovensko/presovsky/vysoke_tatry/
         krajina  kraj      výsek   (úrovne, čo nedávajú zmysel, sa vynechajú)

    presovsky-vysoke_tatry.zip                    základná mapa, BEZ riadkov nižšie,
                                                  ale S hľadaním a navigáciou;
                                                  bez glyfov a viewera (tie sú na Pages)
    presovsky-vysoke_tatry-vrstevnice-skaly.zip   len tie dve vrstvy (.pmtiles)
    presovsky-vysoke_tatry-tienovanie.zip         len výškové dlaždice (.pmtiles)
    presovsky-vysoke_tatry-linie.zip              značené trasy a obmedzenia na ceste –
                                                  LÍNIE z OSM (.pmtiles)
    presovsky-vysoke_tatry-body.zip               pramene, jaskyne, rozhľadne, … –
                                                  BODY z OSM (.pmtiles)
    presovsky-vysoke_tatry-wikipedia.zip          články z Wikipédie

Každý balík je aj ako **`.aar` (Apple Archive)** – ten istý obsah, to isté
meno, iná prípona. iOS a macOS ho rozbalia systémovo (framework AppleArchive),
bez tretej knižnice v aplikácii, a LZFSE je na Apple hardvéri rýchlejšie než
deflate. Robí to vlastný job na `macos-latest`, lebo nástroj `aa` je súčasť
macOS; vypína sa voľbou `apple_archive=false`. V `maps.json` má každý balík
`formats.zip` aj `formats.aar`. + index.json
```

**Základná mapa vrstevnice, skaly ani tieňovanie NEOBSAHUJE.** Sú to ťažké
vrstvy z výškového modelu, ktoré mapa na to, aby sa nakreslila, nepotrebuje,
a vážia porovnateľne s ňou samou, takže majú vlastné balíky presne preto, aby
si ich človek nemusel sťahovať, keď ich nechce. Kto ich chce, rozbalí
príslušný ZIP navrch: cesty vnútri sú tie isté ako v `_site`, takže sa dá
rozbaliť jeden cez druhý.

**Značené trasy, obmedzenia na ceste a body v krajine sú z rovnakého dôvodu
VONKU aj zo základnej mapy** – od nej, na rozdiel od vrstevníc a skál, mapa
vyzerá rovnako aj bez nich (kreslí sa nad hotovými cestami), takže tu ide
výlučne o veľkosť sťahovania:

| balík | čo v ňom je | z ktorých `.pmtiles` |
|---|---|---|
| `linie` | značené trasy a obmedzenia na ceste – ČISTO líniové dáta z OSM | `-trails`, `-roads` |
| `body` | pramene, jaskyne, rozhľadne, pamiatky, banské dedičstvo, geodetické body | `-points` |

Krajinné línie a plochy (`-features.pmtiles`: násypy, múry, ploty, vedenia,
parkoviská, zjazdovky, …) VLASTNÝ balík nemajú a ostávajú v základnej mape –
sú to línie AJ plochy naraz, takže by nesadli čisto do ani jedného z balíkov
vyššie bez toho, aby sa appke sľúbilo niečo, čo v nej nie je (rozpis pri
pravidle 2: keď rozsah nie je celý, musí sa zmeniť meno).

**Body majú VLASTNÝ `.pmtiles`** (`workers/features/points.yml`) presne kvôli
balíku `body`: `feature_line`, `feature_area` aj `feature_point` kedysi
vznikali v jednom súbore (`features.yml`) a appka ich nemala ako rozdeliť bez
toho, aby ho rozbalila a filtrovala obsah sama. Vstup aj predfilter zostali
spoločné (`workers/features/build.sh` beží Planetiler nad tým istým PBF
druhýkrát, raz na každú schému) – rozdelenie sa na to, čo je na mape VIDIEŤ,
neprejaví, len na tom, v ktorom súbore to leží.

**Hľadanie a navigácia sú naopak V NEJ – sú to časti, nie balíky.** Vlastný
`-search.zip` mali a bola to chyba v tom, čo mapa sľubuje: kto si stiahol mapu
kraja, dostal mapu, v ktorej sa nedá nič nájsť ani nikam doviesť, a že mu chýba
druhý súbor, nemal ako vedieť – žiadny „stiahni si aj toto" v aplikácii nie je.
Cena je jednotky až desiatky MB proti stovkám za dlaždice. Balík `-search`
preto zanikol (`ZRUSENE` v `publish-map.py`) a starý sa na Drive maže; graf
Valhally (`_site/routing/`) sa balí rovnako.

**Obe sú vždy za ten jeden región**, ktorého je balík. Index je z toho istého
PBF ako mapa; graf sa stavia z `data/region.osm.pbf` toho istého behu
(workflow [`navigation-region.yml`](../.github/workflows/navigation-region.yml)),
takže **trasa v ňom končí na hranici kraja** – hrana, ktorej v rezanom PBF
chýba druhý koniec, je slepá ulica. Je to zámer a `graf.json` v balíku to
o sebe hovorí (`rozsah: "region"`, `hranica: …`); kto potrebuje prejsť
hranicu, má na to celoštátny graf z [`navigation.yml`](../.github/workflows/navigation.yml).
Rozpis oboch je v [`docs/navigation.md`](../docs/navigation.md).

**Koľko z balíka tie časti sú, je vidieť v katalógu** – `maps.json` má pod
balíkom `mapa` kľúč `casti` s `raw_size` (bajty pred zabalením, preto iné meno
než `size` balíka) a počtom súborov. Časť, ktorá sa nedá odmerať, je presne to,
čím bol `search-index.db` predtým, než sa naň niekto pozrel: ležal v balíku
dvakrát a na veľkosti to nikto nepoznal.

**Balík, ktorý v `publish-map.py` pribudne, patrí vždy aj do `vylucit`** –
vynechať ho je ticho: mapa je v poriadku, len o toľko väčšia, a na súbore to
nikto nepozná.

**Ani glyfy a webový viewer v ňom nie sú.** Fonty boli po dlaždiciach druhá
najväčšia vec v balíku (tri fontstacky Noto Sans po ~34 MB, celý unicode, a mapa
kraja z nich použije zlomok) a `index.html` s `*.js` z `poc/web` je stránka,
ktorú si aplikácia nespúšťa – má vlastnú mapu. Oboje ostáva v `_site`, teda na
Pages.

**Kde sú teda glyfy.** Na dvoch miestach, a ani jedno nie je balík:

| kto | odkiaľ |
| --- | --- |
| web | z Pages. `manifest.json` v balíku nesie ich **absolútnu** adresu (`site.sh` ju skladá z `$BASE`), takže štýl vie, kam siahnuť. |
| aplikácia | **zo seba**. `skifahrer/rikimaps` si tri orezané stacky (3,5 MB, `Resources/Glyphs/`) nesie v binári a `glyphs` si pri načítaní štýlu prepíše na ne (`GlyphStore`). |

To druhé je dôvod, prečo sa vynechávajú **vždy** a nie podľa tvaru adresy
v manifeste. Kým appka glyfy nemala, bolo rozhodnutie odvodené z dát: vynechaj
ich práve vtedy, keď na ne manifest odkazuje absolútne – pri relatívnom odkaze
(mapa sveta) bol balík jediné miesto, kde ich štýl našiel. Odkedy ich má appka
v sebe, to neplatí ani tam, a offline mapa už nezávisí od toho, či sa dá dostať
na Pages: **na hrebeni sa naň dostať nedá**, a presne tam mapa bez písmen
vyzerá ako pokazený štýl.

Mapa sveta si preto do manifestu píše adresu verejnej služby
(`fonts.openmaptiles.org`) – nie odkaz do balíka, kde už glyfy nie sú –, aby mal
odkiaľ brať aj ten, kto appka nie je. Koľko toho balík nenesie, sa píše do logu,
a `obsah.json` v ňom to hovorí tiež (`bez_glyfov`, `glyphs`, `glyfy_kde`,
`bez_viewera`) – rovnako ako `bez_skal`. Stráži to
[`workers/lint/packaging.py`](lint/packaging.py), vrátane toho, že viewer
z `_site` nezmizne: z balíka je vynechaný práve preto, že je na Pages.

**Vrstevnice a skaly sú v jednom balíku** zámerne: sú z toho istého výpočtu nad
tým istým DEM a jedna bez druhej sa nepoužíva. Tieňovanie je zvlášť, lebo je to
jeden raster `.pmtiles` a váži rádovo inak.

**Meno je stále** — rovnaký kraj (a rovnaký výsek) má vždy to isté meno, takže
ďalší build starý balík **prepíše** a v priečinku je jeden aktuálny súbor
namiesto histórie behov. Poradie je „najprv nahraj, potom zmaž starý"
(`folder.upload_clobber`): Drive dovolí dva súbory s tým istým menom vedľa
seba, takže „najprv zmaž" by po spadnutom nahrávaní nenechalo ani nové, ani
staré. Balík vrstvy, ktorú tento build **nevyrobil**, sa zmaže – inak by vedľa
novej mapy ostal starý `-tienovanie.zip` z iného behu a na súbore by to nikto
nepoznal.

**Čo je v balíku, hovorí `obsah.json` v ňom.** Kým bolo meno jedinečné, nieslo
zoom, vrstvy a ich zdroje:

```
presovsky-vysoke_tatry-test4km2-z16-vrstevnice_dmr5_10m-skaly_dmr5-…-20260810-0748-r73.zip
```

To isté je teraz súborom vnútri: výrez, zoomy vrstiev, **z ktorého modelu sú
spočítané** (podľa toho, čo build naozaj použil, nie čo bolo vo formulári), prah
sklonu, bbox, dátum, číslo a id behu. Vrstva, ktorá v mape nie je, je tam
napísaná tiež (`bez_skal`) – mlčanie sa dá čítať aj ako „zabudlo sa to
dopísať". Fakty o mape sa neopisujú, kopírujú sa z `manifest.json`, ktorý ich
už nesie (pravidlo 1).

**Rýchly test má v mene `test4km2`** a je to nutné dvakrát: aby sa mapa z pár
km² nedala pomýliť s ostrou, a aby ju **neprepísala**.

Robí to [`workers/deploy/publish-map.py`](deploy/publish-map.py), vypnúť sa to dá
voľbou `publish=false` v poli `options` a pozrieť si balíky lokálne ide bez
Drive:

```bash
REGION_KEY=presovsky AREA_KEY=cely TILES_MAXZOOM=14 \
  python3 workers/deploy/publish-map.py --site=_site --out=/tmp --zip-only
```

### Články z Wikipédie k objektom v regióne

**Vlastný workflow: `Build wiki` (`.github/workflows/wiki.yml`).** Bol to
job v Build map a odsťahoval sa, lebo sú to tri rôzne veci naraz: **iná sieť**
(cudzí server, ktorý sa nemá čím nahradiť – keď nepustí, nemá to zhodiť
hodinový build mapy), **iná životnosť** (mapa sa prerába pri zmene dát alebo
štýlu, články si žijú vlastným tempom a ťahať ich pri každom builde je tisíce
požiadaviek za nič) a **iný výstup** (text vedľa mapy, do `_site` nejde nič).

Balík aj zápis do `maps.json` robí ďalej `publish-map.py`, len s
`--only=wikipedia`: publikuje jediný balík a položku regiónu **doplní**,
namiesto aby ju prepísal – inak by zmazal odkazy na mapu, o ktorej nič nevie.
Druhý packer by bol druhá pravda o tom istom.

Kto v regióne odkazuje na wiki, dostane článok. Body, čiary aj plochy majú v OSM
tagy `wikipedia` a `wikidata`; workflow ich z regionálneho PBF vyberie
a stiahne články **po päťdesiatich na požiadavku do jedného súboru**:

```
data/region.osm.pbf
  → osmium tags-filter   len objekty s wiki odkazom (z 30 MB PBF ostane ~1 MB,
                         takže ďalšie kroky sú sekundy)
  → osmium cat -f opl    typ, id a tagy KAŽDÉHO takého objektu
  → wikidata sitelinks   `Q…` → názov článku v požadovanom jazyku (50/req)
  → api.php prop=revisions  celý článok, PÄŤDESIAT NA POŽIADAVKU
  → wiki-out/articles.ndjson + wiki-out/index.json
```

#### Angličtina a jazyk krajiny, nie jeden z nich

Sťahuje sa **vždy anglický** článok a k nemu **v jazyku krajiny, v ktorej bod
leží**. Zoznam vzniká z troch zdrojov a každý rieši inú vec:

| zdroj | čo dáva | prečo |
|---|---|---|
| vždy `en` | anglický článok | jediný jazyk, v ktorom je článok skoro o všetkom |
| krajina regiónu | `sk` pre slovenské kraje | to, čo číta domáci. Tabuľka je [`workers/data/wiki-languages.json`](data/wiki-languages.json), kľúč je `country` z `regions.json` – tá istá hodnota, ktorá rozhoduje o priečinku na Drive |
| tag objektu | `wikipedia=pl:Rysy` → `pl` | bod na poľskej strane hrebeňa dostane poľský článok bez toho, aby o Poľsku niekto musel vedieť vopred |

**Krajina bodu sa berie z regiónu, nie z bodu.** Extrakt kraja je rezaný jeho
hranicou (`-s smart` k tomu pridá členov plôch, čo presahujú – tie sú ale
plochy, nie body s wiki odkazom), takže bod v ňom v tej krajine naozaj leží;
presnejšie by to bolo len
reverzným geokódovaním hraníc – celá ďalšia pipeline kvôli pár bodom pri
hranici, a tie sa aj tak chytia tretím riadkom tabuľky.

**Druhý jazyk sa dohľadá cez `langlinks`.** Objekt má v tagoch typicky jeden
`wikipedia=sk:…`; anglický článok o tom istom mieste existuje, len sa volá inak
a z tagu ho nikto neuhádne. Je to jedna dávková otázka na tie isté články,
ktoré aj tak sťahujeme. Dve veci, na ktorých to stálo:

* prepojenie príde pod menom **cieľa presmerovania** (`Devín (hrad)`), kým
  objekt má v tagu meno, ktoré sme **pýtali** (`Devínsky hrad`) – zapisuje sa
  preto pod obe, inak sa nájde a ticho zahodí;
* `index.json` viaže objekt na **článok v každom jazyku** (`keys: {sk: …, en:
  …}`), nie na jeden. Kým to bolo jedno pole, posledný jazyk prepísal predošlý
  a anglický článok sa stiahol nadarmo.

**Odkaz má v dátach štyri podoby** a všetky sa čítajú: `wikipedia=sk:Devín
(hrad)` (jazyk v hodnote), `wikipedia:sk=Devín (hrad)` (jazyk v kľúči),
`wikipedia=https://sk.wikipedia.org/wiki/Devín` (celé URL) a `wikidata=Q123456`
(článok sa dohľadá cez sitelinks). `brand:wikipedia` a `operator:wikipedia` sa
zámerne neberú – to nie je článok o tom mieste, ale o firme, a v kraji by z toho
boli stovky kópií článku o Lidli.

**Jeden súbor, nie súbor na článok.** Formát je **NDJSON** – riadok = jeden
článok ako JSON (`key`, `lang`, `title`, `pageid`, `revid`, `url`, `text`). Tak
to robí aj Wikimedia Enterprise so svojimi dumpmi a má to dva namerané dôvody
(vzorka 153 článkov sk wiki, 267 kB textu):

| balenie | ZIP | záznamov v ZIPe |
|---|--:|--:|
| súbor na článok | 149,1 kB | 153 |
| jeden NDJSON | **101,3 kB** | 1 |

Za tým rozdielom je jedna vec dvakrát: ZIP má na každý záznam hlavičku
(~320 B nameraných vrátane centrálneho adresára – pri 5000 článkoch 1,6 MB
samej režie) a **deflate si na každom súbore začína slovník odznova**, takže
tisíc krátkych článkov o tej istej doline sa komprimuje horšie než jeden prúd.
K tomu praktické: rozbaliť 5000 súborov je citeľne pomalšie než jeden.

**`index.json` je súčasť výsledku, nie príloha.** Hovorí, ktorý článok patrí
ktorému OSM objektu (`osm`: `node/123` → kľúč článku, meno, súradnice) – bez
neho je to hromada textov, ktorú sa v mape nemá ako na čo napojiť. Text článku
v ňom **nie je** (ten je v NDJSON, pravidlo 1), len `offset` a `len` riadka,
takže sa dá skočiť `seek`-om priamo na článok. A článok, ktorý sa nestiahol
(preklep v odkaze, premenovaný článok, jazyk bez článku), je tam v `chybne`,
nie zamlčaný: „stiahlo sa 900 z 1000" musí byť napísané.

**Plný text sa dávkovať DÁ, ale nie cez `prop=extracts`** – a to je celý dôvod,
prečo sa články berú z `prop=revisions` a wikitext sa prevádza u nás. Namerané
na `sk.wikipedia.org`, 10 názvov v jednej požiadavke:

```
prop=extracts&explaintext=1&exlimit=20      1 z 10 článkov, k tomu warning
    „exlimit was too large for a whole article extracts request, lowered to 1"
    – ostatných deväť vyzerá ako neexistujúce
prop=revisions&rvprop=content&rvslots=main  10 z 10, jedna požiadavka
```

Strop je **50 názvov na požiadavku** a nad ním API vráti chybu `toomanyvalues`,
nie ticho zrezanú dávku. Prevod wikitextu robí `mwparserfromhell` (knižnica od
Wikimedie) plus odstrihnutie tabuliek pred parsovaním – bez toho v texte ostanú
riadky `| align=center` (namerané: 102 zvyškov na ôsmich článkoch, s ním jeden).
Proti hotovému textu z `extracts` má takto prevedený článok 92–144 % dĺžky
(medián ~106 %), takže o nič neprichádzame.

| `wiki_format` | čo stiahne | koľko požiadaviek |
|---|---|--:|
| `text` (default) | celý článok ako čistý text | **jedna na 50 článkov** |
| `wikitext` | celý článok bez prevodu | **jedna na 50 článkov** |
| `intro` | len úvod článku | jedna na 20 článkov |
| `html` | celý článok v HTML z REST API | jedna na článok |

Namerané: **153 článkov v 4 požiadavkách za 2,7 s** (18 ms na článok), kým po
jednom to bolo 484 ms na článok – 27× viac. Kraj s tisíckou článkov je teda
dvadsať požiadaviek a sekundy, nie tisíc požiadaviek a pár minút. Job to hovorí
v pláne dopredu (pravidlo 4) a na konci porovná odhad s nameraným; pri `html`
navyše rovno napíše, že dávka tam neexistuje. Voči Wikimedii sa chodí slušne:
sériovo (tak to žiada API:Etiquette), s `User-Agent`, ktorý hovorí kto sme,
s `maxlag=5`, a pri 429/503 sa čaká `Retry-After`.

**Neznámy `wiki_format` alebo nečíselný `wiki_max` job odmietne** s návodom, čo
zvoliť. Náhrada za predvolenú hodnotu by znamenala zelený beh s iným obsahom
balíka, než si vypýtal – pravidlo 8.

**Na Pages to NEIDE.** Desiatky MB textu by zjedli rozpočet stránky
(`size_limit_mb`) a v mape ich nikto nekreslí, takže články idú vlastným
artefaktom do jobu `deploy` a odtiaľ na Drive ako **štvrtý balík**
`<kraj>[-<výsek>]-wikipedia.zip` (a do `maps.json` ako `wikipedia`). Vypína sa
**switchom `wikipedia`** vo formulári, jazyky sa vyberajú `wiki_langs=sk,en`,
strop počtu článkov je `wiki_max`.

**Cache je na Drive a neplatí ju kalendár, ale `lastrevid`.** Obnovuje sa cez
predponu (`wiki-v1-<región>-<jazyky>-<podoba>-`), takže sa berie najnovší
záznam toho istého regiónu; plný kľúč má na konci číslo behu, aby sa dal
doplniť (existujúci kľúč sa neprepisuje). Keď je v cache z čoho recyklovať,
`collect.py` si najprv dá **jednu dávkovú otázku `prop=info` na 50 článkov**
a stiahne len tie, ktorým sa medzitým zmenil `lastrevid`:

| tá istá dávka 50 článkov | zo siete |
|---|--:|
| `prop=info` (len `lastrevid`) | 19,9 kB |
| `prop=revisions` (s obsahom) | 197,4 kB |

Čo sa tým **neušetrí**: počet požiadaviek – dávka je dávka. Ušetria sa bajty
(desatina), prevod wikitextu, a pri `wiki_format=html`, kde dávka neexistuje,
celé minúty. Koľko sa naozaj recyklovalo, job vypíše (`z cache 812 z 830
článkov (98 %)`) – inak sa nedá odlíšiť „cache funguje" od „cache je tam, ale
kľúč nesedí", a to druhé je zelené a tiché, len o desiatky sekúnd dlhšie.

Cache je ten istý `articles.ndjson`, aký ide do balíka, takže sa nemá ako
rozísť s tým, čo je v mape. Nedopísaný posledný riadok (beh, ktorý niekto
zrušil v polovici zápisu) sa **preskočí**, nie odmietne – jeden pokazený riadok
nesmie zahodiť 900 článkov pred ním.

**Cachovanie je predvolené; obísť sa dá voľbou `rebuild: clanky`** (alebo
`vsetko`) – to je na prípad, keď sa zmenil zberač a `lastrevid` o tom nevie.
Podrobnosti v kapitole [Pregenerovanie](#pregenerovanie).

Rozpis: [`workers/wiki/collect.py`](wiki/collect.py) a
[`workers/wiki/build.sh`](wiki/build.sh).

#### `maps.json` – zoznam hotových máp v repozitári

Na Drive sa **bez tokenu a bez klikania** nedá zistiť, ktoré mapy vlastne
existujú: priečinky sú tri úrovne hlboko a mená balíkov si nikto nepamätá.
Preto je v koreni repozitára [`maps.json`](../maps.json) – jediný zoznam toho,
ktoré mapy sú hotové a kde ležia. Dopisuje ho **build**, hneď po nahratí
balíkov (`publish-map.py --maps=maps.json`, lebo len ten pozná id súborov),
a krok `Zapíš mapu do maps.json` ho commitne do vetvy, z ktorej beh vyšel
([`workers/deploy/catalog.sh`](deploy/catalog.sh)). Rýchly test má vedľa neho
vlastný [`maps-test.json`](../maps-test.json) s tým istým tvarom – rozpis
o pár odstavcov nižšie.

```json
{
  "_comment": "…", "_updated_at": "2026-08-11T18:35:52Z", "_updated_ts": 1760207752,

  "slovensko": {
    "name": "Slovensko",
    "regions": {
      "zilinsky": {
        "name": "Žilinský kraj",
        "maps": { "mapa": { "file": "zilinsky.zip", "link": "…", "download": "…", "size": 900000000 },
                  "vrstevnice-skaly": { … }, "tienovanie": { … },
                  "linie": { … }, "body": { … } },
        "bbox": [18.305, 48.72, 20.08, 49.635], "maxzoom": 16,
        "contours_maxzoom": 16, "contour_interval": 5, "rocks_maxzoom": 16,
        "rock_slope": 50, "dem_source": "dmr5", "layers": ["vrstevnice_dmr5_5m", "…"],
        "drive": "slovensko/zilinsky", "run": "105",
        "updated_at": "2026-08-11T18:35:52Z", "updated_ts": 1760207752,
        "subregions": {
          "sulovske_skaly": { "name": "Súľovské skaly",
                              "area_bbox": [18.53, 49.11, 18.72, 49.22], "maps": { … } }
        }
      }
    }
  }
}
```

**Hlavný kľúč je krajina** – rovno v koreni, bez obálky. Metadáta katalógu ležia
vedľa nej a poznať ich je po čom: začínajú podčiarkovníkom (`_comment`,
`_updated_at`, `_updated_ts`). Je to tá istá konvencia ako vo
[`workers/data/areas.json`](data/areas.json), kde sú kľúče pohorí tiež v koreni
a `_comment` medzi nimi – kto katalóg číta, preskočí kľúče na `_`.

**Zvyšok štruktúry sedí s cestou na Drive** (krajina → kraj `regions` → výsek
`subregions`), a to zámerne: je to tá istá odpoveď na otázku „čoho sa tá mapa
týka", akú dáva `cesta()`. Dve rôzne hierarchie tých istých máp by sa raz
rozišli. Build celej krajiny (`admin_level: 2`) nemá kraj, takže má `maps` rovno
pri krajine – vedľa `regions` s krajmi, ktoré sa stavali zvlášť.

Zápis je **„nahraď celú položku"**: keď mapa v zozname nie je, pridá sa; keď je,
prepíše sa celá – vrátane balíkov, ktoré tento build nevyrobil, aby v nej
nezostal odkaz na súbor, ktorý sa medzitým zmazal. `subregions` pri tom ostávajú
(build jedného pohoria neruší mapu celého kraja a naopak). Pri `bbox` treba
čítať pozorne: to je bbox **mapy**, teda celého regiónu aj pri builde na výrez –
kde v tej mape naozaj sú vrstevnice a skaly, hovorí `area_bbox`.

**Ten prepis sa ale týka len balíkov, o ktorých beh ROZHODUJE** (`spravuje=` –
ten istý zoznam, podľa ktorého sa maže starý balík na Drive). `wikipedia` robí
vlastná pipeline a Build map o nej nič nevie, takže „nevyrobil som ju"
neznamená „v mape nie je" – v položke preto ostane. Na Drive to rozlíšenie
platilo od začiatku vlastnej pipeline, v katalógu chýbalo: každý build mapy,
teda každá zmena štýlu, z `maps.json` balík článkov ticho zmazal, hoci ZIP na
Drive ležal ďalej. Balík, o ktorom beh rozhoduje a nevyrobil ho (vypnuté skaly,
vypnutý terén), naopak z položky zmizne – to je to isté mazanie ako na Drive,
len z druhej strany.

**Rýchly test má vlastný SÚBOR, nie len vlastný uzol.** Zapisovať sa musí –
balík `…-test4km2.zip` leží na Drive v priečinku ostrej mapy a bez katalógu sa
o ňom bez tokenu nikto nedozvie –, ale do `maps.json` nepatrí: ten je jediná
odpoveď na otázku „ktoré mapy sú hotové" a mapa, v ktorej je terén na 4 km²,
medzi ne nepatrí. Vlastný uzol (`…_test4km2`) ju síce na položku ostrej mapy
nepustil, lenže stál v tom istom zozname vedľa nej a vyzeral ako ďalší výsek;
že je to test, bolo vidieť až na `test_km2` v položke, čiže na poli, o ktorom
čitateľ nemusí vedieť. To je pravidlo 2 z druhej strany: **keď rozsah nie je
celý, musí sa zmeniť meno** – a tu je tým menom meno súboru.

```
maps.json        hotové mapy       slovensko/regions/presovsky/subregions/vysoke_tatry
maps-test.json   rýchle testy      slovensko/regions/presovsky/subregions/vysoke_tatry_test4km2
```

Oba súbory majú **rovnaký tvar** a píše ich ten istý kód; líšia sa len tým, čo
je v nich. Ktorý z nich to je, hovorí **jedno miesto** –
`katalog_subor()` v [`deploy/catalog.py`](deploy/catalog.py). Pýtajú sa naň
traja (`publish-map.py`, ktorý zapisuje; `deploy/apple-archive.sh`, ktorý si ho
pýta z vetvy a dopĺňa doň `.aar`; a cezeň krok, ktorý ho commituje), takže tri
výpočty toho istého by sa raz rozišli – a rozísť sa tu znamená zapísať jeden
súbor a commitnúť druhý, so zeleným behom. Meno súboru preto chodí do
`catalog.sh` **výstupom kroku** (`steps.publish.outputs.maps_file`), nie
natvrdo.

Tá istá otázka sa pritom kladie **dvakrát za sebou**, a preto musí mať
`katalog_subor()` zakaždým tú istú odpoveď: `apple-archive.sh` si meno vypýta
(`catalog.py --subor`), aby vedel, ktorý katalóg si stiahnuť z vetvy, a podá
ho `publish-map.py` v `--maps` – ten sa pýta znova, už nad testovacím menom.
Kým sa `-test` lepilo bez pozerania, vyšlo z toho `maps-test-test.json`:
v behu 33677718750 boli oba joby zelené, päť `.aar` na Drive, a
`maps-test.json` o nich nevedel – zápis šiel do súboru, ktorý `catalog.sh` ani
necommitol (nový súbor, o ktorom `git diff` mlčí; oboje je odvtedy opravené a
stráži to `workers/lint/catalog.py`). Katalóg rýchlych testov mal preto
`formats.zip` a nikdy `formats.aar`.

**Kedy tá mapa vznikla, hovorí položka dvakrát:** `updated_at` je ISO 8601
v UTC (dá sa prečítať okom a zoradiť ako text) a `updated_ts` sú sekundy od
epochy (vek mapy je jedno odčítanie, bez parsovania dátumu). Sú to dva zápisy
JEDNÉHO okamihu, nie dve merania – skladá ich `teraz()` v `catalog.py`. To isté
nesie každý balík zvlášť, lebo balík z inej pipeline (`wikipedia`) je iný vek
než mapa. V koreni katalógu je ten istý pár ako `_updated_at` / `_updated_ts`.

A po **neúspešnom nahratí sa nezapíše vôbec**
(`if: steps.publish.outcome == 'success'`) – zoznam, ktorý ukazuje na súbory,
čo na Drive nie sú, je horší než žiadny. Že to tak ostane, stráži
[`workers/lint/catalog.py`](lint/catalog.py) – vrátane prežitia cudzieho
balíka, časových pečiatok a rozdelenia oboch katalógov, ktoré sa staticky
prečítať nedajú, a tak ich skúša naostro.

### Základná mapa sveta (`Mapa · Build svet`)

Mapa kraja odpovedá na „kde som a kade ísť". Ostáva ale otázka o krok skôr:
**ktorý kus mapy si vôbec stiahnuť** – a na tú sa bez mapy sveta odpovedá
zoznamom mien. `world-map.yml` preto robí podklad, na ktorom je to vidieť:

```
svet.pmtiles     water           moria a oceány z pobrežných čiar OSM + jazerá
(z0–z6, ~desiatky MB)  boundary  hranice štátov (sporné prerušovane)
                 place           popisky štátov
                 download        regióny sťahovania – plochy
                 download_label  ich mená
```

**Dve podoby, input `variant`.** `plna` je mapa vyššie; **`basic` má z nej iba
`boundary`, `place`, `download` a `download_label`** – teda hranice štátov
a regióny sťahovania s ich menami, bez vodstva a jazier. Vodstvo je v tej mape
to drahé (rastie zhruba 3× na zoom), takže basic vyjde na jednotky MB proti
desiatkam a **zmestí sa do 15 MB aj na z8**. Namerané (Planetiler; regióny
sťahovania nahradené polygónmi štátov, lebo Geofabrik nebol z toho stroja
dostupný):

| | z4 | z6 | z8 |
|---|---|---|---|
| hranice + popisky | 0,2 MB | 0,5 MB | 1,1 MB |
| regióny sťahovania | 0,9 MB | 2,5 MB | 6,4 MB |
| **basic spolu** | **1,1 MB** | **3,0 MB** | **7,6 MB** |

Celý balík `basic` na z6 vyšiel na **3,3 MB** vrátane štýlov a písma.

**Podoba nie je druhá schéma.** `world.yml` ostáva jediný popis toho, čo sa
vyrába; [`variant.py`](world/variant.py) z neho vyberie vrstvy podoby (číselník
[`workers/data/world-variants.json`](data/world-variants.json)) a zloží schému,
ktorú Planetiler dostane. Zo `sources:` tej orezanej schémy zároveň vypadne,
ktoré podklady sa vôbec sťahujú – basic tak nesťahuje 60 MB vodných polygónov
ani nepotrebuje GDAL. Štýl si z toho istého číselníka berie, ktoré vrstvy
kresliť, a `workers/lint/world.py` porovnáva schému so štýlom pre každú podobu.

**A pozor, v tom balíku nie sú to drahé dlaždice, ale PÍSMO.**
[`glyphs.sh`](assets/glyphs.sh) už rozsahy raz oreže (latinka, gréčtina,
cyrilika, interpunkcia – ~1,2 MB na stack), lebo pri mape kraja nevie, aké
mená v nej budú. Tu sa to VIE, tak [`glyphs.py`](world/glyphs.py) necháva len
tie rozsahy, ktoré sú v menách na mape, a MERIA ich z podkladov: všetkých 516
mien z Natural Earth padne do jediného rozsahu 0–255, takže z ~2,4 MB písma
ostane 256 kB. Keď sa podklad nedá prečítať, neoreže sa nič – väčší balík je
lepší než prázdne štvorčeky namiesto mien.

(Kým `glyphs.sh` rozsahy nerezal, mal jeden fontstack 33 MB a dva 69 MB –
vtedy bol `glyphs.py` jediné, čo basic do 15 MB vôbec vopchalo.)

**`basic` má vlastný kľúč regiónu `svet_basic`**, teda vlastný priečinok na
Drive (`<koreň>/svet_basic/`) aj vlastný uzol v `maps.json`. Meno je sľub
o rozsahu: kto si podľa katalógu stiahne „mapu sveta", nesmie dostať mapu bez
morí – tá istá úvaha, akou má rýchly test v mene `test4km2`.

Každý región v `download` nesie `id`, `name`, `parent`, `level`
(svetadiel → štát → výsek) a **`pbf`, teda odkaz, ktorý sa dá naozaj
stiahnuť**. Úrovne sa odkrývajú podľa zoomu (svetadiel od z0, štát od z2,
výsek od z5) – všetkých ~500 naraz je pri pohľade na celý svet kaša, v ktorej
sa nedá ťuknúť na ten správny.

**`planet.osm.pbf` sa nepoužíva a je to zámer.** Planéta má cez 80 GB
a Planetiler nad ňou potrebuje rádovo terabajt a hodiny; runner má ~60 GB
voľných a strop 360 minút, ktorý sa vypnúť nedá. Mapa preto stojí na tých
istých podkladoch, z akých si nízke zoomy skladá aj Planetiler sám (Natural
Earth), a na pobrežiach na OSM (`simplified-water-polygons`, robené na z0–z9).
Delenie na kusy je z `index-v1.json` Geofabriku – jediná odpoveď na „na aké
kusy je OSM delené", ktorá je v JEDNOM súbore aj s polygónmi. Naše buildy
sťahujú PBF z osm.fr, ktorý polygóny svojich výrezov nepublikuje; delenie je
u oboch to isté a mapa ukazuje delenie, nie náš zoznam.

**Balí sa to isté a tým istým**: `svet.zip` a `svet.aar` (job na macOS) cez
`workers/deploy/publish-map.py`, do `<koreň>/svet/` na Drive, a do `maps.json`
ako vlastný koreňový uzol `svet`. V balíku sú dlaždice, štýly pre všetky štyri
témy, glyfy a `manifest.json` – mapa sa teda otvorí aj bez siete.

| súbor | čo robí |
|---|---|
| [`workers/world/sources.py`](world/sources.py) | stiahne cudzie zdroje (len tie, ktoré podoba potrebuje) a spraví z nich podklady |
| [`workers/world/variant.py`](world/variant.py) | podoba: ktoré vrstvy, ktoré podklady, aké meno a strop |
| [`workers/world/glyphs.py`](world/glyphs.py) | oreže písmo na rozsahy znakov, ktoré sú v menách na mape |
| [`workers/world/world.yml`](world/world.yml) | schéma Planetilera – päť vrstiev a ich zoomy |
| [`workers/world/style.mjs`](world/style.mjs) | štýl MapLibre (farby z `poc/web/themes.js`) |
| [`workers/world/build.sh`](world/build.sh) | celý beh: podklady → dlaždice → štýly → manifest |
| [`workers/lint/world.py`](lint/world.py) | štýl kreslí presne tie vrstvy a od tých zoomov, čo schéma robí |

### Súhrn buildu

Každý beh napíše do záložky **Summary** prehľad: čo sa robilo, ako dlho to
trvalo a s akým výsledkom.

| krok | trvanie | výsledok |
|---|--:|---|
| PBF regiónu | 0:00:12 | Prešovský kraj, 63M (z cache) |
| DEM dlaždice (Sonny) | 0:01:44 | 9 z 21 dlaždíc, 412M |
| Vrstevnice (gdal_contour) | 0:04:31 | interval 10 m, 218M |
| Skalné plochy | 0:36:07 | 41 802 plôch, sklon ≥ 50°, mriežka 2 m (výpočet) |
| Vrstevnice a skaly → PMTiles | 0:06:12 | maxzoom 14, 187M |
| Značené trasy z OSM | 0:01:38 | ~1 400 trás, ~39 000 úsekov, ~6 000 ciest s viac trasami |
| Značené trasy → PMTiles | 0:00:44 | maxzoom 14, ~9M |
| Tieňovanie a 3D terén | 0:00:31 | 24 118 PNG dlaždíc do z13, 96 MB (sklad dem-terrain) |
| Mapové dlaždice (Planetiler) | 0:18:20 | maxzoom 16, 421 MB |
| Ikonky (SDF sprity) | 0:00:09 | sady: maki temaki osm-bright, štýl používa temaki (z cache) |

*(Ukážka – čísla sa líšia podľa regiónu a nastavení.)*

Pod tabuľkou je **detail skál** za tento beh (počet plôch, mriežka, bunka DEM,
najmenšia/priemerná/najväčšia plocha, koľko km² skalného terénu spolu) a
prehľad, **čo prišlo z cache a čo sa naozaj počítalo** – takže sa hneď vidí,
či mal beh trvať hodinu, alebo minútu.

#### Nastavenia tohto behu

Píše ich **prvý job behu** – `settings`
([workers/plan/settings.sh](plan/settings.sh)) – a nie súhrn na konci: keď beh
po hodine spadne, práve vtedy treba vedieť, s čím išiel. Vypíše celý formulár
a označí, čo bolo iné než predvolené:

| pole | hodnota | |
|---|---|---|
| `region` | `presovsky` | default |
| `area` | `mala_fatra` | **iné než default** |
| `test` | `true` | default |
| `rock_slope` | `45` | **iné než default** |

Je to preto, že formulár *Run workflow* sa vždy otvorí s predvolenými
hodnotami – GitHub si nepamätá, s čím si beh pustil naposledy, a v API to
nikde nie je. Keď teda chceš beh zopakovať a zmeniť jedinú vec (typicky
`rebuild`), z tohto bloku vidíš, čo treba nastaviť späť. Predvolené hodnoty
si blok číta priamo z workflowu ([workers/plan/summary-inputs.py](plan/summary-inputs.py)),
takže sa s formulárom nemôžu rozísť.

Za formulárom je druhá tabuľka: **`env:` workflowu**, teda nastavenia, ktoré
vo formulári nie sú a menia sa prepísaním `build-map.yml` – prahy skál,
hladenie vrstevníc, mená skladov, rozpočty veľkosti na vrstvu. Kľúče sú
z workflowu, hodnoty z prostredia behu, takže je vidieť to, s čím beh naozaj
ide. Čo je v YAMLe `secrets.*`, sa nevypisuje: repozitár je public a súhrn
behu vidí ktokoľvek.

A keď je vo formulári nezmysel (neznáma voľba v `options`), spadne to práve
tu – po pár sekundách, nie o desať jobov neskôr.


## Značené trasy (turistika, cyklo, bežky)

**Trasa nie je cesta.** V OpenStreetMape je značená trasa `type=route`
**relácia**: zoznam cudzích ciest plus samotné značenie – farba pásika
([`osmc:symbol`](https://wiki.openstreetmap.org/wiki/Key:osmc:symbol),
`colour`), sieť (`network`), názov, `ref`, dĺžka. Schéma OpenMapTiles relácie
trás **nepozná**: v dlaždiciach ostane len cesta (`class=path`) a z nej sa
nedá zistiť, či po nej vedie červená turistická, dve cyklotrasy, alebo nič.

Preto majú trasy vlastný krok pipeline a vlastný `.pmtiles`:

```
data/region.osm.pbf
  → osmium tags-filter r/route=hiking,foot,…   len relácie trás a ich členovia
  → workers/trails/routes.py (pyosmium)         relácie → línie s pruhmi
  → data/trails.geojson
  → planetiler generate-custom --schema=workers/trails/trails.yml
  → {región}-trails.pmtiles
```

### Pásiky vedľa cesty, nie namiesto nej

Trasa sa kreslí ako farebný pásik **vedľa** cesty (`line-offset`), takže pod
ním zostane vidieť, aká je to vlastne cesta – chodník, lesná cesta, asfaltka.
**Pešie trasy idú na jednu stranu, kolesové na druhú** a druhá trasa v rade sa
nalepí na prvú bez medzery:

```
╍╍ MTB        (side −1, off 1) ╍╍
╍╍ cyklotrasa (side −1, off 0) ╍╍
── chodník ──────────────────────    zostane vidieť, aká to je cesta
━━ červená    (side +1, off 0) ━━
━━ modrá      (side +1, off 1) ━━    nalepená na červenú, bez medzery
━━ zelená     (side +1, off 2) ━━
```

Po jednej ceste vedie bežne viac trás naraz, takže sa každá zapíše do dlaždíc
zvlášť a dostane vlastný **pruh**. Detaily, ktoré na tom závisia:

| vec | ako to je | prečo |
|---|---|---|
| strana cesty | pešie (turistická, ferrata, bežky, jazdecká) `+1`, kolesové (cyklo, MTB) `−1` | po jednom chodníku vedie bežne turistická značka **aj** cyklotrasa; v jednom rade by sa druhá odsunula tak ďaleko, že by pri nej nebolo vidieť, ku ktorej ceste patrí |
| číslovanie pruhov | na každej strane zvlášť, od cesty von: 0 · 1 · 2 … | keby boli vycentrované, koniec jednej trasy by posunul všetky ostatné |
| poradie | sieť → druh → farba → id relácie | závisí len od trasy, takže si dve trasy na susedných úsekoch pruhy neprehodia; dôležitejšia je bližšie k ceste |
| smer čiary | podľa toho, na čo cesta **nadväzuje** (`orient_ways`) | `line-offset` posúva podľa smeru geometrie – viď nižšie |
| duplikáty | nadradená trasa a jej časť sa zlúčia | superroute a jej člen sú dve relácie na tých istých cestách; dva rovnaké pásiky vedľa seba nie sú informácia, ale chyba |

### Smer čiary: prečo sa reťazí a nenormalizuje

`line-offset` posúva pásik podľa smeru geometrie, takže **smer rozhoduje o
strane**. Kým sa normalizoval „od západnejšieho konca", rozhodovala o ňom pri
severojužnom chodníku pár metrov široká kľukatina – a pásik preskakoval na
druhú stranu na každom druhom úseku:

```
úsek A (mierne na východ)  → kreslí sa na sever → pásik vpravo
úsek B (mierne na západ)   → kreslí sa na juh   → pásik VĽAVO
úsek C (mierne na východ)  → kreslí sa na sever → pásik vpravo
```

Nepomôže ani „normalizuj podľa dlhšej osi": seam sa len presunie zo severojužného
smeru na uhlopriečku. **Žiadne pravidlo nad jednou čiarou to nevyrieši** – smer
čiary je vlastnosť dvojice susedov, nie jednej cesty.

`orient_ways` preto berie cesty ako **hrany grafu** (vrcholy sú uzly OSM) a od
každej neprebranej ide do šírky: susedovi pridelí smer tak, aby v spoločnom
uzle jedna KONČILA a druhá ZAČÍNALA. Pásik potom drží stranu cez celý chodník
bez ohľadu na to, ako kto ktorý úsek nakreslil. Vstupom sú len koncové uzly
(`{cesta: (uzol, uzol)}`), takže druhý priechod nad PBF nepotrebuje index
súradníc a je lacný.

Čo to **nevyrieši a vedieť sa to má:** na križovatke troch a viac chodníkov
„nadväzovať" nie je definované – dve vetvy z uzla vychádzajú a tretia doň
vchádza, takže niektorá stranu prehodí. Je to ale križovatka, kde sa trasa aj
tak vetví, nie prostriedok chodníka. Koľko takých miest v území ostalo, píše
beh do logu aj do súhrnu (`side_flips`) a nad 5 % ciest to varuje – je to
číslo, ktoré má byť malé, a keď skočí, smerovanie sa pokazilo.

Fyzická strana (severná či južná) je pre každú reťaz ľubovoľná, ale **stála**:
berie sa najmenšie id cesty a v nej menšie id uzla. Dôležité je, že sa strana
nemení pozdĺž trasy, nie to, ktorá to je.

### Odstup od cesty: dve čísla, nie jedno

Odstup pásika **nemôže byť jedno číslo**: miestna cesta je pri z16 v mape
široká 9 px plus obrys, chodník 2,2 px. Odstup, pri ktorom sa pásik lepí na
chodník, by ležal uprostred cesty. Preto ide do dlaždíc aj `way` – po čom
trasa vedie – a štýl má dva odstupy:

| po čom vedie | `way` | odstup pri z16 | ako to vyzerá |
|---|---|---:|---|
| cesta (asfaltka, spevnená) | `road` | 6,6 px | pásik ide **tesne za okraj** cesty aj s jej obrysom: žiadna medzera, ale ani prekryv |
| chodník, lesná a poľná cesta | `path` | 3,6 px | **jemný odstup**, nech je pod pásikom vidieť aj samotný chodník a to, že je prerušovaný |
| rozostup dvoch trás | – | 2,6 px | **šírka pásika**, čiže sú nalepené na sebe; tri značky na jednom chodníku vyzerajú ako jeden trojfarebný pás |

Čísla nie sú odhad – sú spočítané zo šírok čiar v štýle (polovica čiary +
obrys + polovica pásika) a sedia pri **miestnej ceste**, po ktorej trasy
chodia najčastejšie. Celá krivka (z9 až z20) sa škáluje pomerom voči hodnote
pri z16, takže v developer móde stačí prepísať jedno číslo.

**Rozostup nie je vlastné číslo, je to šírka pásika** – doslova tá istá krivka
(`TRAIL_STRIPE`), ktorou sa kreslí `line-width`, aj ten istý druh interpolácie.
Kým to boli dve krivky, sedeli si len v šiestich zlomoch: šírka rastie
`exponential 1.5` (ako všetky hrúbky v štýle), rozostup rástol lineárne, takže
pri z18 bol rozostup 4,3 px na pásik široký 3,65 px. Tá sedmina pixela nie je
biela – presvital cez ňu podklad pásikov (`trail-halo`), takže medzi červenou
a modrou trasou viedla tmavá čiara a vyzeralo to, že sú trasy od seba odsunuté.

**Pod z16 rozhoduje o odstupe METER, nie pixel.** Pixel je pri z13 dvanásť
metrov, takže „2,6 px od chodníka" znamenalo 33 m – viac, než je v horách
rozostup ramien serpentíny. `line-offset` posúva každý vrchol po osi jeho
zlomu, takže taký pásik obehne vlásenku oblúkom širším než samotná zákruta,
ramená sa navzájom prekryjú a v mape je z toho farebná **plocha**, nie čiara.
Odstup je preto zhora ohraničený tým, koľko je pri ceste miesta v teréne
(`TRAIL_OFFSET_LIMIT_M`: 12 m pri ceste, 8 m pri chodníku – ten má serpentíny
tesnejšie). Nad z16 je to ohraničenie voľnejšie než výpočet zo šírky čiary,
takže tam ostalo všetko tak, ako bolo:

| | z13 | z14 | z15 | z16 | z18 | z20 |
|---|---:|---:|---:|---:|---:|---:|
| chodník, predtým | 19 m | 15 m | 9,4 m | 5,7 m | 2,3 m | 1,1 m |
| chodník, teraz | 7,9 m | 8,0 m | 6,9 m | 5,7 m | 2,3 m | 1,1 m |

Že to drží spolu naprieč tromi súbormi (`routes.py` číslu je rady,
`trails.yml` to pustí do dlaždíc, `themes.js` z toho ráta `line-offset`),
stráži [`workers/lint/trails.mjs`](lint/trails.mjs) – rozídené strany, posunutý
zlom krivky, rozostup, ktorý prestal byť šírkou pásika, odstup nad limit
v metroch ani zahodené reťazenie smerov nespadnú, len sú cyklotrasy zrazu na
tej istej strane ako turistické, prípadne pásiky preskakujú.

### Ostrý zlom: pásik má ten istý uhol ako chodník (`line-join: miter`)

`line-offset` posúva KAŽDÝ VRCHOL čiary a dĺžku toho posunu berie z toho, aký
spoj je nastavený. Práve preto bola v zákrute z pásika plocha:

| spoj | čo urobí s vrcholom | ako to vyzerá |
|---|---|---|
| `round` | posunie ho o odstup po **normále každého ramena zvlášť** | rovnobežky sa v zlome nestretnú: na vonkajšej strane ostane medzi nimi **klin** (biely zárez uprostred pásika), na vnútornej sa prekryjú – a pri troch značkách na jednej ceste si k tomu farby prelezú cez seba |
| `miter` | posunie ho po **osi zlomu** o `odstup / cos(zlom/2)` | presne roh rovnobežky: pásik má v zákrute **ten istý ostrý uhol ako chodník pod ním** a rovnakú hrúbku |

Geometria sa pritom **neupravuje**: pásik má presne tie body, ktoré má cesta
v OSM. Zaobliť zlom v dátach by znamenalo, že pásik zákrutu odreže a ide
inokade než chodník pod ním – a to je horšie než ten klin.

`line-miter-limit` je strop toho posunu: `odstup / cos(zlom/2)` rastie nad
všetky medze (pri zlome 173° je to 16-násobok odstupu) a MapLibre ho pakuje do
bajtu, takže sa nad **dvojnásobok** nedostane. Dvojnásobok je presne zlom
**120°** – ostrejší zlom zreže na `bevel`, čiže obe ramená pásika sa skončia
pred zlomom a v zákrute ostane diera. V mape to vyzerá, že sa pásik zúžil.

Preto na to nadväzuje jediná úprava geometrie, ktorú trasy majú: `ease_corners`
v [`routes.py`](trails/routes.py) **rozdelí zlom nad 120° na niekoľko po 60°**
(posun 1,15× odstupu, hlboko pod stropom), takže ich už `miter` zošije a pásik
ide zákrutou v rovnakej hrúbke. Nie je to zaobľovanie: reže sa **2 m**, čiže
pásik je od zlomu chodníka najviac **1 m** – pri z16 0,6 px, pri z14 (strop
dlaždíc trás) 0,15 px. Menej sa rezať nedá, dlaždice majú pri z14 rozlíšenie
0,39 m a Planetiler ich pred zápisom ešte zjednodušuje (~0,6 m), takže kratší
oblúk by sa v nich stratil a zlom by bol späť.

Zlomov nad 120° je málo – namerané na 419 tatranských cestách z Overpassu
(22 238 bodov): **354, teda 1,6 % vrcholov**, a geometria z toho narastie
o 6,3 %. Deliť aj miernejšie zlomy nemá zmysel (`miter` ich zošije) a nie je
zadarmo: pri hranici 30° má zlom nad ňou tretina vrcholov a bodov by bolo
o 108 % viac. Vlásenka nad ~150° ostane vlásenkou – tam sa pásik pri hrote
skončí, lebo zošiť ju by znamenalo odrezať špičku o desiatky metrov.

Že to drží: `workers/lint/trails.mjs` stráži `miter` aj ten limit na každej
`trail-*` čiarovej vrstve (aj na podklade pásikov, ktorý sa musí v zákrute
ohnúť rovnako ako to, čo podkladá) a k tomu to, že hranica delenia v `routes.py`
**vychádza z toho limitu** – `line-miter-limit` 2 znamená 120°, takže sa tie
dve čísla nemôžu ticho rozísť.

### Farba ide z OSM, odtieň z palety

Farba sa berie z `osmc:symbol` (prvé pole je farba pásika na strome), inak
z `colour`/`color`:

| v OSM | v dlaždiciach | v mape |
|---|---|---|
| `osmc:symbol=red:white:red_bar` | `colour=red` | farba `Značka červená` z palety |
| `colour=blue` | `colour=blue` | farba `Značka modrá` z palety |
| `colour=#0000ee` | `colour=blue` | zaokrúhlené na modrú (je dosť blízko) |
| `colour=#ff69b4` | `hex=#ff69b4` | presne tento hex – žiadnej značke sa nepodobá |
| *(nič)* | – | farba podľa druhu trasy |

**Prečo cez paletu a nie priamo hex z OSM.** „Červená" značka má v každej téme
vyzerať ako červená značka, nie ako presne to `#ff0000`, ktoré do OSM napísal
ten, kto trasu zadával. V tmavej téme je navyše čierna značka svetlosivá –
inak by na tmavom podklade zmizla. Všetkých desať farieb značiek je v palete
v skupine **Značené trasy**, takže sa dajú v developer móde doladiť ako
čokoľvek iné.

### Druhy trás

| druh | `route` v OSM | predvolená ikona | čiara | strana |
|---|---|---|---|---|
| turistická | `hiking`, `foot`, `walking` | vrch | plná | +1 |
| ferrata | `via_ferrata` | lezec | krátke čiarky | +1 |
| cyklotrasa | `bicycle` | bicykel | **bodkovaná, ružovo-fialová** | −1 |
| horská cyklotrasa | `mtb` | bicykel | bodkovaná hustá | −1 |
| lyžiarska / bežkárska | `ski`, `nordic`, `skitour` | lyžiar | dlhé čiarky | +1 |
| jazdecká | `horse` | koliesko | krátke čiarky | +1 |

**Cyklotrasa má farbu od nás, nie z OSM.** Cykloznačka v teréne farbu nenesie
(na rozdiel od turistickej), takže je to naša voľba – a musí sa odlíšiť od
turistických značiek, ktoré zaberajú červenú, modrú, zelenú aj žltú. Preto
ružovo-fialová a bodkovaná.

Každý druh má vlastnú vrstvu pre čiaru, ikonu aj názov. Nastavuje sa to ale
v **záložke Trasy** v developer móde, nie po vrstvách – jeden druh trasy sú tri
vrstvy naraz a odstup od cesty je vlastnosť všetkých.

### Názov pozdĺž trasy

Trasy s názvom alebo `ref` majú od z12 popisok **pozdĺž čiary a vo farbe
trasy** (`0801 Chodník hrdinov SNP`). Aby sa názov nekreslil po 200-metrových
kúskoch, Planetiler v dlaždici **zlepí úseky s rovnakými atribútmi** –
teda tej istej trasy v tom istom pruhu (`merge_line_strings`).

Klik na pásik ukáže popup s názvom, druhom, farbou značky, sieťou a odkazom
na reláciu v OSM.

### Od akého zoomu je čo vidieť

Riadi to `network` (`iwn`/`nwn`/`rwn`/`lwn` a cyklo obdoby), lebo diaľkovú
trasu má zmysel vidieť aj z prehľadu, kým miestny okruh až vtedy, keď je
vidieť aj cesta pod ním:

| sieť | v dlaždiciach od | typicky |
|---|--:|---|
| medzinárodná (`iwn`, `icn`) | z8 | E-cesty, Eurovelo |
| národná (`nwn`, `ncn`) | z8 | magistrály |
| regionálna (`rwn`, `rcn`) | z10 | väčšina našich značených trás |
| miestna (`lwn`, `lcn`) | z12 | okruhy, náučné chodníky |

Keď trasa sieť nemá, rozhodne `distance` (nad 150 km = národná, nad 50 km =
regionálna, inak miestna).

### Ovládanie

Vo workflowe: `trails` (zap/vyp) a `trails_maxzoom` (default 14). Okrem
turistiky, cyklo, bežiek a jazdeckých trás sa berú aj **ferraty**
(`route=via_ferrata`) – vlastný druh, lebo po ferrate sa nedá ísť bez výstroja
a od turistickej značky sa má odlíšiť na prvý pohľad. V mape sa
trasy vypínajú prepínačom **Značené trasy** v paneli ⚙. Job sa **necachuje** –
celé sú to pár minút a závisí to od PBF, ktoré sa mení denne.

Súhrn buildu píše, koľko trás sa v území našlo, koľko z nich má názov, po
koľkých cestách vedú a koľko z tých ciest nesie viac trás naraz.

## Krajinné prvky (čo OpenMapTiles nemá)

**Schéma sa pozerá len na tridsať kľúčov.** V celom
`openmaptiles/planetiler-openmaptiles` sa slovo `embankment` nevyskytuje ani
raz. To isté platí pre `barrier` ako líniu (múr, plot, živý plot), `power`
(elektrické vedenie), `man_made=cutline`, `piste:type` (zjazdovky),
`natural=cave_entrance` aj `man_made=tower` (rozhľadňa sa do dlaždíc dostane
jedine vtedy, keď má navyše `tourism=viewpoint`). Nedá sa to zapnúť – tie
prvky v základných dlaždiciach jednoducho **nie sú**.

Preto sa z toho istého PBF ťahajú druhýkrát, vlastnou schémou a do vlastného
`.pmtiles` – rovnaký vzor ako značené trasy a skaly. Bodové prvky idú do
VLASTNÉHO súboru (`workers/features/points.yml`), presne kvôli balíku na
stiahnutie, ktorý appka ponúka zvlášť od línií a plôch (balíky `linie`
a `body`, `workers/deploy/publish-map.py`) – rovnaký predfilter, len druhý
beh Planetileru:

```
data/region.osm.pbf
  → osmium tags-filter --expressions=workers/features/filter.txt
  → data/features.osm.pbf                      (Andorra: 3,4 MB → 198 kB)
  → planetiler generate-custom --schema=workers/features/features.yml
  → {región}-features.pmtiles                  (línie a plochy)
  → planetiler generate-custom --schema=workers/features/points.yml
  → {región}-points.pmtiles                    (body)
```

`class` rozlišuje čo v ktorej vrstve je:

| súbor | vrstva | čo v nej je | od zoomu |
|---|---|---|--:|
| `features.pmtiles` | `feature_line` | **násyp**, zárez, múr, hradby, plot, živý plot, elektrické vedenie, **plánovaná cesta**, priesek, nadzemné potrubie, stromoradie, priehradný múr, hať, výmoľ | 11–15 |
| `features.pmtiles` | `feature_area` | parkovisko, skládka, halda, hospodársky dvor, skleníky, opustený priemysel, kamenné pole | 11–14 |
| `features.pmtiles` | `piste` | zjazdovka, bežkárska trať, skialp, sánkarská dráha – čiara aj plocha, s obťažnosťou | 11 |
| `points.pmtiles` | `feature_point` | prameň, vodopád, jaskyňa, závrt, rozhľadňa, stožiar, vodojem, kríž pri ceste, pomník, archeologické nálezisko, štôlňa, útulňa, horský priechod, núdzový bod, geodetický bod | 11–15 |

**Zoomy sú tu hlavné rozhodnutie, nie estetika.** Plotov je v OSM viac než
všetkých ciest dokopy, takže idú až od z15; vedenie vysokého napätia je
v otvorenej krajine orientačný bod na kilometre, takže od z11. Nie je to vkus,
je to priamo veľkosť súboru.

**Plánované cesty (`highway=proposed`) sú tu, nie v základných dlaždiciach.**
OpenMapTiles má pre rozostavané cesty vlastné triedy (`motorway_construction`
až `raceway_construction`, `highway=construction`), ale pre `proposed` v celej
vrstve `transportation` **žiadnu** – overené v jej zozname tried. Trasa, na
ktorej sa ešte ani nekope, sa teda ťahá z PBF druhýkrát ako každý iný prvok tu:
od z11 (plánovaná diaľnica je čiara cez celý kraj a práve na tom zoome má
zmysel vedieť, kade pôjde), s `name`, `ref` a `subclass`. Čo sa plánuje, hovorí
`proposed=motorway` alebo `proposed:highway=motorway` – berú sa oba, cez
`coalesce`, takže z plánovanej diaľnice a plánovanej lesnej cesty nie je tá istá
čiara. V mape je **bodkovaná a šedšia** než rozostavaná cesta, ktorá je
čiarkovaná a farebná: „stavia sa" a „je to zatiaľ na papieri" sa musia dať
odlíšiť na prvý pohľad. Klik povie meno, označenie aj čo sa plánuje.

**Násyp a bralo sa kreslia zúbkami.** Kolmé čiarky MapLibre nevie, takže sa
robia druhou čiarou: širokou, prerušovanou a odsunutou nabok (`line-offset`),
z čoho pri hrane ostanú krátke hrubé kúsky. Kladný offset je vpravo v smere
čiary a presne tam je podľa konvencie OSM dolná strana.

**Zjazdovka je raz čiara a raz plocha.** Uzavretá cesta s `piste:type` vyjde
ako plocha aj ako čiara, takže dostane výplň s obrysom; otvorená len čiaru
(os zjazdovky). Farba je podľa `piste:difficulty` – modrá, červená, čierna,
tie isté odtiene ako pri značkách trás, aby sa mapa nerozpadla na dve sady
farieb.

### Čo sem NEPATRÍ, hoci to tak vyzerá

`natural=cliff`, `ridge` a `arete` v základných dlaždiciach **sú** – Planetiler
ich dáva ako línie do vrstvy `mountain_peak` (od z13). Chýbala len kresba
v štýle; horšie, symbolová vrstva „Vrcholy hôr" im dávala doprostred
trojuholníček vrcholu aj s popiskom, lebo `cliff` nebol medzi vylúčenými
triedami. Teraz sú z nich bralné hrany so zúbkami a čiarkované hrebene.

Podobne sa v štýle opravilo aj to, čo v dlaždiciach bolo od začiatku a nekreslilo
sa: cesty vo výstavbe (`*_construction`), plochy vo vrstve `transportation`
(námestia, pešie zóny, telesá mostov, plošné móla), brody (`brunnel=ford`),
nástupištia (`subclass=platform`), plocha priehrady (`landuse class=dam`)
a kosodrevina odlíšená od lúky (`landcover subclass=scrub/heath/fell`).

### Ovládanie

Vo workflowe: `options: features=false` (vypnutie) a `features_maxzoom`
(default 15). Nižšia hodnota nie je zakázaná, ale **ticho zahodí** triedy
s vyšším `min_zoom` – Planetiler o tom nepovie nič, preto na to job
upozorní varovaním. Pri z14 takto chýbali ploty, živé ploty, geodetické body
a hraničné kamene; z15 stojí 1,6× väčší súbor (nameraná Andorra: 248 kB →
394 kB), čo sú pri jednotkách MB drobné. V mape sa prvky vypínajú prepínačom **Krajinné prvky**
v paneli ⚙. Vrstvy sú v developer móde v skupine **Krajinné prvky (mimo
schémy)**, farby v rovnomennej skupine palety. Job sa **necachuje** a beží
súbežne so všetkým ostatným; podiel na rozpočte stránky je
`BUDGET_FEATURES_PCT` (4 %).

## Typy máp – čo ktorá mapa ukazuje

Jedna mapa nemôže byť dobrá turistická aj dobrá cestná naraz. Turista chce
skaly, chodníky a čo najviac detailu; vodič chce cesty, pumpy a odpočívadlá
a vrstevnice mu majú len naznačiť kopec. Preto sa z jedného zoznamu vrstiev
generuje **päť máp**, každá s vlastným profilom
([poc/web/map-types.js](../poc/web/map-types.js)):

| typ mapy | čo ukazuje | čo zámerne nie |
|---|---|---|
| **Turistická** (predvolená) | skaly od z11, turistické chodníky od z10, značené trasy od z8, vrcholy od z8, plný detail | lyžiarske trasy a strediská |
| **Lyžiarska** | lyžiarske a bežkárske trasy od z8, vleky a lanovky od z9, strediská a ich body, skaly | ostatné značené trasy až od z14 a stlmené |
| **Cestná** | cesty, pumpy, nabíjačky, odpočívadlá, servis a parkoviská od z10; vrstevnice **len po 50 m** a stlmené | vrstevnice po 10 m, skaly, chodníky, značené trasy, tieňovanie; krajina je stlmená, bežné POI až od z15 |
| **Historická** | hrady, zámky, pamiatky, bane, štôlne, haldy a lomy od z9, POI od z12, terén ako pri turistickej | turistické chodníky, schody a značené trasy |
| **Základná (všetko)** | všetky vrstvy tak, ako ich generuje štýl – na ladenie | – |

Profil je len **predvolený stav**: v developer móde sa dá každej mape
nastaviť po svojom (viď nižšie), takže „na cestnej mape toto nechcem"
neznamená „nikde to nechcem".

Typ mapy sa vyberá v paneli ⚙ (výber **Typ mapy**) a pamätá si ho prehliadač.
Pipeline generuje `styles/{región}-{typ mapy}-{téma}.json` pre každú
kombináciu – teda 5 × 4 = 20 štýlov, plus predvolený typ aj pod pôvodným
menom `{región}-{téma}.json`, aby fungovali staršie odkazy.

### Terénna trojica

Tri farby, ktoré robia z mapy horskú mapu, sú v každej téme z tej istej rodiny –
prevzatej z papierovej horskej mapy:

| čo | farba | kde je v palete |
|---|---|---|
| podklad mapy (základná farba horského terénu) | **#f0efeb** bielosivá | `Pozadie mapy` |
| skalnaté partie a sutiny | **#9c9286** teplá stredná sivohnedá | `Skaly / suť` (OSM) a `Skalné plochy (plná výplň)` (počítané z DEM) |
| kamienky v suti | **#6b6154** tmavšia sivohnedá, jemný vzor s krytím 0,75 | `Kamienky v suti (vzor)` |
| vrstevnice | **#8b8676** tenké olivovosivé línie s popiskom výšky | `Vrstevnica`, `Hlavná vrstevnica`, `Popisok výšky` |

**Podklad je bielosivý, nie zelenkastý – a je to rozhodnutie o tom, čo v mape
znamená zelená.** Nad hranicou lesa je hola, kameň a sneh; kým mal podklad
zelený nádych, vyzeralo to celé ako riedka vegetácia a les sa od neho odlíšil
len o odtieň. **Zelená je vyhradená lesu** (`Les`) – je to jediná sýta zelená
v mape. Lúka, kosodrevina, záhrada aj ihrisko sú odstupňované do olivovo-khaki:
vegetácia áno, les nie. Otvorená lúka je pritom skoro na farbe podkladu, čo je
zámer: v horskej mape je „nič zvláštne" podklad a farba patrí tomu, čo treba
rozoznať.

Sivá pritom nie je neutrálna: má ten istý teplý zemitý nádych ako skaly
a vrstevnice (odtieň okolo 45°, sýtosť do 6 %). Neutrálna sivá vedľa zemitých
hnedých vyzerá domodra a mapa z toho vyjde studená.

**Suť má vzor drobných kameňov, počítané skalné plochy nie.** `natural=scree`
a `bare_rock` z OSM (`Skaly a suť`) sú popadané kamene pod stenou, kamenné more
a holá skala – papierová horská mapa ich značí kamienkami odjakživa a plná
farba to nepovie. Vzor je jemný (dlaždica 9 px, teda kamienok veľký dva-tri
pixely na každom zoome; zadáva sa v pixeloch obrazovky, nie v metroch).
**Počítané skalné plochy z DEM ho zámerne nemajú**: tie hovoria „tu je terén
strmý", teda stena a bralo, a kresba popadaných kameňov by tvrdila opak.

**Chodníky pre peších sú tmavosivé, nie hnedé** (`Turistické chodníky`,
`Chodníky, priechody a nástupištia`). Hnedá je na mape farba zeme – poľná
a lesná cesta ju má ďalej – a keď ju mal aj chodník, splývali. Tmavá sivá je
navyše čitateľná nad všetkým: nad bielosivým podkladom, nad zeleným lesom aj
nad skalnou plochou.

Každá téma má **veľmi jemne iný** odtieň tej istej trojice, nie kópiu jednej
hodnoty: *Svetlá* je neutrálna, *Outdoor* o odtieň teplejšia a tmavšia (je to
turistická mapa), *Retro* o odtieň svetlejšia a *Tmavá* má tú istú rodinu
preloženú do tmy – teda neutrálne teplú, nie domodra ako predtým. Rozdiel je
pár krokov: dosť na to, aby sa témy dali rozoznať, málo na to, aby niektorá
vyzerala ako iná mapa.

Suť z OSM (`Skaly / suť`) sa kreslí s krytím 0,8, takže sa s podkladom mieša –
hodnota v palete je preto tmavšia než to, čo je v mape vidieť, a výsledok je
o odtieň svetlejší než počítané skalné plochy. To je zámer: suť je sypká
a svetlejšia než stena.

**Tematické body.** Každý typ mapy má skupinu bodov, ktorá je preň tá hlavná –
`poi-historic` (hrady, zrúcaniny, pamätníky, archeológia), `poi-mining`
(bane, štôlne, haldy, lomy), `poi-ski` (vleky, lanovky, požičovne, školy)
a `poi-road` (pumpy, nabíjačky, odpočívadlá, servis). Sú to samostatné vrstvy:
väčšie, s vlastnou farbou v palete a s prednosťou pri umiestňovaní popiskov,
takže sa zapnú skôr než ostatné POI a v developer móde sa ladia zvlášť.
Filtrujú sa podľa `class`/`subclass` z OpenMapTiles – zoznamy tried sú štedré,
trieda, ktorú dlaždice neobsahujú, sa jednoducho nikdy netrafí.

## Developer mode – ladenie mapy v prehliadači

Mapa sa dá doladiť priamo vo viewri, bez čakania na pipeline. Zapína sa
prepínačom **🛠 Developer mode** v paneli ⚙ (alebo cez `?dev=1` v URL).

| záložka | čo sa v nej dá |
|---|---|
| **Vrstvy** | všetkých ~140 vrstiev po skupinách, s druhom (plocha / línia / bod / popisok / 3D / reliéf). Filtre podľa druhu a hľadanie, zapnutie a vypnutie vrstvy aj celej skupiny, rozsah zoomu (pásik z0–z20 aj `od z` / `do z`), farby všetkých `*-color` vlastností, **ikona** pri symbolových vrstvách, **druh čiary**, hrúbka a krytie, **vzor** a **okraj**. Riadok sa rozklikne kliknutím na názov |
| **Prvky** | inšpektor: klik do mapy vypíše **všetko, čo je pod kurzorom** – naraz zo všetkých vrstiev, s celým obsahom dlaždice. Viď nižšie |
| **Paleta** | ~90 farieb aktuálnej témy po skupinách. Zmena farby prefarbí naraz všetky vrstvy, ktoré ju používajú |
| **Trasy** | značené trasy: **odstup pásika od cesty** (zvlášť pri ceste, pri chodníku a rozostup dvoch trás vedľa seba), a pre každý druh trasy **farba**, **vzor čiary** (plná / čiarkovaná / bodkovaná / čiarka-bodka…) a **ikona**. Plus všetkých desať farieb turistických značiek |
| **Ikony** | sada ikoniek pre POI, vrcholy a letiská – s náhľadom, počtom obrázkov a licenciou |
| **POI** | ktoré triedy bodov sa zobrazujú (zoznam sa načíta z dlaždíc v aktuálnom výreze) |
| **Súbor** | stiahnutie, nahratie a vymazanie úprav |

### Trasy: prečo vlastná záložka a nie zoznam vrstiev

Značené trasy sa cez záložku Vrstvy ladiť nedajú, hoci sú to vrstvy ako každé
iné. Sú na to tri dôvody a každý z nich je vidieť až pri pokuse:

- **jeden druh trasy sú TRI vrstvy** (pásik, ikona, názov) – zmeniť farbu
  cyklotrasy by znamenalo nájsť a upraviť tri riadky v troch skupinách,
- **farba nie je v `paint`, ale vo výraze**: pásik si ju vyberá podľa značky
  z OSM (`colour=red` → farba z palety), takže políčko „farba vrstvy" by ju
  prebilo pre všetky značky naraz,
- **odstup od cesty je vlastnosť všetkých naraz**, nie jednej vrstvy.

Záložka je preto o **druhu trasy**, nie o vrstve: riadok = druh (`hiking`,
`bicycle`, …), v ňom farba, vzor čiary s náhľadom a ikona zo sady, ktorá je
práve nasadená (aj s možnosťou *žiadna*). Odstupy sú hore, v pixeloch pri z16;
ostatné zoomy sa škálujú s nimi.

Farba sa zapisuje do **palety** (`trailCycling`, `trailRed`…), nie vedľa nej –
z tej istej farby žije aj pásik, aj ikona, aj názov trasy, a druhá cesta k nej
by sa raz rozišla. Vzor a ikona idú do `trails.types.<druh>` v úpravách štýlu.

### Každá mapa zvlášť

Developer mode ladí vždy **tú mapu, ktorá je práve na obrazovke** (výber *Typ
mapy* v paneli ⚙). Nad zoznamom vrstiev aj v záložke POI je preto prepínač
rozsahu:

| rozsah | kam sa úprava zapíše |
|---|---|
| **len táto mapa** | `maps.<typ mapy>` – platí len pre ňu (napr. „na cestnej mape nechcem vrstevnice po 10 m") |
| **všetky mapy** | `layers` / `poi` – platí pre všetky typy máp naraz |

Pri každom je v zátvorke počet úprav, ktoré ten priečinok drží. Vrstva
upravená v práve zvolenom rozsahu má v riadku modrú bodku. Zapnutie alebo
vypnutie vrstvy v rozsahu *všetky mapy* zároveň zruší výnimky nastavené
v jednotlivých mapách – inak by tlačidlo tvrdilo, že vrstvu zapína, a nič by
sa nestalo.

Keď vrstvu vypína profil typu mapy (lyžiarske trasy na turistickej mape),
zapnutie sa uloží ako výslovné `visible: true` – iba „prestať ju vypínať"
by tam nestačilo.

### Zoom: čo sa na ňom zobrazí a čo nie

Zoom nie je len informácia, ale hlavný nástroj: **nastav zoom a povedz, čo na
ňom má a nemá byť.**

- **Posuvník zoomu** (mapa tam skočí) + skratky `z4 z8 z10 z12 z14 z16 z18 z20`
  na zoomy, kde sa mapa láme. Posuvník sleduje aj bežné zoomovanie myšou.
- **Štítok s rozsahom v riadku** (`z13–16`, `z9+`, `vždy`) je **prepínač**:
  klik povie, či sa vrstva na aktuálnom zoome kresliť má, alebo nie. Rozsah
  ostáva jeden súvislý interval – zapnutie natiahne bližší koniec, vypnutie
  ustúpi tým, ktorý je bližšie. Keď by z rozsahu neostalo nič, vrstva sa rovno
  vypne.
- **Pásik zoomov z0–z20** v detaile vrstvy: jedna bunka = jeden zoom,
  zvýraznené sú tie, na ktorých sa vrstva kreslí, oranžový rámček je aktuálny
  zoom. Klik do bunky ju zapne alebo vypne – z pásika je hneď vidieť, čo
  vrstva robí.
- **Tlačidlá `od z…` / `do z…`** v detaile nastavia hranicu na aktuálny zoom,
  `⟲` vráti pôvodný rozsah.
- **Hromadne:** zaškrtni vrstvy a použi `Zobraziť od z…` alebo `Skryť na z…`.
- Hlavička skupiny má počítadlo `aktívne/všetky`, vrstvy orezané zoomom sú
  bledé a prepínač **len aktívne** schová zvyšok.

**Inšpektor prvkov (záložka Prvky).** Mapa je poskladaná z desiatok vrstiev
nad sebou: na jednom mieste býva plocha, cesta, jej obrys, vrstevnica, pásik
trasy aj popisok. Klik do mapy preto nevyberie „ten jeden prvok", ale vypíše
**všetko, čo je pod kurzorom** – pri každom prvku vrstvu, z ktorej pochádza,
zdrojovú vrstvu dlaždice a po rozkliknutí **všetky jeho atribúty** tak, ako sú
v dlaždici. Vybrané prvky sa v mape zvýraznia oranžovo (aj po zmene farieb či
témy) a každý sa dá skopírovať ako JSON alebo jedným tlačidlom nájsť
v záložke *Vrstvy* a hneď preštýlovať.

Nad zoznamom je zvlášť sekcia **Značené trasy tadiaľto**: pásiky trás sú
posunuté vedľa cesty, takže klik do chodníka by ich netrafil – hľadajú sa
preto v širšom okolí a vypíšu sa všetky relácie, ktoré tadiaľ vedú, s farbou
značky, sieťou, pruhom a odkazom do OSM. Polomer výberu (predvolene 6 px) sa
dá zmeniť; k dispozícii sú aj súradnice kliknutého miesta a odkaz naň
v OpenStreetMape.

### Druh čiary a výplň plochy

Detail vrstvy je rozdelený na sekcie **Zoom → Farby → Ikona → Štýl čiary /
Štýl plochy → Okraj**, takže je vidieť, čo sa kde nastavuje.

**Štýl čiary** (línie): výber druhu čiary s **náhľadom** vedľa rozbaľovačky –
12 predvolieb: plná, čiarkovaná, dlhé čiarky, krátke čiarky, bodkovaná,
bodkovaná hustá, bodkovaná riedka, čiarka-bodka, **čiarka-bodka-bodka
(náučný chodník)**, čiarkovaná 1 : 1 (železnica), priečky, rebrík lanovky. K tomu
hrúbka a krytie čiary. Malý chodník sa teda spraví bodkovaný a náučný
chodník čiarka-bodka-bodka jedným výberom – a keďže úprava vie ísť len do
jednej mapy, môže to platiť napríklad iba na turistickej.

**Štýl plochy** (plochy a 3D): krytie výplne + opakujúci sa **vzor** (19
predvolieb – šrafovanie, mriežka, bodky, vlnky, stromčeky, šupiny, **kamienky**,
tehly, krížiky, priečky, šípky…) s vlastnou farbou, veľkosťou dlaždice, hrúbkou
ťahu a krytím.

**Plochu sa dá nechať BEZ VÝPLNE** – zaškrtávatko *„bez výplne – ostane len
vzor a okraj"* pri farbe plochy. V úpravách je to `"fill-color": "none"`
a v štýle z toho vyjde priehľadná farba. Nie je to to isté ako dve veci, ktoré
sa na prvý pohľad ponúkajú:

| páka | čo urobí |
|---|---|
| **`fill-color: none`** | zmizne len farba pozadia; **vzor aj okraj ostanú** |
| krytie 0 | `fill-opacity` násobí všetko, čo vrstva kreslí – **zhasne aj obrys** z `fill-outline-color` (má ho `pedestrian-area` a `building`) |
| vypnutie vrstvy | zmizne aj **vzor**, ktorý na nej visí (odvodená vrstva drží viditeľnosť predlohy) |

Preto sa `none` dá zadať len na ploche (`fill-color`, `fill-extrusion-color`) –
čiaru alebo popisok treba vypnúť cez viditeľnosť, nie priehľadnou farbou, aby na
to isté neboli dve páky. Kontrola pri importe to odmietne a povie prečo.

#### Farba a hrúbka podľa zoomu

Farba, krytie aj hrúbka sa dajú nastaviť **pre každý zoom zvlášť** – nie len
jednou pevnou hodnotou. V paneli je pri každej z nich riadok *„podľa zoomu"*
s tlačidlom **`+ zlom pri z14`**, ktoré pridá zlom na zoome, KDE PRÁVE STOJÍ
MAPA. Tak sa mapa aj ladí: nastav zoom, pozri sa, oprav farbu; písať zoom do
políčka a až potom sa naň presunúť by bolo to isté dvakrát, druhý raz naslepo.

V úpravách je to pole `[[zoom, hodnota], …]` a v štýle z neho vyjde
`interpolate` podľa zoomu:

```json
"landcover-wood": { "paint": { "fill-color": [[12, "#00ff00"], [18, "#ff00aa"]] } }
"rail-bg":        { "paint": { "line-width": [[11, 1], [16, 4], [20, 12]] } }
```

Kým sú zlomy zapnuté, pevné políčko tej istej vlastnosti sa **zamkne** – dve
páky na jednu vlastnosť by sa tichým prepisom rušili. Jeden zlom je platný
a znamená pevnú hodnotu; strop je 8 zlomov.

**Zlomy sa zoraďujú podľa zoomu hneď pri zápise, nie až pri skladaní štýlu**,
a nie je to kozmetika: `interpolate` vyžaduje striktne rastúce vstupy a MapLibre
pri porušení odmietne **celý štýl**, nie len tú vlastnosť – mapa sa nenačíta
vôbec. Overené jeho vlastným validátorom (*„Input/output pairs for `interpolate`
expressions must be arranged with input values in strictly ascending order"*).
V paneli pritom zlomy vznikajú v poradí, v akom ich naklikáš (najprv z18, potom
z12), takže nezoradený vstup je normálny stav. Zoraďuje ich jedna funkcia
(`sortStops`) na všetkých troch miestach, kde vznikajú: import súboru, zápis
z panela aj skladanie štýlu.

**Vzor, ktorý má vyzerať ako rozsyp, musí prečnievať za hranu dlaždice.**
Vzory sa dlaždicujú, takže keď v nich všetky tvary ležia vnútri (súradnice
0–1), má dlaždica po obvode prázdny okraj – a z opakovania je **mriežka
prázdnych uličiek každých `size` pixelov**, ktorú oko na hotovej ploche vidí
ako raster. Jedna dlaždica pritom vyzerá úplne v poriadku a MapLibre nepovie
nič, čiže je to tichý omyl. Kamienky (`rocks`) to raz mali: namerané krytie
inkom na šve bolo 3,4 % proti 25,8 % v celej dlaždici a najprázdnejší pás 0 %.
Odvtedy časť kameňov presahuje za hranu (rasterizér počíta vzdialenosť aj
k 3×3 susedným kópiám, takže druhá polovica sa objaví na opačnej strane sama)
a na šve je 27,1 %. Kontroluje to `workers/lint/style.mjs` pri každom vzore,
ktorý sa hlási ako `scatter: true`; pravidelné motívy v bunke (bodky, krúžky,
krížiky na cintoríne, stromčeky v lese) majú prázdny okraj zámerne a tie sa
nekontrolujú.

**Vzor môže mať plocha aj priamo zo štýlu**, nie len z naklikanej úpravy –
skalné plochy majú predvolene kamienky (`rocks`). Developer mode vtedy
neukazuje „žiadny", ale ten vzor, ktorý je naozaj v mape: dá sa doladiť
(farba, veľkosť, hrúbka, krytie), vymeniť za iný alebo **vypnúť** – vypnutie
sa uloží ako `pattern: null`, teda „vzor zo štýlu preč", nie ako „nič som
nezmenil". Zvýraznenie *zmenené* svieti len vtedy, keď úprava naozaj existuje.

**Okraj** je pri ploche obrysová čiara, pri čiare širší obrys pod ňou
(casing) – oboje s farbou, šírkou, druhom čiary (tá istá ponuka s náhľadom)
a krytím.

Číselné polia (hrúbka, krytie) sú prázdne s nápisom `auto`, keď je hodnota
v štýle zadaná interpoláciou podľa zoomu; vyplnením sa nahradí pevnou
hodnotou, vymazaním sa vráti pôvodná interpolácia.

Vzory nie sú hotové obrázky: **názov obrázka je jeho predpis**
(`pat:trees:2f5a28:22:12`), takže si ho prehliadač dokreslí sám cez
`styleimagemissing`, a pipeline tie isté názvy nájde v hotovom štýle a
dopečie ich do spritu ([workers/styles/patterns.mjs](styles/patterns.mjs)),
aby fungovali aj v statickom `style.json` pre iOS.

**Ikona a farby z palety priamo v riadku vrstvy.** Symbolová vrstva s pevne
zadanou ikonou (ikony trás, vrcholy, letiská) má v detaile výber **Ikona** so
všetkými obrázkami z nasadenej sady. Vrstvy, ktoré si farbu vyberajú
**výrazom** – pásik trasy podľa značky z OSM – nemajú v `paint` hex, ktorý by
sa dal prepísať; namiesto toho je v riadku sekcia *farby z palety*, kde sa
dajú doladiť rovno tam, kde je vidieť, čo menia. Taká zmena platí pre celú
tému (je to paleta, nie vrstva).

**Sady ikoniek.** Schéma OpenMapTiles pomenúva POI cez `class`/`subclass`
(`restaurant`, `cafe`, `fuel`, …) a štýl z toho skladá meno ikony – zdroj je
teda použiteľný len vtedy, keď jeho ikony nesú rovnaké mená. Nasadené sú tri:

| sada | obrázkov | pokrytie bežných tried | poznámka |
|---|---|---|---|
| **OSM Liberty (maki)** – predvolená | 244 | 44/50 | jediná so šípkou jednosmeriek; symboly sú v bielom koliesku |
| **OSM Liberty Topo** | 242 | 42/50 | turistická odvodenina s outdoorovými symbolmi |
| **OSM Bright (OpenMapTiles)** | 101 | 42/50 | bez koliesok, len svetlé halo; menej tried, čistejšia kresba |

Preverené a zamietnuté: sprity ostatných štýlov OpenMapTiles (positron,
dark-matter, klokantech, maptiler-basic, fiord) obsahujú 1–4 obrázky, teda
žiadne POI ikony; sprite Protomaps v4 má vlastné pomenovanie a z bežných tried
OSM pokryje asi tretinu, navyše s rámčekom okolo symbolu.

**Hromadné úpravy a kopírovanie.** V oboch zoznamoch sa dajú položky
zaškrtnúť (aj celá skupina naraz alebo „Vybrať zobrazené" podľa filtra)
a potom ich naraz zobraziť, skryť, zafarbiť jednou farbou, skopírovať ako
JSON alebo resetovať. Každá farba má vedľa seba hex pole aj tlačidlo na
skopírovanie; v palete sa dá aj vložiť JSON s farbami.

Zmeny sa priebežne ukladajú **do prehliadača** (`localStorage`) a hneď sa
prejavia v mape.

### Cesta úprav do zdrojáku

```
mapa na Pages ─► 🛠 developer mode ─► „Stiahnuť style-overrides.json"
                                       │
                                       ▼
              Actions ─► „Mapa · úpravy štýlu" (vlož obsah súboru)
                                       │
                       workers/styles/overrides.mjs – kontrola a prečistenie
                                       │
                       poc/web/style-overrides.json v repozitári
                                       │
                       ďalší „Build map" ─► mapa pre web aj iOS s úpravami
```

`pattern` a `outline` sa nezapisujú do pôvodnej vrstvy – pipeline z nich
vyrobí odvodené vrstvy `<id>__pattern` a `<id>__outline` (okraj plochy nad
ňou, obrys čiary pod ňou), takže sa dajú kedykoľvek odobrať bez stopy.

Workflow **Mapa · úpravy štýlu** berie obsah súboru ako vstup
(prípadne `overrides_url` pri väčšom súbore), overí ho tou istou funkciou ako
prehliadač – neznáma farba, neplatný hex, neprepísateľná vlastnosť či
prehodený rozsah zoomu skončia varovaním a vyhodia sa – a až potom ho
commitne (voliteľne cez pull request). `reset` vráti pôvodný štýl.

Formát súboru:

```json
{
  "version": 2,
  "icons": "osm-bright",
  "palette": { "outdoor": { "forest": "#a8cc8e", "trailRed": "#cc2222" } },
  "layers": {
    "landcover-wood": {
      "paint":   { "fill-color": "#a8cc8e" },
      "pattern": { "id": "trees", "color": "#2f5a28", "size": 22, "weight": 1.2, "opacity": 0.7 },
      "outline": { "color": "#2f5a28", "width": 1, "dash": "dashed", "opacity": 1 }
    },
    "rail-bg":          { "dash": "ties", "outline": { "color": "#5a5a5a", "width": 1 } },
    "trail-hiking-icon": { "icon": "triangle_11" },
    "housenumber":      { "visible": false },
    "road-motorway":    { "minzoom": 6, "maxzoom": 20 }
  },
  "poi": { "hidden": ["fast_food"] },

  "maps": {
    "turisticka": {
      "layers": {
        "road-path":  { "dash": "dotted", "paint": { "line-width": 2 } },
        "trail-ski":  { "visible": true }
      },
      "poi": { "hidden": [] }
    },
    "cestna": {
      "layers": { "poi-road": { "minzoom": 8 } },
      "poi": { "hidden": ["picnic_site"] }
    }
  }
}
```

`layers` a `poi` platia pre **všetky** typy máp, `maps.<typ>` len pre jeden a
prebíja spoločné nastavenie (`paint` sa mieša po jednotlivých vlastnostiach).
Súbory z verzie 1 (bez `maps`) sa načítajú bez zmeny – všetko z nich sa berie
ako spoločné.

Prehliadač uprednostní to, čo má uložené v `localStorage`; ak tam nič nie je,
použije `style-overrides.json` zo stránky. Tlačidlo **Vymazať všetky zmeny**
vráti mapu na to, čo je v zdrojáku.

## Zoom a detail

Planetiler má tvrdý limit `maxzoom <= 16`
(`PlanetilerConfig.MAX_MAXZOOM`) – vyššia hodnota zhodí build hláškou
`Max zoom must be <= 16`. Pipeline preto zoom nad 16 automaticky oreže na 16
a upozorní v logu.

Priblíženie až na **z20** to nijako neblokuje: dlaždice z16 sa dopočítavajú
**overzoomom** v MapLibre (web aj iOS majú `maxZoom = 20`). Aby overzoom
vyzeral ostro, najvyšší zoom sa generuje bez zjednodušovania geometrie:

```
--maxzoom=16 --render_maxzoom=16
--min_feature_size_at_max_zoom=0     # nezahadzuj malé prvky
--simplify_tolerance_at_max_zoom=0   # presná geometria
--transportation_z13_paths=true      # všetky chodníky/cestičky
--building_merge_z13=false           # samostatné budovy, nie zlepence
```

Čo je vidieť na akom zoome (`DETAIL_Z = 14` v `themes.js`):

| zoom | správanie |
|---|---|
| < 14 | mapa sa orezáva – vrstvy sa zapínajú postupne podľa `minzoom`. Cesty sa kreslia už od z4 vlasovými čiarami (obrysy až od z10), aby bola sieť čitateľná aj na malých mierkach |
| 14–15 | plný detail, POI filtrované na `rank <= 24`, aby mapa nebola zahltená |
| 16+ | **všetko bez filtra** – všetky body, línie aj plochy, 3D budovy |
| 17+ | navyše súpisné čísla domov |

Toto je základ; **typ mapy tieto hranice posúva** – turistická púšťa chodníky
a trasy skôr (z8–z10), cestná naopak bežné POI až od z15 a chodníky vôbec.
Konkrétne posuny sú v [poc/web/map-types.js](../poc/web/map-types.js) a dajú sa
prekliknúť v developer móde.

**Dno z11 pre vrstevnice a skaly typ mapy neposúva a ani nemôže**: pod ním pre
ne nie sú dlaždice (`min_zoom` v schémach), takže by profil ukazoval prázdno.
Je to zámer – na prehľadovej mierke sa nedá prečítať ani jedna vrstevnica a zo
skál je sivá škvrna, ale podklady s nimi sa sťahujú tak či tak.

**Výplň nad zmiešanou geometriou (a čudné polygóny od z13).** `--transportation_z13_paths=true`
vyššie má jeden dôsledok, ktorý stál opravu v štýle: od z13 sú v dlaždiciach
všetky chodníky, a to sú **čiary**. MapLibre `fill` vrstve čiary nepreskočí –
otvorenú lomenú čiaru pošle earcutu, ako keby to bol uzavretý prstenec, a
vyrobí z nej sebaprekrývajúci sa mnohouholník. Vrstva `pedestrian-area` (`fill`
nad `transportation`, `minzoom: 13`) tak od z13 kreslila útvary „prerezané" cez
krajinu, a keďže farba `pedestrian` je od podkladu na nerozoznanie, vyzeralo to
ako diera do podkladu. Každá výplň nad vrstvou, ktorá nesie viac typov
geometrie (`transportation`, `piste`, `aeroway`, `park`), preto ide cez
`polygonOnly(…)` a stráži to kontrola
[`workers/lint/style.mjs`](lint/style.mjs). Rozpis:
[docs/pipeline.md](../docs/pipeline.md#výplň-nad-zmiešanou-geometriou-prečo-boli-od-z13-čudné-polygóny).

**Veľkosť vs. zoom.** GitHub Pages zvládne stránku do ~1 GB a do toho sa musia
zmestiť dlaždice **aj vrstevnice, fonty a sprity** – nie každé zvlášť. Celé
Slovensko má pri z14 ~800 MB, vrstevnice po 10 m do z14 ďalších niekoľko sto,
takže spolu by limit prekročili. Pipeline preto hospodári s jedným rozpočtom:

- `size_limit_mb` (default 900) – rozpočet na **celú stránku**,
- vrstevnice sa robia **pred** dlaždicami a majú strop 40 % rozpočtu; keď sú
  nad ním, prepočítajú sa o zoom nižšie (z hotového GPKG, teda v sekundách –
  DEM sa znovu nesťahuje),
- dlaždice potom dostanú presne to, čo zvýšilo, a `auto_shrink` (default áno)
  ich zmenší na zoom, ktorý sa doň vojde. Keďže nižší zoom zmenší dlaždice
  zhruba 3,5×, skáče sa rovno o toľko zoomov, koľko treba (najviac o dva
  naraz), aby sa nerobili zbytočné hodinové behy Planetileru,
- `crop_bbox` – oreže PBF na menšie územie (`west,south,east,north`), čím sa
  maxzoom 16 pohodlne zmestí.

Vďaka tomu build na veľkosti nepadne až na konci po hodinách tilovania, ale
sám sa zmestí a do logu napíše, čím ubral. Ak chceš väčší detail, ubrať treba
územiu (`crop_bbox`, kraj) alebo vrstevniciam (`contour_interval` 20 m,
`contour_maxzoom` 12, prípadne `contours: nie`).

Pre maximálny detail na z20 teda voľ **kraj alebo `crop_bbox` + maxzoom 16**;
pre celé Slovensko nechaj pipeline zvoliť najvyšší zoom, ktorý sa zmestí.
- **iOS / multiplatform:** appka v [app/ios](../app/ios), návrh v
  [docs/ios-multiplatform.md](../docs/ios-multiplatform.md).
- **Backend:** [backend](../backend) – NestJS API (`/api/health`, `/api/regions`).

## Prvé spustenie

1. **Pages si beh zapne sám.** Prvý krok skontroluje nastavenie repozitára
   a keď zdroj Pages nie je *GitHub Actions*, prepne ho (a keď Pages nie sú
   zapnuté vôbec, zapne ich). Je to preto, že na stránke má byť **mapa a nie
   README**: pri zdroji „vetva" beží popri nás zabudovaný Jekyll builder,
   ktorý po každom pushi nasadí koreň repozitára a mapu prepíše. Keby na to
   token nemal práva, beh sa zastaví v tretej sekunde s návodom –
   Settings → Pages → Build and deployment → Source: **GitHub Actions**.
2. Actions → **Mapa · Build map** → *Run workflow*.
   Formulár má **desať polí** – viac `workflow_dispatch` inputov GitHub
   neprijme (pri 26 sa workflow prestal načítať a beh skončil ako „failure"
   s nula jobmi). Vo formulári sú preto veci, ktoré sa naozaj menia:

   | input | typ | čo robí |
   |---|---|---|
   | `region` | výber | `slovensko` alebo kraj (default **`bratislavsky`**) |
   | `area` | **výber** | pohorie, na ktorom sa počíta terén – `cely_region`, `tatry`, `slovensky_raj`, `mala_fatra`… (default **`cely_region`**) |
   | `test` | **switch** | **rýchly test**: celý beh (mapa aj terén) len na štvorci 4 km² zo stredu výrezu a mapu otvoriť rovno tam (predvolene **odškrtnutý** – predvolený beh je ostrý; zapisuje sa do `maps-test.json`) |
   | `contour_source` | **výber** | odkiaľ **vrstevnice**: `sonny` (20 m), `dmr35` (10 m), `dmr5` (LiDAR – s výrezom 1 m, inak 5 m), `ziadne` |
   | `rock_source` | **výber** | odkiaľ **skaly**: ten istý zoznam modelov (počíta sa sklon), alebo `tienovanie` (hotové polygóny z tieňovaných dlaždíc), alebo `ziadne` |
   | `shading_source` | **výber** | odkiaľ **tieňovanie a 3D terén**: `sonny`, `dmr35`, `dmr5`, `ziadne` |
   | `wikipedia` | **switch** | stiahnuť **články z Wikipédie** k objektom v regióne (vlastný ZIP na Drive; predvolene zapnuté) |
   | `rock_slope` | text | od akého sklonu (°) je terén skala |
   | `rebuild` | výber | `nic` / `vrstevnice` / `skaly` / `tienovanie` / `vsetko` (staré `teren` sa ešte prijme, ale už sa neponúka) |
   | `options` | text | zriedka menené nastavenia ako `kľúč=hodnota` (napr. veľkosť testu `test_km2=5`, mriežka na obrys skál `rock_res=1`) |

   **Defaulty sú jedno rozhodnutie, nie tri nezávislé voľby** – Bratislavský
   kraj (najmenší), `cely_region` a odškrtnutý test, čiže predvolené spustenie
   je ostrý build celého kraja, ktorý sa dá zaplatiť. Výrez je predvolene
   `cely_region`, teda „nezmenšuj mi mapu za mňa": kým tu stálo `vysoke_tatry`,
   dostal ten, kto si vybral iný kraj a ten riadok prehliadol, mapu bez
   vrstevníc a skál skoro všade — a v logu o tom bolo len `::warning::`.
   Zmenšovanie behu má tým pádom jednu páku a je ňou switch `test`.
   Formulár *Run workflow* sa totiž po každom
   otvorení vracia na predvolené hodnoty: GitHub si nepamätá, s čím si beh
   pustil naposledy, a z API sa to ani nedá zistiť. Čím menej treba
   prekliknúť, tým menej sa toho zabudne. Čo bolo v konkrétnom behu iné než
   default, vypíše súhrn v bloku **Nastavenia tohto behu** – z neho sa dá
   beh zopakovať bez hádania.

   **Prečo je vo formulári `test` a nie `rock_res`.** Polí je desať a je to
   strop, takže sa dá pridať len to, za čo niečo vypadne. Rýchly test sa
   zapína a vypína pri každom behu — to je switch. Jeho veľkosť aj mriežka na
   obrys skál sa menia zriedka, takže sú z nich voľby (`test_km2=5`,
   `rock_res=1`); mriežku navyše `auto` vyberie z bunky DEM a rozpočtu času
   lepšie, než sa háda ručne.

   **A prečo `wikipedia` a nie `contour_interval`.** Ten istý obchod, o jedno
   kolo neskôr. Články sa zapínajú a vypínajú podľa toho, či ide o ostrý build
   alebo o ladenie terénu — to je switch. Interval vrstevníc má z DMR 5.0 dobrý
   default 5 m a mení sa pri prechode do nížin, nie pri každom behu, takže sa
   píše ako voľba (`options: contour_interval=10`). Že sa jedenásty input
   nepridá, chytí **actionlint** do dvoch sekúnd („maximum number of inputs for
   workflow_dispatch event is 10") – nie je to na dôvere, je to overené.

   **Tri výbery zdroja, jeden na vrstvu.** Kým to bol jeden `dem_source` pre
   všetko, nedalo sa povedať to, čo dáva zmysel najčastejšie: skaly
   z najjemnejšieho modelu (aj keď ho máme len na výrez) a tieňovanie
   z hrubšieho, ktorý pokrýva celý región. `ziadne` vrstvu vypne – zapínač je
   tým pádom v tom istom poli ako zdroj, takže sa nedá zadať „generuj
   vrstevnice, zdroj žiadny". Nahradilo to aj pole `layers`; značené trasy
   (jediná vrstva bez výberu zdroja, ide z toho istého PBF ako mapa) sa
   vypínajú cez `options: trails=false`.

   `dmr5` má dve podoby a rozhoduje rozsah, nie ďalší výber: s vyplneným
   `area` plné 1 m, bez neho dlaždice na 5 m. Zoznamy vo formulári stráži
   `Kontrola · lint workflowov` proti [workers/data/dem-sources.json](data/dem-sources.json)
   – zdroj sa nedá pridať do jedného a zabudnúť v druhom.

   Zoznam pohorí v `area` sa berie z
   [workers/data/areas.json](data/areas.json) – keď tam pribudne pohorie, treba
   ho dopísať aj do výberu vo workflowe. Vlastný bbox ide cez
   `options: area_bbox=W,S,E,N`.

   Do `options` idú veci, ktoré sa menia zriedka – napíšu sa za sebou,
   oddelené medzerou:

   ```
   crop_bbox=18.9,49.1,19.2,49.3 size_limit_mb=1200 contour_maxzoom=15
   ```

   Známe kľúče s predvolenými hodnotami sú vo
   [workers/plan/options.py](plan/options.py): `crop_bbox`,
   `area_bbox`, `size_limit_mb`, `auto_shrink`, `ugkk_fallback`, `ugkk_urls`,
   `contour_maxzoom`, `contour_smoothing`, `trails`, `trails_maxzoom`,
   `terrain_maxzoom`, `maxzoom`, `rock_img_asset`, `rock_img_zoom`,
   `rock_img_options`, `custom_pbf_url`, `custom_name`, `custom_bbox`,
   `region_clip`.

   **`region_clip` je DOČASNE `false`**, teda dlaždice sa nerežú na hranicu
   regiónu (`--polygon` Planetileru) a vyrobia sa na celom obdĺžniku bboxu.
   V mape to vidieť nie je – hranicu dokresľuje maska v štýle, ktorá je „celý
   svet mínus región". Merané na Bratislavskom kraji (maxzoom 14): 1607
   dlaždíc namiesto 1271 (+26 %) za +0,7 % bajtov a rovnaký čas, a v tých
   navyše je územie za hranicou kraja vrátane cudzích sídel. Kým je vypnutý,
   hlási to `::warning::` v každom behu; späť sa zapína `region_clip=true`.
   Rozpis a merania: [workers/lib/region-clip.sh](lib/region-clip.sh).

   Zdroj skál sa vyberá **inputom `rock_source`**, nie tu – prepína celý
   pôvod vrstvy, takže patrí do formulára. Cez `options` sa dá nanajvýš
   vynútiť konkrétny asset (`rock_img_asset=rockimg-…gpkg.zst`); viď
   [Druhá cesta k skalám](#druhá-cesta-k-skalám-tmavé-plochy-v-tieňovaní-pokus).

   **Preklep je chyba, nie ticho ignorovaná hodnota.** `size_limit=1200` build
   zastaví so zoznamom známych kľúčov – inak by bežal hodinu s iným
   nastavením, než si myslíš. Na začiatku behu sa vypíše tabuľka všetkých
   nastavení s vyznačením toho, čo si zmenil.

3. Mapa je na `https://<user>.github.io/fricomaps/` – ovládanie je zbalené pod
   tlačidlom ⚙ vľavo hore, aby bolo vidieť hlavne mapu. V paneli je prepínač
   témy, regiónu, vrstevníc a skál, 3D terénu a developer módu.

Pipeline si po nasadení sama overí, že mapa naozaj funguje (**smoke test**):
`manifest.json`, `style.json`, sprite, glyfy a `Range` request na `.pmtiles`
(musí vrátiť `206`). Ak niečo z toho chýba, workflow zlyhá s konkrétnou URL –
namiesto ticha a bielej mapy v prehliadači. Viewer navyše chyby načítania
vypisuje priamo do panela.

**Ikonky a nápisy** nevisia na cudzích službách: sprite aj glyfy (Noto Sans)
sa kopírujú na naše Pages a pred nahratím sa kontroluje, že štýl odkazuje len
na fontstacky a ikony, ktoré tam naozaj sú.

> Pozn.: ak deploy zlyhá na ochrane prostredia `github-pages`, povoľ v
> Settings → Environments → github-pages nasadzovanie aj z tejto vetvy
> (alebo zmerguj do default vetvy a spusti workflow tam).

## Lokálny vývoj

```bash
npx serve poc/web        # viewer (dlaždice vznikajú až v CI)
cd backend && npm install && npm run start:dev   # API na :3000
```
