# Navigácia: čo na ňu treba a čo z toho máme

Zadanie (august 2026): navigovať **autom, pešo, bicyklom, autobusom a vlakom**.
Pri aute k tomu voľby *vyhnúť sa diaľniciam / rýchlostným cestám /
spoplatneným cestám / cestám I., II. a III. triedy / lesným cestám a
chodníkom*, **maximálna rýchlosť vozidla** a **diaľničná známka po krajinách**
(mám ju, a dokedy). Viacero smerovacích motorov je vítaných.

Tento súbor je návrh, nie popis hotového stavu. Čo z neho už v repozitári je,
stojí na konci.

> **September 2026: §4 a §7 sú prekonané.** Graf Valhally po krajoch vážil
> 176 – 192 MB na kraj (§7a) a na hranici končil. Namiesto neho sa vozia
> **dlaždice so značkami** a cenu počíta telefón – rozpis je v §10 a celý plán
> v [`skifahrer/rikimaps`, `.planning/navigation.md`](https://github.com/skifahrer/rikimaps/blob/master/.planning/navigation.md).
> Čo tento súbor hovorí o VÝZNAME volieb (známka ≠ mýto, `bus` ≠ `transit`,
> transit potrebuje GTFS), platí ďalej.

## 1. Dnešný stav: v mapách nie sú ani dáta na to

Dlaždice robí Planetiler so **štandardným profilom OpenMapTiles** a jeho vrstva
`transportation` nesie len toto (overené v `openmaptiles/layers/transportation/
transportation.yaml`):

```
class, subclass, network, oneway, ramp, brunnel, service, access,
toll, expressway, layer, level, indoor, bicycle, foot, horse,
mtb_scale, official, surface
```

Teda **žiadne `maxspeed`, `maxheight`, `maxweight`, `width` ani `lanes`**, a nič
o odbočovacích zákazoch. Vlastné schémy (`workers/features/features.yml`,
`trails/trails.yml`) doťahujú z PBF veci, ktoré OpenMapTiles nemá, ale rozmerový
ani rýchlostný atribút cesty medzi nimi nie je a `features/filter.txt` tie kľúče
z PBF ani nepustí.

**A aj keby tam boli, navigovať sa z nich nedá.** Vektorová dlaždica je kreslený
obraz, nie graf: geometria je zjednodušená a orezaná po hranicu dlaždice,
`merge_line_strings` úseky zlepuje, cesty nenesú OSM `id` a relácie
(`type=restriction`) v nich nie sú vôbec. Smerovanie je preto **druhá dátová
cesta z toho istého PBF**, nie ďalší atribút v dlaždici.

## 2. Zadanie sa delí na dve polovice a majú inú povahu

| polovica | čo v nej je | z čoho stojí |
|---|---|---|
| **auto, pešo, bicykel** | cesty, zákazy, povrchy, rozmery | OSM – to isté PBF, ktoré pipeline už sťahuje |
| **autobus, vlak** | *kedy* čo ide | **GTFS – cestovné poriadky, ktoré v OSM NIE SÚ** |

To je dôležité rozdelenie, lebo prvá polovica je práca s dátami, ktoré máme, a
druhá je závislosť na cudzom zdroji. OSM vie, kde koľaj vedie a kde je zastávka;
kedy tam čo ide, v ňom nie je a nikdy nebude.

Pozor aj na názvoslovie: `bus` v motore je **vozidlo**, nie linka – trasa pre
autobus ako pre auto s inými zákazmi. Dať sa odviezť autobusom je `transit`
a to sú poriadky.

## 3. Ktorý motor to vie povedať

Merané na zdrojáku, nie na dokumentácii – dokumentácia Valhally je na tomto
mieste rok za kódom. Zdroje: `src/sif/*cost.cc` a `valhalla/sif/dynamiccost.h`
(master, august 2026), `docs/core/custom-models.md` GraphHoppera.

| voľba zo zadania | Valhalla | GraphHopper |
|---|---|---|
| vyhnúť sa diaľniciam | **áno** – `exclude_highways` | áno |
| vyhnúť sa rýchlostným cestám | **len približne** – `use_highways: 0` | áno |
| vyhnúť sa spoplatneným | **áno** – `exclude_tolls` | áno |
| cesty I. triedy | **NIE** | áno |
| cesty II. triedy | **NIE** | áno |
| cesty III. triedy | **NIE** | áno |
| lesné cesty a chodníky | áno – `use_tracks: 0` + `exclude_unpaved` | áno |
| max. rýchlosť vozidla | **áno** – `top_speed` | áno – `speed: limit_to` |
| známka po krajinách | **NIE** | **áno** – `country == SVK` |
| pešo / bicykel / autobus / transit | áno (aj SAC stupnica) | áno |

Tri riadky s „NIE" majú jednu spoločnú príčinu a je to konkrétne miesto v kóde.
`exclude_highways` je vo Valhalle **presne `RoadClass::kMotorway`**
(`dynamiccost.h`, riadok ~403) – na rýchlostnú cestu teda nesadá. A `use_highways`
len škáluje pevnú tabuľku (`src/sif/autocost.cc`, riadok 76):

```c
constexpr float kHighwayFactor[] = {
    1.0f, // Motorway
    0.5f, // Trunk
    0.0f, // Primary
    0.0f, // Secondary
    0.0f, // Tertiary
    0.0f, // Unclassified
    0.0f, // Residential
    0.0f  // Service, other
};
```

Pri Primary, Secondary a Tertiary je nula, takže `use_highways` na cesty I., II.
a III. triedy nemá **slabý účinok, ale nulový**. Žiadnou kombináciou parametrov
sa to dnes povedať nedá.

### Záplata `kHighwayFactor`

Tá istá tabuľka je aj odpoveď: stačí ju spraviť **nastaviteľnou** – osem čísel
z `costing_options` namiesto `constexpr` – a k tomu tvrdý zákaz v tom istom
`Allowed()`, kde už sedí `exclude_highways_`. Je to zmena v desiatkach riadkov
v jednom súbore a ide **po srsti kódu**: `use_tracks` a `use_living_streets` sú
presne tento vzor, len pre `Use`, nie pre `RoadClass`. Ten istý zásah vyrieši aj
známku (per-krajina zoznam vylúčených tried), lebo hrana svoju krajinu v grafe
pozná – v costingu k nej len nie je prístup.

Cena záplaty nie je jej napísanie, ale **jej držanie**: vlastná vetva Valhally,
ktorá sa musí prekladať pre iOS aj Android a doťahovať za upstreamom.

## 4. Rozhodnutie: Valhalla ako prvý motor, profil nad oboma

Celá táto mapa stojí na tom, že si človek **stiahne región a otvorí ho bez
signálu** – offline štýly, balíky na Drive, maska regiónu. Navigácia, ktorá
potrebuje server, by bola v tomto repozitári cudzie teleso, a v horách bez
signálu presne to, čo netreba. Z dvojice motorov beží v telefóne len jeden:
**Valhalla** (C++, dlaždicový graf – ten istý druh veci ako naše mapové
dlaždice). GraphHopper je JVM, do iOS sa nedostane.

Takže: **Valhalla v telefóne, GraphHopper ako druhý motor „so signálom"**, kde sa
zatiaľ dá povedať celé zadanie. To nie sú dve pravdy, ak – a len ak – sa profil
napíše **raz** a preloží sa do oboch dialektov. Preto je prvý kus tejto práce
`workers/data/routing-profiles.json` + `workers/routing/profile.py`, a nie graf.

Poradie práce z toho vychádza samo:

1. **profil ako číselník** (hotové, viď §7) – bez neho by sa každý ďalší krok
   písal dvakrát,
2. **graf a balík** – `valhalla_build_tiles` z PBF, ZIP na Drive, položka
   v katalógu; s tým sa dá navigovať autom, pešo aj na bicykli so **šiestimi
   z deviatich** volieb pre auto,
3. **záplata `kHighwayFactor`** – dorobí tri triedy ciest a známku,
4. **`transit`** – až keď je jasné, odkiaľ GTFS (§6).

## 5. Známka nie je mýto a nie je to jedna otázka

`toll=yes` v OSM je **mýto za prejazd** (brána, tunel, most). Známka sa platí za
**čas** a platí na **sieť**. Kto ich zlúči, dostane nezmysel v oboch smeroch: s
ročnou známkou by sa vyhýbal diaľnici, ktorú má zaplatenú, a bez známky by prešel
tunelom s mýtom. Preto sú to dve voľby – `avoid_toll` a `vignettes`.

Číselník je `workers/data/vignettes.json`: pri každej krajine to, čo sa nemení
pri každej ceste – **či známku pozná** a **na aké OSM triedy platí**. Či ju
používateľ má a dokedy, tam nie je a byť nesmie: to je stav aplikácie.

**Odpovede sú tri, nie dve** – „mám do 30. 9.", „nemám" a „táto krajina známku
nepozná". V Poľsku sa diaľnici netreba vyhýbať preto, že tam známka
neexistuje, kým v Rakúsku bez nej treba. A štvrtá možnosť je **„nevieme"** –
krajina, o ktorej používateľ nepovedal nič. Tá sa nesmie dosadiť potichu ani na
jednu stranu: „mám" vypíše pokutu, „nemám" pošle sto kilometrov po okreskách.
`profile.py` ju berie ako „nemám" (z tých dvoch lacnejší omyl, a je vidieť na
trase) a **hlasno to vypíše**.

Dve veci, ktoré tento model zatiaľ nevie a sú v číselníku napísané:

* **Maďarské krajské známky.** „Mám známku" tam nie je jedna odpoveď na celú
  krajinu.
* **Úseky oslobodené od známky** (obchvaty miest na Slovensku). Z `highway=*` sa
  to prečítať nedá, musí to prísť z `toll=no` na tých úsekoch v OSM.

A dátumy a rozsahy sietí sú vecou zákona, nie prispievateľov OSM, takže má každý
záznam `zdroj` a `stav`. Kým je `stav: doplnit`, **nesmie to ísť do aplikácie
ako fakt** – všetkých deväť záznamov je dnes `doplnit` a `profile.py` to pri
každom zložení profilu vypíše.

## 6. Verejná doprava: chýba zdroj, nie kód

Oba motory transit vedia (Valhalla `multimodal`, GraphHopper `pt`) a oba chcú
**GTFS**. Otázka je, odkiaľ ho na Slovensko vziať:

* **vlaky** – GTFS feed ZSSK je zverejnený cez Transitland
  ([`f-eo0-zssk`](https://www.transit.land/feeds/f-eo0-zssk)), teda aspoň jedna
  cesta existuje,
* **autobusy** – roztrieštené medzi dopravcov a integrované systémy; jednotný
  celoštátny otvorený GTFS sa mi z tohto behu **nepodarilo overiť** (odchádzajúca
  sieť tejto sessions je zúžená, Overpass ani osm.fr neboli dostupné).

Kým to nie je rozhodnuté, je `transit` v číselníku so značkou `needs_gtfs`
a `profile.py` pri ňom povie, že bez zdroja motor vráti „no route" – a že to
nie je chyba profilu. Prázdny režim, ktorý sa tvári hotový, by bol horší.

## 7. Kde graf žije – DVA ROZSAHY, nie jeden

Graf sa stavia **v dvoch rozsahoch a obidva sú potrebné**, lebo odpovedajú na
dve rôzne otázky. Stavia ich ten istý skript (`workers/routing/graph.sh`) –
dva by boli dve pravdy o tom, ako sa graf stavia a čo sa v ňom kontroluje.

### 7a. Graf KRAJA – vlastný balík vedľa mapy

Mapu si človek sťahuje po krajoch a chce v nej navigáciu. Preto sa ku každému
kraju stavia graf z **toho istého PBF, z akého je mapa** (`data/region.osm.pbf`,
job `navigacia` → `.github/workflows/navigation-region.yml`) a balí sa do
**`<kraj>-navigacia.zip` a `.aar`** vedľa mapy toho kraja, s cestami
`routing/*` vnútri.

**Prvá verzia ho balila DOVNÚTRA `<kraj>.zip`** – to isté rozhodnutie ako pri
vyhľadávacom indexe a z toho istého dôvodu: druhý balík, o ktorom sa
v aplikácii nedozvie, je mapa, ktorá „nefunguje“. Argument stál na tom, že je
to „jednotky až desiatky MB proti stovkám za dlaždice“. **Namerané to tak nie
je** (`maps.json`, beh 6):

| kraj | mapa spolu | z toho graf |
|---|--:|--:|
| Banskobystrický | 283 MB | 192 MB |
| Prešovský | 276 MB | 189 MB |
| Bratislavský | 172 MB | 176 MB\* |

\* `raw_size` pred zabalením, preto viac než celý ZIP.

Dve tretiny „základnej mapy“ teda bola sieť, po ktorej sa jazdí, nie mapa,
ktorá sa kreslí – a to je presne prípad vrstevníc a tieňovania: ťažká vec,
ktorú mapa na to, aby sa nakreslila, nepotrebuje. Kto navigáciu nechce, ju
odteraz nemá za čo sťahovať; **kto ju chce, sa o nej dozvie z katalógu** –
`maps.json` nesie `-navigacia.zip` pod `maps.navigacia` vedľa `cesty` a `body`,
takže je v aplikácii v tom istom zozname na stiahnutie ako ony. Argument
z prvej verzie tým nepadol, len ho drží katalóg a nie balenie.

**Chvíľu cestoval graf v balíku `linie` a vrátil sa do vlastného.** Argument
pre spojenie bol, že značené trasy, obmedzenia na ceste aj graf sú **tá istá
sieť z toho istého PBF**, raz nakreslená a raz zjazdná. Odkedy je v balíku
**celá dopravná sieť** (`-transport.pmtiles`: cesty od diaľnice po schody,
železnice, trajekty, lanovky – rozpis v hlavičke
[`workers/transport/transport.yml`](../workers/transport/transport.yml)), to už
neplatí: tá kreslená sieť váži desiatky MB proti 170–190 za graf, takže by
z balíka bolo deväť desatín graf a kto chce sieť len vidieť, sťahoval by ho
tak či tak. Sú to teda zase dve položky v katalógu – a sú to dve otázky: „chcem
vidieť, kadiaľ sa dá ísť“ a „chcem, aby ma to tam doviezlo“.

Rozbaľuje sa **do toho istého priečinka regiónu** ako mapa, takže po rozbalení
je graf v `…/<kraj>-navigacia/routing/` – appka ho hľadá skenom priečinka
(`RoutingGraphPath` v `skifahrer/rikimaps`), nie na pevnej ceste, takže je
jedno, z ktorého balíka prišiel.

**Trasa v ňom končí na hranici kraja.** PBF je rezaný `osmium extract -s smart`
– celé cesty a doplnení členovia relácií, urobené pre **plochy** – takže hrana,
ktorej chýba druhý koniec, je slepá ulica a relácie zákazov odbočenia na
hranici môžu byť neúplné. Je to **zámer, nie opomenutie**, a `graf.json`
v balíku to o sebe hovorí (`rozsah: "region"`, `hranica: "trasa končí na
hranici regiónu…"`) – mlčanie by sa dalo čítať ako pokazený graf.

**A je to naozaj hranica kraja.** Kým sa PBF orezávalo `.poly`-gónom z osm.fr,
bol graf kraja o 2 – 4 km väčší než jeho mapa: ten polygón je okolo hranice
rozšírený. Odkedy sa reže presnou OSM reláciou kraja pretnutou s reláciou štátu
([`workers/plan/boundary.py`](../workers/plan/boundary.py)), pokrýva navigácia
presne ten istý kraj ako mapa, hľadanie a vrstvy z výškového modelu – ani meter
susedného kraja alebo cudziny navyše. Že si job berie práve to PBF
(`ROUTING_PBF: data/region.osm.pbf`, artefakt `pbf` z prípravy) a nie iný
extrakt, stráži [`workers/lint/navigation.py`](../workers/lint/navigation.py).

Na Pages ten graf **nejde** (nie je čo kresliť a rozpočet stránky je 900 MB na
celú mapu), preto sa jeho artefakt volá `navigacia-graf` a nie `site-…`:
`deploy` ho sťahuje až za krokom, ktorý nahráva na Pages. Koľko váži, hovorí
`maps.json` – `maps.navigacia.size`, ako pri každom inom balíku.

### 7b. Graf ŠTÁTU a susedov – vlastný balík

Známka po krajinách má zmysel len vtedy, keď trasa **môže prejsť hranicu**, a
cezhraničná trasa potrebuje sieť, ktorá na hranici nekončí. Tento graf sa preto
stavia z **celých štátnych extraktov** (`workers/routing/pbf.sh`, **nič sa
nereže**) a má vlastný balík na Drive, ten istý vzor ako Wikipédia:

```
<koreň>/navigacia_slovensko_susedia/…
```

…s položkou v `maps.json`, aby sa o ňom bez tokenu dalo dozvedieť, a s
`obsah.json` aj `graf.json` vnútri, ktoré povedia, z akého PBF a s akou verziou
motora je postavený. Verzia motora v ňom **musí** byť: graf a knižnica, ktorá
ho číta, si musia sedieť a nesúlad vyzerá ako pokazená trasa.

**Ktorý z tých dvoch klient má, sa pozná z `graf.json`** (`rozsah`), nie
z veľkosti súboru ani z priečinka.

### 7c. Prázdny graf je VAROVANIE, nie pád behu

Koľko je v grafe ciest, hovorí `graf.json` (`cesty`) a berie sa to z toho, čo
si Valhalla pri stavbe narátala sama – **`routable ways`, teda aj chodník
(`highway=footway`), pešia cesta (`path`), schody a `sidewalk`**, lebo aj po
tých sa trasa vedie (profil `pedestrian`). Nula preto neznamená „nie sú tu
cesty pre autá“, ale že v PBF nie je nič, po čom by sa dalo ísť.

Podľa **veľkosti** grafu to poznať nejde a chvíľu sa to skúšalo: `graph.sh`
mal na `valhalla_tiles.tar` spodnú hranicu 1 MB a zhadzoval na nej správne
postavené grafy malých výrezov (beh 33412856848 – 20 KB tar, v ktorom bolo 29
ciest a 42 hrán). Veľkosť tare hovorí o veľkosti územia, nie o tom, či sa
v ňom dá niekam dôjsť.

Prázdny graf preto **beh nezhadzuje** – malý `area` či štvorec rýchleho testu
ho môžu mať legitímne a zhodiť kvôli nemu celý build mapy by znamenalo zahodiť
aj dlaždice, vrstevnice a trasy, ktoré sú v poriadku. Nezmizne to ale ticho:
v logu je `::warning::` a číslo je v balíku, takže „trasa sa nenašla“ sa
v telefóne dá odlíšiť od pokazenej navigácie. Chýbajúci alebo useknutý súbor
zo štvorice pád behu **je** – to nie je malé územie, ale rozbitý balík.

## 8. Čo z tohto je hotové

| kus | čo robí |
|---|---|
| `workers/data/routing-profiles.json` | čo si používateľ vypýta – režimy, voľby, preklad do oboch motorov, a pri každej nepokrytej voľbe DÔVOD |
| `workers/data/vignettes.json` | kde treba známku a na ktoré triedy ciest |
| `workers/routing/profile.py` | z profilu `costing_options` (Valhalla) alebo `custom_model` (GraphHopper); `--check` je matica pokrytia, `--strict` padne na nepokrytej voľbe |
| `workers/lint/routing.py` | kľúče Valhally proti zoznamu z jej zdrojáku, výrazy GraphHoppera proti jeho zakódovaným hodnotám, každá voľba má pre každý motor odpoveď |

| `workers/data/routing-areas.json` | na aký CELOŠTÁTNY rozsah sa graf stavia |
| `workers/routing/pbf.sh` | štátne extrakty z osm.fr, zliate `osmium merge`; **nič sa nereže** |
| `workers/routing/graph.sh` | graf Valhally v Dockeri pre OBA rozsahy (`AREA` = štát, `REGION_KEY` = kraj), overenie všetkých štyroch súborov, `graf.json` s verziou motora, počtom ciest a s tým, kam trasa smie |
| `.github/workflows/navigation.yml` | „Mapa · Build navigácia“ – celoštátny graf, vlastný balík na Drive, zápis do `maps.json` |
| `.github/workflows/navigation-region.yml` | graf KRAJA z PBF mapy; artefakt `navigacia-graf` ide do `<kraj>-navigacia.zip` aj `.aar`, nie na Pages |
| `workers/lint/navigation.py` | rozsah má vlastný uzol v katalógu, celoštátny PBF sa nereže, graf kraja o svojej hranici hovorí a má vlastný balík vedľa dopravnej siete, `admins.sqlite` sa nestratí, formulár sedí s číselníkom |
| `workers/lint/packaging.py` | čo je v ktorom balíku – čítané z NAOZAJ zabalených ZIPov: graf je celý v `-navigacia.zip` a v základnej mape ani v `-linie.zip` nie je (inak by sa sťahoval dvakrát) |
| `workers/transport/transport.yml` | obmedzenia na ceste v DLAŽDICIACH (výška, šírka, hmotnosť, rýchlosť) – sú to atribúty tej istej siete, balík `cesty`; §1, „Áčko“ |

**A to isté obmedzenie sa dá aj POUŽIŤ, nielen pozrieť.** Profil pozná rozmery
vozidla – `vehicle_height`, `vehicle_weight`, `vehicle_width`,
`vehicle_length` (Valhalla `height`/`weight`/`width`/`length`, GraphHopper
`max_height` a spol.) – takže „mám 3,9 m vysoké auto" znamená trasu, ktorá sa
podjazdu vyhne. Tagy v grafe **vždy boli**: `workers/routing/pbf.sh` berie celé
štátne extrakty a nefiltruje nič, takže chýbalo len to, aby si ich niekto
vypýtal. Jednotka sa prepočítava tu a nie v dlaždici: motor chce číslo, kým
v OSM je hodnota reťazec s jednotkou (`3.8 m`, `12'6"`).

Trasu už teda počítať **je z čoho**: graf existuje, dá sa postaviť a stiahnuť.
Čo v ňom nie je: `multimodal` (autobus a vlak), lebo ten stojí na GTFS; a tri
voľby pre auto plus známka po krajinách, kým nie je hotová záplata z §3.
`graf.json` v balíku o sebe hovorí `multimodal: false`, aby to klient nemusel
hádať.

**Neoverené:** samotná stavba grafu nebežala – v tomto prostredí nie je
dostupný Docker obraz Valhally ani PBF (odchádzajúca sieť je zúžená). Overené je
všetko ostatné: číselníky, zápis do katalógu (skúšaný priamo, vrátane toho, že
dva rozsahy si položku neprepíšu), balenie `publish-map.py --zip-only`
a kontroly. Prvý beh má doplniť namerané časy a veľkosti do
`routing-areas.json` – `graph.sh` ich vypíše.

```bash
python3 workers/lint/navigation.py
python3 workers/routing/profile.py --list
python3 workers/routing/profile.py --check
python3 workers/routing/profile.py --mode=auto --engine=valhalla \
    --set avoid_motorway=ano --set top_speed=110
python3 workers/routing/profile.py --mode=auto --engine=graphhopper \
    --set avoid_primary=ano --vignette SK=2026-09-30 --vignette AT=nie
python3 workers/lint/routing.py
```

## 9. Otvorené otázky

1. **Offline v telefóne, alebo server?** Návrh vyššie predpokladá offline
   (Valhalla) – z toho vyplýva aj záplata. Ak je pre auto v poriadku „so
   signálom", GraphHopper dá celé zadanie bez jediného riadku C++ a bod 3
   odpadá.
2. **Berieme na seba vetvu Valhally?** Bez nej sú tri triedy ciest a známka
   nedostupné offline.
3. **Odkiaľ GTFS na autobusy?**
4. **Pešo** – zadanie ešte len príde. V číselníku sú zatiaľ tri voľby, ktoré
   Valhalla má a na turistickej mape dávajú zmysel hneď (`walking_speed`,
   `use_hills`, `max_hiking_difficulty` = SAC stupnica). Doplnenie je riadok
   v číselníku, nie zmena kódu.
5. **Zobraziť limity v mape** (výška podjazdu, šírka, max. rýchlosť) je
   samostatná vec od smerovania – vlastná schéma prvkov ciest, ako
   `features.yml`. Súvisí, ale nezávisí.

## 10. Prekopanie: dlaždice so značkami namiesto grafu

Zadanie z rikimaps znie: **nesťahovať veľa dát navyše a čo najviac počítať
v telefóne**, a k tomu **navigačné profily**, kde si používateľ zapne alebo
vypne každý typ cesty, zadá rozmery vozidla, známky po krajinách a povolenú
dĺžku prejazdu cez vypnutú cestu.

Tá druhá polovica rozhodne o prvej. Taký profil sa do predpočítaného grafu
zapiecť nedá – a keď cenu ráta telefón, tak sa **vozia značky, nie ceny**,
a to je zároveň tá malá vec.

### Prečo graf padol

| | dnes (Valhalla) | plán |
|---|--:|--:|
| Banskobystrický kraj | 192 MB | jednotky MB |
| celé Slovensko | ~1,5 GB (8 krajov) | ~25 – 30 MB |

Pravá stĺpec je odhad z **nameraného** referenčného bodu: BRouterove `rd5`
(10. 9. 2026, `brouter.de/brouter/segments4/`) nesú `E15_N45` – Slovensko,
Maďarsko, Slovinsko, Chorvátsko, Bosnu, Srbsko, východné Rakúsko, južné Poľsko
a východné Česko – v **124 MB** aj s výškou na uzol a každým chodníkom. Celá
planéta je 5,1 GB. Slovensko je z toho štvorca asi 23 % plochy.

BRouter to dokáže preto, že v súbore má **tagy**, nie cenu: profil sa
vyhodnocuje až pri hľadaní trasy. To je presne to, čo tu treba – a je to aj
odpoveď na §3 tohto dokumentu. Záplata `kHighwayFactor` sa nepíše: vlastná
vetva Valhally pre tri prepínače, ktorú by sme museli prekladať pre iOS
a doťahovať za upstreamom, sa nevyplatí, keď cenu aj tak počíta telefón.
**BRouter sa portovať nedá** (je to Java a port do C neexistuje), takže sa
preberá návrh, nie kód.

### Čo sa stavia

Jeden archív na kraj, `<kraj>-routing.pmtiles`, **PMTiles** – katalóg, fronta
sťahovania, účtovanie miesta aj maska regiónu už ten formát vedia. Dlaždice sú
**z9**, tá istá mriežka ako mapa. Vnútri je vlastné binárne telo (nie MVT: MVT
reže geometriu a zahadzuje topológiu, presne ako hovorí §1) – uzly s **OSM id**,
hrany ako dvojice indexov, sada značiek cez slovník, odbočovacie zákazy.

**Hranica krajov zmizne.** Mriežka je globálna a uzly majú OSM id, takže dva
susedné kraje majú okrajové dlaždice na tých istých z/x/y a telefón si ich
zjednotí. Trasa cez hranicu funguje vo chvíli, keď dobehne druhý kraj: nič sa
nedopočítava a nič nedosťahuje. Slepá ulica z §7a prestáva byť vlastnosťou dát
a celoštátny balík zo §7b prestáva byť dôvod, prečo existuje.

**Zjednotí ich ale po PRVKOCH, nie po dlaždiciach** – a to je oprava tohto
odseku, ktorá vyšla najavo pri stavbe (P2). Prvá verzia počítala s tým, že sú
okrajové dlaždice susedov bajt po bajte zhodné a duplikát sa dá zahodiť. Nie sú
a nemôžu byť: PBF kraja je rezaný jeho hranicou, takže v okrajovej dlaždici má
každý kraj len tú časť siete, ktorá padla do neho – zahodiť jednu z dvoch
takých dlaždíc znamená zahodiť polovicu križovatky. Zjednotenie preto ide cez
OSM id uzlov a dvojicu `(od, do)` na hrane. Skontrolovať sa dá to, čo z toho
naozaj platí: že sa spoločné prvky **nerozídu** (P4).

Rozmery ostávajú **reťazcom**, ako to už `workers/transport/transport.yml`
rozhodol. Parser v pipeline, ktorý z `12'6"` prečíta 12, pošle karavan pod
podjazd a v builde nespadne nič.

### Kroky

| lístok | čo |
|---|---|
| **P1** ✓ | `workers/data/routing-tags.json` – slovník značiek; je to zároveň páka na veľkosť |
| **P2** ✓ | `workers/routing/tiles.py` – archív z `data/region.osm.pbf` na mriežke z9, s OSM id uzlov; `graf` v metadátach archívu s verziou formátu, id slovníka, id poradia a počtom hrán |
| **P3** ✓ | `workers/routing/order.py` – poradie uzlov (nested dissection) nad **celým stavaným územím**, jedno číslo na uzol. Viď §11; rez je zatiaľ inerciálny, nie InertialFlowCutter |
| **P4** ✓ | `workers/lint/routing-tiles.py` – každá značka je v slovníku, spoločné prvky okrajových dlaždíc susedov sa nerozchádzajú, všetky archívy jedného behu majú to isté id poradia, žiadna dlaždica neprekročí rozpočet |
| **P5** | `navigation-region.yml` publikuje nový archív; položka v katalógu pod `maps.navigacia` namiesto Valhally |
| **P6** | balík grafu kraja sa prestane publikovať. `graph.sh` a celoštátny job ostávajú – sú referenčná stavba, proti ktorej sa nový motor krížom kontroluje |
| **P7** | `workers/lint/roadtypes.py` – zoznam typov ciest v appke proti triedam v štýle |

Prvý beh má potvrdiť odhad veľkosti (P2). Kým to nie je namerané, je to odhad
odvodený z cudzieho čísla, nie naše číslo.

**Hotové je P1 – P4**, teda formát a všetko, čo ho stráži; rozpis formátu je
v [`docs/routing-tiles.md`](routing-tiles.md). Chýba P5 – P7: archív sa ešte
nepublikuje, balík grafu Valhally sa ešte neprestal publikovať a zoznam typov
ciest v appke ešte nikto neporovnáva so štýlom. **Neoverené na pravých dátach:**
skúšané je to na vyrobených PBF (mriežka ulíc, jednosmerka, trajekt, zákaz
odbočenia), lebo v tomto prostredí nie je PBF kraja – takže odhad veľkosti
z tabuľky vyššie ostáva odhadom.

## 11. Jedna drahá vec, ktorá patrí sem a nie do telefónu

Motor v telefóne je **CCH** (Customizable Contraction Hierarchies) – rozbor
a namerané čísla sú v pláne v rikimaps, §4. Pre pipeline z toho vyplýva jediná,
ale podstatná povinnosť.

CCH delí prípravu na dve časti a **len jedna z nich závisí od profilu**:

| časť | závisí od | kde beží |
|---|---|---|
| poradie uzlov (nested dissection) | len od **tvaru siete** | **tu, v pipeline** |
| kontrakcia podľa poradia | tvar siete | telefón, raz na zostavu krajov |
| customizácia (dosadenie cien) | profil používateľa | telefón, pri každej úprave profilu |
| hľadanie trasy | – | telefón, 0,31 ms |

Poradie je **nezávislé od profilu aj od cien**, takže ho počítať v telefóne by
bola čistá strata: pre západnú Európu je to 256 s na stroji s viacerými
jadrami, pre Slovensko sekundy. Ide do archívu ako **jedno číslo (rank) na
uzol**, ~2 – 3 bajty s varintom.

Dve veci z toho treba dodržať, inak sa to nedá spojiť:

* **Poradie sa počíta nad celým stavaným územím**, nie po krajoch. Zúženie
  globálneho poradia na podgraf je stále platné poradie preň; poradia počítané
  po krajoch zvlášť sa spojiť nedajú.
* **Každý archív nesie `id poradia`.** Kraj postavený proti inému poradiu sa
  s týmto spojiť nesmie a klient to musí vedieť odmietnuť – nesúlad by sa
  navonok javil ako pokazená trasa, presne ako nesúlad verzie motora
  a grafu pri Valhalle (§7b).

A ešte jedna vec do formátu: **odbočovacie zákazy musia byť v archíve ako
plnohodnotné dáta**, nie ako príloha. CCH beží na hranovo rozvinutom grafe
(hrany sa stanú vrcholmi, odbočky hranami) a ten si telefón odvodí z hrán
a zákazov. Merané (Buchhold a spol., ATMOS 2020): kompaktný model s tabuľkami
odbočiek je pri CCH 34× pomalší na customizácii, 53× na dotazoch – a zaberie
viac miesta než rozvinutý graf, teda presne naopak, než na čo bol vymyslený.

Obe polia – `rank` na uzle aj zákazy – musia byť v archíve **od prvej verzie**.
Doplniť ich neskôr znamená zmenu formátu a znovustiahnutie každého kraja.

## 12. Čo z OSM ide do grafu: len križovatky

Toto je pri OSM **dôležitejšie rozhodnutie než výber algoritmu** a patrí do
`workers/routing/tiles.py` (P2).

Namerané ([Engineering Data Reduction for Nested Dissection](https://arxiv.org/pdf/2004.11315)):

| inštancia | vrcholov | hrán |
|---|--:|--:|
| **OSM Európa, surová** | **174 mil.** | 348 mil. |
| z toho stupňa 2 (geometria) | 143 mil. | – |
| z toho stupňa > 2 (križovatky) | 23 mil. | – |
| DIMACS Európa (čistený graf) | 18 mil. | 42 mil. |

**82 % vrcholov OSM je geometria, nie križovatka** – body, ktoré ohýbajú cestu
a nerozhoduje sa v nich o ničom. Všetky čísla z literatúry (aj tie v §11) sú
merané na tom čistenom grafe s 18 miliónmi vrcholov. Kto pošle do algoritmu
surové OSM, počíta na grafe o rád väčšom, než na akom sa merali – na serveri je
to trápne, v telefóne smrteľné.

Do archívu preto ide **graf križovatiek**:

* `nodes` sú **len uzly stupňa > 2** (a konce ciest),
* tvar cesty je **vnútorná geometria hrany** – body bez id, ktoré nikdy nie sú
  vrcholom grafu; sú tam na kreslenie trasy a na výpočet dĺžky, nie na hľadanie.

Je to zároveň zavedený postup práve pre nested dissection, teda pre prípravu,
ktorú §11 posiela do pipeline: po odstránení simpliciálnych uzlov a uzlov
stupňa 2 ostane z OSM inštancií „menej než 20 % uzlov".

Aj potom si OSM svoju daň vyberie a je vidieť v meraniach: dotazy nad **OSM
Nemeckom** trvajú ~440 µs proti ~300 µs nad DIMACS Európou – **hoci je Nemecko
menší graf**. Za rozdiel môže jemnejšie modelovanie OSM. Zbaviť sa toho úplne
sa nedá; ide o to, aby to nestálo rád.

Vzor na to, ako sa OSM číta, je [`RoutingKit`](https://github.com/RoutingKit/RoutingKit/blob/master/doc/OpenStreetMap.md):
z PBF postaví graf s kontrahovanými geometrickými uzlami, so zákazmi odbočenia
(zakazujúcimi aj prikazujúcimi), s jednosmerkami a s profilmi auto/bicykel/pešo.
Dve jeho obmedzenia si treba prevziať vedome: súradnice geometrických uzlov
zahadzuje (my ich držíme ako geometriu hrany) a počíta s 32-bitovými id (na kraj
či štát to stačí, na planétu nie).
