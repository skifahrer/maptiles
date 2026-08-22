# Navigácia: čo na ňu treba a čo z toho máme

Zadanie (august 2026): navigovať **autom, pešo, bicyklom, autobusom a vlakom**.
Pri aute k tomu voľby *vyhnúť sa diaľniciam / rýchlostným cestám /
spoplatneným cestám / cestám I., II. a III. triedy / lesným cestám a
chodníkom*, **maximálna rýchlosť vozidla** a **diaľničná známka po krajinách**
(mám ju, a dokedy). Viacero smerovacích motorov je vítaných.

Tento súbor je návrh, nie popis hotového stavu. Čo z neho už v repozitári je,
stojí na konci.

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

## 7. Kde graf žije – a prečo NIE po krajoch

Mapa sa publikuje po krajoch a končí na hranici regiónu. **Graf tak deliť nemožno**
a je to priamo dôsledok zadania: známka po krajinách má zmysel len vtedy, keď
trasa môže prejsť hranicu. Navigačný balík preto patrí na **štát a jeho
susedov**, nie na kraj – inak sa v Rakúsku nedá jazdiť, takže sa v ňom nedá ani
vyhnúť tomu, že tam nemám známku.

Druhá vec, ktorú treba pri stavbe grafu overiť: pipeline reže PBF kraja
`osmium extract -s smart`, čo je urobené pre **plochy** (`docs` k
`workers/plan/pbf.sh`). Pre graf je dôležitá referenčná úplnosť **relácií
zákazov odbočenia**; pravdepodobne je pre navigáciu správne siahnuť po
nerezanom štátnom PBF, ktoré pipeline aj tak sťahuje, a nie po výreze kraja.

Balenie je inak ten istý vzor ako Wikipédia – **piaty balík na Drive**, nie na
Pages (graf je desiatky až stovky MB a rozpočet stránky je 900 MB na celú mapu):

```
<koreň>/slovensko/navigacia/slovensko+susedia-navigacia.zip
```

…s položkou v `maps.json`, aby sa o ňom bez tokenu dalo dozvedieť, a s
`obsah.json` vnútri, ktorý povie, z akého PBF a s akou verziou motora je
postavený. Verzia motora v ňom **musí** byť: graf a knižnica, ktorá ho číta, si
musia sedieť a nesúlad vyzerá ako pokazená trasa.

## 8. Čo z tohto je hotové

| kus | čo robí |
|---|---|
| `workers/data/routing-profiles.json` | čo si používateľ vypýta – režimy, voľby, preklad do oboch motorov, a pri každej nepokrytej voľbe DÔVOD |
| `workers/data/vignettes.json` | kde treba známku a na ktoré triedy ciest |
| `workers/routing/profile.py` | z profilu `costing_options` (Valhalla) alebo `custom_model` (GraphHopper); `--check` je matica pokrytia, `--strict` padne na nepokrytej voľbe |
| `workers/lint/routing.py` | kľúče Valhally proti zoznamu z jej zdrojáku, výrazy GraphHoppera proti jeho zakódovaným hodnotám, každá voľba má pre každý motor odpoveď |

| `workers/data/routing-areas.json` | na aký rozsah sa graf stavia (a prečo nie po krajoch) |
| `workers/routing/pbf.sh` | štátne extrakty z osm.fr, zliate `osmium merge`; **nič sa nereže** |
| `workers/routing/graph.sh` | graf Valhally v Dockeri, overenie všetkých štyroch súborov, `graf.json` s verziou motora |
| `.github/workflows/navigation.yml` | „Mapa · Build navigácia“ – graf, balík na Drive, zápis do `maps.json` |
| `workers/lint/navigation.py` | rozsah má vlastný uzol v katalógu, PBF sa nereže, `admins.sqlite` sa nestratí, formulár sedí s číselníkom |
| `workers/roads/*` | obmedzenia na ceste v DLAŽDICIACH (výška, šírka, hmotnosť, rýchlosť) – §1, „Áčko“ |

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
python3 workers/lint/roads.py
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
