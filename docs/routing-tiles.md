# Smerovacie dlaždice `RTIL`

Formát archívu `<kraj>-routing.pmtiles` – toho, z čoho telefón počíta trasu.
Prečo vôbec vzniká a čo nahrádza, je v [`navigation.md`](navigation.md) §10;
tento súbor hovorí, čo je v ňom bajt po bajte.

Píše ho [`workers/routing/tiles.py`](../workers/routing/tiles.py), kóduje
[`workers/routing/format.py`](../workers/routing/format.py) a stráži
[`workers/lint/routing-tiles.py`](../workers/lint/routing-tiles.py).

## Čo v ňom je a čo nie

**Značky, nie ceny.** Profil používateľa – vypnuté typy ciest, rozmery
vozidla, známky, povolený prejazd cez vypnutú cestu – sa mení za behu, takže sa
do predpočítaného grafu zapiecť nedá. V archíve je preto to, čo je v OSM, a
cenu ráta telefón.

**Graf križovatiek, nie surové OSM.** 82 % vrcholov OSM sú body, ktoré ohýbajú
cestu a nerozhoduje sa v nich o ničom (§12). Uzol archívu je preto len
križovatka alebo koniec cesty; tvar cesty medzi nimi je vnútorná geometria
hrany – body bez `id`, ktoré nikdy nie sú vrcholom grafu.

**Vlastné binárne telo, nie MVT.** MVT reže geometriu po hranicu dlaždice
a zahadzuje topológiu; presne to robí `-transport.pmtiles` nepoužiteľným na
smerovanie. PMTiles ostáva ako obálka, lebo katalóg, fronta sťahovania,
účtovanie miesta aj maska regiónu ten formát už vedia.

Vo verzii 1 **nie je**: nadmorská výška uzlov (pole je definované, príznak
`vyska` je 0), zábrany na uzloch (`barrier=*`), podmienené zákazy
(`restriction:conditional`), smerové rýchlosti (`maxspeed:forward`) a krajina
hrany z `admin_level=2` – tú dnes dosadzuje `--krajina` na celý archív, lebo
kraj je celý v jednej krajine.

## Mriežka

Dlaždice sú **z9 XYZ**, tá istá mriežka ako mapa. Hrana patrí do dlaždice
**svojho prvého uzla** – to je vlastnosť way v OSM, nie kraja, takže dvom
behom nad tými istými dátami vyjde tá istá dlaždica.

**Nad mestom sa z9 nezmestí.** Rozpočet na jednu dlaždicu je `ROZPOCET_KB`
(1 MB) a je to strop na pamäť telefónu, nie na stránku: nad ním sa archív
sťahuje po kusoch, ktoré sa v ňom nedajú rozumne držať. Bratislavská z9 má
4,2 MB, košické dve po 2,9 a 2,7 MB. Dlaždica nad rozpočtom sa preto **reže na
štvrtiny o zoom hlbšie** a tie znova, až kým sa telo nezmestí alebo kým nepríde
`ZOOM_MAX` (z13). Reže sa tá istá mriežka, takže dieťa celé leží vo svojej z9.

Rozdelená dlaždica v archíve **nie je**: na jej `z/x/y` nie je nič a kto ju
tam hľadá, zostúpi o zoom nižšie – tak, ako to hovorí `delenie` v `graf`.
Ktoré zoomy v archíve sú, povie `zoom` a `zoom_max` tamtiež a `min_zoom`
/`max_zoom` v hlavičke PMTiles.

## Telo dlaždice

Celé telo je zabalené `gzip`-om; v PMTiles je to `tile_compression: GZIP`
a `tile_type: UNKNOWN`.

Čísla sú `varint` (LEB128, bez znamienka); kde je hodnota so znamienkom, je
navyše `zigzag`. Stĺpce (`uzly`, `hrany`) sa píšu po poliach, nie po záznamoch –
gzip potom komprimuje rovnaké veci vedľa seba.

| úsek | obsah |
|---|---|
| hlavička | `RTIL`, verzia formátu, príznaky (`vyska`, `poradie`), `id` slovníka, `id` poradia, `z/x/y`, bbox obsahu |
| `uzly` | zoradené podľa OSM `id`: Δ`id`, Δ`lat_e7`, Δ`lon_e7`, [výška], [rank] |
| `hrany` | index `od`, index `do`, index sady značiek, dĺžka v cm, smer, počet bodov geometrie, potom body ako Δ od predošlého |
| `tagsety` | sady značiek, každá zoznam `(index kľúča, hodnota)`; rovnaká sada je v dlaždici raz |
| `retazce` | hodnoty voľných kľúčov (`name`, `ref`, `maxheight`…) |
| `zakazy` | druh, výnimky (`except`), reťaz hrán ako dvojice OSM `id` uzlov v smere jazdy |
| `okraj` | uzly, ktoré ležia mimo tejto dlaždice – tie sa nájdu aj vedľa |

Hodnota v sade značiek sa číta podľa druhu kľúča v slovníku: vymenovaný kľúč
nesie index hodnoty, `cislo` zigzag číslo, `volny` index do `retazce`.

**Smer** je len to, čo je v tagoch (`oneway`, `junction=roundabout`).
Predpoklady podľa druhu vozidla – `highway=motorway` je jednosmerka,
`oneway:bicycle=no` neplatí pre bicykel – patria do profilu v telefóne. Inak by
tá istá vec bola povedaná dvakrát a raz by sa rozišla.

## Slovník značiek

[`workers/data/routing-tags.json`](../workers/data/routing-tags.json) hovorí,
podľa čoho je way cesta (`siet`) a čo sa o nej vezie (`kluce`). Čo tam nie je,
sa do telefónu nedostane – je to zároveň páka na veľkosť archívu.

`id` slovníka **sa nepíše ručne, počíta sa z obsahu** (`workers/routing/tags.py`)
a je v každej dlaždici. Archívy s rôznym `id` sa spojiť nesmú: index by
ukazoval na inú hodnotu a trasa by vyšla, len iná.

## Poradie uzlov

`rank` je miesto uzla v poradí eliminácie pre CCH a počíta sa **nad celým
stavaným územím** ([`workers/routing/order.py`](../workers/routing/order.py)),
nie po krajoch – poradia počítané po krajoch sa spojiť nedajú. Je nezávislé od
profilu aj od cien, takže v telefóne by bolo čistou stratou (§11).

Dnešný rez je **inerciálny**: zo štyroch smerov ten, ktorý pretne najmenej
hrán, a z prerezaných hrán hladivý vrcholový oddeľovač. Merané na mriežke
40 × 40 dáva proti náhodnému poradiu 7,8× menej dopočítaných hrán a maximálny
stupeň nahor 59 namiesto 511; 100 000 uzlov trvá 2,5 s. InertialFlowCutter
(rez maximálnym tokom namiesto mediánu) dá lepší oddeľovač a je to miesto, kam
sa vráti, keď bude na čom merať – nie zmena formátu.

Poradie ráta vlastný workflow **„Navigácia · poradie uzlov"**
([`routing-order.yml`](../.github/workflows/routing-order.yml)) nad PBF celého
územia (`workers/routing/pbf.sh`, ten istý, z akého sa stavia celoštátny graf)
a ukladá ho do cache na Drive pod kľúč `routing-order-v1-<územie>-<run_id>`.
Build kraja si ho odtiaľ vezme cez `restore-keys`, teda **najnovšie uložené
poradie toho územia**; ktoré územie to je, hovorí `routing_area` pri krajine
vo `workers/data/regions.json` – všetky kraje krajiny musia stáť na tom istom.
Že kľúč znie na oboch stranách rovnako, stráži
[`workers/lint/navigation.py`](../workers/lint/navigation.py): keby sa rozišiel,
build kraja by nenašiel nič, archívy by šli bez poradia a nespadlo by pri tom
nič.

**Poradie sa preto neprepočítava pri každom builde** a nemusí: závisí len od
tvaru siete. Uzol, ktorý pribudol po jeho výpočte, dostane rank **na konci
podľa svojho OSM id** – je to stále globálne poradie (OSM id je jedno na celý
svet, takže dva kraje dosadia tomu istému uzlu to isté číslo), takže mierne
zastarané poradie je stále platné poradie. `tiles.py` vypíše, koľko takých
uzlov bolo; keď ich je veľa, workflow sa spustí znova.

Archív bez poradia (`tiles.py` bez `--poradie`, teda kým cache ešte nič nemá)
sa postaviť dá a `graf` v metadátach archívu to o sebe povie
(`poradie: null`); telefón si vtedy poradie musí dorátať sám.

## Ako sa kraje spájajú

Uzly nesú **OSM `id`** a mriežka je globálna, takže dva susedné kraje majú
okrajové dlaždice na tých istých `z/x/y` a telefón ich spojí. Že si jeden kraj
tú istú z9 rozdelil a druhý nie, na tom nič nemení: spája sa po prvkoch, nie
po dlaždiciach. Trasa cez hranicu funguje vo chvíli, keď dobehne druhý kraj –
nič sa nedopočítava a nič nedosťahuje.

**Spája sa ale po prvkoch, nie po dlaždiciach, a to je oprava návrhu.** Plán
predpokladal, že okrajové dlaždice susedov sú bajt po bajte zhodné a duplikát
sa dá zahodiť. Nie sú a nemôžu byť: PBF kraja je rezaný jeho hranicou
(`osmium extract -s smart`), takže v okrajovej dlaždici má každý kraj len tú
časť siete, ktorá padla do neho. Zahodiť jednu z dvoch takých dlaždíc znamená
zahodiť polovicu križovatky. Zjednotenie preto ide cez OSM `id` uzlov
a dvojicu `(od, do)` na hranách – rovnaký prvok z dvoch archívov je ten istý
prvok. Čo sa naozaj dá skontrolovať, je, že sa spoločné prvky **nerozídu**;
robí to `workers/lint/routing-tiles.py` nad archívmi jedného behu.

## Kde to v pipeline sedí

Kraj: job `navigacia` v „Mapa · Build map region" volá
[`navigation-region.yml`](../.github/workflows/navigation-region.yml), ten
[`workers/routing/build.sh`](../workers/routing/build.sh) nad tým istým
`data/region.osm.pbf`, z akého je mapa. Archív ide do `_site/tiles/` ako každá
iná vrstva, do manifestu pod `routing` a odtiaľ do balíka `navigacia`
(`workers/data/packages.json`). Predfilter PBF si berie zoznam tried zo
slovníka (`tags.py --filter`), takže druhý zoznam neexistuje, a hotový archív
beh overí tou istou kontrolou, aká beží v lintoch.

Krajina hrany (`krajina`) sa berie z `iso` v `workers/data/regions.json` cez
`country` kraja – bez nej nemá diaľničná známka na čom stáť.

Graf Valhally (`workers/routing/graph.sh`,
[`navigation.yml`](../.github/workflows/navigation.yml)) ostáva ako celoštátna
referenčná stavba; po krajoch sa už nestavia.

## Ako sa to spúšťa

```bash
# poradie – nad celým územím, nie po krajoch (workflow to robí za teba)
python3 workers/routing/order.py --pbf=data/routing.osm.pbf \
    --out=data/routing-order.json --nazov=Slovensko

python3 workers/routing/tiles.py --pbf=data/region.osm.pbf \
    --out=_site/tiles/presovsky-routing.pmtiles \
    --region-key=presovsky --name=Prešovský --krajina=SK \
    --poradie=data/routing-order.json

python3 workers/lint/routing-tiles.py _site/tiles/*-routing.pmtiles
```
