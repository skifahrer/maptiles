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

**Výšky nie sú z OSM** – PBF ich nemá – ale z DMR 5.0 (sklad `dem-dmr5-v2`,
prevzorkovaný na 5 m): `build.sh` si ho pre bbox kraja stiahne a `vysky.py`
odoberie bilineárne výšku pod cestou. Keď ho pre kraj v sklade ešte nikto
nevyrobil, spadne sa na Sonnyho 20 m a beh to napíše do súhrnu.

**Výška uzla** je meter nad morom pod križovatkou a berie sa z konca profilu
susednej hrany, takže sa tie dve čísla nemôžu rozísť. Uzol, pod ktorým model
nič nemá, vezme výšku od suseda v grafe; keď ani ten ju nemá, má 0 m a beh to
povie.

**Výškový profil hrany** je to, čo z výšok robí stúpanie. Do verzie s ním
niesla hrana len výšku svojich dvoch koncov, a medzi dvomi križovatkami je aj
desať kilometrov cesty: sedlo, na ktoré sa vyšlo a z ktorého sa zišlo, nebolo
v žiadnom z tých dvoch čísel a trasa cez hrebeň hlásila nulové stúpanie.
Hrana preto nesie výšku **každých 5 m svojej dĺžky** (`profil_krok_m`
v `graf`, `krok_dm` v tele), v **decimetroch** – zaokrúhlenie na meter je pri
takom kroku väčší šum než sám sklon a sčítané stúpanie z neho rastie.

Vzorka `i` leží `i × krok` od uzla `od` pozdĺž geometrie hrany; **posledná
leží na jej konci**, nech je hrana akokoľvek dlhá. Prvá a posledná sú teda
výšky oboch uzlov. Koľko ich je, hovorí `format.pocet_vzoriek` – jedno
pravidlo pre zápis, lint aj čítačku.

Profil sa pred zápisom **vyhladí** dvomi prechodmi `[1 2 1]` s pevnými koncami:
pri 5 m kroku je priečny šum modelu (priekopa, zárez vedľa osi cesty)
porovnateľný so sklonom a surový súčet kladných rozdielov z neho spraví
stúpanie, ktoré tam nie je. **Most a tunel** dostanú namiesto terénu priamku
medzi koncami – model je zem pod nimi, takže most cez dolinu by inak hlásil
jej dno.

Vo verzii 1 **nie je**: zábrany na uzloch (`barrier=*`), podmienené zákazy
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
| hlavička | `RTIL`, verzia formátu, príznaky (`vyska`, `poradie`, `profil`), `id` slovníka, `id` poradia, `z/x/y`, bbox obsahu |
| `uzly` | zoradené podľa OSM `id`: Δ`id`, Δ`lat_e7`, Δ`lon_e7`, [výška], [rank] |
| `hrany` | index `od`, index `do`, index sady značiek, dĺžka v cm, smer, počet bodov geometrie, potom body ako Δ od predošlého |
| `tagsety` | sady značiek, každá zoznam `(index kľúča, hodnota)`; rovnaká sada je v dlaždici raz |
| `retazce` | hodnoty voľných kľúčov (`name`, `ref`, `maxheight`…) |
| `zakazy` | druh, výnimky (`except`), reťaz hrán ako dvojice OSM `id` uzlov v smere jazdy |
| `okraj` | uzly, ktoré ležia mimo tejto dlaždice – tie sa nájdu aj vedľa |
| `profil` | krok v dm, počet hrán, počet vzoriek na hranu, prvé vzorky ako Δ medzi hranami, potom v každej hrane Δ od predošlej |

**Blok `profil` je až za `okrajom` a preto sa verzia formátu nedvíha.**
Čítačka, ktorá o ňom nevie, dočíta dlaždicu po `okraj` a zvyšok nechá ležať,
takže archív s profilmi je čitateľný aj pre appku spred neho – hlásila by len
stúpanie z koncov hrán, tak ako dovtedy. Nová čítačka nad starým archívom vidí
príznak `profil` nulový a nesiaha za `okraj`.

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

Poradie ráta [`workers/routing/order.sh`](../workers/routing/order.sh) nad
PBF celého územia (`workers/routing/pbf.sh`, ten istý, z akého sa stavia
celoštátny graf) a leží v cache na Drive pod kľúčom
`routing-order-v1-<územie>-<run_id>`. **Build kraja si ho odtiaľ vezme** cez
`restore-keys`, teda najnovšie uložené poradie toho územia – a keď tam nie je
alebo je staršie než 30 dní (`order_max_age_days`), **dopočíta ho sám a uloží**,
takže prvý kraj štafety ho vyrobí a ostatné ho vezmú. Ručne ho skôr prepočíta
**„Navigácia · poradie uzlov"** ([`routing-order.yml`](../.github/workflows/routing-order.yml))
tým istým skriptom. Ktoré územie to je, hovorí `routing_area` pri krajine
vo `workers/data/regions.json` – všetky kraje krajiny musia stáť na tom istom.
Že kľúč znie na všetkých stranách rovnako, stráži
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
iná vrstva, do manifestu pod `routing` a odtiaľ do **základnej mapy** (časť
`navigacia`, `casti_baliku` vo `workers/deploy/subory.py`) **aj do balíka
`cesty`** (`workers/data/packages.json`): kto má mapu, dá sa v nej doviezť, a
kto si berie len siete, dostane aj tú, po ktorej sa počíta trasa. Vlastný
balík `navigacia` zanikol (`zrusene`). Predfilter PBF si berie zoznam tried zo
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
    --poradie=data/routing-order.json \
    --dem=dem/dmr5/all.vrt --profil-krok=5

python3 workers/lint/routing-tiles.py _site/tiles/*-routing.pmtiles

# vzorové archívy pre testy čítačky v appke (skifahrer/rikimaps)
python3 workers/routing/fixture.py --out=/tmp/fixture
```

Vzorový archív je písaný ručne, nie z PBF: jedna križovatka so zákazom
odbočenia, hrana cez hranicu dlaždice a hustá mriežka, ktorá sa rozdelí na
z10. `--out` napíše šesť súborov – celú sieť a jej západný a východný výrez,
ktoré zdieľajú hranu cez hranicu a spájajú sa podľa OSM id, sieť ciest:
hlavný ťah s obchádzkami po miestnych uliciach a dve ulice spojené jedine
poľnou cestou, raz krátkou a raz dlhou, cestu cez hrebeň, ktorá jediná má
výšky a profily (dve vlny na hrane, aby sa stúpanie z profilu nedalo
zameniť s rozdielom koncov), a sieť križovatiek na pokyny: diaľnica s výjazdom a nájazdom,
kruhový objazd so štyrmi ramenami, vidlica, zmena mena ulice a slepý koniec
s jedinou odbočkou. Poradie uzlov je nad všetkým, čo `fixture.py` píše, takže
archívy sa dajú čítať aj spolu.

Vedľa nich ešte `iny-rank/routing-fixture-east.pmtiles`: ten istý východný
výrez pod iným `id` poradia a s inými rankmi. Je tam preto, aby ho mala appka
čo odmietnuť, takže do behu nepatrí a lint sa nad ním nepúšťa.
