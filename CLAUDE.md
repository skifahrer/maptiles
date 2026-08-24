# CLAUDE.md

Pokyny pre Clauda (a poznámky pre ľudí) k tomuto repozitáru.

## Čo to je

Mapová aplikácia: vektorové mapy Slovenska z OSM dát. Jedna pipeline, jeden
formát (PMTiles), spoločné štýly pre web aj mobil. Detailne
[`workers/README.md`](workers/README.md), a čo robí každý krok pipeline –
[`docs/pipeline.md`](docs/pipeline.md), 1700 riadkov. **Prečítaj tú kapitolu,
ktorej sa dotýkaš, skôr než čokoľvek zmeníš.** Väčšina neintuitívnych vecí tam
má napísané, prečo je taká, a k tomu číslo behu, ktorý ju spôsobil.

```
app/ios/            iOS (SwiftUI + MapLibre Native)
backend/            NestJS API (regióny)
poc/web/            web viewer (MapLibre GL JS + PMTiles) + dev mode
workers/            výkonné časti pipeline (Python / bash / mjs)
docs/               návrhy a podrobný popis pipeline
.github/workflows/  CI: výškové modely, build mapy, deploy na Pages
.github/actions/    cache-restore a cache-save (cache leží na Google Drive)
```

### Mapa pipeline

Deväť workflowov, ale nie deväť samostatných vecí – sú to **štyri skupiny**
a v každej patria kusy k sebe. Toto je celý obrázok:

```
   ty ──┐
        │   ┌── Mapa ─── čo z regiónu vypadne von ──────────────────┐
        ├──►│ Build map      PBF → dlaždice → _site + ZIPy          │──► Pages
        ├──►│ Build wiki     objekty s wikipedia/wikidata → články  │──► Drive
        ├──►│ Build navigácia PBF štátov → graf Valhally            │──► Drive
        ├──►│ Build svet     vodstvo, hranice, regióny sťahovania   │──► Drive
        └──►│ úpravy štýlu   style-overrides.json z developer módu  │──► repozitár
            └───────────────────────────────────────────────────────┘
                 │  Build map si dopĺňa, čo mu v sklade chýba
                 ▼
            ┌── Dáta ─── čo do skladu na Drive nateká ──────────────┐
            │ výškové modely  Sonny / ÚGKK DMR 3.5 → dem-sonny…     │
            │ DMR 5.0         Drive cez HTTP Range → dem-ugkk, dem-dmr5
            │ tieňované skaly hillshade z freemap.sk → dem-rocks-img │
            └───────────────────────────────────────────────────────┘

            ┌── Kontrola ─── beží sama pri pushi ──────────────────┐
            │ lint workflowov  actionlint + 34 vlastných kontrol   │
            └──────────────────────────────────────────────────────┘

            ┌── Údržba ─── o infraštruktúru, nie o mapu ───────────┐
            │ týždenné upratovanie  behy, releasy, cache, sklad    │
            │ prihlásenie Drive     refresh token do secretu       │
            └──────────────────────────────────────────────────────┘
```

**Meno workflowu je `Skupina · dve slová`.** Skupina hovorí, do ktorého
z tých štyroch rámčekov patrí, a dve slová stačia na to, aby sa dal odlíšiť –
dlhší popis patrí do hlavičky súboru, nie do zoznamu v Actions. Kým mená
vznikali jedno po druhom, stálo v zozname `Build map (PBF → PMTiles) & deploy
Pages` vedľa `Upratať cache` a `DMR 5.0 z Drive (ETRS89) – toto si volá Build
map`; z toho sa nedalo prečítať, čo je vstup, čo výstup a čo tam nemá čo robiť.

| workflow | meno v Actions | spúšťaš to ty? |
|---|---|---|
| `build-map.yml` | Mapa · Build map | **áno** – toto je tá pipeline |
| `wiki.yml` | Mapa · Build wiki | áno, vedľa mapy toho istého regiónu |
| `world-map.yml` | Mapa · Build svet | áno, ale raz za dlho – svet sa nemení |
| `roads.yml` | Mapa · obmedzenia ciest | nie – volá si ho Build map |
| `navigation.yml` | Mapa · Build navigácia | áno, ale raz za dlho – cestná sieť sa nemení pri štýle |
| `save-style-overrides.yml` | Mapa · úpravy štýlu | áno, po ladení štýlu v developer móde |
| `update-dem.yml` | Dáta · výškové modely | volá si ho Build map (aj ručne) |
| `dmr5-drive.yml` | Dáta · DMR 5.0 | volá si ho Build map, dvoma jobmi |
| `shading-rocks.yml` | Dáta · tieňované skaly | volá si ho Build map pri `rock_source: tienovanie` |
| `lint-workflows.yml` | Kontrola · lint workflowov | beží sám pri pushi |
| `cleanup.yml` | Údržba · týždenné upratovanie | beží sám raz za týždeň |
| `drive-login.yml` | Údržba · prihlásenie Drive | raz, a potom už len keby účet odvolal prístup |

**`Build map` a `Build wiki` sú tie dve slová naschvál.** Tak sa tie dve
pipeline volajú v komentároch aj v hláškach na deviatich desiatkach miest
a nové meno nemá dôvod ich všetky zneplatniť. Prefix pribudol, meno ostalo.

**Zoznam v Actions je zoradený podľa mena**, takže skupiny idú za sebou
(Dáta, Kontrola, Mapa, Údržba) a v každej sú jej kusy pri sebe. Hlavná
pipeline tým pádom nie je prvá – to je cena za to, že skupina je vidieť skôr
než meno, a je zaplatená vedome.

**Meno pipeline je aj v hláškach, takže sa mení na oboch stranách naraz.**
Keď `fetch-dem` povie „spusti workflow X", to X musí byť meno, ktoré je
v Actions naozaj vidieť – inak posiela človeka hľadať niečo, čo tam nie je.

**Jedna otázka, jeden workflow.** Upratovanie bolo dva (`cleanup-actions.yml`
a `cleanup-cache.yml`): dva riadky v zozname, dva plány posunuté o pol hodiny,
aby si nelezli do cesty, a dva formuláre s tým istým `dry_run`. Je z toho
`cleanup.yml` s dvoma jobmi – `github` a `drive` – lebo to, čo ich vie zhodiť,
je rôzne (GitHub API vs. Drive API), ale otázka „upraceš po behoch?" je jedna.

### Ako je usporiadané `workers/`

**Priečinok je job, súbor je krok.** Z cesty má byť vidieť, kto to volá, bez
toho, aby si musel grepovať – `workers/terrain/build.sh` je krok jobu
`terrain`, `workers/plan/pbf.sh` je krok jobu `plan`. Preto sa v mene súboru
už neopakuje to, čo hovorí priečinok (`contours-rocks/build.sh` →
`contours-rocks/build.sh`).

```
workers/data/            číselníky: areas, regions, dem-sources
workers/lib/             čo patrí viacerým jobom (watch, planetiler, png, rozpočet,
                         bunky, orez dlaždíc na región, pečenie do spritu)
workers/plan/            joby `settings`, `plan` a `keys`: čo si vypýtal,
                         voľby, výrez, PBF, kľúče cache
workers/dem/             job `check-dem` a doplnenie modelu (`update-dem.yml`)
workers/drive/           Google Drive: DMR 5.0, sklad, cache, prihlásenie
workers/contours-rocks/  joby `contours` a `rocks` – jeden skript, dve polovice
workers/rocks-shading/   `shading-rocks.yml`: dlaždice → raster → vektor
workers/terrain/         job `terrain` (tieňovanie a 3D)
workers/trails/          job `trails`      workers/features/  job `features`
workers/search/          job `search`: vyhľadávací index (SQLite FTS5) z PBF
workers/roads/           `roads.yml`: obmedzenia na ceste (výška, šírka, rýchlosť)
workers/routing/         navigácia: profil (costing) a graf Valhally
workers/wiki/            `wiki.yml`: články z Wikipédie k objektom mapy
workers/world/           `world-map.yml`: základná mapa sveta (podklad pod výber)
workers/tiles/           job `tiles`       workers/assets/    job `assets`
workers/styles/          štýly pre web aj iOS (deploy + save-style-overrides)
workers/deploy/          job `deploy`: zloženie, kontrola, súhrn, publikovanie
workers/lint/            kontroly, ktoré púšťa `lint-workflows.yml`
workers/tools/           mimo buildu (upratovanie – `cleanup.yml`)
```

Keď skript patrí **dvom jobom**, nemá dve kópie ani dva domovy: `contours`
a `rocks` sú dva joby nad jedným `contours-rocks/build.sh` (polovicu vyberá
`ONLY`), a čo používa viac jobov, ide do `workers/lib/`.

Python moduly sa kvôli pomlčke v mene načítavajú cez `importlib`
(`load("rock_plan", "rock-plan.py")`); v rámci priečinka sa cesta píše holým
menom, mimo neho cez `_WORKERS` / `_DATA` / `_DRIVE`. **Hĺbka je vždy jedna
úroveň** – práve preto, aby `os.path.dirname(_HERE)` znamenalo `workers/`
všade rovnako.

## Jazyk

**Kód, komentáre, mená krokov, hlášky aj commit messages sú po slovensky.**
Identifikátory (premenné, funkcie, mená súborov) sú anglické. Toto je vedomé
a platí to pre celý repozitár – nepíš nové veci po anglicky preto, že je to
zvykom inde.

Hlášky pre používateľa musia povedať aj **čo s tým** („zvoľ 5 m, alebo si
vyber pohorie"), nie len že sa niečo nepodarilo.

## Pravidlá, ktoré tu platia

Sú to pravidlá vypísané krvou – každé z nich vzniklo z konkrétneho spadnutého
behu. Čísla behov sú v komentároch pri kóde.

**1. Jedna otázka, jedna odpoveď, jedno miesto.** Keď si tú istú vec počítajú
dve miesta, raz sa rozídu – a je to tichý druh chyby, lebo obe strany vyzerajú
samy o sebe správne. Preto existuje `workers/dem/target.py` („ktorý sklad
a ktoré súbory"), `workers/plan/area.py` („čo je výrez") a
`workers/plan/options.py` („čo je vo formulári"). Keď potrebuješ odpoveď,
ktorú niekto už pozná, **podaj si ju**, neprepočítavaj.

  - Beh 31307163093: kontrola hľadala výrez v `dem-ugkk`, kým tieňovanie
    sťahovalo dlaždice z `dem-dmr5`. Dve pravdy o jednej veci.
  - To isté, len drahšie: `mirror-dmr5-area` dostával kľúč pohoria a riešil si
    ho z `data/areas.json` druhýkrát, takže rýchly test na 2 km² čítal z Drive
    541 km² Vysokých Tatier. Odvtedy sa podáva **bbox** toho, čo si beh naozaj
    vypýtal, a meno assetu zvlášť.

**2. Meno assetu je sľub o rozsahu.** `N49E020.tif` hovorí „tento celý stupeň
je tu" a `ugkk-vysoke_tatry.tif` „celé Vysoké Tatry sú tu". Keby pod tým menom
ležal len prienik s bboxom, ďalší beh by kontrolou prešiel („je tam") a mapa by
ticho skončila v polovici. Keď rozsah nie je celý, **musí sa zmeniť meno** –
preto má testovací výrez v kľúči príponu `_test4`.

**3. Veľký `run:` blok patrí do `workers/`, nie do YAMLu.** Súbor s workflowom
má strop 128 KiB a **GitHub nad ním workflow ticho neprijme** – po pushi
vznikne beh bez jobov, s červeným krížikom a prázdnym logom, ktorý vyzerá, že
sa spustil sám. `build-map.yml` už cez ten strop raz prešiel; odvtedy je z neho
graf jobov a bash je v `workers/<job>/*.sh`. **Nevracaj ho tam** –
rozpis patrí do `workers/<job>/*.sh`, `workers/<job>/*.py` alebo `docs/pipeline.md`
a v YAMLe ostane odkaz naň. (`Kontrola · lint workflowov` varuje od 120 KiB.)

Pri sťahovaní bloku do skriptu sú dve tiché chyby: `${{ výraz }}` sa zmení na
`$PREMENNÚ` a tá sa zabudne dopísať do `env:` kroku (skript potom beží
s prázdnym reťazcom a **nespadne**), alebo sa premenuje `id` kroku, na ktorý
sa odkazujú výstupy jobu (job ticho vráti prázdno). Stráži to krok *„Skripty vo
workers dostávajú svoje env"*. Blok, ktorý má viac jobov, patrí do JEDNÉHO
súboru – dve kópie sa vždy raz rozídu (`contours-rocks/site.sh` majú joby
`contours` aj `rocks`, `lib/planetiler.sh` päť jobov).

**4. Dlhý krok musí hovoriť, čo robí a ako ďaleko je.** Hodina ticha v logu sa
nedá odlíšiť od zaseknutého behu. Pred drahou časťou vypíš **plán s odhadom**
(trojhodinový job, ktorý spadne na timeout, minie celý rozpočet a nevyrobí nič),
počas nej **postup** – `[7/12] … zostáva ~5 min` – a na konci namerané čísla
oproti odhadu. Odhady rob z merania a to meranie napíš do komentára.

A to isté platí na ZAČIATKU: **s čím beh ide, musí byť vidieť skôr, než sa
začne počítať.** V Build map je na to PRVÝ job – `settings`
(`workers/plan/settings.sh`): vypíše formulár (a označí, čo je iné než
default), `env:` workflowu, teda tie nastavenia, ktoré vo formulári nie sú,
a to, čo z volieb vyšlo. Bol to krok jobu `plan`, čiže schované za dvoma
rozkliknutiami pod jobom, ktorý popri tom sťahuje 380 MB PBF. Nikto naň nemá
`needs:` (pár sekúnd na kritickej ceste štyridsaťminútového buildu by za lepšie
poradie v zozname nestálo), ale keď je vo formulári nezmysel, spadne to tam –
za pár sekúnd, nie o desať jobov neskôr. **Nič v ňom sa nepočíta druhýkrát**:
tabuľky skladá ten istý `plan/options.py`, ktorý o kus ďalej rozoberá voľby
pre zvyšok behu, a hodnoty `env:` sa čítajú z prostredia behu. A hodnota, ktorá
je v YAMLe `secrets.*`, sa nevypisuje – repozitár je public a súhrn behu vidí
ktokoľvek.

**5. Rozdeľuj joby, kroky a súbory.** Strop času platí na job, takže dlhé fázy
majú byť každá vo svojom – a platí to aj bez `timeout-minutes`: tie sme
zrušili (zabíjali prácu, ktorá by bola dobehla, a drahé fázy sa nedajú
prerušiť a nadviazať), ale GitHub dáva jobu najviac **360 minút** a to sa
vypnúť nedá. Prácu stráži sklad (`.part` + premenovanie), strop pamäte
a plán s odhadom, nie budík. V rámci jobu radšej viac malých krokov než jeden
veľký: z mena kroku, ktorý spadol, má byť hneď vidieť, či nesedelo zadanie,
zlyhala sieť, došlo miesto na disku alebo upload.

To isté platí na dĺžku súboru: **`workers/*` majú strop 800 riadkov** a je to
tvrdá chyba. V dlhšom sa nedá naraz prehliadnuť, čo tam je, a ďalšia zmena
pridáva vedľa namiesto toho, aby to použila – teda pravidlo 1 z druhej strany.
Rezať sa má tam, kde sa mení otázka; `rocks-shading/` sa preto delí na
sťahovanie dlaždíc, raster tmavosti a vektorizáciu (tie isté tri fázy ako tri
joby v `shading-rocks.yml`), `drive/auth.py` na „kto sme" a „volanie API"
a `contours-rocks/rock-areas.py` na plán („akú mriežku a ako dlho",
`rock-plan.py` – pýta sa ho aj `contours-rocks/slope-chunks.py`) a samotnú vektorizáciu.

**Pri workflowoch je ten istý strop len varovanie**, a nie je to zľava:
`build-map.yml` je GRAF JOBOV, kde je z 2013 riadkov 598 komentár a 197 vnútro
`run:` blokov – holej YAML štruktúry je 1100 na 17 jobov. Pod 800 sa nedá dostať
presunutím ničoho, len rozrezaním na ďalšie `workflow_call` súbory, a tam sa
zoznam ~20 inputov na job musí napísať dvakrát (v `inputs:` volaného aj v
`with:` volajúceho). Čo workflow naozaj zabije, je **strop 128 KiB** – ten je
chyba a stráži sa v bajtoch.

**6. Drahý medzivýsledok sa ukladá hneď, ako vznikne.** `actions/cache` ukladá
až v post-kroku a len keď job dobehne úspešne – takže sa používa `cache/restore`
hore a `cache/save` s `if: always()` hneď po tom, čo dáta vzniknú. Časti, ktoré
sa počítajú dlho (sklon, bloky z Drive), sa zapisujú cez `.part` a premenovanie,
takže **zrušený beh nezahodí hotovú prácu** a ďalší dopočíta len zvyšok.

**7. Nikdy nesťahuj viac, než treba.** DMR 5.0 má 145 GB a runner ~60 GB
voľných; všetko sa číta cez HTTP Range po blokoch. Keď sa pýtaš na územie,
pýtaj sa presne na to, ktoré beh potrebuje – nie na obdĺžnik z `data/areas.json`,
v ktorom leží.

**8. Tichý omyl je horší než pád.** Keď doplnenie nedoplní, nesmie zazelenať
(`what: dmr5` v `update-dem.yml` je preto chyba). Keď GDAL nemá mriežku geoidu,
nesmie ticho nechať elipsoidické výšky (`ERROR_ON_MISSING_VERT_SHIFT=YES`).
Keď sa použije náhradný model, `dem-source.txt` musí niesť, čo sa NAOZAJ
použilo.

## DMR 5.0: jeden workflow, dva joby

Model je na Google Drive ako dva holé BigTIFFy v jednom priečinku a berie sa
**len odtiaľ**:

| súbor | meno v Actions | volá to Build map? |
|---|---|---|
| `dmr5-drive.yml` | Dáta · DMR 5.0 | **áno**, a to **dvoma jobmi** |

Kedysi k tomu bola záloha z archívu ÚGKK (`dmr5.yml`): ten istý model, ale
198 GB ZIP, v ktorom je raster jedným deflate prúdom – nedá sa v ňom skočiť
dopredu, takže platilo „čítaj raz a sekvenčne" a výrez na juhu Slovenska stál
prechod celým súborom. Na Drive sú súbory holé, Range funguje na ľubovoľnom
offsete a číta sa len to, čo výrez pretína. **Tá záloha je zrušená** – odkedy
Drive púšťa spoľahlivo, neoplácalo sa udržiavať druhú cestu s opačnými
pravidlami.

**Zdroj je PRIEČINOK, nie dve file id.** Vo `workers/drive/dmr5.py` je jediné
číslo (`FOLDER_ID`) a súbory sa v ňom hľadajú podľa mena – presun modelu inam
je zmena jedného čísla namiesto dvoch id na štyroch miestach v hláškach.

**Číta sa prihlásený ako vlastník dát, a inak sa nečíta vôbec.** Čo je
v priečinku, povie len Drive API a to anonymné požiadavky neobsluhuje –
verejný odkaz (denný limit na súbor, zdieľaný so všetkými, kto naň siahnu) už
k DMR 5.0 nevedie. Token vlastníka je v secrete `GDRIVE_CREDENTIALS` (alebo po
kusoch: premenná `DRIVE_CLIENT` a secrety `DRIVE_SECRET`/`DRIVE_REFRESH` –
`client_id` tajný nie je, chodí v každej adrese prihlásenia), drží ho
`workers/drive/auth.py` (`--login` z počítača, `drive-login.yml` z telefónu –
tam sa token nikde nevypíše, lebo log public repozitára vidí ktokoľvek;
`dmr5-drive.py --auth-check` overí). Bez secretu beh spadne hneď a s návodom.

**Rozsah tokenu je `drive`, teda aj zápis** – nie preto, že by pipeline
zapisovala samotný model, ale preto, že na Drive leží aj sklad hotových dát,
cache buildu a hotové mapy (všetko nižšie). Readonly token DMR 5.0 číta ďalej,
len sa pod ním nič neuloží.

**Ten strop visí na VLASTNÍKOVI súboru, nie na tom, kto sťahuje.** Na DMR 5.0
(naše vlastné súbory) prihlásenie strop dvíha; na cudzí priečinok zdieľaný
odkazom – Sonny – nie, a nesmie sa tváriť, že áno (`drive/folder.py` preto
vypíše, koľko súborov účet nevlastní). Aj tam sa ale prihlásiť oplatí: Drive
API povie dôvod odmietnutia rovno, kým verejná cesta vráti HTTP 200 a HTML
stránku. Proti Sonnyho stropu chráni zrkadlo v sklade, nie token.

**Token sa musí dostať na všetky miesta, kde sa z Drive číta** –
`workflow_call` nededí secrets sám:

| kde | čo | ako |
|---|---|---|
| `dmr5-drive.yml` | DMR 5.0 | `secrets: inherit` z `build-map.yml` |
| `update-dem.yml` | Sonnyho priečinok | `secrets: inherit` z `build-map.yml` |
| `shading-rocks.yml` | cache stiahnutých dlaždíc | `secrets: inherit` z `build-map.yml` |
| job `contours` | vrstevnice z `dmr5` | `env:` workflowu |
| job `rocks` | sklon z `dmr5` rovno z Drive | `env:` workflowu |
| každý krok s cache | cache buildu | `env:` workflowu |
| krok `Publikuj mapu na Drive` | hotová mapa ako ZIP | `env:` workflowu |

Odkedy je na Drive aj cache, je tých miest priveľa na to, aby stáli pri každom
jobe – preto je prihlásenie v `env:` celého workflowu.

`Kontrola · lint workflowov` to stráži staticky, z oboch strán, a hlási
aj nekompletnú dvojicu secretov `DRIVE_SECRET`/`DRIVE_REFRESH` (polovica údajov nie je „veď
tam niečo je" – `drive/auth.py` na nej padne). `DRIVE_CLIENT` medzi nimi nie
je: `vars.*` sa v tom istom repozitári čítajú priamo, bez `secrets: inherit`.

**Keď Drive nepustí, DMR 5.0 sa v tom behu nedoplní** – a nesmie to byť tiché:
`drive/serve.py` vráti 502 s vysvetlením, beh spadne v sekundách a so zapnutým
`ugkk_fallback` prejde na hrubší model, čo `dem-source.txt` aj atribúcia
povedia. Prvá vec, čo s tým: prihlásiť sa ako vlastník. Až potom nahrať kópiu
do iného priečinka a prepísať `FOLDER_ID` vo `workers/drive/dmr5.py`.

Tie **dva joby** sú `mirror-dmr5-area` a `mirror-dmr5-tiles` – dve volania
jedného workflowu, lebo DMR 5.0 má dve podoby a chýbať môžu naraz:

```
výrez     ugkk-<kľúč>.tif  → dem-ugkk      plné 1 m   vrstevnice, skaly
dlaždice  N49E020.tif      → dem-dmr5-v2   5 m        tieňovanie (celý región)
```

**Prevzorkúva sa RAZ a kernel vyberá `workers/lib/cell.py`.** Dlaždice sa
čítajú zo 4 m pyramídy a robia sa z nich 5 m bunky – pomer 1,25. Pri tom
pomere `-r average` nepriemeruje: GDAL berie celé zdrojové pixely z okna
`[floor, ceil)`, takže každý štvrtý preskočí, a z toho rytmu spraví hillshade
(derivácia výšky) pravidelnú svetlo-tmavú **mriežku**. Vrstevnice sa trasujú
z toho istého modelu, takže boli zubaté s tým istým rastrom – a nepomohli na
to opravy v `terrain/tiles.py`, lebo tie riešia, ako sa z modelu robia
dlaždice, kým mriežka bola zapečená už v tom modeli. Namerané
(`workers/dem/measure-resampling.py`, mriežka = stredná |Laplacián|
tieňovania ×10⁻³ na hladkom teréne, kolísanie = rozptyl drsnosti na reálnom):

| reťazec | mriežka | kolísanie |
|---|--:|--:|
| referencia (nič sa nepokazilo) | 25,5 | 9,1 % |
| `average`@1,25 + `bilinear`@1:1 | 51,9 | 15,0 % |
| `cubicspline`@1,25 + `cubicspline`@1:1 | 23,6 | 10,4 % |

**Meno skladu nesie podobu, lebo meno súboru nesmie.** `N49E020.tif` je sľub
o rozsahu (pravidlo 2) a ten sa meniť nedá, takže opravu nesie `-v2` v mene
skladu – presne tak, ako ju pri tieňovaní nesie `-v4` v mene assetu. Bez toho
by `check-dem` našiel staré dlaždice, usúdil „model máme" a mapa by ostala
zrnitá pri zelenom builde. Cena je, že si prvý build nad každým regiónom
prečíta DMR 5.0 z Drive znova (~20 min na stupeň); starý `dem-dmr5` na Drive
ostáva, kým ho niekto nezmaže. Stráži to `workers/lint/dem-resampling.py`.

Skaly z `dmr5` si DEM **nedopĺňajú vôbec**: `workers/contours-rocks/slope-chunks.py` číta
z Drive rovno tie časti, ktoré územie pretína, a odkladá si ich do skladu.

## Publikuje sa LEN na Drive – ani release, ani artefakt

Do GitHubu nejde nič, čo má prežiť beh. Osem druhov drahých medzivýsledkov
kedysi ležalo v releasoch (`dem-sonny`, `dem-dmr35`, `dem-dmr5`, `dem-ugkk`,
`dem-terrain`, `dem-rocks`, `dem-rocks-img`, `dem-slope`) a medzivýsledky na
pozretie v artefaktoch s 90-dňovou retenciou. Oboje je teraz v **sklade na
Drive**.

| čo | kde |
|---|---|
| `workers/drive/store.py` | celý formát skladu (`--check`, `--list`, `--names`, `--index`, `--latest`, `--get`, `--put`, `--rm`, `--prune`) |
| `workers/deploy/publish-results.sh` | medzivýsledky na pozretie → sklad `vysledky` |
| `cleanup.yml` | zmaže releasy, ich tagy aj artefakty (týždenne + ručne) |
| `workers/lint/publishing.py` | stráži, že sa `gh release` ani dlhodobý artefakt nevrátia |

```
<koreň>/dem-dmr5/N49E020.tif        <koreň> = fricomaps-sklad v My Drive
<koreň>/dem-ugkk/ugkk-vysoke_tatry.tif        (alebo DRIVE_STORE_FOLDER)
         sklad     meno – to isté, aké mal asset releasu
```

**Mená súborov sa nezmenili** (pravidlo 2: meno je sľub o rozsahu) a ktorý
sklad ktorá vrstva hľadá, hovorí ďalej jediné miesto – `dem/target.py`.

Čo tým odpadlo a čo nie: **2 GB strop na asset** odpadol. **Dve podoby DMR 5.0**
ostávajú – tie nedržal strop releasu, ale runner: jedna 1°×1° dlaždica má
v metri ~48 GB a voľných je ~60 GB.

**Artefakt smie žiť najviac jeden deň.** `site-*` a `steps-*` s
`retention-days: 1` nie sú publikovanie, ale prepravky – tými si joby jedného
behu podávajú kusy `_site` a bez nich sa stránka nedá zlepiť. Čokoľvek s dlhšou
retenciou je uložený výsledok a patrí do skladu `vysledky`;
`Kontrola · lint workflowov` to odmietne. Jediná výnimka je `upload-pages-artifact`, bez ktorého sa Pages
nenasadia.

**„Clobber" je najprv nahrať, potom zmazať staré.** Drive dovolí dva súbory
s tým istým menom vedľa seba, takže „najprv zmaž" by po spadnutom uploade
nenechalo ani nové, ani staré – a ďalší beh by hodinu počítal niečo, čo tam
pred pár minútami bolo. Pri čítaní preto vyhráva NAJNOVŠÍ súbor daného mena.

## Cache je na Drive, nie v GitHube

GitHubová cache má na repozitár **10 GB** a keď sa naplní, **nič nepovie** –
ticho vyhodí najstaršie záznamy. Jeden výrez do nej ukladal desiatky GB (DEM
dlaždice, sklad častí sklonu, vrstevnice, tieňovanie, dlaždice tieňovania),
takže si záznamy vyhadzovali navzájom a hodiny výpočtu sa rátali odznova bez
toho, aby to bolo na čom vidieť – build je zelený, len trvá hodinu namiesto
minút. To je pravidlo 8 v čistej podobe.

| čo | kde |
|---|---|
| `.github/actions/cache-restore` / `cache-save` | náhrada za `actions/cache/*` |
| `workers/drive/cache.py` | celý formát a pravidlá (aj `--check`, `--list`, `--prune`) |
| `cleanup.yml` | zmaže GitHub cache a preriedi tú na Drive (týždenne) |

**Sémantika ostala tá istá ako v GitHube**, nech platí to, čo je pri kľúčoch
napísané: `cache-hit` len pri PRESNEJ zhode kľúča, `restore-keys` sú PREDPONY
a berie sa NAJNOVŠÍ záznam, existujúci kľúč sa NEPREPISUJE (preto majú kľúče,
ktoré sa majú dať dopĺňať, v sebe `github.run_id`). Zhoda sa hľadá podľa
plného kľúča z `description`, nie podľa mena súboru – v mene sú znaky mimo
`[A-Za-z0-9._-]` nahradené podčiarkovníkom a dva rôzne kľúče by mohli vyzerať
rovnako.

Dve veci, ktoré GitHub robil sám a Drive nie: **nič sa nemaže samo** (na to je
`--prune` a týždenný workflow) a **bez prihlásenia to nefunguje** (krok vtedy
spadne s návodom; `Kontrola · lint workflowov` stráži, že token dostane
každý cache krok).
Nový `uses: actions/cache…` tá istá kontrola odmietne.

## Hotová mapa ide na Drive – tri ZIPy so stálym menom

Okrem Pages sa každý build publikuje aj do priečinka na Drive
(`workers/deploy/publish-map.py`, vypína to voľba `publish=false`):

```
<koreň>/slovensko/presovsky/vysoke_tatry/
         krajina  kraj      výsek        (úrovne, čo nedávajú zmysel, sa vynechajú)

    presovsky-vysoke_tatry.zip                    základná mapa, BEZ riadkov nižšie
                                                  (a bez glyfov a viewera – tie sú na Pages)
    presovsky-vysoke_tatry-vrstevnice-skaly.zip   tie dve vrstvy (jeden balík)
    presovsky-vysoke_tatry-tienovanie.zip         výškové dlaždice PNG
    presovsky-vysoke_tatry-wikipedia.zip          články z Wikipédie
```

**Základná mapa neobsahuje vrstevnice, skaly ani tieňovanie.** Sú to ťažké
vrstvy z výškového modelu a majú vlastné balíky presne PRETO, aby si ich
človek nemusel sťahovať, keď ich nechce – keby boli aj v základnej mape, ten
dôvod by neplatil a „iba mapa" by vážila rovnako ako mapa so všetkým. Kto ich
chce, rozbalí príslušný ZIP navrch: cesty vnútri sú tie isté ako v `_site`
(`workers/deploy/pack.py`), takže sa dá rozbaliť jeden cez druhý.

**A neobsahuje ani glyfy a webový viewer – tie sú na Pages.** Fonty boli po
dlaždiciach druhá najväčšia vec v balíku (tri fontstacky Noto Sans po ~34 MB,
celý unicode, z čoho mapa kraja použije zlomok) a `index.html` s `*.js`
z `poc/web` je stránka, ktorú si aplikácia nespúšťa – má vlastnú mapu. Oboje
ostáva v `_site`, teda na Pages, a manifest v balíku nesie ABSOLÚTNU adresu
glyfov (`site.sh` ju skladá z `$BASE`), takže štýl vie, odkiaľ si ich vziať.

**Rozhoduje o tom tvar tej adresy, nie prepínač.** Glyfy sa vynechajú práve
vtedy, keď na ne manifest odkazuje absolútne; mapa sveta má
`fonts/{fontstack}/{range}.pbf`, teda odkaz DO BALÍKA – na Pages nejde a jej
glyfy sú orezané na stovky kB –, takže tej sa nechajú. Keď sa manifest prečítať
nedá, ostanú tiež: „neviem" nesmie znamenať „zahoď", lebo väčší balík je chyba,
ktorú vidno na veľkosti, kým mapa bez písmen vyzerá ako pokazený štýl. Koľko
toho balík takto nenesie, sa vypisuje do logu (pravidlo 4). Stráži to
`workers/lint/packaging.py` – aj to, že viewer z `_site` nezmizne, lebo z balíka
je vynechaný práve preto, že je na Pages.

**Články z Wikipédie sú štvrtý balík a na Pages NEIDÚ.** Job `wiki` vyberie
z regionálneho PBF všetko, čo má tag `wikipedia` alebo `wikidata` (body, čiary
aj plochy), stiahne články a pridá `index.json`, ktorý hovorí, ktorý článok
patrí ktorému OSM objektu. Desiatky MB textu by v `_site` zjedli rozpočet
stránky, takže idú vlastným artefaktom do `deploy` a odtiaľ na Drive.

**Zapína ich switch `wikipedia`** vo formulári – a miesto naň sa muselo uvoľniť:
`workflow_dispatch` dovolí najviac 10 inputov, takže `contour_interval` sa
presťahoval do `options` (5 m z DMR 5.0 je dobrý default, mení sa pri prechode
do nížin; články sa zapínajú a vypínajú pri každom ladení). Jedenásty input
chytí actionlint. **Cache článkov je na Drive** a neplatí ju kalendár, ale
`lastrevid`: keď je z čoho recyklovať, predradí sa dávková otázka `prop=info`
(50 článkov za 19,9 kB proti 197,4 kB s obsahom) a stiahne sa len to, čo sa
zmenilo. Počet požiadaviek to nezníži, bajty a prevod áno – a pri `html`, kde
dávka neexistuje, celé minúty. **Cachovanie je predvolené**, obchádza ho
`rebuild: clanky` – a to je páka na zmenený ZBERAČ (iné podoby odkazu, iný
prevod), lebo vtedy je `lastrevid` ten istý a cache by vrátila články po
starom. Rýchly test články zámerne NEpregenerúva: nezávisia od testovacieho
štvorca ani od prahov, ktoré sa ním ladia. Kľúč článkov sa pri pregenerovaní
nemaže (na rozdiel od vrstevníc a terénu) – má na konci číslo behu, takže nový
záznam vždy vznikne a predpona vyberie najnovší.

**Jeden NDJSON, nie súbor na článok, a dávky po päťdesiatich.** Oboje má
namerané dôvody: ZIP má na každý záznam ~320 B hlavičky a deflate si na každom
súbore začína slovník odznova (153 článkov: 149 kB v súboroch vs 101 kB
v jednom NDJSON), a plný text sa dávkovať DÁ – len nie cez `prop=extracts`
(ten nad `exlimit=1` vráti JEDEN článok a ostatné vyzerajú ako neexistujúce),
ale cez `prop=revisions&rvslots=main`, kde je strop 50 názvov a nad ním hlasná
chyba `toomanyvalues`. Wikitext prevádza `mwparserfromhell`. Namerané: 153
článkov v 4 požiadavkách (18 ms/článok) proti 484 ms/článok po jednom. Rozpis
vo `workers/wiki/collect.py`.

**Meno je STÁLE, nie jedinečné** – rovnaký kraj a výsek má vždy to isté meno,
takže ďalší build starý balík prepíše a v priečinku je jeden aktuálny súbor
namiesto histórie behov. Prepis je „najprv nahraj, potom zmaž starý"
(`folder.upload_clobber`) – to isté pravidlo ako v sklade. Balík vrstvy, ktorú
beh nevyrobil, sa ZMAŽE: starý `-tienovanie.zip` vedľa novej mapy je tichý omyl.

**Čo v tom balíku je, hovorí `obsah.json` v ňom** – nie meno (pravidlo 2 sa
neruší, len sa sľub presunul dovnútra): výrez, zoomy, ktoré vrstvy tam sú a
Z ČOHO sú spočítané podľa toho, čo joby NAOZAJ použili, prah sklonu, bbox,
dátum a číslo behu. Vrstva, ktorá tam nie je, sa píše tiež (`bez_skal`).
Kopíruje sa to z `manifest.json`, ktorý tie fakty už nesie.

**Rýchly test má v mene `test4km2`** – inak by mapa zo 4 km² vyzerala ako celá
a navyše by tú celú prepísala. Publikuje sa len mapa, ktorá prešla kontrolou
pred nasadením; rozbitý ZIP v priečinku vyzerá presne ako dobrý.

**A tie 4 km² sú odteraz CELÝ beh, nie len terén.** Rýchly test (switch `test`)
oreže aj samotné PBF, takže dlaždice, trasy, prvky a ZIP sú z toho štvorca –
`bbox` behu sa rovná `dem_bbox`. Kým sa mapa nechávala celá, bol test polovičný:
kraj sa aj tak stiahol, prehnal Planetilerom, zabalil a nahral, takže sa okolo
štvorca s pár km² terénu viezol celý kraj. Dôvod, prečo to tak bolo – „nech sa
ten štvorec dá pozerať v mape, do ktorej patrí" – nesie obrázok „kde to je"
(`workers/plan/test-map.py`), na ktorý celý kraj netreba. Celý kraj s terénom
len v jednom pohorí sa dá stále postaviť: switch `test` odškrtnúť a `area`
prepnúť na pohorie.

**Ktoré mapy vôbec existujú, hovorí `maps.json` v koreni repozitára** – na Drive
sa to bez tokenu a bez klikania nezistí. **Rýchle testy majú vedľa neho vlastný
`maps-test.json`** s tým istým tvarom: mapa, v ktorej je terén na 4 km², nemá
čo robiť v zozname hotových máp, ale zapísať sa musí (balík `…-test4km2.zip`
leží na Drive a inak sa o ňom bez tokenu nikto nedozvie). Ktorý z tých dvoch
súborov beh zapisuje, hovorí JEDNO miesto – `katalog_subor()` v
`workers/deploy/catalog.py` –, lebo sa naň pýtajú traja (zápis, doplnenie
`.aar` a commit); meno preto chodí do `deploy/catalog.sh` výstupom kroku
(`steps.publish.outputs.maps_file`), nie natvrdo. **A každá položka hovorí,
kedy vznikla, dvakrát**: `updated_at` (ISO 8601 v UTC – na čítanie okom
a zoradenie ako text) a `updated_ts` (sekundy od epochy – vek mapy je jedno
odčítanie). Sú to dva zápisy jedného okamihu, nie dve merania; to isté nesie
každý balík zvlášť a koreň katalógu ako `_updated_at` / `_updated_ts`. Dopisuje ho build hneď po nahratí
(`publish-map.py --maps=`, pozná id súborov) a commitne `deploy/catalog.sh`; je
to JEDINÉ miesto, kde beh zapisuje do repozitára, a preto má job `deploy`
`contents: write`. Štruktúra je tá istá ako cesta na Drive – **hlavný kľúč je
krajina** (rovno v koreni), pod ňou `regions` (kraj) a `subregions` (výsek) a
v každej úrovni `maps` s tromi odkazmi; metadáta katalógu majú v koreni prefix
`_` (`_comment`, `_updated_at`), tak ako `_comment` v `data/areas.json`. Zápis je
„nahraď celú položku" a `subregions` pri tom ostávajú – **a prepis sa týka len
balíkov, o ktorých beh ROZHODUJE** (`spravuje=`, ten istý zoznam ako pri mazaní
starého balíka na Drive): `wikipedia` robí vlastná pipeline, takže „nevyrobil
som ju" neznamená „v mape nie je" a v položke ostane. Kým to tam nebolo, mazal
ju z katalógu každý build mapy, hoci ZIP na Drive ležal ďalej. **Rýchly test sa
zapisuje tiež, ale do VLASTNÉHO SÚBORU a v ňom do vlastného uzla**
(`maps-test.json`, uzol `vysoke_tatry_test4km2` – tá istá prípona, akú nesú
jeho balíky): na Drive leží v priečinku ostrej mapy, takže bez katalógu sa
o ňom bez tokenu nedá dozvedieť, ale medzi hotové mapy nepatrí – terén je
v ňom na pár km² a kto si ho podľa zoznamu stiahne, dostane mapu s dierou.
Vlastný uzol na to nestačil: v `maps.json` stál vedľa ostrých máp a vyzeral
ako ďalší výsek. Že je to test, hovorí kľúč, meno („– rýchly test 4 km²") aj
`test_km2` a `area_bbox` v položke.

**Z kľúča uzla sa NEDÁ odvodiť meno súboru** a položka je preto písaná tak, aby
to nikto nemusel skúšať: uzol je `bratislavsky_test4km2`, balík
`bratislavsky-test4km2.zip` a dlaždice v ňom `tiles/bratislavsky_test4-…`
(prípona `_test4` je z voľby `test_km2`, nie z mena kraja). Tri zápisy,
lebo každý odpovedá na inú otázku. Cesty preto nesie `tiles` v položke –
prepísané z `manifest.json`, ktorý ich pozná, lebo podľa neho číta dlaždice aj
viewer. **A strop zoomu musí byť pri každej vrstve, ktorá ho má vlastný**
(`trails_maxzoom` 14, `features_maxzoom` 15, `terrain_maxzoom`): kto ho
nenájde, dosadí `maxzoom` mapy (16) a nad skutočným stropom pýta neexistujúce
dlaždice – trasy a prvky ticho zmiznú a vyzerá to ako pokazené ťuknutie do
mapy, nie ako chýbajúce dáta. **A každá vrstva z výškového modelu hovorí,
z čoho JE**: `dem_source` sú vrstevnice, `rock_source` skaly a `terrain_source`
tieňovanie – tri polia preto, že sa každá z nich smie prepnúť na náhradný
model sama (pravidlo 8). Na načítanie mapy aj na atribúciu tak stačí
`maps.json`; `obsah.json` v balíku je jeho vlastný podpis pre toho, kto má ZIP
bez katalógu, nie druhé miesto, kam sa treba pozerať. Stráži to
`workers/lint/catalog.py` – vrátane toho, že testovací uzol je v
`maps-test.json` a nie v `maps.json`, a že časové pečiatky sedia navzájom.

Po neúspešnom nahratí sa nezapíše nič –
zoznam, ktorý ukazuje na neexistujúce súbory, je horší než žiadny. Čo sa do
katalógu píše, skladá `workers/deploy/catalog.py` (`publish-map.py` prerástol
strop 800 riadkov); stráži to `workers/lint/catalog.py`.

## Mapa končí na hranici regiónu, nie na obdĺžniku jeho bboxu

Používateľ si v aplikácii stiahne REGIÓN a potom ho prezerá offline. Dovtedy
mapa siahala ďaleko za jeho hranicu: dlaždice sa robia na OBDĹŽNIKU bboxu
(Prešovský kraj má bbox 199 × 82 km, takmer dvojnásobok svojej plochy)
a Planetiler do nich okrem OSM dát kreslí aj vodstvo, pobrežia a Natural Earth,
ktoré sú celosvetové. Za hranicou teda ostalo podfarbené prázdno bez ciest
a sídel – čo vyzerá ako mapa, ktorá sa nedonačítala, nie ako koniec mapy.

Sú na to **tri kusy a všetky treba**:

| kus | čo robí | kde |
|---|---|---|
| dlaždice sa mimo regiónu nevyrobia | `--polygon` Planetileru v jobe `tiles`, `trails` a `features` | `workers/lib/region-clip.sh` |
| tieňovanie má mimo regiónu rovinu | pixely mimo kraja dostanú výšku 0, takže hillshade z nich nekreslí nič | `workers/lib/region-mask.py` (`pixel_mask`) → `workers/terrain/tiles.py` |
| presnú hranicu dokreslí štýl | plocha `mimo` (farba podkladu) a obrys `hranica` úplne navrchu | `workers/deploy/region-mask.py` → `_site/region.geojson` |

**Tieňovanie je tretí kus, lebo dlaždica je nedeliteľná.** Ktorá sa kraja
dotkne, vyrobí sa celá – a na nízkych zoomoch je obrovská, takže tieňovaný
reliéf pokračoval ďaleko za hranicu stiahnutého regiónu: namerané na Prešovskom
kraji **z10 2,2× jeho plochy, z8 6,2×**. Bola to tichá chyba – v mape to
zakrývala plocha `mimo` zo štýlu, takže to bolo vidieť, len keď sa nekreslila
(alebo v 3D pod iným uhlom). Odpoveď je jemnejšia otázka („ktoré PIXELY ležia
v kraji?") a rovina mimo nich; hillshade kreslí krytím podľa sklonu, takže
z roviny nenakreslí nič. Stena medzi terénom a rovinou pritom **nesmie stáť
presne na hranici** – bol by z nej prstenec po jej vnútornej strane, teda
v mape –, tak je posunutá o `--edge` (2 px) za ňu. Stráži to
`workers/lint/terrain.py`.

**PBF kraja sa REŽE Z RODIČA (`osmfr.parent`), hotový export kraja sa
nepoužíva.** osm.fr má pre každý kraj vlastný `{kraj}-latest.osm.pbf` (36 MB)
rezaný po jeho administratívnej hranici a chvíľu sa sťahoval priamo – bolo to
o krok kratšie a o 337 MB lacnejšie. Lenže **ten súbor nie je referenčne
úplný**: viacpolygónovej ploche, ktorá pokračuje do susedného kraja, v ňom
chýbajú členské cesty, a Planetiler taký objekt **zahodí CELÝ** – aj tú
polovicu, čo v kraji leží. Preto sa sťahuje `slovakia-latest.osm.pbf` (373 MB)
a kraj sa z neho reže `osmium extract -s smart -S types=multipolygon,boundary
--polygon` na jeho `.poly` (`workers/plan/pbf.sh`, ~30 s).

**Nie je to kozmetika na hranici a raz sme sa na tom pomýlili.** Prvé meranie
počítalo objekty (97 čiar, 66 plôch, 19 viacpolygónových plôch, dokopy 0,7 %
prvkov v dlaždiciach) a uzavrelo to „sú to objekty na hranici, tie maska aj tak
schová". Lenže objekt sa nezmenší, zmizne CELÝ – a tie veľké sú vidieť najviac.
Namerané na `bratislavsky-latest.osm.pbf`: z 3075 plošných relácií malo 250
chýbajúceho člena, z toho 49 krajinnej pokrývky a ochrany prírody. Chýbala
**CHKO Malé Karpaty, CHKO Záhorie, CHKO Dunajské luhy, NPR Aluvium Moravy**,
les Záhoria (relácia s 1011 členmi) aj Zdrž Hrušov – teda plochy z vnútra
kraja, ktoré maska neschová, lebo ich niet. Po reze z rodiča ostane z tých 49
päť a všetky sú na rakúskej hranici pozdĺž Dunaja a Moravy (ich členovia nie sú
ani v slovenskom extrakte, doplnil by ich až extrakt Európy).

**`-S types=multipolygon,boundary` nie je ozdoba.** Predvolene `smart` dopĺňa
členov len reláciám `type=multipolygon`, kým CHKO je `type=boundary` – bez toho
prepínača ostali všetky tri CHKO rozbité aj po reze z rodiča (9 zvyšných plôch
namiesto 5). Platí to pri KAŽDOM reze v `pbf.sh`, aj pri `crop_bbox` a pri
štvorci rýchleho testu; zo 4 km² vytŕča skoro každá plocha, takže sa tam ten
prepínač prejaví najskôr.

Koľko plôch beh naozaj stratil, počíta `workers/plan/pbf-areas.py` (dve volania
`osmium`, ~1 s) a píše to do logu aj do súhrnu behu – inak by sa tento druh
chyby zase neohlásil. Statickú stranu stráži `workers/lint/pbf-source.py`:
rodiča v číselníku, oba prepínače rezu a to, že sa pri chýbajúcom `.poly`
**spadne** namiesto návratu k priamemu sťahovaniu (na tom padla prvá verzia
tohto kroku – beh bol zelený a CHKO zase chýbali).

**Orez je DOČASNE VYPNUTÝ** (`region_clip=false` vo voľbách). Merané na
Bratislavskom kraji (maxzoom 14, kraj je 57 % svojho bboxu): `--polygon` dá
1271 dlaždíc a 19 330 130 B, `--bounds` 1607 dlaždíc a 19 467 060 B – teda
**+26 % dlaždíc za +0,7 % bajtov** a rovnaký čas. Vidieť to nie je, lebo maska
je „celý svet mínus región" a všetko za hranicou prekryje. Nie je to ale nič:
v tých 336 dlaždiciach navyše bolo na z12 228 popisov sídel, 55 chránených
území, 19 hraníc, cesty aj vodstvo – vrátane rakúskych a maďarských mien.
**Rezaný PBF to nerieši**: vodstvo, pobrežia a Natural Earth kreslí Planetiler
zo svojich celosvetových podkladov, ktoré v našom PBF nie sú vôbec, takže orez
a rez PBF sú dve rôzne veci. Kým je vypínač v `false`, hlási to `::warning::`
v každom behu (pravidlo 8); späť sa zapína `region_clip=true`.

`--polygon` je HRUBÝ OREZ – Planetiler vynechá celé dlaždice, ktoré sa tvaru
nedotknú, takže na z14 môže presahovať ešte zhruba kilometer a pol. Presne
preto je aj ten druhý kus; a preto je maska v štýle **posledná vrstva**
(prekrýva aj popisky a tieňovanie). Vrstva pridaná za ňu by mimo regiónu opäť
kreslila a nikto by to nepovedal – stráži to `workers/lint/style.mjs`.

**`--bounds` a `--polygon` sa Planetileru NEDÁVAJÚ naraz** – druhý sa tým ticho
vypne. `Bounds` si to, čo o dlaždici rozhoduje, spočíta už v konštruktore
(teda z `--bounds` a s prázdnym tvarom) a `setShape()` prepočet nespustí; tvar
je v logu vidieť a neoreže nič. Namerané na Monaku (maxzoom 15): bez orezu 27
dlaždíc, `--polygon` na polovicu územia 17, `--polygon` **aj** `--bounds` zase
27. Preto sa `--bounds` dáva len vtedy, keď polygón nie je.

**Hranica je jedna a je to tá istá, ktorou je orezaný PBF**: `.poly` z osm.fr,
ktorý sťahuje `workers/plan/region-poly.py` (a z ktorého žije `-cutline`
vrstevníc aj maska tieňovania). Druhá definícia hranice by sa raz rozišla
s prvou a mapa by vyzerala celá – len by jej kúsok chýbal alebo prebýval.

**Do statických štýlov sa vkladá PRIAMO, nie ako URL.** Tie štýly číta
aplikácia, ktorá si mapu stiahne a otvorí offline – a všetko ostatné si pri tom
prepisuje z adresy Pages na svoje súbory. Odkaz, na ktorý by sa v tom prepise
zabudlo, by nespadol: maska by sa len nenačítala a mapa by zase presahovala.
Dáta majú jednotky kB (Prešovský kraj 8,9 kB), takže sa kópia v štýle zaplatí.
Viewer na webe si ich načíta z `region.geojson` za behu; že tam ten súbor je,
overuje `deploy/check.sh` aj smoke test.

## Štýl: hodnota podľa zoomu má dva tvary

Skoro všetko v štýle (hrúbka čiary, farba, krytie, sila tieňovania) závisí od
zoomu – a sú na to **dve otázky, nie jedna**:

| tvar | otázka | v úprave | v štýle |
|---|---|---|---|
| **krivka** | ako hodnota RASTIE | `[[9, 2], [16, 6]]` | `interpolate` |
| **pásma** | čo PLATÍ v tomto rozsahu | `[[9, 11, 2], [12, 12, 4], [13, 17, 6]]` | `step` |

Dvojica je bod krivky, trojica je pásmo; **miešať sa nesmú** a rozlišuje sa
POČTOM PRVKOV V RIADKU, nie obalom navyše – v JSON súbore úprav je tak vidieť
bez legendy, čo je čo. Pásmo `[od, do, hodnota]` platí pre zoomy
`od ≤ z < do + 1` (teda `do` VRÁTANE aj s desatinami), zadáva sa v celých
zoomoch a pásma musia ísť **za sebou bez medzier a bez prekryvov**. Pod prvým
`od` a nad posledným `do` platí krajné pásmo – rovnako, ako `interpolate` drží
svoje krajné hodnoty.

**Prečo pásma pribudli.** Kým bola len krivka, „od z9 do z11 takáto čiara, na
z12 takáto, od z13 do z17 takáto" sa muselo napísať šiestimi zlomami – tú istú
hodnotu dvakrát, na oboch hranicách každého pásma –, inak sa medzi nimi
plynule menila. Pri strope `MAX_PAINT_STOPS` (8) sa do toho zmestili štyri
pásma a piate už nie.

**Medzera a prekryv sú TVRDÁ chyba** (`cleanPaintBands`), a to z toho istého
dôvodu ako pravidlo 2: „do 11" je sľub, kde pásmo končí. Keby sa medzera
dopĺňala držaním predošlej hodnoty, `do 11` by neplatilo a nikto by to nemal
ako spozorovať. Z developer módu sa medzera vyrobiť nedá ani omylom: pásmo tam
vzniká ROZDELENÍM toho, v ktorom mapa práve stojí, a `do` sa dopočítava
z `od` nasledujúceho (editovateľné je len `od`, a `do` toho posledného).

**Pásma sú `step`, nie `interpolate` s dvoma zlomami na pásmo.** Susedné pásma
`[9,11]` a `[12,12]` by potrebovali zlomy 9, 11, 12, 12 a dva zlomy na tom
istom zoome MapLibre odmietne aj s celým štýlom. A `["zoom"]` smie byť podľa
style-spec iba priamym vstupom najvrchnejšieho výrazu, takže sa krivka DO
pásma vnoriť nedá ani obchádzkou – kto chce plynulý prechod, píše krivku.

| kde | čo |
|---|---|
| `poc/web/themes.js` | `zs()`, `paintValue`, `cleanPaintZoom` / `cleanPaintBands` |
| `poc/web/layer-style.js` | `valueAtZoom` a odfotenie `step` vrstvy späť na pásma |
| `poc/web/devmode.js` | prepínač krivka ⇄ pásma (prepnutie nezahodí, čo je nastavené) |
| `workers/lint/overrides.mjs` | medzera, prekryv, zmiešaný tvar, hranica pásma |

**Krivka aj pásma platia aj na `layout`, nie len na `paint`.** MapLibre má dve
police a veľkosť ikony ani rozostup symbolov po čiare v `paint` nie sú – práve
tie dve pritom rozhodujú, ako husto sedia turistické značky po trase a aké sú
veľké. Prepísať sa dá VYMENOVANÝ zoznam (`LAYOUT_PROPS` v `themes.js`:
`icon-size`, `symbol-spacing`, `icon-padding`, `text-size`); `symbol-placement`
alebo `icon-rotation-alignment` sú rozhodnutia štýlu, nie ladenie.

**A `layout` sa nasadzuje LEN na symbolovú vrstvu.** Neznáma vlastnosť
v `layout` je pre MapLibre tvrdá chyba – neodmietne vrstvu, ale CELÝ štýl,
takže by sa mapa nenačítala vôbec (v `paint` neznáme len ignoruje). Stráži to
`workers/lint/icons.mjs`.

### Poradie kreslenia sa dá zmeniť bez commitu

MapLibre kreslí vrstvy tak, ako idú v štýle za sebou – **navrchu je tá
posledná**. Čo je nad čím, je teda rozhodnutie štýlu, lenže vidieť ho je až
v mape (násyp nad cestou, plot cez chodník), a kým sa to dalo zmeniť len
v zdrojáku, znamenala každá taká otázka commit a build. V developer móde je
teraz pri každej vrstve **Poradie kreslenia**: „vyššie / nižšie / navrch"
a výber „kresliť tesne pod <vrstvu>“.

**Celý stoh je v záložke „Poradie".** Zoznam v záložke „Vrstvy" je zoradený
PO SKUPINÁCH (cesty, vodstvo, popisky), lebo tam sa hľadá „kde sa nastaví
hrúbka chodníka" – a v takom zozname sa na „čo je nad čím" odpovedať nedá:
násyp a cesta sú v ňom na dvoch rôznych miestach. „Poradie" je preto jeden
dlhý zoznam v poradí kreslenia, **prvý riadok navrchu**, s ťahaním (`⠿`) aj
šípkami. Kým je v ňom zadané hľadanie, ťahanie sa vypína – v prefiltrovanom
zozname nie je vidieť, medzi ktoré dve vrstvy by vrstva padla.

**Ukladá sa ZOZNAM PRESUNOV, nie celé poradie** (`overrides.order`, položka
`{"id": "feature-embankment", "before": "road-minor"}`). Uložiť všetkých ~250
id by znamenalo, že sa úpravy rozsypú pri prvej vrstve, ktorá v štýle pribudne
alebo zmizne (iná téma, iný typ mapy, chýbajúci `featuresUrl`) – a rozsypú sa
TICHO. Presun je oproti tomu odpoveď na jednu otázku, dá sa prečítať a vrstvu,
ktorú ten štýl nepozná, jednoducho preskočí. **Jeden presun na vrstvu**
a vyhráva posledný: presuny sa vyhodnocujú v rade za sebou, takže by ich pri
klikaní pribúdali stovky a nedalo by sa z nich prečítať, kde vrstva skončí.

**Presúva sa celá rodina.** Niektoré prvky sú v štýle DVE vrstvy, lebo inak sa
povedať nedajú: hrana so zúbkami (druhá čiara odsunutá nabok) a železnica
(tmavá čiara a na nej svetlé čiarkovanie), k tomu vzor a okraj z developer
módu. Farbu a hrúbku majú vlastnú – to sú naozaj dve otázky –, ale poradie je
pri nich jedna, inak by ostali zúbky nad cestou a hrana pod ňou. Drží to
`frico:with` v metadátach (`frico:derived` pri vzore a okraji).

**Maska regiónu ostáva posledná, nech sa presúva čokoľvek.** Vrstva za ňou by
kreslila aj mimo stiahnutého regiónu – presne tá tichá chyba, kvôli ktorej
maska existuje. Panel ju preto neponúka presúvať a `applyLayerOrder` ju na
koniec vráti aj tak.

A ešte jedna tichá vec, ktorú tá záložka priniesla: **zoznam záložiek
(`TABS`) a prepínač v `renderBody` sú dve miesta**. Keď v prepínači niektorá
chýba, nespadne nič – ťuknutie prepadne do poslednej vetvy a otvorí sa
„Súbor" s JSON-om, čo vyzerá ako pokazený panel. Stráži to
`workers/lint/overrides.mjs`.

Stráži to `workers/lint/overrides.mjs`: presun nesmie zmeniť počet vrstiev
(stratená vrstva v mape nie je a štýl je pritom platný), musí vziať so sebou
druhú polovicu dvojice a maska musí ostať navrchu.

**Poradie je spoločné pre všetky typy máp**, aj keď sa práve zapisuje do
priečinka jednej mapy: čo je nad čím, je stavba mapy, nie jej téma – a keby si
každá mapa niesla vlastné, ten istý presun by sa musel naklikať štyrikrát.

### Prerušovanie čiary: „zo štýlu“ je odpoveď, „Plná“ je úprava

Výber „Čiara“ v developer móde si predvoľbu čítal z ÚPRAVY, a tá je prázdna,
kým sa niečo nezmení – takže pri **železnici ukazoval „Plná“**, hoci je
čiarkovaná (`rail-hatch` má `line-dasharray` zabudované v štýle). A „Plná“ sa
pri ukladaní zahadzovala ako „veď to je predvolené“, takže sa čiarkovanie
železnice nedalo ani vrátiť, ani vypnúť: panel voľbu prijal a v mape sa
nestalo nič. Tichý omyl v čistej podobe.

Držia to tri kusy a treba všetky tri:

| kus | čo robí | kde |
|---|---|---|
| `frico:dash` v metadátach | čo má vrstva zo štýlu (predvoľba, alebo rovno pole čísel) | `add()` v `themes.js` |
| položka „— zo štýlu (…) —“ | prvá vo výbere = „nechaj, ako to bolo“ | `dashField` v `devmode.js` |
| „Plná“ ako plnohodnotná úprava | `normalizeOverrides` ju nezahodí a `applyLayerOverrides` vlastnosť ZMAŽE | `themes.js` |

**Prečo metadáta a nie `paint`.** Panel dostáva štýl, na ktorom už úpravy
sedia – v `paint` je teda to, čo platí TERAZ, nie to, na čo sa dá vrátiť.
**A prečo aj holé pole čísel:** brod má `[1, 1]`, zúbky brala `[0.35, 2.2]` –
prerušovanie, ktoré medzi predvoľbami vôbec nie je, a pomenovať ho niektorou
z nich by ho pri prvom uložení prepísalo na inú čiaru.

**„Plná“ znamená vlastnosť ZMAZAŤ**, nie nastaviť na `null` – `dashArray("solid")`
je práve `null` a taký štýl by MapLibre neprijal. Stráži to
`workers/lint/overrides.mjs` (metadáta každej čiary s prerušovaním, prežitie
„solid“ cez normalizáciu aj to, že v hotovom štýle po nej `line-dasharray`
naozaj nie je).

### Trasy sa v developer móde ladia po vrstvách

Jeden druh značenej trasy je v štýle ŠTYRI vrstvy a každá odpovedá na inú
otázku: pásik „ako hrubo", značka „ako veľká a ako často", ikonka druhu „kde
značka nie je", názov „aké veľké písmo". V záložke „Trasy" sú preto pod každým
druhom rozkliknuteľné všetky štyri – s rozsahom zoomu a s tými istými krivkami
a pásmami, aké má záložka Vrstiev:

```
Turistické trasy (značené)          ▾
  Pásik        trail-hiking         od z8  do z–   hrúbka · krytie
  Značka       trail-hiking-mark    od z12 do z–   veľkosť · rozostup · padding
  Ikona druhu  trail-hiking-icon    od z13 do z–   veľkosť · rozostup · krytie
  Názov trasy  trail-hiking-label   od z12 do z–   veľkosť písma · rozostup
```

Nie je to druhá páka na tú istú vec: zapisuje sa do `overrides.layers[<id>]`,
teda presne tam, kam píše záložka Vrstiev. Rozdiel je len v tom, že je tu
pokope to, čo patrí k jednej trase – v zozname vrstiev sú tie štyri na štyroch
rôznych miestach a bez farby a značky vedľa nich sa nedá povedať, ktorá je
ktorá.

### Vzor: vidieť ho ako obrázok, aj nad čím leží – a dá sa nahrať vlastný

Vzor sa vyberal z rozbaľovačky s menami („Šrafovanie /", „Šupiny (skaly)")
a to je horšie než pri ikone: meno nepovie ani ako je hustý, ani ako je hrubý,
ani ako vyzerá nad farbou, ktorú tá plocha má. Teraz je z toho **mriežka
s náhľadmi**, kreslená tým istým rasterizérom (`renderPattern`), aký vyrobí
obrázok pre mapu aj pre sprite.

**Náhľad sa kreslí NAD FARBOU PODKLADU** a tá je hneď vedľa neho na zmenu
(vrátane „bez výplne"). Vzor je totiž vždy DRUHÁ vrstva nad plochou
(`fill-pattern` sa nedá kresliť do tej istej vrstvy ako výplň), takže sám
o sebe nehovorí nič – to isté šrafovanie vyzerá inak nad tmavozeleným lesom
a inak nad svetlou lúkou.

**Vlastný obrázok ako vzor je uložený ako VLASTNÁ IKONA** (`own:…`, PNG
v `data:` adrese) – a to nie je obchádzka, ale celá pointa: taký obrázok sa
nesie priamo v úpravách (funguje offline aj v balíku pre mobil), prehliadač ho
dokreslí cez `styleimagemissing` a do každého spritu ho dopečie
`workers/assets/custom-icons.mjs`. Druhá pečiaca cesta pre „obrázky, ktoré sú
vzory" by bola druhé miesto, ktoré sa raz rozíde s prvým. Preto sa aj
**kontroluje, že to meno je naozaj medzi vlastnými ikonami úprav**: hocijaké
iné by sa do štýlu dostalo, do spritu nie, a MapLibre neznámy `fill-pattern`
ticho preskočí.

**Veľkosť dlaždice sa vyberá pri nahratí** a obrázok sa na ňu rovno
prevzorkuje. `fill-pattern` sa v MapLibre neškáluje – dlaždicuje sa tak, ako
je obrázok veľký –, takže „veľkosť až pri kreslení" by musel rovnako spraviť
aj sprite; čo je uložené, je to, čo mapa kreslí. Farba, veľkosť a hrúbka
zostávajú len pri KRESLENOM vzore: obrázok ich má v sebe, takže by to pri ňom
boli tri políčka, ktoré nič nerobia.

| kde | čo |
|---|---|
| `poc/web/dev-patterns.js` | náhľad nad podkladom, mriežka vzorov |
| `poc/web/patterns.js` | `patternSpec`/`patternImageName` – obrázok je iný druh odpovede, nie ďalšie pole |
| `workers/lint/icons.mjs` | obrázok vzoru musí byť medzi vlastnými ikonami a nesmie sa dostať medzi kreslené vzory (rasterizér by ho v atlase prepísal) |

### Ikona kategórie: vidieť tú terajšiu a vymeniť ju

Záložka „POI" vedela kategórie len skrývať – aká ikona je pri ktorej, sa
z nej nedalo zistiť ani zmeniť. Teraz je pri každom riadku **náhľad tej
ikony, ktorá je naozaj v mape**, a po rozkliknutí mriežka na výber
(`overrides.poi.icons[<kategória>]`).

**Tri odpovede, nie dve** – tá istá úvaha ako pri značke druhu trasy:
chýbajúci kľúč je „ikona podľa sady", prázdny reťazec je „žiadna" (ostane len
popisok) a meno je „táto". Preto sa rozhoduje podľa toho, či kľúč EXISTUJE,
nie podľa toho, či je hodnota pravdivá.

**Ktorá ikona kategórii patrí, hovorí `poiIconName`** – jedna funkcia pre štýl
(čo nakresliť) aj pre panel (čo ukázať). Kým to boli dva výpočty, ukazoval by
panel raz niečo iné, než je v mape; `iconClassesOf` je z toho istého dôvodu
funkcia, a nie riadok v `buildStyle`.

**Ikona je nasadená ako HOLÉ MENO obrázka** (`case` nad `class`/`subclass`),
nie `concat` z dát – a meno, ktoré sprite nemá, MapLibre ticho preskočí, takže
prejde len to, čo `hasIcon` pozná (vlastná ikona sa pritom za dostupnú pokladá
aj pred dopečením). Zoznam kategórií aj samotný výber platia rovnako pre POI
z OpenMapTiles aj pre **vlastné body** (prameň, jaskyňa, rozhľadňa) – je to tá
istá otázka a jeden zoznam, takže od tejto zmeny na `feature-point` platia aj
skryté kategórie. Ikony sú spoločné pre všetky typy máp (skrývanie ostáva
podľa rozsahu). Stráži to `workers/lint/icons.mjs`.

### Ikony: vidieť, čo si vyberám – a vlastné obrázky

Výber ikony bol `select` s menami (`aeroway_11`, `alcohol_shop_11`, …), z
ktorých sa nedalo prečítať, ako ikona vyzerá; vybrať tú správnu znamenalo
skúšať jednu po druhej a pozerať sa do mapy. Teraz je to **mriežka s náhľadmi**
(`poc/web/dev-icons.js`) – kreslí sa z toho istého spritu, aký má mapa, takže
je to presne to, čo v nej bude. SDF sa pri tom musí prekresliť: vzdialenostné
pole v alfe vyzerá bez prahovania ako rozmazaná škvrna.

**Tá istá ikona je v sade dvakrát** (`aerialway` aj `aerialway_11`) a v mriežke
by boli dve dlaždice, ktoré vyzerajú rovnako. Štýl používa tú s príponou, takže
tá bez nej sa zo zoznamu vynecháva.

**Vlastná ikona je obrázok, ktorý si človek nahrá** (PNG, JPG aj SVG). Prevedie
sa v prehliadači na PNG a uloží sa PRIAMO do úprav ako `data:` adresa – nie ako
odkaz na cudzí server. Má to tri dôvody a všetky tri sú o tom istom: obrázok
musí byť tam, kde je mapa.

  * offline mapa a balík pre mobil odkaz na cudzí server nemajú kde načítať,
  * pipeline ho vie dopiecť do spritu bez toho, aby musela rasterizovať SVG
    (`workers/assets/custom-icons.mjs` len dekóduje PNG),
  * a čo je v mape vidieť, je presne to, čo sa uložilo.

V prehliadači sa ikona nakreslí HNEĎ (`styleimagemissing` v `poc/web/app.js`,
to isté miesto, kde sa dokresľujú vzory), do spritu ju dopečie build. Preto
`hasIcon` v štýle pokladá vlastnú ikonu za dostupnú aj vtedy, keď v sprite ešte
nie je – inak by sa dala vybrať, ale mapa by ju ticho nenakreslila.

**Vlastná sada ikoniek** je adresa spritu bez prípony
(`overrides.iconSets`, id s predponou `own-`). Pipeline ju sťahuje a prerába na
SDF rovnako ako tie tri overené v `icon-sources.js` a `deploy/site.sh` ju dá do
manifestu, takže ju viewer ponúkne v prepínači. Kým ju build nespracuje, načíta
sa v prehliadači priamo z jej adresy – vtedy je to cudzí sprite, takže ikony
majú svoje pôvodné farby a nedajú sa prefarbiť.

| kde | čo |
|---|---|
| `poc/web/dev-icons.js` | mriežka s náhľadmi, prevod nahraného súboru na PNG |
| `poc/web/dom.js` | `el()` – zdieľa ho panel aj výber ikoniek |
| `workers/assets/custom-icons.mjs` | dopečie vlastné ikony do každého spritu |
| `workers/assets/icons.sh` | sťahuje aj vlastné sady (`allIconSources`) |
| `workers/lint/icons.mjs` | tiché veci: nedopečená ikona, nesťahovaná sada, `layout` na čiare |

### Tieňovanie reliéfu: sila RASTIE so zoomom

Krivka `hillshade-exaggeration` roky klesala (`0,5 → 0,25`), takže presne tam,
kde má výškový model najviac detailu (DMR 5.0 má mriežku 5 m a dlaždice idú do
z15), bolo tieňovanie najslabšie – terénne nerovnosti, kvôli ktorým sa človek
približuje, pri priblížení mizli. Teraz je to obrátene (`0,55 → 0,95`).

`hillshade-exaggeration` je odteraz **bežná vlastnosť úprav** – jediná mimo
trojice farba/krytie/hrúbka. Menuje sa celá, nie príponou: `hillshade` je
jediný druh vrstvy, ktorý ju má, a `line-exaggeration` z preklepu by MapLibre
odmietol aj s celým štýlom.

**Silu ale nedrží tá krivka, ale ALFA FARIEB.** Tieňovanie je prekryvná
vrstva: krytie, ktorým prekrýva mapu pod sebou, je `sin` zo sklonu (a ten sa
prevýšením ešte natiahne), takže s nepriehľadnou farbou je nad ~20° sklonu
krytie 0,97–1,0 – pod tieňovaním nie je vidieť mapu, ale samotnú farbu
tieňovania. Namerané na svetlej téme (z15, 49° s. š., prevýšenie 0,95, svah
30°, ten istý shader počíta `workers/lint/hillshade.mjs`):

| farba lesa `#b7d69f` na 30° svahu | privrátený k svetlu | odvrátený |
|---|---|---|
| nepriehľadné farby | `#fcfcfb` (biela) | `#5c4c3c` (hnedá) |
| s alfou (0,36 / 0,70 / akcent 0,22) | `#cbdabb` | `#757257` |

Teda: z lesa bola na osvetlenom svahu **biela plocha** a na zatienenom tá istá
hnedá ako z lúky – nad hranicou lesa bola z mapy vytieňovaná reliéfna maketa
bez krajinnej pokrývky. Reliéf sa alfou nestratí (rozdiel medzi stranami je
41 jednotiek L*, viac, než oko na tvar potrebuje); ubudlo len to, čo tvar
nenieslo.

**Tam, kde model dáta NEMÁ, sa nevyrobí hladina mora.** Terrarium je RGB
a nemá podobu „hodnota tu nie je“, takže do dlaždice sa niečo zapísať musí –
a `gdalwarp` na to dlho dostával `-dstnodata 0`. Z „model tu nemáme“ sa tým
stalo „nula metrov nad morom“ a vyšli z toho tri veci naraz, ani jedna hlasná
(namerané na publikovanom `bratislavsky_test4-terrain.pmtiles`):

| | |
|---|---|
| stena na hranici dát | skok 668 m na 407 m/px = **sklon 59°** (na z9 69°) |
| plocha bez tieňovania za ňou | z5 **99,6 %** dlaždice presne 0 m, z9 43 %, z10 35 % |
| hlavička sľubovala cudzie územie | `11,25 / 40,98 / 22,50 / 48,92` nad mapou `17,167 / 48,321 / 17,195 / 48,340`, teda **182 751× väčšia plocha** |

Hillshade je derivácia výšky, takže tá stena nie je kozmetika: nakreslí sa ako
ostrá svetlo-tmavá čiara cez mapu na mieste, kde o žiadnu hranicu nejde, a za
ňou je rovina – čiže plocha, ktorá tieňovanie NEMÁ. Odteraz je `NODATA`
sentinel mimo rozsahu skutočných výšok (−9999), chýbajúce hodnoty dopĺňa
`vypln_nodata` NAJBLIŽŠOU platnou (to isté, čo robí `gdal_fillnodata`, len
štyrmi priechodmi indexov) a dlaždica bez jediného platného pixela sa
**nezapíše vôbec** – nie je to rovina, je to územie, o ktorom model nič
nehovorí (pravidlo 2: rozsah je sľub).

**Konštanta by stenu nezrušila, len znížila**, preto sa dopĺňa okolím: výška
za hranicou plynulo pokračuje tou, ktorá je na hranici, takže z nej hillshade
nemá čo nakresliť. Namerané na napodobenine dlaždice: sklon steny 57–68° → 6°
a platné výšky ostávajú nedotknuté. Dopĺňa sa **najprv po riadkoch, potom po
stĺpcoch** – pixel v rohu nemá platného suseda ani vo svojom riadku, ani vo
svojom stĺpci, takže z „to bližšie z oboch osí“ by vyšiel nedoplnený a v mape
by ostal sentinel, čiže −9999 m vedľa 600 m.

**Rozsah v hlavičke `.pmtiles` sa reže na bbox behu** (`pack.py --clip-bbox`).
Zjednotenie CELÝCH dlaždíc je totiž rozsah tej najväčšej z nich a dlaždica na
z5 má 11,25° – pyramída nad jedným krajom sa ním vykázala ako pol Európy.
Klientovi to neuberie ani jednu dlaždicu: MapLibre porovnáva `bounds`
s dlaždicou PRIENIKOM, takže tá z5, do ktorej kraj padne, ostáva v rozsahu.
Stráži to `workers/lint/terrain-nodata.py`.

**A svetlo svieti od severozápadu a drží sa terénu.** MapLibre má predvolene
335° (25° od severu – práve preto boli najbielejšie SEVERNÉ svahy) a
`illumination-anchor: viewport`, teda svetlo priviazané k obrazovke: pri
otočení mapy sa prelieva na druhú stranu hrebeňa a to isté údolie raz vyzerá
ako údolie a raz ako chrbát. V štýle je preto `315` a `map` – oboje napísané,
lebo predvolená hodnota je tu tá zlá.

Alfa má cenu, ktorú platí developer mód: `input[type=color]` alfu nepozná,
takže ju drží textové políčko vedľa pipetky (`normColor` v `devmode.js`). Kým
to tak nebolo, ťuknutie do farby tieňa ju ticho zahodilo.

### Štítky s číslom cesty (`D1`, `R1`, `I/18`)

Číslo cesty je iná vec než jej meno, a preto je to iná vrstva: meno beží
pozdĺž cesty a je unikátne, číslo je **značka** – opakuje sa po celej dĺžke, je
krátke a človek ho na mape hľadá. `road-name` ho nekreslila vôbec.

```
poc/web/shields.js          tvar, veľkosť a rozťahovacie pásma obrázka
workers/assets/shields.mjs  dopečie ho do každého spritu (aj @2x)
poc/web/themes.js           SHIELD_DEFS: ktorá trieda, aká farba, od akého zoomu
workers/lint/shields.mjs    tri tiché veci nižšie
```

**Podklad je HOTOVÝ FAREBNÝ obrázok pečený na tvar × triedu × tému**, nie SDF:
úradná značka má dva rovnako hrubé prstence (biely a za ním farebný) a tie sa
cez `icon-color` a jedno `icon-halo` spraviť nedajú. Cena je, že farba sa pečie
pri builde – v developer móde sa zmení až po prebuildovaní spritu. Naťahuje sa
len rovná časť hrán (`stretchX`/`stretchY`), rohy nie, inak by z obdĺžnika bola
pri dlhom čísle kapsula; na bežnom rastri to funguje, na vzdialenostnom poli
nie (rozpis v hlavičke `poc/web/shields.js`).

**Zoom, veľkosť čísla a rozostup po ceste sa ladia pri každej triede** (tá istá
záložka, ten istý `layerBlock` ako pri značkách trás – je to jedna vrstva
`road-shield-<trieda>`, takže to ide do `overrides.layers`, nie do
`overrides.shields`). Veľkosť štítka JE veľkosť písma: podklad má
`icon-text-fit`, teda je natiahnutý presne na číslo, a vlastnú `icon-size`
naschvál nemá – keby ju dostal, prestal by číslu sedieť.

**Čo sa v developer móde prepnúť DÁ, je TVAR** (záložka „Štítky",
`overrides.shields[<trieda>].shape`): v sprite sú všetky tvary naraz, takže je
to zmena mena obrázka, nie prebuildovanie. Preto sa pečie tvar × trieda × téma
a nie len ten jeden tvar, ktorý je práve v `SHIELD_DEFS` – keby sa pieklo
menej, prepnutie by nechalo číslo bez podkladu a vyzeralo by to, že sa ten tvar
nedá. Stráži to `workers/lint/shields.mjs`.

**Triedy sú z dlaždíc, nie z čísla.** Lákalo by rozlíšiť štítok podľa toho, čím
sa `ref` začína („D" = diaľnica), ale to je pravidlo o slovenskom číslovaní
zapísané v štýle, ktorý sa stavia nad hocijakým regiónom – v Rakúsku je „A1"
diaľnica a „B1" hlavná cesta.

Tri tiché veci, na ktoré je kontrola: premenovaný obrázok nechá číslo **bez
podkladu** (`hasIcon` ho ticho nahradí hrubým halom), stratené
`stretchX`/`content` pri **preskladaní spritu** (`workers/styles/patterns.mjs`
dopeká vzory nad tým istým atlasom) ho natiahnu aj s rohmi, a keby sa vrstva
dostala **za `road-name`**, číslo by na hustej sieti prehrávalo s menom ulice –
MapLibre umiestňuje popisky v poradí vrstiev a kto je skôr, berie si miesto
prvý.

### Turistická a cyklistická značka (SK + CZ)

Pozdĺž trasy sa v pravidelných intervaloch kreslí **to, čo je namaľované na
strome**: štvorec s vodorovným pásom vo farbe trasy, podklad biely (pešia
značka) alebo žltý (cyklistická), a k tomu tvarové značky – trojuholník na
vrchol, „L" k pamiatke, „U" k prameňu, bicykel na českej cyklotrase.

```
poc/web/marks.js            tvary, farby, dvojice podklad×farba, kreslenie
workers/assets/marks.mjs    dopečie ich do každého spritu (aj @2x)
workers/trails/tags.py      `osmc:symbol` → tvar, podklad, farba (do dlaždíc)
poc/web/themes.js           vrstva `trail-<druh>-mark`: rozostup, veľkosť, stĺpik
workers/lint/marks.mjs      tiché veci nižšie
```

**Ikonka druhu trasy to nenahradí a preto ju značka vytláča.** Horský štít
pozdĺž chodníka povie „tadiaľ ide nejaká turistická", ale „choď po červenej"
sa z neho prečítať nedá. Ikonka preto ostáva len tam, kde trasa značku NEMÁ
(neznáma farba z OSM) – dva symboly na jednej čiare by si len brali miesto.

**Meno obrázka sa skladá z DÁT** (`mark-<podklad>-<farba>-<tvar>`, `concat`
v štýle), takže sú to tri miesta, ktoré musia sedieť naraz: `tags.py` píše
trojicu, `themes.js` z nej skladá meno a `marks.mjs` ho musí mať v sprite.
Neznámy obrázok MapLibre **ticho preskočí** a po trase nie je nič – preto je na
to kontrola a preto sa pečú aj dvojice, ktoré vznikajú náhradou (podklad vo
farbe pásu je prázdny štvorec, takže sa vymení).

**Farby značiek nejdú cez tému, a je to zámer.** Značka je obrázok fyzickej
tabuľky – červená je červená aj na tmavej mape. Pásik trasy pod ňou naopak
témou ide (`trailRed` a spol.), lebo to je prvok mapy. Témovať aj značky by
znamenalo štvornásobok obrázkov v sprite.

**Značky dvoch trás na jednej ceste sa stavajú NAD SEBA, tesne.** Trasy majú
v dlaždiciach tú istú geometriu (pásiky vedľa seba robí až `line-offset`, ktorý
na symboly neplatí), takže bez posunu padnú všetky značky na jedno miesto
a kolízia nechá jednu – vždy tú istú, lebo poradie vrstiev je pevné. Posúva sa
`icon-offset`-om podľa `side` a `off` (pešie nahor, kolesové nadol), a to je
v PIXELOCH násobených `icon-size`, nie vo výškach značky: kým tu boli „výšky",
bol posun pod jeden pixel a z troch trás bola v mape vidieť jedna.

**Krok stĺpika je `MARK_BOX`, čiže presne strana štvorca – bez medzery.**
Obrázok je o `MARK_PAD` (1 px) na každej strane väčší než tá strana, takže sa
priehľadné okraje prekryjú a VIDITEĽNÉ tabuľky sedia na sebe tak, ako sedia na
strome. Cena je **`icon-allow-overlap`, a bez nej to nejde**: kolízny obdĺžnik
je celý obrázok (`MARK_IMAGE`) plus `icon-padding`, takže sa dve susedné
priečky o dva pixely prekrývajú a MapLibre by druhú značku ZAHODILA – presne to
sa dialo predtým z opačnej strany (pri kroku 16 bola z červenej a modrej vidieť
len červená) a riešilo sa to medzerou 12 px. `icon-padding` je preto nula:
neškáluje sa s `icon-size`, takže by pri malej značke vážil dvojnásobne. To
isté platí pre **ikonku druhu trasy** – stojí v tom istom stĺpiku (`off` a
`side` sa číslujú raz na cestu, nie raz na značku), takže sa ikonky viacerých
trás na jednej ceste už neprekrývajú. Stráži to `workers/lint/marks.mjs`:
keď je krok menší než kolízny obdĺžnik, `icon-allow-overlap` musí byť zapnuté.

**Čo sa dá v developer móde** (záložka „Trasy"): rozostup značiek po trase,
ich veľkosť a krok stĺpika nad sebou (`overrides.trails.marks` –
`spacing`, `size`, `step`; medze na jednom mieste v `TRAIL_MARK_RANGES`),
a pri každom druhu trasy tvar značky –
`podľa OSM` (predvolené), konkrétny tvar, alebo `žiadna`
(`overrides.trails.types[<druh>].mark`). Tie tri odpovede sa nedajú stlačiť do
dvoch: „taká, aká je v OSM" nie je meno tvaru.

## Navigácia: profil je jeden, motory sú dva

Zadanie (auto, pešo, bicykel, autobus, vlak; pri aute obchádzanie tried ciest,
mýta, maximálna rýchlosť a diaľničná známka po krajinách) a celý rozpis toho,
čo na to treba, je v [`docs/navigation.md`](docs/navigation.md). Tu je len to,
čo platí pri každej zmene:

**Voľba je napísaná RAZ a k nej stojí, ako sa prekladá do každého motora.**
Číselník je `workers/data/routing-profiles.json` (a `vignettes.json` pri
známkach), skladá z neho `workers/routing/profile.py`. Dva profily vedľa seba –
jeden pre Valhallu, jeden pre GraphHopper – by boli dve pravdy o jednej otázke
a rozišli by sa TICHO: oba sú samy o sebe platné a trasa sa spočíta, len by
jedna obchádzala diaľnicu a druhá nie.

**Čo motor nevie, musí byť napísané, nie vynechané.** Pri každej voľbe je pre
každý motor buď mapovanie, alebo `unsupported` s dôvodom; `profile.py` to dá do
`_nepokryte` aj na chybový výstup a `--strict` na tom padne. Ticho zahodená
voľba je pravidlo 8 v čistej podobe – používateľ si odškrtne „vyhnúť sa cestám
I. triedy", trasa ho po nich povedie a nič o tom nepovie. **A vo Valhalle sú
tri také voľby naozaj** (I., II. a III. trieda) plus známka: `use_highways` len
škáluje pevnú tabuľku `kHighwayFactor[]`, ktorá má pri Primary aj nižšie nulu,
takže účinok nie je slabý, ale nulový. Rozpis aj cesta von (záplata) je
v `docs/navigation.md`.

**Neznámy kľúč costingu sa TICHO ignoruje** – `top_speeed` namiesto `top_speed`
vráti platnú trasu, len nie tú vypýtanú. Preto `workers/lint/routing.py` drží
kľúče Valhally proti zoznamu vyzobranému z jej zdrojáku a výrazy GraphHoppera
proti jeho zakódovaným hodnotám.

**Známka nie je mýto.** `toll=yes` je platba za prejazd (brána, tunel) a rieši
ju `avoid_toll`; známka sa platí za čas a platí na sieť. A odpovede o nej sú
TRI – „mám do…", „nemám" a „táto krajina známku nepozná" –, plus štvrtá
„nevieme", ktorá sa nesmie dosadiť potichu ani na jednu stranu: „mám" vypíše
pokutu, „nemám" pošle sto kilometrov po okreskách.

**Graf sa NEDELÍ po krajoch, ako sa delí mapa.** Známka po krajinách má zmysel
len vtedy, keď trasa smie prejsť hranicu, takže navigačný balík patrí na štát
a jeho susedov (`workers/data/routing-areas.json`, workflow `navigation.yml`).
Publikuje sa ako ďalší balík na Drive, nie na Pages – jedným packerom
(`publish-map.py`), tak ako mapa sveta.

**A PBF sa preň NEREŽE.** Pri mape je orez na hranicu podstatný, tu by bol
chybou: hrana, ktorej chýba druhý koniec, je slepá ulica a trasa cez ňu
neprejde – graf sa pritom postaví a beh zazelená. Rovnako sa nesmie stratiť
`admins.sqlite`: bez neho Valhalla nevie, v ktorej krajine hrana leží, takže
nefunguje prechod hranice ani strana jazdy, a nefunguje to TICHO. Oboje stráži
`workers/lint/navigation.py` – aj to, že každý rozsah má **vlastné `country`**
v `regions.json`: pri `admin_level: 2` je krajina zároveň uzol v `maps.json`,
takže dva rozsahy pod jedným menom si položku navzájom prepíšu (tá istá úvaha
ako `svet_basic`).

## Obmedzenia na ceste: hodnota ide do dlaždice tak, ako je v OSM

Výška podjazdov a tunelov, šírka, hmotnosť, maximálna rýchlosť, jazdné pruhy
a stúpanie – vrstva `transportation` OpenMapTiles z toho nenesie **ani jednu**
hodnotu, takže sa to isté PBF čítá druhýkrát vlastnou schémou
(`workers/roads/roads.yml`), presne ako trasy a krajinné prvky.

**Hodnota je REŤAZEC a `tag_mappings: double` je chyba.** Planetiler parsuje
číslo cez `NumberFormat.parse`, ktorý vezme číslo zo ZAČIATKU a jednotku
zahodí: z `12'6"` (3,8 m) je 12 a z `50 mph` je 50 – bez jedinej hlášky. Do
dlaždice preto ide to, čo je v OSM, a mapa kreslí presne to, čo je na tabuli.
Číslo z tej hodnoty potrebuje len smerovanie a to si ju parsuje samo.

**Dva bloky, dva zoomy, a musia sa vylučovať.** Rozmer a hmotnosť od z12
(rozhodujú, či tam vozidlo prejde), rýchlosť a pruhy od z14 (sú takmer na
každej ceste). Druhý blok má `__not__` nad zoznamom rozmerov – bez neho by
cesta s výškou aj rýchlosťou vypadla dvakrát a štítok by sa kreslil cez seba.
Stráži to `workers/lint/roads.py`, a samotnú schému **testy v nej**
(`java -jar planetiler.jar verify workers/roads/roads.yml`).

## Build svet: vlastná pipeline, `svet.zip` a `svet.aar`

`world-map.yml` robí **základnú mapu celého sveta** – vodstvo, hranice štátov
a regióny, na aké kusy je OSM rozdelené na sťahovanie. Nie je to mapa na
chodenie (nie sú v nej cesty, sídla ani terén), je to **podklad pod výber
„ktorý kus si stiahnuť"**: v `download` vrstve má každý región `id`, `name`,
`level` a `pbf`, teda odkaz, ktorý sa dá naozaj stiahnuť.

```
<koreň>/svet/svet.zip                dlaždice, štýly (4 témy), glyfy, manifest
<koreň>/svet/svet.aar                to isté ako Apple Archive (job na macOS)
<koreň>/svet_basic/svet_basic.zip    podoba `basic` – bez vodstva, ~3 MB
<koreň>/svet_basic/svet_basic.aar
```

**DVE PODOBY, a rozhoduje input `variant`** (číselník
`workers/data/world-variants.json`): `plna` je celá mapa, `basic` z nej má iba
**hranice štátov a regióny sťahovania** – teda to, čo drží tvar výberu – bez
vodstva a jazier. Vodstvo je v tej mape to drahé (rastie ~3× na zoom), takže
basic vyjde na jednotky MB proti desiatkam a zmestí sa do 15 MB aj na z8.

**Podoba nie je druhá schéma, len výber vrstiev z tej istej.** `world.yml`
ostáva jediný popis toho, čo sa z podkladov vyrába; `workers/world/variant.py`
z neho vyberie vrstvy podoby a zloží schému, ktorú Planetiler naozaj dostane –
a zo `sources:` orezanej schémy zároveň vypadne, ktoré podklady sa vôbec
sťahujú (basic tak nesťahuje 60 MB vodných polygónov ani nepotrebuje GDAL).
Štýl si z toho istého číselníka berie, ktoré vrstvy kresliť, a
`workers/lint/world.py` porovnáva schému so štýlom pre KAŽDÚ podobu.

**A `basic` má vlastný kľúč regiónu (`svet_basic`), nie príponu.** Meno je sľub
o rozsahu (pravidlo 2), takže nesmie sadnúť na `svet.zip` ani na jeho uzol
v `maps.json` – kto si podľa katalógu stiahne „mapu sveta", nesmie dostať mapu
bez morí. Je to tá istá úvaha, akou má rýchly test v mene `test4km2`.

**V tom balíku nie sú to drahé dlaždice, ale PÍSMO.** Jeden fontstack Noto Sans
má 33 MB (celý unicode) a v balíku sú dva – do 15 MB by sa `basic` nezmestil
ani prázdny. `workers/world/glyphs.py` preto nechá len tie rozsahy znakov,
ktoré sú v menách na mape, a MERIA ich z podkladov (516 mien z Natural Earth sa
vojde do jediného rozsahu 0–255 → 69 MB na stovky kB). Keď sa podklad nedá
prečítať, NEOREŽE SA NIČ: väčší balík je lepší než prázdne štvorčeky namiesto
mien.

**Vlastná pipeline z tých istých troch dôvodov ako `Build wiki`**: iné dáta (nie
regionálne PBF), iná životnosť (hranice štátov sa nemenia pri každej zmene
štýlu) a iný výstup (nejde na Pages a nemá čo robiť v rozpočte stránky).
**Packer a zápis do katalógu to ale nerušia** – balí `publish-map.py` a `.aar`
`deploy/apple-archive.sh`, tie isté ako pri mape kraja. V katalógu je `svet`
vlastný koreňový uzol (hlavný kľúč je krajina, svet je nad nimi).

**`planet.osm.pbf` sa NEPOUŽÍVA a je to zámer**: planéta má cez 80 GB
a Planetiler nad ňou potrebuje rádovo terabajt a hodiny, kým runner má ~60 GB
a strop 360 minút. Mapa preto stojí na podkladoch, z ktorých si nízke zoomy
skladá aj Planetiler sám – Natural Earth (hranice, jazerá, štáty) –
a na pobrežiach na OSM (`simplified-water-polygons`, robené na z0–z9). Regióny
sťahovania sú z `index-v1.json` Geofabriku: je to jediná odpoveď na „na aké
kusy je OSM delené", ktorá je v JEDNOM súbore aj s polygónmi. Naše buildy
sťahujú PBF z osm.fr, ktorý polygóny svojich výrezov nepublikuje – delenie je
u oboch to isté, a to, čo mapa ukazuje, je delenie, nie náš zoznam.

**Ticho tam nesmie ostať prázdna vrstva.** Cudzí server vráti chybovú stránku
a mapa by len „nemala hranice", tak má každý výstup v `workers/world/sources.py`
dolnú hranicu počtu prvkov a pod ňou to je tvrdá chyba. Druhá tichá vec je
MENO vrstvy: keď v štýle stojí `source-layer: downloads` a schéma vrstvu volá
`download`, MapLibre nepovie nič a regióny v mape jednoducho nebudú – stráži to
`workers/lint/world.py` (a k tomu dno zoomu, tak ako `zoom-floor.py` pri
vrstevniciach).

**Čo je v mape, hovorí `MAP_LAYERS`.** Bez neho by si `publish-map.py` vypýtal
vrstvy mapy kraja a do `obsah.json` aj do `maps.json` napísal „bez_vrstevnic,
bez_skal, bez_tienovania" – to znie ako mapa kraja s vypnutým terénom, a to
táto mapa nie je. Musí byť **rovnaké v oboch jobov**: `.aar` položku katalógu
prepisuje navrch, takže inou hodnotou by prebil to, čo napísal ZIP. Odkedy sú
podoby dve, sa nepíše v `env:` workflowu, ale **skladá sa z vrstiev podoby**
(`_nazvy` v číselníku) a chodí VÝSTUPOM jobu do oboch – dva prepisy tej istej
hodnoty by sa raz rozišli a katalóg by tvrdil vrstvy, ktoré v mape nie sú.

## Než niečo pushneš

```bash
# actionlint – chytí to, čo GitHub inak zamlčí
curl -sSL https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_linux_amd64.tar.gz \
  | tar xz actionlint && ./actionlint

# veľkosť workflowov (strop 128 KiB, varovanie od 120 KiB)
wc -c .github/workflows/*.yml

# bash vo workers (shellcheck nie je v CI, actionlint ho volá len na `run:`)
for f in workers/*/*.sh; do bash -n "$f" || echo "CHYBA $f"; done

# python vo workers – `py_compile` chytí len syntax, `pyflakes` aj nedefinované
# meno a nepoužitý import. Pri rozdeľovaní súboru na moduly je to to jediné,
# čo spoľahlivo povie, na čo sa zabudlo naviazať (a v CI to nie je).
python3 -m pyflakes workers/*/*.py  # pip install pyflakes

# kontroly z „Kontrola · lint workflowov" sa dajú spustiť aj lokálne
python3 - <<'PY'
import subprocess, sys, yaml
d = yaml.safe_load(open(".github/workflows/lint-workflows.yml"))
for st in d["jobs"]["lint"]["steps"]:
    if st.get("run") and st.get("name") != "actionlint":
        print("=====", st["name"])
        subprocess.run(["bash", "-c", st["run"]])
PY

# workery sa dajú spustiť aj lokálne – hodnoty berú z prostredia práve preto
python3 workers/plan/area.py --region-bbox=18.7,48.8,20.6,49.6 --area=vysoke_tatry
python3 workers/dem/target.py --source=dmr5 --area-key=vysoke_tatry --bbox=20.1,49.1,20.2,49.2
python3 workers/lint/publishing.py     # nepublikuje sa do releasov/artefaktov
python3 workers/lint/catalog.py        # katalóg drží tvar; test je v maps-test.json
python3 workers/lint/packaging.py      # glyfy a viewer sú mimo balíka, ale na Pages
python3 workers/lint/rebuild.py        # `rebuild` prepočíta to, čo sľubuje
python3 workers/lint/dem-empty.py      # prázdny stupeň sa overuje presne
python3 workers/lint/terrain.py        # tieňovanie nestráca zvislú presnosť
python3 workers/lint/terrain-nodata.py # tam, kde model nie je, sa nevyrobí hladina mora
python3 workers/lint/dem-resampling.py # kernel DEM vyberá lib/cell.py, nie autor riadku
python3 workers/lint/geojson-srs.py    # GeoJSON výstup bez SRS – inak sú z metrov stupne
python3 workers/dem/measure-resampling.py  # čím prevzorkovať, aby v tieni nebola mriežka
node    workers/lint/style.mjs         # výplne v štýle chcú len plochy
node    workers/lint/hillshade.mjs     # tieňovanie neprekryje mapu pod sebou
node    workers/lint/shields.mjs       # štítky ciest: obrázok, rozťahovanie, poradie
node    workers/lint/marks.mjs         # značky trás: tvar, dvojica farieb, meno obrázka
node    workers/lint/icons.mjs         # vlastné ikony a sady sa dostanú do mapy
node    workers/lint/overrides.mjs     # úprava z developer módu prejde normalizáciou celá
python3 workers/trails/tags.py --osmc=red:white:red_bar --route=hiking  # akú značku z toho
python3 workers/lint/features.py       # predfilter pustí, čo schéma prvkov chce
node    workers/lint/trails.mjs        # strana a odstup trás držia naprieč súbormi
python3 workers/lint/routing.py        # profil navigácie prejde do motora celý
python3 workers/lint/navigation.py     # graf: rozsah, uzol v katalógu, celý balík
python3 workers/lint/roads.py          # obmedzenia na ceste: filter, jednotky, bloky
python3 workers/lint/job-refs.py       # needs.*.outputs.* mieri na existujúci výstup
java -jar planetiler.jar verify workers/roads/roads.yml  # testy schémy obmedzení
python3 workers/routing/profile.py --check  # ktorú voľbu ktorý motor vie
python3 workers/lint/world.py          # štýl sveta kreslí to, čo schéma vyrába
python3 workers/lint/planetiler.py     # kto púšťa Planetiler, má aj Javu 21
python3 workers/lint/pbf-source.py     # kraj sa reže z rodiča a dopĺňa členov plôch
python3 workers/plan/pbf-areas.py data/region.osm.pbf  # ktoré plochy Planetiler zahodí celé
python3 workers/world/variant.py --list        # podoby mapy sveta
python3 workers/world/sources.py --out=data/world --only=boundaries  # podklad sveta
python3 workers/plan/region-poly.py --region=presovsky --out=/dev/null  # polygón kraja
python3 workers/lib/region-mask.py --poly=… --bbox=… --zoom=14  # čo padne mimo kraj
python3 workers/deploy/region-mask.py --poly=… --bbox=… --out=_site/region.geojson  # hranica pre viewer
workers/lib/region-clip.sh 19.8,48.7,22.5,49.4      # argumenty orezu pre Planetiler
python3 workers/drive/store.py --check # čo je v sklade (chce token)
BBOX=… AREA_KEY=… AREA_BBOX=… SRC_CONTOURS=dmr5 workers/dem/check.sh
REGION_KEY=… BASE_URL=… ICONS_NAME=… … workers/deploy/site.sh   # a tak ďalej
```

`Kontrola · lint workflowov` (`.github/workflows/lint-workflows.yml`) beží pri každom pushi
do `.github/workflows/**`, `workers/**` a `poc/web/**` a kontroluje aj veci,
ktoré actionlint nevie: veľkosť aj dĺžku súboru, zdvojené zátvorky v `run:`,
dĺžku popisov inputov, súlad výberov s `data/areas.json` a `data/dem-sources.json`,
existenciu `needs.*.outputs.*` a `steps.*.outputs.*`, to, že každý
`workers/<job>/*.sh` dostane env, ktoré číta, že cesta k DMR 5.0 ostane celá, že
cache ostane na Drive (žiadne `actions/cache`, každý cache krok sa vie
prihlásiť), že sa **nepublikuje do releasov ani do dlhodobých artefaktov**
(`workers/lint/publishing.py`), že **každá výplň v štýle nad vrstvou so
zmiešanou geometriou chce len plochy a dôležitejšia cesta je nad menej
dôležitou** (`workers/lint/style.mjs` – MapLibre kreslí vrstvy v poradí zo
štýlu, takže kým sa cesty pridávali od diaľnice nadol, kreslila sa účelová
cesta cez diaľnicu a na križovatkách ju prerušovala), že
**„v tomto stupni terén nie je" nerozhodne vzorkovaná štatistika a že sa tá
odpoveď podpíše** (`workers/lint/dem-empty.py`), že **tieňovanie nestratí
zvislú presnosť, ktorou stojí a padá** (`workers/lint/terrain.py` – výška
zaokrúhlená na celé metre a `-r average` pri zväčšovaní DEM spravili
z hillshadu, ktorý je derivácia výšky, pravidelnú tkaninu cez celú mapu; nič
nespadlo – a k tomu, že **tieňovanie končí na hranici regiónu**: dlaždicový
orez hrubší než dlaždica byť nemôže, takže reliéf presahoval na z10 na
dvojnásobok plochy kraja), že **si resampling výškového modelu nikto nevyberá sám**
(`workers/lint/dem-resampling.py` – tá istá mriežka o krok skôr, rovno
v modeli: `-r average` pri pomere 4 m → 5 m, kde GDAL každú štvrtú zdrojovú
bunku preskočí, takže vrstevnice aj tieňovanie ju majú zapečenú v dátach;
spoznať sa to dalo len okom na hotovej mape), že **GeoJSON výstup nedostane
SRS** (`workers/lint/geojson-srs.py` – ovládač podľa neho súradnice PREPOČÍTA
do WGS84, takže `-a_srs EPSG:3035` z metrov spraví stupne a ogr2ogr pri tom
skončí úspechom; raz z toho mala každá skala 1e-9 m² a filter ich vyhodil
všetky, raz vyšla únia švov v stupňoch a zahodila sa ako „stratená plocha"),
že **tam, kde výškový model dáta nemá, sa nevyrobí hladina mora**
(`workers/lint/terrain-nodata.py` – `-dstnodata 0` znamenalo „model tu
nemáme“ = „nula metrov n. m.“, takže na hranici dát stála stena so sklonom
59°, za ňou plocha bez tieňovania a `.pmtiles` sa tými dlaždicami vykázal ako
rozsahom: hlavička sľubovala 182-tisíckrát väčšie územie, než popisuje),
že **predfilter PBF pustí
všetko, čo si schéma krajinných prvkov vyžiada** (`workers/lint/features.py` –
to isté rozhodnutie je v `filter.txt` aj `features.yml` a keď sa rozídu,
Planetiler vyrobí dlaždice bez tej triedy a nepovie nič), že **pásik značenej
trasy drží naprieč tromi súbormi** (`workers/lint/trails.mjs` – strana cesty,
zlomy kriviek odstupu a atribúty v schéme dlaždíc), že **tieňovanie
reliéfu neprekryje mapu pod sebou** (`workers/lint/hillshade.mjs` – krytie
prekryvnej vrstvy rastie so sklonom, takže z nepriehľadnej `hillHighlight`
je na svahu privrátenom k svetlu biela plocha namiesto lesa; štýl je pri tom
platný), že **štítok s číslom cesty
(`D1`) prežije preskladanie spritu a ostane nad menom ulice**
(`workers/lint/shields.mjs` – rozťahovateľný obrázok bez `stretchX` sa natiahne
aj s rohmi a premenovaný obrázok nechá číslo bez podkladu; ani jedno nespadne),
že **vlastná ikona a vlastná sada ikoniek sa naozaj dostanú do mapy**
(`workers/lint/icons.mjs` – obrázok nahratý v paneli musí dopiecť
`custom-icons.mjs` do spritu, sadu musí stiahnuť `icons.sh` a zapísať
`site.sh` do manifestu; a `layout` úprava na inej než symbolovej vrstve by
zhodila celý štýl), že **turistická značka, ktorej meno obrázka sa skladá až
z DÁT, je naozaj v sprite** (`workers/lint/marks.mjs` – tvar z `osmc:symbol`, dvojica
podklad × farba a meno `mark-…` musia sedieť v troch súboroch naraz, inak
MapLibre obrázok ticho preskočí a po trase nie je nič; a bez posunu podľa
pruhu si značky dvoch trás sadnú na jedno miesto a kolízia nechá jednu),
že **úprava z developer
módu prejde normalizáciou celá** (`workers/lint/overrides.mjs` – nulová hrúbka
čiary je zmiznutá vrstva, nie vypnutá, a kopírovanie štýlu z vrstvy do vrstvy
nesmie vyrobiť polovicu, ktorú `normalizeOverrides` pri zápise do repozitára
zahodí), že **PBF kraja sa reže z rodičovského extraktu a dopĺňa členov
plôch** (`workers/lint/pbf-source.py` – hotový `{kraj}-latest.osm.pbf` z osm.fr
nie je referenčne úplný, takže CHKO Malé Karpaty, Záhorie aj Dunajské luhy
Planetiler zahodil CELÉ a build bol pri tom zelený; kontrola stráži rodiča
v číselníku, `-s smart -S types=multipolygon,boundary` pri každom reze aj to,
že sa pri chýbajúcom `.poly` spadne a nesiahne po hotovom exporte), že
**každý job, ktorý
púšťa Planetiler, má aj `setup-java` s tou istou verziou**
(`workers/lint/planetiler.py` – `setup-java` je akcia, tá sa do
`workers/lib/planetiler.sh` presunúť nedá, takže je to jedna veta na šiestich
miestach a šiesty na ňu zabudol), že **výber `rebuild` naozaj prepočíta to, čo sľubuje**
(`workers/lint/rebuild.py` – hodnota vo formulári, ktorú `plan/options.py`
nepozná; príznak, ktorý `plan` nevydá ako výstup, takže sa k jobu nedostane
a pregenerovanie ticho nespraví nič; a `rebuild: skaly` pri
`rock_source: tienovanie`, kde sklon nepočíta nikto a obrysy robí
podpipeline – tá bez `fresh=1` nadviaže na svoje rozrobené kusy a vráti
výsledok predošlého behu, so zeleným behom), že sa
ten istý sklad nevolá v dvoch workflowoch rôzne a že **worker leží
v priečinku podľa jobu** (`workers/lint/layout.py` – plochý `workers/`
by ticho vypol kontroly, ktoré cesty hľadajú vzorom). **Keď
opravíš tichú chybu, pridaj naň kontrolu** – tak sú tam všetky ostatné.

## Commity a PR

Commit message je **jedna veta po slovensky o tom, čo sa zmenilo vecne** – nie
zoznam súborov. Pozri `git log`: „Skaly po častiach: sklad sklonu, ktorý prežije
zrušený beh", „Z dvoch výberov výškového modelu jeden: `dmr5` si podobu berie
podľa rozsahu".

**PR zakladaj vždy, aj keď oň nikto nepožiadal.** Hotová práca na vetve, ku
ktorej PR nie je, sa nemá ako dostať do mastera – a z histórie tohto repozitára
je vidieť, že tadiaľ ide všetko (#54 … #71). Nečakaj na vyzvanie: keď je zmena
dokončená a pushnutá, otvor k nej PR.

Do popisu PR patrí to isté, čo do commit message – **čo sa zmenilo vecne a
prečo** – a k tomu ako sa to overilo (`Kontrola · lint workflowov`, lokálne spustené
workery, číslo behu). Keď ostalo niečo nedokončené alebo neoverené, napíš to
tam; tichý PR, ktorý vyzerá hotovo, je tá istá trieda chyby ako tichý omyl
v behu.
