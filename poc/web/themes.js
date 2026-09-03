/**
 * Farebné témy a generátor MapLibre štýlu pre OpenMapTiles schému
 * (výstup Planetileru). Zdieľané medzi webom (prehliadač) a pipeline
 * (workers/styles/build.mjs generuje statické style.json aj pre iOS).
 *
 * Filozofia detailu:
 *   - do zoomu DETAIL_Z (14) sa mapa postupne "oreže" – nižšie zoomy
 *     ukazujú len dôležité prvky, aby bola čitateľná,
 *   - od DETAIL_Z vyššie sa nič nefiltruje: všetky body, línie aj plochy,
 *     ktoré OpenMapTiles schéma obsahuje, sú viditeľné,
 *   - dlaždice končia na zoome 16 (tvrdý limit Planetileru), vyššie zoomy
 *     (až po MAX_DISPLAY_Z = 20) rieši MapLibre overzoomom.
 *
 * Developer mode:
 *   Každá vrstva nesie `metadata` (`frico:group`, `frico:label`, `frico:kind`,
 *   `frico:palette`), takže sa dá v prehliadači vypísať, zapnúť/vypnúť a
 *   prefarbiť bez toho, aby sa zoznam vrstiev musel udržiavať dvakrát.
 *   Úpravy z developer módu prichádzajú späť ako `overrides` – ten istý
 *   objekt sa dá uložiť do zdrojáku (poc/web/style-overrides.json) a potom
 *   ho použije aj pipeline pre statické štýly pre iOS.
 */

import {
  ICON_SOURCE_IDS,
  CUSTOM_SET_PREFIX,
  allIconSources,
  iconSourceIn,
  DEFAULT_ICON_SOURCE,
  iconSource,
  specialIcons
} from "./icon-sources.js";
import {
  PATTERN_IDS,
  DASH_IDS,
  dashArray,
  dashIdOf,
  patternDef,
  patternImageName
} from "./patterns.js";
import {
  MARK_SHAPE_IDS,
  DEFAULT_MARK_SHAPE,
  MARK_BOX,
  MARK_MINZOOM,
  markImage
} from "./marks.js";
import { SHIELD_SHAPE_IDS } from "./shields.js";
import {
  MAP_TYPE_IDS,
  DEFAULT_MAP_TYPE,
  normalizeMapType,
  applyMapType,
  HISTORIC_CLASSES,
  MINING_CLASSES,
  SKI_CLASSES,
  ROAD_SERVICE_CLASSES
} from "./map-types.js";

/** Zoom, od ktorého je mapa plne detailná (nižšie sa orezáva). */
export const DETAIL_Z = 14;

/** Najvyšší zoom, na ktorý sa dá v mape priblížiť (overzoom nad dlaždicami). */
export const MAX_DISPLAY_Z = 20;

/** Najvyšší zoom dlaždíc, ktorý Planetiler dokáže vygenerovať. */
export const MAX_TILE_Z = 16;

/**
 * Zoom, od ktorého sú v mape vrstevnice a skaly – a pod ktorým nie sú vôbec.
 *
 * Na prehľadovej mierke sa nedá prečítať ani jedna vrstevnica a zo skál je
 * sivá škvrna, ale dlaždice s nimi si prehliadač aj tak sťahuje – čiže sa za
 * ten závoj platí veľkosťou podkladov. Od tohto zoomu je z vrstevníc LEN
 * hlavná trieda (`contour-major`), polovičná od z12 a základná od z13.
 *
 * To isté číslo je aj v schémach Planetilera (`min_zoom` vo
 * `workers/contours-rocks/{contours,rocks}.yml`), lebo tam rozhoduje, čo sa
 * vôbec VYROBÍ – tu len to, čo sa NAKRESLÍ. Keď sa tie dve čísla rozídu, nikto
 * nič nepovie: buď platíme dlaždice, ktoré nikto nevidí, alebo je v mape diera.
 * Stráži to `workers/lint/zoom-floor.py`.
 */
export const TERRAIN_MIN_Z = 11;

/**
 * Zdroj výškových dát pre tieňovanie reliéfu (hillshade) a 3D terén.
 * OpenStreetMap terénny model neobsahuje – `ele` je len bodový tag na
 * vrcholoch a pod. Terén preto ide z AWS Terrain Tiles (Terrarium),
 * ktoré sú verejné a bez autentifikácie.
 */
export const DEFAULT_DEM_TILES =
  "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";

/**
 * Najvyšší zoom výškových dlaždíc. AWS Terrain Tiles idú po z15; naše vlastné
 * (z 30 m DEM) končia nižšie – vyšší zoom by už nepridal detail, len veľkosť.
 * Skutočnú hodnotu dodá pipeline cez `demMaxzoom`.
 */
export const DEFAULT_DEM_MAXZOOM = 15;

/** Násobok prevýšenia 3D terénu. 1.3 mierne zvýrazní tvar chrbtov –
 *  je to tá istá hodnota, akú si web dovtedy nastavoval sám
 *  (`map.setTerrain` v `poc/web/app.js`), nech sa 3D na webe a v štýle
 *  pre iOS nerozchádza. */
export const DEFAULT_TERRAIN_EXAGGERATION = 1.3;

/**
 * Zdroje výšok, z ktorých pipeline počíta vrstevnice, skalné plochy
 * a tieňovanie. Kľúče sú tie isté ako vo `workers/data/dem-sources.json` a ako
 * v troch výberoch vo formulári „Build map" (`contour_source`, `rock_source`,
 * `shading_source`) – každá vrstva môže mať iný model.
 * Licencia každého z nich vyžaduje uvedenie zdroja, preto ide atribúcia
 * priamo do zdroja v štýle (MapLibre ju zobrazí v rohu mapy).
 */
export const DEM_SOURCES = {
  sonny: {
    label: "Sonny's LiDAR DTM",
    note: "LiDAR model terénu – bez stromov a budov",
    attribution:
      '<a href="https://sonny.4lima.de/">Sonny\'s LiDAR DTM</a> (CC BY 4.0)'
  },
  dmr35: {
    label: "ÚGKK DMR 3.5 (10 m)",
    note: "otvorené dáta ÚGKK, mriežka presne 10 × 10 m",
    // Licencia ÚGKK je voľná vrátane komerčného použitia, ale PODMIENENÁ
    // uvedením zdroja – preto to tu je natvrdo, nie voliteľne.
    attribution: '<a href="https://www.geoportal.sk/">ÚGKK SR</a> – DMR 3.5'
  },
  dmr5: {
    label: "ÚGKK DMR 5.0 (LLS, 5 m)",
    note: "slovenský LiDAR prevzorkovaný na 5 m, celé Slovensko",
    attribution: '<a href="https://www.geoportal.sk/">ÚGKK SR</a> – DMR 5.0'
  },
  ugkk: {
    label: "ÚGKK DMR 5.0 (1 m LiDAR)",
    note: "slovenský 1 m LiDAR – najpodrobnejší dostupný model terénu",
    // Licencia ÚGKK je voľná vrátane komerčného použitia, ale PODMIENENÁ
    // uvedením zdroja – preto to tu je natvrdo, nie voliteľne.
    attribution:
      '<a href="https://www.geoportal.sk/">ÚGKK SR</a> – DMR 5.0'
  },
  copernicus: {
    label: "Copernicus GLO-30",
    note: "model povrchu vrátane stromov a budov",
    attribution: '<a href="https://spacedata.copernicus.eu/">Copernicus DEM</a>'
  }
};

/** Predvolený zdroj výšok (pipeline vie prepnúť inputom `dem_source`). */
export const DEFAULT_DEM_SOURCE = "sonny";

/**
 * TERÉNNA TROJICA – odkiaľ sa berú `background`, `rock` / `rockArea`
 * a `contour*`. Sú to farby papierovej horskej mapy, nie ozdoba:
 *
 *   podklad     #f0efeb   bielosivá – holý terén nad lesom, sneh, kamenie
 *   skaly a suť #9c9286   teplá stredná sivohnedá – skalnaté partie, sutiny
 *   vrstevnice  #8b8676   tenké olivovosivé línie s popiskom výšky
 *
 * PODKLAD JE BIELOSIVÝ, NIE ZELENKASTÝ – a je to rozhodnutie o tom, čo v mape
 * znamená zelená. V horách je nad hranicou lesa hola, kameň a sneh; keď mal
 * podklad zelený nádych, vyzeralo to celé ako riedka vegetácia a les sa od
 * neho odlíšil len o odtieň. **Zelená je odteraz vyhradená lesu** (`forest`)
 * – jediná sýta zelená v mape. Lúka, kosodrevina, záhrada či ihrisko sú
 * odstupňované do olivovo-khaki: vegetácia áno, les nie.
 *
 * Sivá pritom nie je neutrálna: má ten istý teplý zemitý nádych ako skaly
 * a vrstevnice (odtieň okolo 45°, sýtosť do 6 %). Neutrálna sivá vedľa
 * zemitých hnedých vyzerá domodra a mapa z toho vyjde studená.
 *
 * KAŽDÁ TÉMA MÁ SVOJ ODTIEŇ, LEN VEĽMI JEMNE INÝ. Nie sú to štyri kópie
 * jednej hodnoty: „Svetlá" je tá neutrálna, „Outdoor" o odtieň teplejšia
 * a tmavšia (je to turistická mapa), „Retro" o odtieň svetlejšia, a „Tmavá"
 * má tú istú **rodinu** preloženú do tmy – teda neutrálne teplú, nie
 * domodra ako predtým. Rozdiel medzi témami je pár krokov, aby sa dali od
 * seba rozoznať, ale aby žiadna nevyzerala ako iná mapa.
 *
 * POZOR NA VÝPLNE, KTORÉ PODKLAD DOBIEHA. `rock` (suť z OSM) sa kreslí
 * s krytím 0,8, takže sa s podkladom mieša – hodnota je preto tmavšia než
 * to, čo je vidieť: 0,8 × #807b6d nad #d9d6cc dá #928d80, čiže tú tmavšiu
 * sivohnedú o odtieň svetlejšie než počítané skalné plochy (`rockArea`,
 * krytie 1). To je zámer: suť je sypká a svetlejšia než stena.
 */
export const THEMES = {
  svetla: {
    label: "Svetlá",
    background: "#f0efeb",
    water: "#a4c8e8",
    waterOutline: "#88b0d8",
    river: "#a4c8e8",
    forest: "#b7d69f",
    grass: "#e4e6d2",
    park: "#d9e6c8",
    parkOutline: "#a8cf90",
    sand: "#f0e6c8",
    ice: "#eef6fa",
    wetland: "#d6e3d0",
    rock: "#968a7b",
    residential: "#eae6e1",
    industrial: "#e4dce8",
    cemetery: "#d3e0d0",
    hospital: "#f6e0e0",
    school: "#f0e8d8",
    military: "#eee0d8",
    quarry: "#ddd6cc",
    pitch: "#dbe4c4",
    garden: "#dfe6c6",
    playground: "#dff0d8",
    building: "#d9cfc5",
    buildingOutline: "#c4b8ac",
    buildingTop: "#e2d8ce",
    aeroway: "#e8e0e8",
    aerowayLine: "#ffffff",
    motorway: "#f0a862",
    motorwayCasing: "#d88a3c",
    trunk: "#f5c26b",
    primary: "#fcd6a4",
    secondary: "#f7ecc8",
    minor: "#ffffff",
    service: "#ffffff",
    pedestrian: "#f2efe9",
    roadCasing: "#c8bda8",
    path: "#55534d",
    footway: "#6d6a63",
    cycleway: "#6a8fd0",
    steps: "#c05a3a",
    track: "#b09060",
    rail: "#454545",
    railHatch: "#ffffff",
    ferry: "#8aa8c8",
    aerialway: "#8a8a8a",
    pier: "#e8e4dc",
    boundary: "#9e7bb5",
    boundaryLocal: "#b8a0c8",
    // Za hranicou stiahnutého regiónu mapa KONČÍ. `regionOutside` je farba
    // toho, čo je za ňou – zámerne tá istá ako `background`, takže tam nie je
    // „iné územie", ale prázdno; mapa sa nemá tváriť, že pokračuje. Odtieň je
    // napísaný a nie prevzatý z `background` preto, aby sa dal v developer
    // móde stlmiť zvlášť (napr. na jemne tmavší tón), keď má byť vidieť,
    // pokiaľ mapa siaha.
    regionOutside: "#f0efeb",
    regionBorder: "#9e7bb5",
    placeText: "#333333",
    roadText: "#5a4a3a",
    waterText: "#4a7bab",
    poiText: "#666655",
    textHalo: "#ffffff",
    poiIcon: "#5f6b52",
    poiIconHalo: "#ffffff",
    peakText: "#6a5a3a",
    geoText: "#6a6252",
    peakIcon: "#7a5a30",
    aerodromeIcon: "#6a6a80",
    onewayIcon: "#8a7a6a",
    roadLimit: "#b02a1a",
    houseText: "#a09488",
    // Tematické body – každý typ mapy má svoju „hlavnú" skupinu bodov
    // (hrady, bane, vleky, pumpy), nech sa dá zvýrazniť zvlášť.
    historicPoi: "#8a4a2a",
    miningPoi: "#5a5a6a",
    skiPoi: "#0f7ea0",
    servicePoi: "#3a6ea5",
    winterSports: "#e0eef6",
    contour: "#8b8676",
    contourMajor: "#77725f",
    contourText: "#6a6555",
    rockArea: "#9c9286",
    rockPattern: "#6b6154",
    // Prvky, ktoré schéma OpenMapTiles vôbec neprenáša (vlastný .pmtiles,
    // workers/features/features.yml) plus tie, ktoré v dlaždiciach sú, ale štýl ich
    // dlho nekreslil – bralná hrana, kosodrevina, cesta vo výstavbe.
    cliffLine: "#7a6a58",
    ridgeLine: "#a89880",
    scrub: "#d3d8b8",
    roadConstruction: "#e0c078",
    roadProposed: "#b0a48c",
    shieldMotorway: "#ba1e10",
    shieldEuro: "#008c27",
    shieldPrimary: "#1f5aa6",
    shieldSecondary: "#ffffff",
    shieldText: "#ffffff",
    shieldTextDark: "#1a1a1a",
    shieldBorder: "#ffffff",
    shieldBorderDark: "#3a3a3a",
    parking: "#e8e4f0",
    farmyard: "#eee4d2",
    dam: "#b0a898",
    embankment: "#a89078",
    wall: "#8a7a66",
    fence: "#a8a08e",
    hedge: "#9dc088",
    powerLine: "#9a94a8",
    cutline: "#c8bfa8",
    treeRow: "#8fbf78",
    pisteArea: "#e8f2fa",
    pisteLine: "#4a90c8",
    featurePoi: "#3f7a6a",
    trailFerrata: "#c04a1a",
    // Tri farby tieňovania reliéfu majú ALFU a je to to podstatné na nich:
    // MapLibre nimi svah PREKRÝVA (krytie rastie so sklonom), takže bez alfy
    // je nad 20° pod tieňovaním vidieť už len tú farbu a nie mapu. Rozpis
    // aj namerané čísla sú pri vrstve `hillshade` nižšie.
    hillShadow: "#5a4a3ab3",
    hillHighlight: "#ffffff5c",
    hillAccent: "#8a7a6a38",
    // Značené trasy. Prvá desiatka sú farby značiek, ako ich pozná OSM
    // (`osmc:symbol`, `colour`): dáta nesú meno farby, mapa až tento odtieň –
    // takže sa dá každá značka doladiť zvlášť a v každej téme inak. Zvyšok sú
    // farby podľa druhu trasy, ktoré sa použijú, keď značka farbu nemá.
    trailRed: "#d42a2a",
    trailBlue: "#2a54c8",
    trailGreen: "#1f8a3c",
    trailYellow: "#d8a000",
    trailBlack: "#3a3a3a",
    trailWhite: "#ffffff",
    trailOrange: "#e2700c",
    trailBrown: "#8a5a2c",
    trailPurple: "#8a3aa8",
    trailGray: "#7c7c7c",
    trailHiking: "#b8342c",
    trailCycling: "#cc2f9c",
    trailMtb: "#7a3aa0",
    trailSki: "#0f9ec0",
    trailHorse: "#8a6a3a",
    trailHalo: "#ffffff"
  },
  tmava: {
    label: "Tmavá",
    background: "#1b1b19",
    water: "#16213e",
    waterOutline: "#1d2b52",
    river: "#16213e",
    forest: "#17251a",
    grass: "#232219",
    park: "#202a20",
    parkOutline: "#2a4030",
    sand: "#2a2820",
    ice: "#1e2630",
    wetland: "#18241d",
    rock: "#34312a",
    residential: "#1b1b28",
    industrial: "#201b28",
    cemetery: "#1a231c",
    hospital: "#281b20",
    school: "#242015",
    military: "#2a1f1f",
    quarry: "#242028",
    pitch: "#26281d",
    garden: "#26261c",
    playground: "#1e2a20",
    building: "#262433",
    buildingOutline: "#33304a",
    buildingTop: "#302d40",
    aeroway: "#232030",
    aerowayLine: "#3a3750",
    motorway: "#b0763a",
    motorwayCasing: "#7a4e20",
    trunk: "#8a6a35",
    primary: "#6a5a35",
    secondary: "#4a4238",
    minor: "#33303f",
    service: "#2b2836",
    pedestrian: "#22222e",
    roadCasing: "#0e0e16",
    path: "#8b8880",
    footway: "#75726a",
    cycleway: "#41618f",
    steps: "#7a4030",
    track: "#5a4a35",
    rail: "#26263a",
    // Priečky na železnici sú v svetlej téme BIELE – čiže presne tak svetlé
    // ako podklad, a vidieť ich je len proti tmavej čiare koľajnice. Prepis
    // toho na „skoro bielu" tu robil opak: proti tmavému podkladu z nich bol
    // najsvetlejší prvok mapy hneď po popiskoch (kontrast 9,8 : 1) a v meste,
    // kde je koľajísk najviac, svietili. Tmavý variant sa preto počíta OD
    // TMAVÉHO PODKLADU: proti koľajnici drží (2,6 : 1), proti pozadiu už nie.
    railHatch: "#65656f",
    ferry: "#3a4a66",
    aerialway: "#55556a",
    pier: "#2a2833",
    boundary: "#7a5f95",
    boundaryLocal: "#5f4a75",
    regionOutside: "#1b1b19",
    regionBorder: "#7a5f95",
    placeText: "#c8c8d8",
    roadText: "#9a8f80",
    waterText: "#5a7bab",
    poiText: "#9a95a8",
    textHalo: "#14141f",
    poiIcon: "#9aa6b8",
    poiIconHalo: "#14141f",
    peakText: "#a8a08a",
    geoText: "#a8a090",
    peakIcon: "#b09a70",
    aerodromeIcon: "#8a8ab0",
    onewayIcon: "#7a7a90",
    roadLimit: "#c0503c",
    houseText: "#6a6678",
    historicPoi: "#d08a5a",
    miningPoi: "#9a9ab0",
    skiPoi: "#5ad0e8",
    servicePoi: "#7aa4ff",
    winterSports: "#1a2430",
    contour: "#4f4b40",
    contourMajor: "#6f6a5c",
    contourText: "#8e8a7c",
    rockArea: "#403c33",
    rockPattern: "#6a6152",
    // Prvky, ktoré schéma OpenMapTiles vôbec neprenáša (vlastný .pmtiles,
    // workers/features/features.yml) plus tie, ktoré v dlaždiciach sú, ale štýl ich
    // dlho nekreslil – bralná hrana, kosodrevina, cesta vo výstavbe.
    cliffLine: "#8a7a64",
    ridgeLine: "#6a6050",
    scrub: "#272a1e",
    roadConstruction: "#6a5628",
    roadProposed: "#585044",
    shieldMotorway: "#d63a2a",
    shieldEuro: "#1fa544",
    shieldPrimary: "#3a6fb5",
    shieldSecondary: "#e9e9f2",
    shieldText: "#f2f2f8",
    shieldTextDark: "#14141e",
    shieldBorder: "#14141e",
    shieldBorderDark: "#14141e",
    parking: "#23202e",
    farmyard: "#2a2419",
    dam: "#3a3630",
    embankment: "#5a4c3e",
    wall: "#4e463a",
    fence: "#3e3a34",
    hedge: "#2a4028",
    powerLine: "#4a4658",
    cutline: "#3a352c",
    treeRow: "#2f4a2a",
    pisteArea: "#18232e",
    pisteLine: "#3a7098",
    featurePoi: "#6aa898",
    trailFerrata: "#c05a2a",
    hillShadow: "#000000b3",
    hillHighlight: "#4a4a605c",
    hillAccent: "#2a2a3a38",
    // V tmavej téme sa značky nekreslia doslova: čierna značka by na tmavom
    // podklade zmizla, preto je svetlosivá. Podstatné je, aby sa dala od
    // ostatných rozoznať – nie aby mala presne tú farbu, čo v teréne.
    trailRed: "#ff6a6a",
    trailBlue: "#7aa4ff",
    trailGreen: "#5ecb6a",
    trailYellow: "#ffd45a",
    trailBlack: "#b4b4c2",
    trailWhite: "#ffffff",
    trailOrange: "#ffa350",
    trailBrown: "#c48a5c",
    trailPurple: "#c481e0",
    trailGray: "#9c9caa",
    trailHiking: "#e07a7a",
    trailCycling: "#f07ad2",
    trailMtb: "#b47ade",
    trailSki: "#5ad0e8",
    trailHorse: "#c0a070",
    trailHalo: "#14141f"
  },
  outdoor: {
    label: "Outdoor / Turistická",
    background: "#edece8",
    water: "#8ec4dd",
    waterOutline: "#6faac6",
    river: "#7ab8d4",
    forest: "#9ecb84",
    grass: "#dcdec2",
    park: "#cfdcb4",
    parkOutline: "#88b070",
    sand: "#ecdfb5",
    ice: "#ffffff",
    wetland: "#bcd8c0",
    rock: "#928678",
    residential: "#e8e2d0",
    industrial: "#ddd6c4",
    cemetery: "#c5d4b5",
    hospital: "#eedcd0",
    school: "#e6dcc0",
    military: "#e2cfc4",
    quarry: "#cfc7b4",
    pitch: "#d0dab2",
    garden: "#d5dcb8",
    playground: "#d2e8b8",
    building: "#c8b8a0",
    buildingOutline: "#a89880",
    buildingTop: "#d8c8b0",
    aeroway: "#ddd8cc",
    aerowayLine: "#f4f1e4",
    motorway: "#e88a4a",
    motorwayCasing: "#b5642a",
    trunk: "#eeaa55",
    primary: "#f2c96b",
    secondary: "#f5e9b8",
    minor: "#fdfaf2",
    service: "#fdfaf2",
    pedestrian: "#efe9da",
    roadCasing: "#a89878",
    path: "#4c4b45",
    footway: "#63615a",
    cycleway: "#3060b0",
    steps: "#a02818",
    track: "#96703c",
    rail: "#42423a",
    railHatch: "#f4f1e4",
    ferry: "#5f93b5",
    aerialway: "#5a5a5a",
    pier: "#e0dac8",
    boundary: "#8a6aa0",
    boundaryLocal: "#a880b8",
    regionOutside: "#edece8",
    regionBorder: "#8a6aa0",
    placeText: "#2a2a1a",
    roadText: "#4a3a2a",
    waterText: "#33688a",
    poiText: "#4a5a3a",
    textHalo: "#ffffff",
    poiIcon: "#3f5a30",
    poiIconHalo: "#f4f1e4",
    peakText: "#5a3a20",
    geoText: "#5a4a2e",
    peakIcon: "#8a3a10",
    aerodromeIcon: "#4a5a7a",
    onewayIcon: "#6a5a45",
    roadLimit: "#8f2414",
    houseText: "#8a7a60",
    historicPoi: "#8a3a10",
    miningPoi: "#5a5548",
    skiPoi: "#0894b8",
    servicePoi: "#2a5f9a",
    winterSports: "#dceef6",
    contour: "#888372",
    contourMajor: "#746f5c",
    contourText: "#676152",
    rockArea: "#988e82",
    rockPattern: "#675e51",
    // Prvky, ktoré schéma OpenMapTiles vôbec neprenáša (vlastný .pmtiles,
    // workers/features/features.yml) plus tie, ktoré v dlaždiciach sú, ale štýl ich
    // dlho nekreslil – bralná hrana, kosodrevina, cesta vo výstavbe.
    cliffLine: "#6f5a44",
    ridgeLine: "#9a8468",
    scrub: "#c9cfa6",
    roadConstruction: "#d8a848",
    roadProposed: "#a89878",
    shieldMotorway: "#b31d10",
    shieldEuro: "#00821f",
    shieldPrimary: "#1a56a0",
    shieldSecondary: "#fffaf0",
    shieldText: "#fffaf0",
    shieldTextDark: "#2a2418",
    shieldBorder: "#fffaf0",
    shieldBorderDark: "#4a4238",
    parking: "#e6e2ee",
    farmyard: "#e8dcc2",
    dam: "#a89e8a",
    embankment: "#9a7f60",
    wall: "#7d6a52",
    fence: "#a09680",
    hedge: "#8ab86a",
    powerLine: "#8e8898",
    cutline: "#c2b596",
    treeRow: "#77b45c",
    pisteArea: "#e2f0f8",
    pisteLine: "#2f86bc",
    featurePoi: "#2f6f5c",
    trailFerrata: "#b03c14",
    hillShadow: "#6a5030b3",
    hillHighlight: "#fffaf05c",
    hillAccent: "#9a806038",
    // Outdoor téma je na turistiku – značky sú tu najsýtejšie, aby sa dali
    // rozoznať aj cez vrstevnice a tieňovanie.
    trailRed: "#cc2222",
    trailBlue: "#1f4fc0",
    trailGreen: "#18862e",
    trailYellow: "#e0a800",
    trailBlack: "#2e2e2e",
    trailWhite: "#ffffff",
    trailOrange: "#e06a00",
    trailBrown: "#7d5124",
    trailPurple: "#8226a4",
    trailGray: "#6e6e6e",
    trailHiking: "#c02a20",
    trailCycling: "#c41a92",
    trailMtb: "#7a2ea0",
    trailSki: "#0894b8",
    trailHorse: "#7d5a30",
    trailHalo: "#f4f1e4"
  },
  retro: {
    label: "Retro / Pastel",
    background: "#f2f0ea",
    water: "#b5d5c5",
    waterOutline: "#95bfa9",
    river: "#a5cbb8",
    forest: "#c7dfa8",
    grass: "#eae9d4",
    park: "#e2e6cc",
    parkOutline: "#c0d8a8",
    sand: "#f5e8cc",
    ice: "#f2f5f0",
    wetland: "#cfe0d5",
    rock: "#9a8e7f",
    residential: "#f7ecdd",
    industrial: "#efe2dc",
    cemetery: "#e0e5d2",
    hospital: "#f8e2dc",
    school: "#f5ead5",
    military: "#f0dcd4",
    quarry: "#e2d8cc",
    pitch: "#e2e6c8",
    garden: "#e6e6cc",
    playground: "#e8f0d4",
    building: "#e8c8b8",
    buildingOutline: "#d0a890",
    buildingTop: "#f0d8c8",
    aeroway: "#eee2d8",
    aerowayLine: "#fdf6ec",
    motorway: "#e08a7a",
    motorwayCasing: "#b8604e",
    trunk: "#eaa88a",
    primary: "#f2c8a0",
    secondary: "#f5e2c5",
    minor: "#fffdf8",
    service: "#fffdf8",
    pedestrian: "#f8f2e8",
    roadCasing: "#d5bfa5",
    path: "#5f5c54",
    footway: "#736f66",
    cycleway: "#7a9fb8",
    steps: "#b06048",
    track: "#b58e6a",
    rail: "#5e5348",
    railHatch: "#fdf6ec",
    ferry: "#8fb8a8",
    aerialway: "#a89c90",
    pier: "#f0e6da",
    boundary: "#c090a8",
    boundaryLocal: "#c8a0b8",
    regionOutside: "#f2f0ea",
    regionBorder: "#c090a8",
    placeText: "#5a4a45",
    roadText: "#7a5a4a",
    waterText: "#4a8a7a",
    poiText: "#8a7060",
    textHalo: "#ffffff",
    poiIcon: "#8a6a55",
    poiIconHalo: "#fdf6ec",
    peakText: "#7a6250",
    geoText: "#8a7362",
    peakIcon: "#9a6a40",
    aerodromeIcon: "#7a7a95",
    onewayIcon: "#a89080",
    roadLimit: "#d4604a",
    houseText: "#b0a294",
    historicPoi: "#a06a4a",
    miningPoi: "#8a8078",
    skiPoi: "#7ab8c0",
    servicePoi: "#6a8fb8",
    winterSports: "#e8f0f2",
    contour: "#8f8a7a",
    contourMajor: "#7b7663",
    contourText: "#6e6959",
    rockArea: "#a0968a",
    rockPattern: "#70665a",
    // Prvky, ktoré schéma OpenMapTiles vôbec neprenáša (vlastný .pmtiles,
    // workers/features/features.yml) plus tie, ktoré v dlaždiciach sú, ale štýl ich
    // dlho nekreslil – bralná hrana, kosodrevina, cesta vo výstavbe.
    cliffLine: "#96745c",
    ridgeLine: "#c0a488",
    scrub: "#dedcc0",
    roadConstruction: "#dcb87c",
    roadProposed: "#b4a488",
    shieldMotorway: "#a83428",
    shieldEuro: "#3f7a48",
    shieldPrimary: "#4a6fa0",
    shieldSecondary: "#fffdf8",
    shieldText: "#fffdf8",
    shieldTextDark: "#3a3226",
    shieldBorder: "#fffdf8",
    shieldBorderDark: "#6a5c46",
    parking: "#efe8f0",
    farmyard: "#f2e6d2",
    dam: "#c4b8a8",
    embankment: "#b89476",
    wall: "#a08a70",
    fence: "#c0b4a4",
    hedge: "#b0cc98",
    powerLine: "#b0a8b8",
    cutline: "#ddd0b8",
    treeRow: "#a8c890",
    pisteArea: "#eef4f6",
    pisteLine: "#6aa8c8",
    featurePoi: "#5a8a78",
    trailFerrata: "#c06038",
    hillShadow: "#8a6a58b3",
    hillHighlight: "#fffdf85c",
    hillAccent: "#c0a09038",
    trailRed: "#d06a5a",
    trailBlue: "#6a8fb8",
    trailGreen: "#6aa06a",
    trailYellow: "#d8b45a",
    trailBlack: "#6a5a55",
    trailWhite: "#fffdf8",
    trailOrange: "#d8905a",
    trailBrown: "#a07a5a",
    trailPurple: "#a87aa8",
    trailGray: "#9a9088",
    trailHiking: "#c07a68",
    trailCycling: "#b8608e",
    trailMtb: "#a87aa8",
    trailSki: "#7ab8c0",
    trailHorse: "#a08a68",
    trailHalo: "#fdf6ec"
  }
};

/**
 * Rozdelenie farieb palety do skupín – slúži developer módu na to, aby sa
 * dali farby hľadať a hromadne meniť. Musí pokrývať všetky kľúče témy
 * (okrem `label`); kontroluje to `paletteCoverage()`.
 */
export const PALETTE_GROUPS = [
  {
    id: "zaklad",
    label: "Základ a reliéf",
    keys: [
      ["background", "Pozadie mapy"],
      ["hillShadow", "Tieň reliéfu"],
      ["hillHighlight", "Osvetlená strana reliéfu"],
      ["hillAccent", "Akcent reliéfu"]
    ]
  },
  {
    id: "voda",
    label: "Voda",
    keys: [
      ["water", "Vodná plocha"],
      ["waterOutline", "Obrys vodnej plochy"],
      ["river", "Rieka / potok"],
      ["waterText", "Popisok vody"]
    ]
  },
  {
    id: "krajina",
    label: "Krajinná pokrývka",
    keys: [
      ["forest", "Les"],
      ["grass", "Tráva / lúka / pole"],
      ["park", "Park"],
      ["parkOutline", "Obrys parku"],
      ["sand", "Piesok"],
      ["ice", "Ľadovec"],
      ["wetland", "Mokraď"],
      ["rock", "Skaly / suť"],
      ["rockPattern", "Kamienky v suti (vzor)"],
      // Kosodrevina a kroviny sú v dlaždiciach ako `landcover subclass`, ale
      // `class` majú `grass` – bez vlastnej farby by lúka a kosodrevina
      // vyzerali rovnako, čo je v Tatrách dosť podstatný rozdiel.
      ["scrub", "Kroviny a kosodrevina"]
    ]
  },
  {
    id: "uzemie",
    label: "Využitie územia",
    keys: [
      ["residential", "Obytná zóna"],
      ["industrial", "Priemysel / obchod"],
      ["cemetery", "Cintorín"],
      ["hospital", "Nemocnica"],
      ["school", "Školstvo"],
      ["military", "Vojenský priestor"],
      ["quarry", "Lom / skládka"],
      ["garden", "Záhrada / sad"],
      ["playground", "Ihrisko / zoo"],
      ["pitch", "Športovisko"],
      ["winterSports", "Lyžiarske stredisko"],
      ["parking", "Parkovisko"],
      ["farmyard", "Hospodársky dvor"],
      ["dam", "Priehradný múr a hať"]
    ]
  },
  {
    id: "budovy",
    label: "Budovy",
    keys: [
      ["building", "Budova (plochá)"],
      ["buildingOutline", "Obrys budovy"],
      ["buildingTop", "Budova 3D"],
      ["houseText", "Súpisné číslo"]
    ]
  },
  {
    id: "cesty",
    label: "Cesty",
    keys: [
      ["motorway", "Diaľnica"],
      ["motorwayCasing", "Obrys diaľnice"],
      ["trunk", "Rýchlostná cesta"],
      ["primary", "Cesta I. triedy"],
      ["secondary", "Cesta II./III. triedy"],
      ["minor", "Miestna cesta"],
      ["service", "Účelová cesta"],
      ["pedestrian", "Pešia zóna"],
      ["roadCasing", "Obrys ciest"],
      ["roadText", "Popisok cesty"],
      ["roadConstruction", "Cesta vo výstavbe"],
      ["roadProposed", "Plánovaná cesta"],
      // Štítky s číslom cesty podľa ČESKOSLOVENSKÉHO ZNAČENIA – červená D/R,
      // modrá I. trieda, biela II./III. Farba čiary sa na to nedá použiť:
      // výplne ciest sú vo všetkých témach svetlé (žltkasté, béžové)
      // a biele číslo na nich nie je čitateľné.
      //
      // Kedysi tu bola zelená a bolo to zámenou tabule za štítok: na diaľnici
      // je zelená SMEROVÁ TABUĽA, ale ČÍSLO cesty sa píše do červeného štítka.
      // Na mape je vidieť štítok.
      ["shieldMotorway", "Štítok D a R"],
      ["shieldEuro", "Štítok E-cesty (E75)"],
      ["shieldPrimary", "Štítok cesty I. triedy"],
      ["shieldSecondary", "Štítok cesty II./III. triedy"],
      ["shieldText", "Číslo na farebnom štítku"],
      ["shieldTextDark", "Číslo na bielom štítku (II./III.)"],
      ["shieldBorder", "Orámovanie farebného štítka"],
      ["shieldBorderDark", "Orámovanie bieleho štítka (II./III.)"]
    ]
  },
  {
    id: "chodniky",
    label: "Chodníky a cestičky",
    keys: [
      ["path", "Turistický chodník"],
      ["footway", "Chodník / priechod"],
      ["cycleway", "Cyklotrasa"],
      ["steps", "Schody"],
      ["track", "Poľná / lesná cesta"]
    ]
  },
  {
    id: "trasy",
    label: "Značené trasy",
    keys: [
      ["trailRed", "Značka červená"],
      ["trailBlue", "Značka modrá"],
      ["trailGreen", "Značka zelená"],
      ["trailYellow", "Značka žltá"],
      ["trailBlack", "Značka čierna"],
      ["trailWhite", "Značka biela"],
      ["trailOrange", "Značka oranžová"],
      ["trailBrown", "Značka hnedá"],
      ["trailPurple", "Značka fialová"],
      ["trailGray", "Značka sivá"],
      ["trailHiking", "Turistická trasa (bez farby)"],
      ["trailCycling", "Cyklotrasa (bez farby)"],
      ["trailMtb", "Horská cyklotrasa (bez farby)"],
      ["trailSki", "Lyžiarska trasa (bez farby)"],
      ["trailHorse", "Jazdecká trasa (bez farby)"],
      ["trailFerrata", "Ferrata (bez farby)"],
      ["trailHalo", "Podklad pod pásikom trasy"]
    ]
  },
  {
    id: "doprava",
    label: "Železnica a ostatná doprava",
    keys: [
      ["rail", "Železnica"],
      ["railHatch", "Čiarkovanie železnice (svetlý diel)"],
      ["ferry", "Kompa"],
      ["aerialway", "Lanovka / vlek"],
      ["pier", "Mólo"],
      ["aeroway", "Letisková plocha"],
      ["aerowayLine", "Dráha / rolovacia dráha"]
    ]
  },
  {
    id: "vrstevnice",
    label: "Vrstevnice a skaly",
    keys: [
      ["contour", "Vrstevnica"],
      ["contourMajor", "Hlavná vrstevnica"],
      ["contourText", "Popisok výšky"],
      ["rockArea", "Skalné plochy (plná výplň)"],
      // Bralná hrana a hrebeň sú `natural=cliff/ridge/arete` – v dlaždiciach
      // sú ako LÍNIE vo vrstve `mountain_peak`, nie ako skalná plocha z DEM.
      ["cliffLine", "Bralná hrana (z OSM)"],
      ["ridgeLine", "Hrebeň (z OSM)"]
    ]
  },
  {
    id: "hranice",
    label: "Hranice",
    keys: [
      ["boundary", "Štátna / krajská hranica"],
      ["boundaryLocal", "Okresná / obecná hranica"],
      ["regionOutside", "Mimo stiahnutého regiónu"],
      ["regionBorder", "Okraj stiahnutého regiónu"]
    ]
  },
  {
    id: "popisky",
    label: "Popisky a ikony",
    keys: [
      ["placeText", "Názov sídla"],
      ["textHalo", "Obrys písmen (čitateľnosť)"],
      ["geoText", "Názov pohoria / oblasti"],
      ["poiText", "Popisok POI"],
      ["poiIcon", "Ikona POI"],
      ["poiIconHalo", "Obrys ikony POI"],
      ["peakText", "Popisok vrcholu"],
      ["peakIcon", "Ikona vrcholu"],
      ["aerodromeIcon", "Ikona letiska"],
      ["onewayIcon", "Šípka jednosmerky"],
      ["roadLimit", "Obmedzenie na ceste (výška, hmotnosť, rýchlosť)"]
    ]
  },
  {
    id: "prvky",
    label: "Krajinné prvky (vlastné dlaždice)",
    keys: [
      ["embankment", "Násyp a zárez"],
      ["wall", "Múr a hradby"],
      ["fence", "Plot a zábradlie"],
      ["hedge", "Živý plot"],
      ["powerLine", "Elektrické vedenie"],
      ["cutline", "Priesek"],
      ["treeRow", "Stromoradie"],
      ["pisteArea", "Zjazdovka (plocha)"],
      ["pisteLine", "Zjazdovka a bežka (čiara)"],
      ["featurePoi", "Prameň, jaskyňa, rozhľadňa"]
    ]
  },
  {
    id: "temy",
    label: "Tematické body (typy máp)",
    keys: [
      ["historicPoi", "Pamiatka (historická mapa)"],
      ["miningPoi", "Baňa, halda, lom (historická mapa)"],
      ["skiPoi", "Lyžiarske stredisko (lyžiarska mapa)"],
      ["servicePoi", "Pumpa a servis (cestná mapa)"]
    ]
  }
];

/** Všetky kľúče palety v poradí skupín. */
export const PALETTE_KEYS = PALETTE_GROUPS.flatMap((g) => g.keys.map(([k]) => k));

/** Ľudský popis kľúča palety. */
export const PALETTE_LABELS = Object.fromEntries(
  PALETTE_GROUPS.flatMap((g) => g.keys)
);

/**
 * Kontrola, že skupiny palety pokrývajú presne kľúče témy. Vracia rozdiely –
 * používa to test v pipeline, aby nová farba v téme nezostala v developer
 * móde neviditeľná.
 */
export function paletteCoverage() {
  const themeKeys = new Set(
    Object.keys(THEMES.svetla).filter((k) => k !== "label")
  );
  const grouped = new Set(PALETTE_KEYS);
  return {
    missing: [...themeKeys].filter((k) => !grouped.has(k)),
    extra: [...grouped].filter((k) => !themeKeys.has(k))
  };
}

/** Skupiny vrstiev tak, ako ich vypisuje developer mode. */
export const LAYER_GROUPS = [
  { id: "zaklad", label: "Základ a reliéf" },
  { id: "krajina", label: "Krajinná pokrývka" },
  { id: "uzemie", label: "Využitie územia" },
  { id: "voda", label: "Voda" },
  { id: "vrstevnice", label: "Vrstevnice a skaly" },
  { id: "letiska", label: "Letiská" },
  { id: "budovy", label: "Budovy" },
  { id: "cesty", label: "Cesty" },
  { id: "chodniky", label: "Chodníky a cestičky" },
  { id: "trasy", label: "Značené trasy" },
  // Vlastné dlaždice s tým, čo schéma OpenMapTiles nemá – násypy, múry,
  // ploty, vedenia, pramene, zjazdovky (workers/features/features.yml).
  { id: "prvky", label: "Krajinné prvky (mimo schémy)" },
  { id: "doprava", label: "Železnica a ostatná doprava" },
  { id: "hranice", label: "Hranice" },
  { id: "popisky", label: "Popisky" },
  { id: "poi", label: "POI a body záujmu" },
  { id: "geo", label: "Pohoria a geografické názvy" },
  { id: "sidla", label: "Sídla" }
];

/** Druhy vrstiev (pre filtre „body / línie / plochy" v developer móde). */
export const LAYER_KINDS = [
  { id: "area", label: "Plochy" },
  { id: "line", label: "Línie" },
  { id: "point", label: "Body" },
  { id: "text", label: "Popisky" },
  { id: "3d", label: "3D" },
  { id: "raster", label: "Reliéf" }
];

/**
 * Záložný zoznam ikon (bez prípony `_11`) pre prípad, že sa nepodarí načítať
 * sprite index. Ak sprite index k dispozícii je, zoznam sa berie z neho –
 * vďaka tomu nikdy neodkazujeme na ikonu, ktorá v sprite neexistuje
 * (chýbajúca ikona = symbol sa nevykreslí).
 */
const FALLBACK_ICONS = [
  "alcohol_shop", "art_gallery", "attraction", "bakery", "bank", "bar",
  "beer", "bicycle", "bus", "cafe", "campsite", "car", "castle", "cemetery",
  "cinema", "clothing_store", "college", "dentist", "doctors", "drinking_water",
  "fast_food", "fire_station", "fuel", "golf", "grocery", "harbor",
  "hospital", "ice_cream", "information", "library", "lodging", "monument",
  "museum", "park", "parking", "pharmacy", "picnic_site", "place_of_worship",
  "playground", "police", "post", "railway", "restaurant", "school", "shop",
  "stadium", "swimming", "theatre", "toilets", "town_hall", "veterinary", "zoo"
];

/**
 * Ikony, ktoré sú samy o sebe len geometrický tvar (kruh, štvorec, …).
 * Ako ikona POI nič nehovoria – mapa s nimi vyzerá ako pole bodiek, preto
 * sa z výberu vylučujú a POI bez vlastnej ikony zostane len s popiskom.
 */
/**
 * Triedy, pre ktoré má sada ikonu `<trieda><prípona>`.
 *
 * Je to funkcia, a nie riadok v `buildStyle`, lebo tú istú otázku si kladie
 * aj developer mode: bez nej by v paneli pri každej kategórii svietilo
 * „bez ikony" alebo naopak ikona, ktorú sada nemá – teda niečo iné, než je
 * v mape. Čisto geometrické tvary (kruh, štvorec…) sa vynechávajú: POI bez
 * vlastnej ikony nemá dostať kruh, ale zostať len s popiskom.
 */
export function iconClassesOf(icons, suffix) {
  return (
    icons && icons.length
      ? [
          ...new Set(
            icons
              .filter((n) => (suffix ? n.endsWith(suffix) : !/_\d+$/.test(n)))
              .map((n) => (suffix ? n.slice(0, -suffix.length) : n))
          )
        ]
      : FALLBACK_ICONS
  ).filter((n) => !SHAPE_ICONS.has(n));
}

/**
 * IKONA JEDNEJ KATEGÓRIE – jedna otázka, jedna odpoveď.
 *
 * Poradie je to isté, aké má výraz v štýle: najprv to, čo si vybral developer
 * mode (`overrides.poi.icons`, prázdny reťazec = „žiadna"), potom
 * `<trieda><prípona>` zo sady, a keď ju sada nemá, nič – žiadne náhradné
 * koliesko. Pýta sa na to štýl (aby vedel, čo nakresliť) aj panel (aby vedel,
 * čo ukázať), a keby si to počítali zvlášť, panel by raz ukazoval inú ikonu,
 * než je v mape.
 *
 * @param {string} cls  `subclass` alebo `class` z dlaždíc
 * @param {{classes: string[], suffix: string, overrides?: object}} opts
 */
export function poiIconName(cls, { classes, suffix, overrides }) {
  const own = overrides?.poi?.icons?.[cls];
  if (own !== undefined) return own;
  return classes.includes(cls) ? `${cls}${suffix || ""}` : "";
}

const SHAPE_ICONS = new Set([
  "circle", "circle_stroked", "square", "square_stroked",
  "triangle", "triangle_stroked", "star", "star_stroked",
  "dot_9", "dot_10", "dot_11", "marker", "cross",
  "default_1", "default_2", "default_3", "default_4", "default_5", "default_6"
]);

const DEFAULT_FONTS = {
  regular: "Noto Sans Regular",
  bold: "Noto Sans Bold",
  italic: "Noto Sans Italic"
};

/**
 * Interpolácia šírky čiary podľa zoomu: zw([[z, w], …]).
 *
 * Pozn.: `["zoom"]` smie byť podľa MapLibre style-spec iba priamym vstupom
 * najvrchnejšieho `interpolate`/`step`. Preto sa šírky obrysov (casing)
 * počítajú pripočítaním k jednotlivým stopom (`widen`), nie výrazom `["+", …]`.
 */
const zw = (stops) => [
  "interpolate",
  ["exponential", 1.5],
  ["zoom"],
  ...stops.flat()
];

/** Lineárna interpolácia podľa zoomu. */
const zl = (stops) => ["interpolate", ["linear"], ["zoom"], ...stops.flat()];

/**
 * ZOOMOVÉ PÁSMA: `zs([[9, 11, 2], [12, 12, 4], [13, 17, 6]])` – „od z9 do z11
 * takto, na z12 takto, od z13 vyššie takto".
 *
 * PREČO POPRI KRIVKE EŠTE PÁSMA. Krivka (`zw`/`zl`) odpovedá na otázku „ako
 * hodnota RASTIE", pásmo na otázku „čo platí v tomto rozsahu". Kým bola
 * k dispozícii len krivka, druhá otázka sa musela písať cez prvú: „od z9 do
 * z11 hrúbka 2" znamenalo napísať zlom `[9, 2]` A EŠTE `[11, 2]`, inak sa
 * hodnota medzi nimi plynulo menila – teda tú istú hodnotu dvakrát, na každej
 * hranici pásma, a pri troch pásmach šesť zlomov namiesto troch riadkov. Pri
 * strope {@link MAX_PAINT_STOPS} sa do toho zmestili štyri pásma.
 *
 * SÉMANTIKA (jedna veta, aby sa nedala pochopiť dvoma spôsobmi):
 * pásmo `[od, do, hodnota]` platí pre zoomy `od ≤ z < do + 1`, teda `do` je
 * VRÁTANE aj s desatinami (na z11,7 ešte platí pásmo `do 11`). Pásma musia
 * ísť za sebou BEZ MEDZIER a BEZ PREKRYVOV (`ďalšie od = predošlé do + 1`)
 * a zadávajú sa v CELÝCH zoomoch – desatiny sú otázka pre krivku, nie pre
 * pásmo. Pod prvým `od` a nad posledným `do` platí krajné pásmo (rovnako
 * ako `interpolate` drží krajné hodnoty za svojimi krajnými zlomami).
 *
 * PREČO `step` A NIE `interpolate` S DVOMA ZLOMAMI NA PÁSMO. Vnútri pásma je
 * hodnota KONŠTANTNÁ a na hranici SKOČÍ – to je celý zmysel pásma. Cez
 * `interpolate` sa to zapísať nedá: susedné pásma `[9,11]` a `[12,12]` by
 * potrebovali zlomy 9, 11, 12, 12 a dva zlomy na tom istom zoome MapLibre
 * odmietne aj s celým štýlom. A `["zoom"]` smie byť podľa style-spec iba
 * priamym vstupom najvrchnejšieho výrazu, takže sa krivka DO pásma vnoriť
 * nedá ani obchádzkou – kto chce plynulý prechod, píše krivku.
 */
const zs = (bands) => {
  const s = sortBands(bands);
  if (s.length === 1) return s[0][2];
  return [
    "step",
    ["zoom"],
    s[0][2],
    ...s.slice(1).flatMap(([od, , v]) => [od, v])
  ];
};

/** Rozšíri každý stop o konštantu – použité na obrysy ciest. */
const widen = (stops, extra) => stops.map(([z, w]) => [z, w + extra]);

/** Bezpečné čítanie atribútu pre `in`/porovnania (chýbajúci atribút = ""). */
const str = (prop) => ["coalesce", ["get", prop], ""];
const num = (prop, fallback) => ["coalesce", ["get", prop], fallback];

/**
 * IBA PLOCHY – povinná stráž pre `fill` vrstvu nad vrstvou so ZMIEŠANOU
 * geometriou.
 *
 * MapLibre `fill` vrstve NEPRESKOČÍ čiary. Prvok pustí do výplne bez ohľadu
 * na typ geometrie a otvorenú lomenú čiaru pošle earcutu, ako keby to bol
 * uzavretý prstenec – vypadne z toho sebaprekrývajúci sa mnohouholník, ktorý
 * s tou čiarou nemá nič spoločné. `fill-outline-color` mu k tomu obtiahne
 * hrany, takže to v mape vyzerá ako útvar „prerezaný" cez krajinu.
 *
 * PRÁVE TO BOLI TIE ČUDNÉ POLYGÓNY OD ZOOMU 13 na obyčajnej mape (bez skál
 * a vrstevníc). Vinníkom bola `pedestrian-area`: `fill` nad vrstvou
 * `transportation` s `class in [pedestrian, path]` a `minzoom: 13`. Vo vrstve
 * `transportation` sú chodníky ČIARY a Planetiler ich pri
 * `--transportation_z13_paths=true` (workers/tiles/build.sh) púšťa do dlaždíc
 * práve od z13 – teda presne odtiaľ, odkiaľ tie útvary pribúdali. A prečo bolo
 * „vnútri len podklad": farba `pedestrian` je od `background` na nerozoznanie
 * (svetlá téma #f2efe9 vs #f8f4f0), takže z toho bola plocha v barve podkladu,
 * ktorá prekryla les aj lúku pod sebou, a `roadCasing` jej obtiahol obrys.
 *
 * Pri `fill` nad `transportation`, `aeroway`, `park` a `piste` teda platí:
 * `class` NESTAČÍ, treba aj typ geometrie. (Ten istý druh omylu ako
 * `LINE_CLASSES` nižšie, len z druhej strany: tam symbolová vrstva umiestnila
 * bod na líniu, tu výplňová vrstva vyplnila líniu.)
 */
const POLYGON_ONLY = ["==", ["geometry-type"], "Polygon"];
const polygonOnly = (filter) =>
  filter ? ["all", POLYGON_ONLY, filter] : POLYGON_ONLY;

/**
 * Triedy `mountain_peak`, ktoré nie sú bodovým vrcholom, ale pretiahnutým
 * útvarom – hrebeňom či masívom. Popisujú územie, takže sa kreslia ako
 * geografický názov, nie ako vrchol s výškou.
 */
const RANGE_CLASSES = ["ridge", "arete", "massif", "range", "mountain_range"];

/**
 * Triedy `mountain_peak`, ktoré prídu ako **línia**, nie ako bod.
 * `natural=cliff`, `ridge` a `arete` mapuje Planetiler do tej istej vrstvy
 * ako vrcholy, ale s líniovou geometriou (MountainPeak.java, od z13). Bez
 * tohto zoznamu dostane bralná hrana doprostred trojuholníček vrcholu aj
 * s popiskom – symbolová vrstva totiž líniu umiestni ako bod.
 */
const PEAK_LINE_CLASSES = ["ridge", "arete", "cliff"];

/** Triedy `place`, ktoré nie sú sídlom, ale geografickou oblasťou. */
const GEO_PLACE_CLASSES = ["island", "archipelago", "peninsula", "region", "sea", "bay"];

/**
 * Farby značiek, ako ich nesú dlaždice (workers/trails/routes.py normalizuje
 * `osmc:symbol` a `colour` na tieto mená) → kľúče palety. Meno vo dvojici je
 * to, čo je v dátach; odtieň dáva až téma.
 */
export const TRAIL_MARK_COLOURS = [
  ["red", "trailRed"],
  ["blue", "trailBlue"],
  ["green", "trailGreen"],
  ["yellow", "trailYellow"],
  ["black", "trailBlack"],
  ["white", "trailWhite"],
  ["orange", "trailOrange"],
  ["brown", "trailBrown"],
  ["purple", "trailPurple"],
  ["gray", "trailGray"]
];

// ------------------------------------------------- odstup pásikov od cesty
// Zoomy, na ktorých sú zlomy všetkých troch kriviek nižšie. Musia byť tie
// isté: `line-offset` sa skladá z odstupu aj rozostupu v JEDNOM `interpolate`
// (`["zoom"]` smie byť len vstupom toho najvrchnejšieho), takže sa hodnoty
// berú po indexoch.
export const TRAIL_OFFSET_ZOOMS = [9, 11, 13, 14, 16, 20];

/**
 * ŠÍRKA PÁSIKA – a zároveň ROZOSTUP dvoch trás na tej istej ceste.
 *
 * Je to JEDNA krivka naschvál: rozostup nie je vlastné číslo, ktoré by sa
 * dalo naladiť, je to šírka pásika. Kým to boli dve krivky, rozišli sa –
 * nie v hodnotách pri zlomoch, ale MEDZI nimi: šírka sa interpoluje
 * `exponential 1.5` (ako všetky hrúbky v štýle), rozostup sa interpoloval
 * lineárne, takže pri z18 bol rozostup 4,3 px na pásik široký 3,65 px.
 * Tá sedmina pixela medzery nie je biela – je v nej vidieť podklad pásikov
 * (`trail-halo`), čiže medzi červenou a modrou trasou viedla tmavá čiara
 * a vyzeralo to, že sú trasy od seba odsunuté. Preto ju teraz kreslí tá istá
 * krivka aj s tým istým druhom interpolácie a pásiky sa dotýkajú na KAŽDOM
 * zoome, nie len na tých šiestich, kde sú zlomy.
 */
export const TRAIL_STRIPE = [
  [9, 0.9], [11, 1.11], [13, 1.54], [14, 1.9], [16, 2.6], [20, 6]
];
/** Rozostup dvoch trás = šírka pásika. Tá istá krivka, nie kópia. */
export const TRAIL_PITCH = TRAIL_STRIPE;

// Odstup osi prvého pásika od osi cesty, v pixeloch. Nie je to odhad – je to
// spočítané z toho, aké široké sú v štýle čiary pod ním: polovica čiary +
// polovica pásika (a pri ceste ešte obrys, ktorý `widen` pridáva k CELEJ
// šírke, takže z osi trčí polovicou).
//
//   miestna cesta    9 px + 1,6 obrys = 10,6 → okraj 5,3 od osi; pásik je
//   (z16)            2,6 široký, takže 5,3 + 1,3 = 6,6 a práve sa jej dotýka
//   lesná cesta      3,5 px → okraj 1,75; 1,75 + 1,3 = 3,05 by bol dotyk,
//   a chodník        3,6 necháva jemnú medzeru, nech je pod pásikom vidieť
//                    aj samotný chodník (a to, že je prerušovaný)
//
// Cesta je jedna hodnota pre všetky triedy ciest, hoci diaľnica je širšia než
// účelová – pásik sa presne dotýka MIESTNEJ cesty, po ktorej trasy chodia
// najčastejšie. Rozlišovať triedu cesty by znamenalo dotiahnuť ju do dlaždíc
// trás a to za tie dve desatiny pixela nestojí.
//
// POD z16 UŽ NEROZHODUJE ŠÍRKA ČIARY, ALE METRE. Pixel je pri z13 dvanásť
// metrov, takže odstup 2,6 px odsunul pásik od chodníka o 33 m – viac, než je
// v horách rozostup ramien serpentíny. `line-offset` posúva každý vrchol po
// osi zlomu, takže taký pásik obieha vlásenku oblúkom širším než je samotná
// zákruta, ramená sa navzájom prekryjú a v mape je z toho farebná PLOCHA,
// nie čiara. Odstup je preto zhora ohraničený tým, koľko je pri ceste miesta
// V TERÉNE: 8 m pri chodníku, 12 m pri ceste (chodník má serpentíny tesnejšie
// než cesta). Nad z16 je ohraničenie voľnejšie než výpočet zo šírky čiary,
// takže tam neplatí nič nové – kde bol pásik pri z16 a vyššie, tam ostal.
// Stráži to `workers/lint/trails.mjs`, aby sa veľké čísla nevrátili.
//
//   metrov na pixel (48,7° s. š.):  z13 12,6   z14 6,31   z16 1,58   z20 0,10
export const TRAIL_OFFSET_ROAD = [
  [9, 0.06], [11, 0.24], [13, 0.95], [14, 1.9], [16, 6.6], [20, 19.8]
];
export const TRAIL_OFFSET_PATH = [
  [9, 0.04], [11, 0.16], [13, 0.63], [14, 1.27], [16, 3.6], [20, 11.0]
];

/** Koľko metrov od cesty smie pásik najviac ísť (rozpis vyššie). */
export const TRAIL_OFFSET_LIMIT_M = { road: 12, path: 8 };

/**
 * SPOJ PÁSIKA V ZÁKRUTE. `miter`, nie `round` – a je to tá vec, ktorá drží
 * pásik v ostrej zákrute rovnako tenký ako na rovine.
 *
 * MapLibre kreslí `line-offset` tak, že KAŽDÝ VRCHOL posunie po osi jeho
 * zlomu, a dĺžku toho posunu berie z toho, aký spoj je nastavený:
 *
 *   `round`  posunie vrchol o odstup po NORMÁLE každého ramena zvlášť. Pásik
 *            sa teda k zlomu dostane dvoma rovnobežkami, ktoré sa nestretnú:
 *            na vonkajšej strane ostane medzi nimi KLIN (v mape biely zárez
 *            uprostred farebného pásika) a na vnútornej sa prekryjú. Pri troch
 *            značkách na jednej ceste si k tomu farby ešte prelezú cez seba.
 *   `miter`  posunie vrchol po OSI zlomu o `odstup / cos(zlom/2)`, čo je
 *            presne roh rovnobežky – pásik má v zákrute ten istý ostrý uhol
 *            ako chodník pod ním a rovnakú hrúbku.
 *
 * `line-miter-limit` je poistka pre vlásenky: `odstup / cos(zlom/2)` rastie
 * nad všetky medze (pri zlome 173° je to 16-násobok odstupu, teda výbežok cez
 * pol obrazovky), takže nad dvojnásobok – čo je zlom 120° – MapLibre spoj
 * zreže (`bevel`). Špička vlásenky je potom useknutá rovno; obe ramená ostanú
 * rovnobežné so svojím chodníkom a nič sa neroztiahne. Je to predvolená
 * hodnota MapLibre, ale píše sa sem naschvál: je to poistka, nie detail.
 *
 * Geometria sa pritom NEUPRAVUJE. Pásik má presne tie body, ktoré má cesta
 * v OSM – zaobliť zlom v dátach by znamenalo, že pásik zákrutu odreže a ide
 * inokade než chodník pod ním.
 */
export const TRAIL_JOIN = { "line-join": "miter", "line-miter-limit": 2 };
/** Metrov na pixel pri z0 v strede Slovenska (48,7° s. š.). */
export const METRES_PER_PX_Z0 = 156543.03 * Math.cos((48.7 * Math.PI) / 180);

/** Referenčný zoom, v ktorom sa odstupy zadávajú aj ladia. */
export const TRAIL_GAP_ZOOM = 16;
const atZoom = (stops, z) => (stops.find(([sz]) => sz === z) || [, 0])[1];

/** Predvolené odstupy v pixeloch pri z16 – to, čo prepisuje developer mode. */
export const TRAIL_GAP_DEFAULTS = {
  road: atZoom(TRAIL_OFFSET_ROAD, TRAIL_GAP_ZOOM),
  path: atZoom(TRAIL_OFFSET_PATH, TRAIL_GAP_ZOOM),
  pitch: atZoom(TRAIL_PITCH, TRAIL_GAP_ZOOM)
};

/**
 * Účinné odstupy: predvolené, prípadne prepísané z developer módu. Celá
 * krivka sa potom škáluje pomerom voči predvolenej hodnote pri z16, takže
 * jedno číslo posunie pásiky na všetkých zoomoch rovnako.
 */
export function trailGapPx(overrides) {
  const raw = overrides?.trails?.gap || {};
  const out = { ...TRAIL_GAP_DEFAULTS };
  for (const key of Object.keys(TRAIL_GAP_DEFAULTS)) {
    const n = Number(raw[key]);
    // Nula je platná odpoveď („nalep to priamo na čiaru"), záporná nie –
    // z tej by bol pásik na opačnej strane, než hovorí `side`.
    if (Number.isFinite(n) && n >= 0 && n <= 60) out[key] = n;
  }
  return out;
}

// -------------------------------------------- značky trás v pravidelných
// TURISTICKÁ A CYKLISTICKÁ ZNAČKA sa kreslí pozdĺž trasy ako obrázok zo
// spritu (`poc/web/marks.js`, pečie `workers/assets/marks.mjs`), nie ako
// ikonka druhu trasy. Rozdiel je v tom, čo hovorí: ikonka povie „tadiaľ ide
// nejaká turistická trasa", značka povie „sleduj červený pás na bielom" –
// a to je presne to, podľa čoho sa človek v teréne orientuje.

/**
 * ROZOSTUP ZNAČIEK po trase v pixeloch obrazovky. Značenie v teréne je
 * pravidelné (KČT má odporúčaných ~100–250 m), takže má byť pravidelné aj
 * v mape – a v pixeloch, nie v metroch: pri odzoomovaní by inak z trasy bola
 * šnúra štvorcov a pri priblížení by na obrazovke nebola ani jedna.
 */
export const TRAIL_MARK_SPACING = [[12, 150], [14, 190], [16, 230], [20, 260]];

/** Veľkosť značky (`icon-size` nad obrázkom širokým `MARK_BOX` px). */
export const TRAIL_MARK_SIZE = [[12, 0.5], [14, 0.75], [16, 1], [20, 1.3]];

/** Referenčný zoom, v ktorom sa rozostup aj veľkosť zadávajú a ladia. */
export const TRAIL_MARK_ZOOM = 16;

/**
 * ZNAČKY DVOCH TRÁS NA JEDNEJ CESTE SA STAVAJÚ NAD SEBA, nie na seba.
 *
 * Po jednom chodníku vedie bežne červená aj modrá turistická a k tomu
 * cyklotrasa – a všetky majú V DLAŽDICIACH TÚ ISTÚ GEOMETRIU (pásiky vedľa
 * seba robí až `line-offset`, ktorý na symboly neplatí). Kým bola značka
 * priamo na čiare, padli všetky na to isté miesto a MapLibre nechala jednu:
 * ostatné cez kolíziu ZAHODILA. Vždy tie isté, lebo poradie vrstiev je pevné –
 * modrá značka nebola v mape skoro nikde a vyzeralo to, že tade nevedie.
 * (Namerané v prehliadači: z troch trás na jednom chodníku bolo vidieť dve.)
 *
 * Značka sa preto posunie `icon-offset`-om podľa toho, KOĽKÁ JE TRASA V RADE
 * (`off`) a na ktorej strane cesty je jej pásik (`side`): pešie idú nahor,
 * kolesové nadol, a v rámci strany každá o svoju výšku ďalej. Vzniká z toho
 * stĺpik značiek nad rozcestím – presne tak, ako sú na strome nad sebou.
 *
 * `icon-offset` je v PIXELOCH, ktoré MapLibre násobí `icon-size` – takže sa
 * stĺpik škáluje so značkami sám, ale zadáva sa v pixeloch obrázka, nie
 * v jeho výškach. (Kým tu boli „výšky značky", teda 0,9 a 2,05, bol posun
 * v mape pod jeden pixel: značky ostali na čiare, kolízia z troch trás
 * nechala jednu a vyzeralo to, že tade ostatné nevedú. Overené v prehliadači
 * na chodníku s červenou, modrou a cyklotrasou.)
 *
 * `base` je odstup prvej značky od čiary (nech nezakrýva pásiky pod sebou),
 * `step` rozostup v stĺpiku.
 *
 * ZNAČKY STOJA TESNE NA SEBE, BEZ MEDZERY – tak, ako sú na strome. Obrázok
 * značky je `MARK_BOX` plus jeden priehľadný pixel na každej strane
 * (`MARK_PAD` – v atlase drží hranu od susedného obrázka), takže krok
 * `MARK_BOX` položí VIDITEĽNÉ štvorce presne na seba: priehľadné okraje sa
 * prekryjú a medzi tabuľkami nie je nič. Krok `MARK_IMAGE` by nechal medzeru
 * dvoch pixelov, krok 26 (ten tu bol) medzeru dvanástich.
 *
 * CENA JE `icon-allow-overlap`, A BEZ NEJ TO NEJDE. Kolízny obdĺžnik je celý
 * obrázok VRÁTANE priehľadného okraja plus `icon-padding`, takže sa dve
 * susedné priečky o dva pixely prekrývajú – a MapLibre by druhú značku
 * zahodila. Presne to sa dialo predtým z opačnej strany (pri kroku 16 bola
 * z červenej a modrej vidieť len červená) a riešilo sa to medzerou; odteraz
 * sa to rieši tým, že sa stĺpik kreslí bez ohľadu na kolízie. Je to bezpečné
 * práve pri ňom: rad je krátky (`TRAIL_MARK_STACK_MAX`), stojí kolmo na
 * trasu a čo si prekrýva, je jeho vlastná priečka. Stráži to
 * `workers/lint/marks.mjs`.
 */
export const TRAIL_MARK_STACK = { base: MARK_BOX + 4, step: MARK_BOX };

/**
 * Miesto okolo značky, ktoré si drží voľné (v pixeloch obrazovky).
 *
 * NULA, lebo stĺpik má stáť na sebe (viď `TRAIL_MARK_STACK`) a padding sa
 * na rozdiel od odstupu NEŠKÁLUJE s `icon-size` – pri malej značke by preto
 * vážil dvojnásobne a rad by rozhodil práve tam, kde je najtesnejší.
 */
export const TRAIL_MARK_PADDING = 0;

/** Koľko priečok stĺpika sa vymenuje (pozri `icon-offset` v štýle). */
export const TRAIL_MARK_STACK_MAX = 4;

/**
 * Predvolené hodnoty pri `TRAIL_MARK_ZOOM` – to, čo prepisuje developer mode.
 *
 * `step` medzi nimi nie je od zoomu: je to odstup v stĺpiku a MapLibre ho
 * násobí `icon-size`, takže sa so značkami škáluje sám.
 */
export const TRAIL_MARK_DEFAULTS = {
  spacing: atZoom(TRAIL_MARK_SPACING, TRAIL_MARK_ZOOM),
  size: atZoom(TRAIL_MARK_SIZE, TRAIL_MARK_ZOOM),
  step: TRAIL_MARK_STACK.step
};

/**
 * Medze tých troch čísel – JEDNO miesto pre normalizáciu, štýl aj políčka
 * v paneli. Kým boli napísané pri každom z nich zvlášť, mohli sa rozísť:
 * panel by pustil hodnotu, ktorú zápis do repozitára potom odmietne.
 *
 * Rozostup NESMIE byť nula (to nie je „žiadne značky", ale nekonečne veľa na
 * čiare – vypínajú sa tvarom „žiadna" pri druhu trasy), odstup v stĺpiku
 * nulu SMIE: vtedy sedia značky presne na sebe, čo je platná odpoveď na
 * „nechcem stĺpik".
 */
export const TRAIL_MARK_RANGES = {
  spacing: [20, 2000],
  size: [0.2, 4],
  step: [0, 80]
};

/**
 * Účinný rozostup a veľkosť značiek: predvolené, prípadne prepísané
 * z developer módu. Celá krivka sa škáluje pomerom voči hodnote pri
 * `TRAIL_MARK_ZOOM`, takže jedno číslo posunie značky na všetkých zoomoch –
 * tá istá úvaha ako pri odstupe pásikov (`trailGapPx`).
 */
export function trailMarkPx(overrides) {
  const raw = overrides?.trails?.marks || {};
  const out = { ...TRAIL_MARK_DEFAULTS };
  for (const [key, [min, max]] of Object.entries(TRAIL_MARK_RANGES)) {
    const n = Number(raw[key]);
    if (Number.isFinite(n) && n >= min && n <= max) out[key] = n;
  }
  return out;
}

/**
 * Druhy značených trás. Jeden zoznam pre štýl (vrstvy, ikony, prerušovanie),
 * developer mode aj popup vo viewri – inak by sa tri kópie časom rozišli.
 *
 * `palette` je farba, ktorá sa použije, keď trasa značku bez farby nemá;
 * `icons` sú kandidáti na ikonu v poradí, prvý existujúci v sade vyhráva.
 *
 * `dash` je ID predvoľby z `patterns.js`, nie pole čísel – tú istú predvoľbu
 * ponúka developer mode v záložke „Trasy", takže sa dá vzor čiary prepnúť bez
 * zásahu do kódu a uložený vzor znamená to isté tu aj tam.
 *
 * `side` je strana cesty (+1 / −1). Musí sedieť so `SIDE_BY_ROUTE`
 * vo `workers/trails/routes.py`, ktorý podľa nej číslu je rady – tu je len na
 * to, aby developer mode vedel povedať, čo kde uvidíš; posúva sa podľa dát.
 */
export const TRAIL_TYPES = [
  {
    id: "hiking",
    label: "Turistické trasy (značené)",
    short: "turistická trasa",
    palette: "trailHiking",
    icons: ["mountain", "triangle"],
    dash: "solid",
    side: 1
  },
  {
    // Ferrata je `route=via_ferrata` relácia ako každá iná značená trasa, len
    // vedie po skale. Vlastný druh preto, že sa má na prvý pohľad odlíšiť od
    // turistickej značky – po ferrate sa nedá ísť bez výstroja.
    id: "ferrata",
    label: "Ferraty",
    short: "ferrata",
    palette: "trailFerrata",
    icons: ["climbing", "mountain", "triangle"],
    dash: "dashed-fine",
    side: 1
  },
  {
    // Cyklotrasy sú bodkované a ružovo-fialové: značka v teréne farbu nemá
    // (na rozdiel od turistickej), takže farba je naša voľba – a musí sa
    // odlíšiť od turistických značiek, ktoré zaberajú červenú, modrú, zelenú
    // aj žltú. Kolesové trasy idú navyše na opačnú stranu cesty než pešie.
    id: "bicycle",
    label: "Cyklotrasy",
    short: "cyklotrasa",
    palette: "trailCycling",
    icons: ["bicycle"],
    dash: "dotted",
    side: -1
  },
  {
    id: "mtb",
    label: "Horské cyklotrasy (MTB)",
    short: "horská cyklotrasa",
    palette: "trailMtb",
    icons: ["bicycle"],
    dash: "dotted-dense",
    side: -1
  },
  {
    id: "ski",
    label: "Lyžiarske a bežkárske trasy",
    short: "lyžiarska trasa",
    palette: "trailSki",
    icons: ["skiing", "mountain"],
    dash: "dashed-long",
    side: 1
  },
  {
    id: "horse",
    label: "Jazdecké trasy",
    short: "jazdecká trasa",
    palette: "trailHorse",
    icons: ["horse", "circle"],
    dash: "dashed-fine",
    side: 1
  }
];

export const TRAIL_TYPE_IDS = TRAIL_TYPES.map((t) => t.id);
const TRAIL_BY_ID = Object.fromEntries(TRAIL_TYPES.map((t) => [t.id, t]));

/**
 * Účinné nastavenie druhu trasy: zoznam vyššie + to, čo prepísal developer
 * mode (`overrides.trails.types`). Pýtajú sa naň štýl aj developer mode, tak
 * je odpoveď na jednom mieste – inak by panel ukazoval jedno a mapa kreslila
 * druhé.
 *
 * Farba tu NIE JE zámerne: tá ide cez paletu (`palette`), lebo z nej žije aj
 * pásik, aj ikona, aj názov trasy. Druhá cesta k tej istej farbe by sa raz
 * rozišla.
 */
export function trailTypeDef(type, overrides) {
  const own = overrides?.trails?.types?.[type.id] || {};
  const icon = typeof own.icon === "string" ? own.icon.trim() : "";
  // TVAR ZNAČKY má tri odpovede, nie dve: `undefined` je „ako je v OSM"
  // (`osmc:symbol` – pásová, vrcholová, bicykel…), prázdny reťazec „žiadna"
  // a meno tvaru „vždy tento". Prostredná sa nedá vyjadriť menom tvaru, tak
  // ako sa „žiadna ikona" nedá vyjadriť menom ikony.
  const mark = typeof own.mark === "string" ? own.mark.trim() : null;
  return {
    ...type,
    dash: DASH_IDS.includes(own.dash) ? own.dash : type.dash,
    // Ikonu treba vedieť aj VYPNÚŤ – prázdny reťazec je „žiadna", nie „vezmi
    // predvolenú"; trasa hustá na ikonky sa inak nedá zbaviť inak než skrytím
    // celej vrstvy.
    iconPick: "icon" in own ? (icon ? [icon] : []) : type.icons,
    markPick: mark === null ? null : (MARK_SHAPE_IDS.includes(mark) ? mark : "")
  };
}

/**
 * Tvar štítka s číslom cesty pre jednu triedu (`SHIELD_DEFS`), aj s tým, čo
 * na ňom prepísal developer mode (`overrides.shields[<trieda>].shape`).
 *
 * Prepnúť sa dá preto, že sprite nesie VŠETKY tvary naraz (pečie ich
 * `workers/assets/shields.mjs`) – v prehliadači sa tým mení len meno obrázka,
 * nič sa neprebuildováva. Neznámy tvar sa ticho ignoruje: obrázok, ktorý
 * v sprite nie je, by nechal číslo cesty bez podkladu.
 */
export function shieldShapeFor(id, fallback, overrides) {
  const want = overrides?.shields?.[id]?.shape;
  return typeof want === "string" && SHIELD_SHAPE_IDS.includes(want)
    ? want
    : fallback;
}

const isTunnel = ["==", ["get", "brunnel"], "tunnel"];
const isBridge = ["==", ["get", "brunnel"], "bridge"];
const isSurface = ["all", ["!=", ["get", "brunnel"], "tunnel"], ["!=", ["get", "brunnel"], "bridge"]];

// ===================== developer overrides =====================

/**
 * Prázdna sada úprav z developer módu.
 *
 * `layers` a `poi` platia pre **všetky** typy máp, `maps[<typ>]` len pre jeden.
 * Vďaka tomu sa dá povedať aj „táto farba všade" aj „na cestnej mape toto
 * nechcem" bez toho, aby sa úpravy museli držať štyrikrát.
 */
export function emptyOverrides() {
  return {
    version: 2,
    icons: DEFAULT_ICON_SOURCE,
    hillshade: false,
    palette: {},
    layers: {},
    // PORADIE KRESLENIA. Nie je to vlastnosť vrstvy (tá o svojich susedoch
    // nevie), ale zoznam presunov „túto kresli tesne pod tamtú" – rozpis pri
    // `applyLayerOrder`.
    order: [],
    // Značené trasy majú vlastnú položku, lebo to nie sú nastavenia JEDNEJ
    // vrstvy: jeden druh trasy má v štýle tri vrstvy (pásik, ikona, názov)
    // a odstup od cesty je vlastnosť všetkých naraz.
    trails: { gap: {}, types: {}, marks: {} },
    // Štítok s číslom cesty má vlastnú položku z toho istého dôvodu ako
    // trasy: nie je to nastavenie jednej vrstvy, ale tvar OBRÁZKA, ktorý si
    // vrstva pýta zo spritu – a ten sa nedá vyjadriť `paint` vlastnosťou.
    shields: {},
    // Vlastné sady ikoniek (sprite z cudzieho servera) a vlastné ikony
    // (obrázok, ktorý si človek nahrá). Sú to dve rôzne veci: sada je
    // odpoveď na „chcem INÉ ikony na všetko", vlastná ikona na „chcem TÚTO
    // jednu vec inak" – a preto sa nedajú stlačiť do jednej položky.
    iconSets: [],
    customIcons: [],
    poi: { hidden: [], icons: {} },
    maps: {}
  };
}

const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;

/** Tvar id vrstvy – to isté, čo pripúšťa MapLibre aj naše `__pattern`. */
const LAYER_ID = /^[A-Za-z0-9_.:-]{1,64}$/;

const isColor = (v) => typeof v === "string" && HEX.test(v.trim());

const clampZoom = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  return Math.min(24, Math.max(0, Math.round(n * 10) / 10));
};

/**
 * „BEZ VÝPLNE" – plocha, ktorá nemá farbu pozadia, ale ostane jej vzor
 * aj okraj.
 *
 * PREČO VLASTNÁ HODNOTA A NIE `krytie 0`. Krytie sa dá nastaviť na nulu už
 * dlho, ale robí niečo iné: `fill-opacity` násobí VŠETKO, čo tá vrstva kreslí
 * – teda aj obrys z `fill-outline-color` (má ho `pedestrian-area` a `building`).
 * Nulou by teda z budovy zmizla aj jej hrana a ostalo by prázdno. Priehľadná
 * FARBA vypne len výplň; `fill-outline-color` je vlastná vlastnosť a kreslí sa
 * ďalej. A nie je to ani `visible: false`: tým by zmizla celá vrstva vrátane
 * vzoru, ktorý na nej visí (odvodená vrstva drží viditeľnosť predlohy).
 *
 * V súbore úprav je to čitateľné slovo, nie `#00000000`, aby bolo pri čítaní
 * jasné, že je to zámer.
 */
export const NO_FILL = "none";
/** Kde má „bez výplne" zmysel – čiara sa vypína cez `visible`, nie farbou. */
const NO_FILL_PROPS = new Set(["fill-color", "fill-extrusion-color"]);
/** Strop počtu zoomových zlomov na jednu vlastnosť. */
export const MAX_PAINT_STOPS = 8;

/**
 * VLASTNOSTI Z `layout`, ktoré sa dajú prepísať – a ich medze.
 *
 * `paint` je „ako to vyzerá", `layout` je „ako to je rozložené", a MapLibre
 * ich drží zvlášť: veľkosť ikony ani rozostup symbolov po čiare v `paint`
 * nie sú. Práve tie dve pritom rozhodujú o tom, ako husto sedia turistické
 * značky po trase a aké sú veľké – teda o veci, ktorá sa ladí okom
 * a po jednom zoome, nie zmenou zdrojáku.
 *
 * Je to VYMENOVANÝ zoznam, nie „čokoľvek z layoutu": `symbol-placement`
 * alebo `icon-rotation-alignment` sú rozhodnutia štýlu (značka stojí
 * narovno, lebo natočená tabuľka už nie je tabuľka), nie ladenie – a
 * prepísané by tichým spôsobom rozbili to, čo je pri nich napísané.
 *
 * VŠETKY SÚ ZO SYMBOLOVEJ VRSTVY. Iný druh vrstvy ich nepozná a MapLibre by
 * taký štýl ODMIETOL CELÝ (neznáma vlastnosť v `layout` je tvrdá chyba, na
 * rozdiel od neznámej v `paint`), takže `applyLayerOverrides` ich inde než
 * na `symbol` nenasadí.
 *
 * `def` je PREDVOĽBA MAPLIBRE – to, čo platí, keď vlastnosť v štýle nie je.
 * Panel podľa nej ukáže, z čoho sa vychádza, aj pri vrstve, ktorá tú vlastnosť
 * nemá nastavenú, a percento má z čoho počítať (`overrideValue`). Bez toho sa
 * dala vlastnosť len ZMENIŤ, nie ZAVIESŤ: rozostup šípok jednosmeriek áno
 * (štýl mu dáva 120), miesto okolo ikony nie – a vyzeralo to, že tá páka
 * neexistuje. Čísla sú zo style-spec, nie odhad.
 */
export const LAYOUT_PROPS = {
  "icon-size": { min: 0.05, max: 8, step: 0.05, def: 1, label: "veľkosť ikony" },
  "symbol-spacing": { min: 1, max: 2000, step: 5, def: 250, label: "rozostup po čiare" },
  "icon-padding": { min: 0, max: 40, step: 1, def: 2, label: "miesto okolo ikony" },
  "text-size": { min: 1, max: 60, step: 0.5, def: 16, label: "veľkosť písma" }
};
export const LAYOUT_PROP_IDS = Object.keys(LAYOUT_PROPS);

/**
 * Zoradí zoomové zlomy podľa zoomu. JEDNA funkcia pre všetky tri cesty, ktoré
 * ich vyrábajú (import súboru, developer mode, skladanie štýlu) – poradie je
 * jedna otázka a musí mať jednu odpoveď.
 *
 * PREČO NA TOM ZÁLEŽÍ VIAC, NEŽ SA ZDÁ: `interpolate` vyžaduje stopy v STRIKTNE
 * RASTÚCOM poradí a MapLibre pri porušení odmietne CELÝ ŠTÝL, nie len tú
 * vlastnosť – mapa sa nenačíta vôbec. Overené jeho vlastným validátorom:
 * „Input/output pairs for "interpolate" expressions must be arranged with input
 * values in strictly ascending order." V developer móde pritom zlomy vznikajú
 * v poradí, v akom ich niekto naklikal (najprv z18, potom z12), takže
 * nezoradené je NORMÁLNY stav vstupu, nie pokazený.
 */
export const sortStops = (list) => [...list].sort((a, b) => a[0] - b[0]);

/**
 * To isté pre ZOOMOVÉ PÁSMA `[[od, do, hodnota], …]` – zoraďuje sa podľa `od`.
 *
 * Vlastná funkcia, hoci by `sortStops` zoradila to isté pole rovnako: pásmo
 * a zlom sú dva rôzne tvary a keby ich obsluhovala jedna funkcia, prvý, kto
 * do nej pridá čokoľvek o hodnote (napr. „jeden zlom nie je krivka"), to
 * spraví aj druhému.
 */
export const sortBands = (list) => [...list].sort((a, b) => a[0] - b[0]);

/**
 * Je to zoznam PÁSIEM (trojice), alebo zoznam ZLOMOV (dvojice)?
 *
 * Rozlišuje sa POČTOM PRVKOV V RIADKU, nie obalom navyše: `[9, 11, 2]` sa
 * číta ako „od 9 do 11 hodnota 2" a `[9, 2]` ako „na z9 hodnota 2" – v JSON
 * súbore úprav je to vidieť bez legendy. Miešať sa nesmú a `cleanPaintZoom`
 * to povie nahlas.
 */
export const isBandList = (list) =>
  Array.isArray(list) && list.length > 0 &&
  list.every((row) => Array.isArray(row) && row.length === 3);

/**
 * RELATÍVNA HODNOTA `{ "scale": 1.4, "add": 0.5 }` – „nechaj, čo štýl počíta,
 * a preškáluj to".
 *
 * ŠTVRTÝ TVAR VEDĽA SKALÁRU, KRIVKY A PÁSIEM, a je tu preto, že ostatné tri
 * odpovedajú na inú otázku. Skalár, krivka aj pásma hovoria „hodnota JE
 * takáto" – teda ZAHODIA to, čo štýl o tej vlastnosti vie. Pri hrúbke čiary
 * to znamená, že „cesty o štvrtinu hrubšie" sa nedalo povedať inak než
 * prepísaním celej krivky ručne, zvlášť pre každú triedu cesty, a prvý zoom
 * navyše alebo zmena v štýle to ticho rozhodila.
 *
 * Relatívna hodnota je oproti tomu ÚPRAVA NAD KRIVKOU: zoomový priebeh ostáva
 * ten zo štýlu, mení sa len jeho mierka. Preto sa nedá zadať „podľa zoomu" –
 * to by boli dve odpovede na tú istú otázku.
 *
 * LEN NA ČÍSLA. Farba sa škálovať nedá a `{scale: 1.4}` nad hexom by nebola
 * chyba, ktorú by niekto videl – bola by to farba, ktorá sa nezmenila.
 */
export const isRelative = (v) =>
  !!v && typeof v === "object" && !Array.isArray(v) &&
  ("scale" in v || "add" in v);

/** Medze relatívnej hodnoty – rovnaké pre `paint` aj `layout`. */
const REL_LIMITS = { scale: [0.1, 10], add: [-20, 40] };

/**
 * Hodnota z úprav → to, čo ide do štýlu.
 *
 * Skalár ostane skalárom, `none` sa zmení na priehľadnú farbu, POLE ZLOMOV
 * `[[zoom, hodnota], …]` na `interpolate` podľa zoomu a POLE PÁSIEM
 * `[[od, do, hodnota], …]` na `step` (v pásme konštanta, na hranici skok).
 * Jeden zlom nie je krivka a jedno pásmo nie je schodisko, takže z nich vyjde
 * obyčajná hodnota – jedna hodnota je čitateľnejšia než `interpolate`
 * s jediným stopom (ten by MapLibre prijal, ale nič nerobí).
 *
 * Zoradenie je tu ZÁMERNE, hoci ho robí aj kontrola pri importe a developer
 * mode pri zápise: toto je posledné miesto pred štýlom a jediný nevzostupný
 * pár tu zhodí celú mapu.
 */
export function paintValue(value) {
  if (value === NO_FILL) return "rgba(0,0,0,0)";
  if (!Array.isArray(value)) return value;
  // ZOOMOVÉ PÁSMA `[[od, do, hodnota], …]` → `step`: v pásme konštanta,
  // na hranici skok. Jediné pásmo nie je schodisko, takže z neho vyjde
  // obyčajná hodnota (`step` s jediným výstupom by nemal na čom skočiť).
  if (isBandList(value)) {
    const bands = sortBands(value);
    if (bands.length === 1) return paintValue(bands[0][2]);
    return [
      "step",
      ["zoom"],
      paintValue(bands[0][2]),
      ...bands.slice(1).flatMap(([od, , v]) => [od, paintValue(v)])
    ];
  }
  if (value.length === 1) return paintValue(value[0][1]);
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    ...sortStops(value).flatMap(([z, v]) => [z, paintValue(v)])
  ];
}

/**
 * ÚPRAVA NAD TÝM, ČO V ŠTÝLE UŽ JE.
 *
 * `paintValue` samo nestačí, lebo relatívna hodnota potrebuje ZÁKLAD – a ten
 * pozná až miesto, kde je po ruke vrstva. Preto sú to dve funkcie a nie jedna
 * s voliteľným argumentom: `paintValue` odpovedá na „čo to je", táto na „čo sa
 * z toho stane nad touto vrstvou".
 *
 * `fallback` je hodnota, ktorú by MapLibre použil, keby vlastnosť v štýle nebola
 * (`LAYOUT_PROPS[...].def`). Bez nej by percento nad nenastaveným rozostupom
 * nemalo z čoho počítať a ticho by nespravilo nič.
 */
export function overrideValue(base, value, fallback) {
  if (!isRelative(value)) return paintValue(value);
  const z = base === undefined ? fallback : base;
  if (z === undefined) return undefined;
  return scaleExpr(z, value);
}

/**
 * Skontroluje jednu hodnotu vlastnosti (bez zoomu). Vracia `undefined`, keď
 * nie je v poriadku – a vtedy už je dôvod v `problems`.
 */
function cleanPaintScalar(prop, value, id, problems, where, atZoom = "") {
  const kde = `${where}Vrstva "${id}": ${prop}${atZoom}`;
  if (prop.endsWith("-color")) {
    if (value === NO_FILL) {
      if (!NO_FILL_PROPS.has(prop)) {
        problems.push(`${kde} nemôže byť "${NO_FILL}" – bez výplne sa dá nechať `
          + `len plocha (${[...NO_FILL_PROPS].join(", ")}). Čiaru alebo popisok `
          + `vypni cez "visible", nie priehľadnou farbou.`);
        return undefined;
      }
      return NO_FILL;
    }
    if (!isColor(value)) {
      problems.push(`${kde} nie je hex farba (${value}).`);
      return undefined;
    }
    return String(value).toLowerCase();
  }
  // Sila tieňovania reliéfu. Je to jediná vlastnosť mimo trojice
  // farba/krytie/hrúbka, ktorú úpravy poznajú – a je tu preto, že „silnejšie
  // tieňovanie" je nastavenie, ktoré človek ladí okom a po jednom zoome, nie
  // zmenou zdrojáku. Menuje sa CELÁ, nie príponou `-exaggeration`: `hillshade`
  // je jediný druh vrstvy, ktorý ju má, a `line-exaggeration` z preklepu by
  // MapLibre odmietol aj s celým štýlom.
  if (prop === "hillshade-exaggeration") {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0 || n > 1) {
      problems.push(`${kde} musí byť medzi 0 a 1 (0 = bez tieňovania, 1 = najsilnejšie).`);
      return undefined;
    }
    return Math.round(n * 100) / 100;
  }
  if (prop.endsWith("-opacity") || prop.endsWith("-width")) {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0) {
      problems.push(`${kde} musí byť nezáporné číslo.`);
      return undefined;
    }
    // NULOVÁ HRÚBKA ČIARY JE TICHO ZMIZNUTÁ VRSTVA. Číselné políčko v developer
    // móde má šípky a prázdne políčko („auto") sa nimi skočí rovno na spodnú
    // medzu – jedno ťuknutie dole teda vrstvu zhaslo a v paneli po ňom ostala
    // len nula, na ktorej sa už nedalo poznať, čo sa stalo. Vypnúť vrstvu sa má
    // cez `visible`, kde je to vidieť aj v zozname. (Halo a obrys sa nerátajú –
    // tam nula znamená „žiadny lem", čo je normálna hodnota zo štýlu.)
    if (n === 0 && prop.endsWith("-width")
        && !prop.includes("halo") && !prop.includes("stroke")) {
      problems.push(`${kde} nesmie byť 0 – čiara s nulovou hrúbkou sa nekreslí `
        + `a v mape to vyzerá ako chýbajúce dáta. Vrstvu vypni cez "visible".`);
      return undefined;
    }
    return n;
  }
  problems.push(`${where}Vrstva "${id}": vlastnosť ${prop} sa nedá prepísať – preskakujem.`);
  return undefined;
}

/**
 * TMAVÝ VARIANT jednej farby (`paintDark`, `outline.colorDark`) – rozpis pri
 * `cleanLayers`. Vlastný čistič, a nie `cleanPaintScalar` s iným menom:
 * tmavý variant pozná LEN farbu (nikdy krivku, pásma ani percento – tie sa
 * tvárou vrstvy nemenia, len jej farbou), takže vlastnosť, ktorá nekončí na
 * "-color", je tu vždy chyba, kým `cleanPaintScalar` na tom istom mene prijme
 * aj krytie či hrúbku.
 */
function cleanDarkColor(prop, value, id, problems, where) {
  const kde = `${where}Vrstva "${id}": ${prop} (tmavý variant)`;
  if (!prop.endsWith("-color")) {
    problems.push(`${kde} – tmavý variant sa dá zadať len pre vlastnosti "*-color".`);
    return undefined;
  }
  if (value === NO_FILL) {
    if (!NO_FILL_PROPS.has(prop)) {
      problems.push(`${kde} nemôže byť "${NO_FILL}" – rovnako ako pri svetlom variante.`);
      return undefined;
    }
    return NO_FILL;
  }
  if (!isColor(value)) {
    problems.push(`${kde} nie je hex farba (${value}).`);
    return undefined;
  }
  return String(value).toLowerCase();
}

/**
 * Jedna hodnota vlastnosti z `layout` (bez zoomu).
 *
 * Oddelené od `cleanPaintScalar` preto, že sa pýta na inú vec: `paint`
 * pozná farbu, krytie a hrúbku podľa PRÍPONY mena, kým `layout` má
 * vymenovaný zoznam aj s medzami (`LAYOUT_PROPS`) – „rozostup 0" je
 * nekonečne veľa symbolov na čiare, „veľkosť 0" je neviditeľná ikona,
 * a ani jedno by nič nezhodilo.
 */
function cleanLayoutScalar(prop, value, id, problems, where, atZoom = "") {
  const kde = `${where}Vrstva "${id}": ${prop}${atZoom}`;
  const medze = LAYOUT_PROPS[prop];
  if (!medze) {
    problems.push(`${kde} sa nedá prepísať – z \`layout\` sa dajú `
      + `${LAYOUT_PROP_IDS.join(", ")}. Ostatné sú rozhodnutia štýlu, nie ladenie.`);
    return undefined;
  }
  const n = Number(value);
  if (!Number.isFinite(n) || n < medze.min || n > medze.max) {
    problems.push(`${kde} musí byť číslo od ${medze.min} do ${medze.max} (${value}).`);
    return undefined;
  }
  return Math.round(n * 100) / 100;
}

/**
 * Jedno číslo ŠÍRKY OKRAJA. Vlastný čistič, hoci `cleanPaintScalar` overuje
 * to isté meno vlastnosti: okraj má hornú medzu (40 px) a hlásenie o „šírke
 * okraja", nie o `line-width` – tú vlastnosť v súbore úprav nikto nenapísal.
 */
function outlineWidthScalar(prop, value, id, problems, where, atZoom = "") {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0 || n > 40) {
    problems.push(`${where}Vrstva "${id}": šírka okraja${atZoom} musí byť medzi 0 a 40 (${value}).`);
    return undefined;
  }
  return Math.round(n * 10) / 10;
}

/**
 * Skontroluje RELATÍVNU hodnotu `{ scale, add }` (rozpis pri `isRelative`).
 *
 * `popis` je meno vlastnosti do hlásenia – pri okraji to nie je `line-width`,
 * ale „šírka okraja", a hláška o vlastnosti, ktorú v súbore úprav nikto
 * nenapísal, by hľadanie chyby predĺžila, nie skrátila.
 */
function cleanRelative(prop, value, id, problems, where, popis = prop) {
  const kde = `${where}Vrstva "${id}": ${popis}`;
  if (prop.endsWith("-color")) {
    problems.push(`${kde} sa nedá zadať ako "scale"/"add" – preškálovať sa `
      + `dajú len čísla, nie farby.`);
    return undefined;
  }
  const out = {};
  for (const [kluc, [min, max]] of Object.entries(REL_LIMITS)) {
    if (value[kluc] == null) continue;
    const n = Number(value[kluc]);
    if (!Number.isFinite(n) || n < min || n > max) {
      problems.push(`${kde}: "${kluc}" musí byť číslo od ${min} do ${max} (${value[kluc]}).`);
      return undefined;
    }
    out[kluc] = Math.round(n * 100) / 100;
  }
  // `{scale: 1}` ani `{add: 0}` nie sú úprava – uložené by boli len šumom
  // v súbore a v paneli by svietilo „zmenené" nad vrstvou, ktorá sa nezmenila.
  if ((out.scale ?? 1) === 1 && (out.add ?? 0) === 0) {
    problems.push(`${kde}: "scale" 1 a "add" 0 nič nemenia – vynechávam.`);
    return undefined;
  }
  return out;
}

/**
 * Jedna hodnota vlastnosti v ktoromkoľvek z tvarov, ktoré úpravy poznajú:
 * relatívna, zoznam podľa zoomu (krivka či pásma), alebo obyčajný skalár.
 *
 * Je to JEDNA BRÁNA, lebo tá otázka je jedna a odpovedá sa na ňu na troch
 * miestach (`paint`, `layout`, šírka okraja). Keby si ju každé písalo samo,
 * raz by sa rozišli – a rozišli by sa ticho, lebo každý tvar je sám o sebe
 * platný vstup toho druhého.
 */
function cleanValue(prop, value, id, problems, where, scalar = cleanPaintScalar, popis) {
  if (isRelative(value)) return cleanRelative(prop, value, id, problems, where, popis);
  if (Array.isArray(value)) return cleanPaintZoom(prop, value, id, problems, where, scalar);
  return scalar(prop, value, id, problems, where);
}

/**
 * Zoznam podľa zoomu – KRIVKA alebo PÁSMA. Jedna brána pre oba tvary, aby
 * bolo na jednom mieste povedané, ktorý je ktorý a čo sa nesmie.
 *
 * MIEŠANIE JE TVRDÁ CHYBA, nie „nejako to vyriešime". `[[9, 2], [12, 13, 4]]`
 * sa dá prečítať dvoma spôsobmi (je to zlom pri z12 s hodnotou 13? alebo
 * pásmo?) a ktorúkoľvek stranu by sme uhádli, tá druhá by ticho zmizla –
 * presne ten druh chyby, po ktorej mapa vyzerá skoro dobre.
 */
function cleanPaintZoom(prop, list, id, problems, where, scalar = cleanPaintScalar) {
  const kde = `${where}Vrstva "${id}": ${prop}`;
  if (!Array.isArray(list) || !list.length) {
    problems.push(`${kde} má prázdny zoznam – vymaž ho, alebo doplň zlom či pásmo.`);
    return undefined;
  }
  const trojice = list.filter((r) => Array.isArray(r) && r.length === 3).length;
  const dvojice = list.filter((r) => Array.isArray(r) && r.length === 2).length;
  if (trojice && dvojice) {
    problems.push(`${kde} mieša dva tvary: dvojica \`[zoom, hodnota]\` je bod `
      + `plynulej krivky, trojica \`[od, do, hodnota]\` je zoomové pásmo `
      + `s konštantnou hodnotou. Zvoľ jeden a prepíš doň aj zvyšok.`);
    return undefined;
  }
  return trojice
    ? cleanPaintBands(prop, list, id, problems, where, scalar)
    : cleanPaintStops(prop, list, id, problems, where, scalar);
}

/**
 * Skontroluje pole ZOOMOVÝCH PÁSIEM `[[od, do, hodnota], …]`.
 *
 * Pásma musia pokrývať svoj rozsah SÚVISLE: `ďalšie od = predošlé do + 1`.
 * Medzera aj prekryv sú tvrdá chyba, a to z toho istého dôvodu ako pravidlo
 * „meno assetu je sľub o rozsahu" – „od 9 do 11" je sľub, že pásmo tam
 * naozaj končí. Keby sa medzera dopĺňala držaním predošlej hodnoty, `do 11`
 * by neplatilo a nikto by to nemal ako spozorovať; keby sa prekryv riešil
 * poradím, o tom istom zoome by rozhodovali dve pásma naraz.
 *
 * Zoomy sú CELÉ ČÍSLA. Pásmo je „na tomto zoome to vyzerá takto" a zoomy sa
 * v mape prepínajú po celých; desatina je otázka pre krivku, kde má zmysel.
 */
function cleanPaintBands(prop, list, id, problems, where, scalar = cleanPaintScalar) {
  const kde = `${where}Vrstva "${id}": ${prop}`;
  if (list.length > MAX_PAINT_STOPS) {
    problems.push(`${kde} má ${list.length} zoomových pásiem, strop je ${MAX_PAINT_STOPS}.`);
    return undefined;
  }
  const out = [];
  for (const band of list) {
    const [od, doZ, hodnota] = band;
    for (const [meno, z] of [["od", od], ["do", doZ]]) {
      if (!Number.isInteger(Number(z)) || z < 0 || z > MAX_DISPLAY_Z) {
        problems.push(`${kde}: "${z}" nie je celý zoom (0–${MAX_DISPLAY_Z}) – `
          + `pásmo sa zadáva celými zoomami ("${meno}"), desatiny patria krivke.`);
        return undefined;
      }
    }
    if (doZ < od) {
      problems.push(`${kde}: pásmo od z${od} do z${doZ} je naopak – "do" nesmie byť menšie než "od".`);
      return undefined;
    }
    const v = scalar(prop, hodnota, id, problems, where, ` v pásme z${od}–z${doZ}`);
    if (v === undefined) return undefined;
    out.push([Number(od), Number(doZ), v]);
  }
  const zoradene = sortBands(out);
  for (let i = 1; i < zoradene.length; i += 1) {
    const [, predoslyDo] = zoradene[i - 1];
    const [od] = zoradene[i];
    if (od === predoslyDo + 1) continue;
    problems.push(
      od <= predoslyDo
        ? `${kde}: pásma z${zoradene[i - 1][0]}–z${predoslyDo} a z${od}–z${zoradene[i][1]} `
          + `sa prekrývajú – o zoome z${od} by rozhodovali dve naraz.`
        : `${kde}: medzi pásmami z…–z${predoslyDo} a z${od}–z… chýbajú zoomy `
          + `z${predoslyDo + 1}–z${od - 1}. Predĺž jedno z nich, alebo tú medzeru vyplň pásmom.`
    );
    return undefined;
  }
  return zoradene;
}

/**
 * Skontroluje pole zoomových zlomov `[[zoom, hodnota], …]`.
 *
 * Zoomy musia RÁSŤ a nesmú sa opakovať: `interpolate` s neusporiadanými
 * stopmi MapLibre odmietne a s ním celý štýl, takže by sa mapa nenačítala
 * vôbec. Namiesto odmietnutia sa preto zoradia – z developer módu môžu prijsť
 * v poradí, v akom ich niekto naklikal.
 */
function cleanPaintStops(prop, list, id, problems, where, scalar = cleanPaintScalar) {
  const kde = `${where}Vrstva "${id}": ${prop}`;
  if (!list.length) {
    problems.push(`${kde} má prázdny zoznam zoomových zlomov – vymaž ho, alebo doplň zlom.`);
    return undefined;
  }
  if (list.length > MAX_PAINT_STOPS) {
    problems.push(`${kde} má ${list.length} zoomových zlomov, strop je ${MAX_PAINT_STOPS}.`);
    return undefined;
  }
  const out = [];
  for (const stop of list) {
    if (!Array.isArray(stop) || stop.length !== 2) {
      problems.push(`${kde}: zoomový zlom musí byť [zoom, hodnota].`);
      return undefined;
    }
    const z = clampZoom(stop[0]);
    if (z == null) {
      problems.push(`${kde}: "${stop[0]}" nie je zoom.`);
      return undefined;
    }
    const v = scalar(prop, stop[1], id, problems, where, ` pri z${z}`);
    if (v === undefined) return undefined;
    out.push([z, v]);
  }
  const zoradene = sortStops(out);
  const zoomy = zoradene.map(([z]) => z);
  if (new Set(zoomy).size !== zoomy.length) {
    problems.push(`${kde}: dva zoomové zlomy na tom istom zoome `
      + `(${zoomy.join(", ")}) – ponechaj jeden.`);
    return undefined;
  }
  return zoradene;
}

/**
 * Prečistí (a skontroluje) objekt úprav – rovnaká funkcia beží v prehliadači
 * pri importe súboru aj v pipeline pred zápisom do zdrojáku, takže do repa
 * sa nikdy nedostane nezmysel.
 *
 * @returns {{overrides: object, problems: string[]}}
 */
export function normalizeOverrides(raw) {
  const problems = [];
  const out = emptyOverrides();
  if (!raw || typeof raw !== "object") {
    problems.push("Súbor s úpravami nie je objekt JSON.");
    return { overrides: out, problems };
  }

  // ---- tieňovanie reliéfu ----
  // Defaultne vypnuté: na mape kaziť farby plôch a pri malých mierkach z nej
  // spraví hnedý šum. Kto ho chce, zapne si ho.
  out.hillshade = raw.hillshade === true;

  // ---- vlastné sady ikoniek ----
  // Musia byť skôr než výber sady: vybrať sa dá aj vlastná a bez zoznamu by
  // sa práve pridaná sada tvárila ako neznáma.
  for (const def of Array.isArray(raw.iconSets) ? raw.iconSets : []) {
    if (!def || typeof def !== "object") {
      problems.push("Vlastná sada ikoniek nie je objekt – preskakujem.");
      continue;
    }
    const id = String(def.id || "").trim();
    if (!/^own-[a-z0-9-]{1,32}$/.test(id)) {
      problems.push(`Vlastná sada "${def.id}": id musí byť `
        + `"${CUSTOM_SET_PREFIX}<meno>" z malých písmen, číslic a pomlčiek.`);
      continue;
    }
    if (ICON_SOURCE_IDS.includes(id) || out.iconSets.some((x) => x.id === id)) {
      problems.push(`Vlastná sada "${id}" už existuje – preskakujem.`);
      continue;
    }
    // Sprite je dvojica súborov `<url>.json` + `<url>.png`, takže sa URL
    // zadáva BEZ prípony – to je aj tvar, v akom ju čaká MapLibre.
    const sprite = String(def.sprite || "").trim();
    if (!/^https:\/\/[^\s"']+$/.test(sprite) || /\.(json|png)$/i.test(sprite)) {
      problems.push(`Vlastná sada "${id}": adresa musí byť https a BEZ prípony `
        + `(pipeline si k nej doplní .json aj .png).`);
      continue;
    }
    const suffix = String(def.suffix ?? "").trim();
    if (!/^[A-Za-z0-9_-]{0,8}$/.test(suffix)) {
      problems.push(`Vlastná sada "${id}": prípona mien ikon smie mať `
        + `len písmená, číslice, "_" a "-" (najviac 8 znakov).`);
      continue;
    }
    out.iconSets.push({
      id,
      label: String(def.label || id).slice(0, 60),
      sprite,
      suffix
    });
  }

  // ---- vlastné ikony ----
  // Obrázok sa nesie PRIAMO v úpravách ako PNG v `data:` adrese. Odkaz na
  // cudzí server by v mape bez internetu (a v balíku pre mobil) nebol ničím –
  // a sprite sa skladá pri builde, takže tam musí byť samotný obrázok.
  for (const def of Array.isArray(raw.customIcons) ? raw.customIcons : []) {
    if (!def || typeof def !== "object") {
      problems.push("Vlastná ikona nie je objekt – preskakujem.");
      continue;
    }
    const name = String(def.name || "").trim();
    if (!new RegExp(`^${CUSTOM_ICON_PREFIX}[a-z0-9_-]{1,40}$`).test(name)) {
      problems.push(`Vlastná ikona "${def.name}": meno musí byť `
        + `"${CUSTOM_ICON_PREFIX}<meno>" z malých písmen, číslic, "_" a "-".`);
      continue;
    }
    if (out.customIcons.some((x) => x.name === name)) {
      problems.push(`Vlastná ikona "${name}" je v úpravách dvakrát – nechávam prvú.`);
      continue;
    }
    const png = String(def.png || "");
    if (!png.startsWith("data:image/png;base64,")) {
      problems.push(`Vlastná ikona "${name}": obrázok musí byť PNG v \`data:\` adrese.`);
      continue;
    }
    if (png.length > CUSTOM_ICON_MAX_BYTES) {
      problems.push(`Vlastná ikona "${name}" má ${Math.round(png.length / 1024)} kB, `
        + `strop je ${Math.round(CUSTOM_ICON_MAX_BYTES / 1024)} kB – zmenši ju.`);
      continue;
    }
    const pixelRatio = Number(def.pixelRatio) === 2 ? 2 : 1;
    if (out.customIcons.length >= CUSTOM_ICON_MAX_COUNT) {
      problems.push(`Vlastných ikon je najviac ${CUSTOM_ICON_MAX_COUNT} – `
        + `"${name}" a ďalšie preskakujem.`);
      break;
    }
    out.customIcons.push({ name, png, pixelRatio });
  }

  // ---- sada ikoniek ----
  if (raw.icons != null) {
    const znama = ICON_SOURCE_IDS.includes(raw.icons)
      || out.iconSets.some((s2) => s2.id === raw.icons);
    if (znama) out.icons = raw.icons;
    else problems.push(`Neznáma sada ikoniek "${raw.icons}" – použije sa predvolená.`);
  }

  // ---- paleta ----
  for (const [themeKey, colors] of Object.entries(raw.palette || {})) {
    if (!THEMES[themeKey]) {
      problems.push(`Neznáma téma "${themeKey}" – preskakujem.`);
      continue;
    }
    const clean = {};
    for (const [key, value] of Object.entries(colors || {})) {
      if (!PALETTE_KEYS.includes(key)) {
        problems.push(`Neznáma farba "${themeKey}.${key}" – preskakujem.`);
        continue;
      }
      if (!isColor(value)) {
        problems.push(`"${themeKey}.${key}" nie je hex farba (${value}).`);
        continue;
      }
      // Rovnakú farbu ako má téma netreba do overrides zapisovať.
      if (value.toLowerCase() === String(THEMES[themeKey][key]).toLowerCase()) continue;
      clean[key] = value.toLowerCase();
    }
    if (Object.keys(clean).length) out.palette[themeKey] = clean;
  }

  // ---- značené trasy ----
  // Odstupy sú v pixeloch pri z16 (TRAIL_GAP_ZOOM) a zapisuje sa len to, čo
  // sa od predvolenej hodnoty naozaj líši – rovnako ako pri palete.
  const rawTrails = raw.trails && typeof raw.trails === "object" ? raw.trails : {};
  for (const [key, def] of Object.entries(TRAIL_GAP_DEFAULTS)) {
    const value = (rawTrails.gap || {})[key];
    if (value == null) continue;
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0 || n > 60) {
      problems.push(`Odstup trás "${key}" musí byť číslo od 0 do 60 px (${value}).`);
      continue;
    }
    const round = Math.round(n * 10) / 10;
    if (round !== def) out.trails.gap[key] = round;
  }
  for (const [id, def] of Object.entries(rawTrails.types || {})) {
    if (!TRAIL_BY_ID[id]) {
      problems.push(`Neznámy druh trasy "${id}" – preskakujem.`);
      continue;
    }
    if (!def || typeof def !== "object") {
      problems.push(`Nastavenie trasy "${id}" nie je objekt – preskakujem.`);
      continue;
    }
    const clean = {};
    if (def.dash != null) {
      if (!DASH_IDS.includes(def.dash)) {
        problems.push(`Trasa "${id}": neznámy vzor čiary "${def.dash}".`);
      } else if (def.dash !== TRAIL_BY_ID[id].dash) {
        clean.dash = def.dash;
      }
    }
    if (def.icon != null) {
      const icon = String(def.icon).trim();
      // Prázdny reťazec je platná odpoveď: „na tejto trase žiadnu ikonu".
      if (icon && !/^[A-Za-z0-9_.:-]{1,64}$/.test(icon)) {
        problems.push(`Trasa "${id}": neplatné meno ikony "${def.icon}".`);
      } else {
        clean.icon = icon;
      }
    }
    if (def.mark != null) {
      const mark = String(def.mark).trim();
      // Prázdny reťazec je „žiadna značka"; meno tvaru je „vždy tento tvar".
      // Chýbajúci kľúč znamená „taká, aká je v OSM" – to je iná odpoveď než
      // ktorákoľvek z týchto dvoch, preto sa nezapisuje.
      if (mark && !MARK_SHAPE_IDS.includes(mark)) {
        problems.push(
          `Trasa "${id}": neznámy tvar značky "${def.mark}" ` +
            `(poznám: ${MARK_SHAPE_IDS.join(", ")}).`
        );
      } else {
        clean.mark = mark;
      }
    }
    if (Object.keys(clean).length) out.trails.types[id] = clean;
  }

  // ---- rozostup a veľkosť značiek ----
  // Zapisuje sa len to, čo sa od predvoleného naozaj líši – ako pri palete
  // aj pri odstupoch pásikov.
  for (const [key, def] of Object.entries(TRAIL_MARK_DEFAULTS)) {
    const value = (rawTrails.marks || {})[key];
    if (value == null) continue;
    const n = Number(value);
    const medze = TRAIL_MARK_RANGES[key];
    if (!Number.isFinite(n) || n < medze[0] || n > medze[1]) {
      problems.push(
        `Značky trás "${key}" musia byť číslo od ${medze[0]} do ${medze[1]} (${value}).`
      );
      continue;
    }
    const round = Math.round(n * 100) / 100;
    if (round !== def) out.trails.marks[key] = round;
  }

  // ---- poradie kreslenia ----
  // JEDEN PRESUN NA VRSTVU a vyhráva ten POSLEDNÝ: presuny sa vyhodnocujú
  // v rade za sebou, takže by ich pri opakovanom klikaní pribúdali stovky
  // a nedalo by sa z nich prečítať, kde vrstva vlastne skončí. Posledný
  // presun tej istej vrstvy je zároveň to, čo si človek naposledy vybral.
  const presuny = new Map();
  for (const item of Array.isArray(raw.order) ? raw.order : []) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      problems.push(`Presun vrstvy nie je objekt {id, before} – preskakujem.`);
      continue;
    }
    const id = String(item.id ?? "").trim();
    const before = item.before == null ? null : String(item.before).trim();
    if (!LAYER_ID.test(id) || (before !== null && !LAYER_ID.test(before))) {
      problems.push(`Presun vrstvy: neplatné id ("${item.id}" → "${item.before}").`);
      continue;
    }
    if (before === id) {
      problems.push(`Vrstva "${id}" sa má kresliť pod seba – to nie je poradie.`);
      continue;
    }
    presuny.delete(id);
    presuny.set(id, { id, before });
  }
  out.order = [...presuny.values()];

  // ---- tvar štítka s číslom cesty ----
  for (const [id, def] of Object.entries(raw.shields || {})) {
    const trieda = SHIELD_DEFS.find(([sid]) => sid === id);
    if (!trieda) {
      problems.push(`Neznáma trieda štítka "${id}" – preskakujem.`);
      continue;
    }
    if (!def || typeof def !== "object") {
      problems.push(`Nastavenie štítka "${id}" nie je objekt – preskakujem.`);
      continue;
    }
    if (def.shape == null) continue;
    const shape = String(def.shape).trim();
    if (!SHIELD_SHAPE_IDS.includes(shape)) {
      problems.push(
        `Štítok "${id}": neznámy tvar "${def.shape}" ` +
          `(poznám: ${SHIELD_SHAPE_IDS.join(", ")}).`
      );
      continue;
    }
    // Predvolený tvar netreba do úprav zapisovať – rovnako ako farbu, ktorú
    // téma už má.
    if (shape !== trieda[5]) out.shields[id] = { shape };
  }

  // ---- vrstvy ----
  // Vlastné ikony sú prečistené vyššie, takže je už známe, ktoré obrázky sa
  // smú použiť ako vzor (a ktoré by v sprite nikdy neskončili).
  const vlastneObrazky = out.customIcons.map((i) => i.name);
  cleanLayers(raw.layers, out.layers, problems, "", vlastneObrazky);

  // ---- vrstvy pre jednotlivé typy máp ----
  // Tu je nadstavba nad tým, čo je vyššie: to isté id vrstvy môže mať iné
  // nastavenie na turistickej a iné na cestnej mape.
  for (const [typeId, def] of Object.entries(raw.maps || {})) {
    if (!MAP_TYPE_IDS.includes(typeId)) {
      problems.push(`Neznámy typ mapy "${typeId}" – preskakujem.`);
      continue;
    }
    if (!def || typeof def !== "object") {
      problems.push(`Úpravy mapy "${typeId}" nie sú objekt – preskakujem.`);
      continue;
    }
    const layers = {};
    cleanLayers(def.layers, layers, problems, `${typeId}: `, vlastneObrazky);
    const hidden = Array.isArray(def.poi?.hidden) ? def.poi.hidden : [];
    const poiHidden = [
      ...new Set(hidden.filter((v) => typeof v === "string" && v && v.length < 64))
    ].sort();
    if (Object.keys(layers).length || poiHidden.length) {
      out.maps[typeId] = { layers, poi: { hidden: poiHidden } };
    }
  }

  // ---- skryté POI triedy ----
  const hidden = Array.isArray(raw.poi?.hidden) ? raw.poi.hidden : [];
  out.poi.hidden = [
    ...new Set(hidden.filter((v) => typeof v === "string" && v && v.length < 64))
  ].sort();

  // ---- ikona POI kategórie ----
  // PRÁZDNY REŤAZEC JE PLATNÁ HODNOTA („táto kategória bez ikony"), takže sa
  // rozhoduje podľa toho, či kľúč existuje – nie podľa toho, či je hodnota
  // pravdivá. Chýbajúci kľúč znamená „ikona podľa sady", a to je iná odpoveď
  // než „žiadna".
  //
  // Ikony sú SPOLOČNÉ pre všetky typy máp (na rozdiel od skrytých tried):
  // akou značkou sa kreslí studnička, je vlastnosť tej kategórie, nie tej
  // mapy – a keby si ju každá mapa niesla vlastnú, ten istý výber by sa
  // musel naklikať štyrikrát.
  out.poi.icons = {};
  for (const [cls, name] of Object.entries(raw.poi?.icons || {})) {
    if (!LAYER_ID.test(cls)) {
      problems.push(`Ikona POI: neplatná kategória "${cls}" – preskakujem.`);
      continue;
    }
    const icon = String(name ?? "").trim();
    if (icon !== "" && !/^[A-Za-z0-9_.:-]{1,64}$/.test(icon)) {
      problems.push(`Ikona POI "${cls}": neplatné meno ikony "${name}".`);
      continue;
    }
    out.poi.icons[cls] = icon;
  }

  return { overrides: out, problems };
}

/**
 * Prečistí sadu úprav vrstiev (spoločnú aj tú pre jeden typ mapy) do `target`.
 * `where` je predpona do hlásení, aby bolo vidieť, ktorej mapy sa problém týka.
 */
function cleanLayers(rawLayers, target, problems, where, images = []) {
  for (const [id, def] of Object.entries(rawLayers || {})) {
    if (!def || typeof def !== "object") {
      problems.push(`${where}Úprava vrstvy "${id}" nie je objekt – preskakujem.`);
      continue;
    }
    const clean = {};
    // `visible: true` nie je to isté ako „nič": vrstvu, ktorú vypol profil
    // typu mapy alebo spoločná úprava, treba vedieť výslovne vrátiť späť.
    if (typeof def.visible === "boolean") clean.visible = def.visible;
    const mn = def.minzoom == null ? null : clampZoom(def.minzoom);
    const mx = def.maxzoom == null ? null : clampZoom(def.maxzoom);
    if (mn != null) clean.minzoom = mn;
    if (mx != null) clean.maxzoom = mx;
    if (mn != null && mx != null && mx <= mn) {
      problems.push(`${where}Vrstva "${id}": maxzoom (${mx}) musí byť väčší ako minzoom (${mn}).`);
      delete clean.maxzoom;
    }
    // Hodnota smie byť SKALÁR, ZOZNAM PODĽA ZOOMU alebo RELATÍVNA ÚPRAVA.
    // Zoznam má dva tvary: KRIVKA `[[zoom, hodnota], …]` (plynulý prechod
    // medzi zlomami) alebo PÁSMA `[[od, do, hodnota], …]` (v pásme konštanta,
    // na hranici skok). Skalár aj zoznam NAHRADIA to, čo štýl počíta podľa
    // zoomu; relatívna úprava `{scale, add}` ho naopak nechá a len preškáluje
    // (rozpis pri `isRelative`). Farba plochy môže byť navyše `none` – bez
    // výplne (viď `NO_FILL`).
    const paint = {};
    for (const [prop, value] of Object.entries(def.paint || {})) {
      const clean = cleanValue(prop, value, id, problems, where);
      if (clean !== undefined) paint[prop] = clean;
    }
    if (Object.keys(paint).length) clean.paint = paint;

    // ---- tmavý variant farieb (dark mode) ----
    // Kým `paint` je „farba je odteraz TAKÁTO", `paintDark` je „a v tmavej
    // téme takáto" – druhá, nezávislá vrstva nad tou istou vlastnosťou, lebo
    // svetlá a tmavá téma nepotrebujú tú istú hodnotu (biela cesta na svetlom
    // podklade je na tmavom oslnivá). Platí len pre tému `tmava`
    // (`applyLayerOverrides`) – ostatné tri témy zostanú pri `paint`.
    //
    // POČÍTA SA OD TMAVÉHO PODKLADU, NIE STLMENÍM SVETLEJ FARBY. Biela ulica
    // je vo svetlej téme čitateľná práve preto, že je skoro ako podklad
    // (kontrast 1,15 : 1) – nesie ju tmavý obrys. Keď sa z nej spraví tmavý
    // variant tak, že sa o kúsok stlmí (`#ffffff` → `#d0c8c8`), proti tmavému
    // podkladu je z toho 10,5 : 1. Na jednej ceste to nevidno; ulice v dedine
    // a v meste sú ale sieť a celé sídlo z nej svieti ako škvrna – miestna
    // ulica bola v tmavej téme nápadnejšia než diaľnica. Váhu dvojice stráži
    // `workers/lint/overrides.mjs` (bod 4).
    const paintDark = {};
    for (const [prop, value] of Object.entries(def.paintDark || {})) {
      const c = cleanDarkColor(prop, value, id, problems, where);
      if (c !== undefined) paintDark[prop] = c;
    }
    if (Object.keys(paintDark).length) clean.paintDark = paintDark;

    // ---- rozloženie (veľkosť ikony, rozostup po čiare, veľkosť písma) ----
    // Ten istý tvar hodnoty ako pri `paint`: skalár, krivka `[[zoom, v], …]`
    // alebo pásma `[[od, do, v], …]`. Preto sa aj kontroluje tou istou bránou,
    // len s iným čističom skalárov – inak by sa „rozostup" musel opísať
    // druhýkrát a raz by sa tie dva popisy rozišli.
    const layout = {};
    for (const [prop, value] of Object.entries(def.layout || {})) {
      const c = cleanValue(prop, value, id, problems, where, cleanLayoutScalar);
      if (c !== undefined) layout[prop] = c;
    }
    if (Object.keys(layout).length) clean.layout = layout;

    // ---- ikona symbolovej vrstvy ----
    // Zoznam ikon závisí od nasadenej sady, tu sa preto kontroluje len tvar
    // mena; či taká ikona v sprite naozaj je, rieši `applyLayerOverrides`.
    if (def.icon != null) {
      const icon = String(def.icon).trim();
      if (!/^[A-Za-z0-9_.:-]{1,64}$/.test(icon)) {
        problems.push(`${where}Vrstva "${id}": neplatné meno ikony "${def.icon}".`);
      } else {
        clean.icon = icon;
      }
    }

    // ---- prerušovanie čiary ----
    // AJ „solid" JE ÚPRAVA. Kým sa zahadzovala ako „veď to je predvolené",
    // nedalo sa vypnúť prerušovanie tam, kde ho vrstva má zo štýlu
    // (`rail-hatch`, `road-ford`, `road-construction`): panel voľbu prijal,
    // uložil z nej prázdno a v mape ostala pôvodná čiarkovaná čiara. Tichý
    // omyl – nespadlo nič, len sa nič nestalo. Developer mode ju zapíše len
    // vtedy, keď vrstva zabudované prerušovanie naozaj má (`frico:dash`).
    if (def.dash != null) {
      if (!DASH_IDS.includes(def.dash)) {
        problems.push(`${where}Vrstva "${id}": neznámy vzor čiary "${def.dash}".`);
      } else {
        clean.dash = def.dash;
      }
    }

    // ---- opakujúci sa vzor ----
    // `null` NIE JE to isté ako „nič": vzor, ktorý má vrstva zabudovaný
    // v štýle (`frico:pattern`, napr. kamienky v skalnej ploche), sa musí dať
    // výslovne vypnúť. Chýbajúci kľúč znamená „nechaj, čo je v štýle".
    if (def.pattern === null) {
      clean.pattern = null;
    } else if (def.pattern?.image) {
      // VLASTNÝ OBRÁZOK AKO VZOR. Musí to byť vlastná ikona z týchto úprav –
      // teda obrázok, ktorý sa nesie SPOLU s nimi a ktorý pipeline dopečie do
      // spritu (`workers/assets/custom-icons.mjs`). Hocijaké iné meno by sa
      // do štýlu dostalo, ale do spritu nie: MapLibre neznámy `fill-pattern`
      // ticho preskočí a plocha ostane bez vzoru.
      const image = String(def.pattern.image).trim();
      if (!images.includes(image)) {
        problems.push(
          `${where}Vrstva "${id}": obrázok vzoru "${image}" nie je medzi vlastnými ` +
          `ikonami úprav – nemal by ho kto dopiecť do spritu.`
        );
      } else {
        clean.pattern = patternDef({ image, opacity: def.pattern.opacity });
      }
    } else if (def.pattern) {
      if (!PATTERN_IDS.includes(def.pattern.id)) {
        problems.push(`${where}Vrstva "${id}": neznámy vzor "${def.pattern.id}".`);
      } else if (!isColor(def.pattern.color)) {
        problems.push(`${where}Vrstva "${id}": farba vzoru nie je hex (${def.pattern.color}).`);
      } else {
        clean.pattern = patternDef(def.pattern);
      }
    }

    // ---- okraj (plocha) / obrys pod čiarou ----
    if (def.outline) {
      // Šírka okraja pozná TIE ISTÉ TVARY ako hrúbka čiary – skalár, krivku,
      // pásma aj relatívnu úpravu. Kým to bolo len jedno číslo, okraj plochy
      // bol na každom zoome rovnako hrubý (teda na prehľade hrubší než plocha
      // sama) a okraj čiary sa nedal spraviť pomerný, len o konštantu širší.
      // Čo z ktorého tvaru vyjde, rozhoduje `outlineWidth` – tam je totiž
      // vidieť DRUH VRSTVY, ktorý tu ešte nepoznáme.
      const width = cleanValue(
        "line-width", def.outline.width, id, problems, where,
        outlineWidthScalar, "šírka okraja"
      );
      if (!isColor(def.outline.color)) {
        problems.push(`${where}Vrstva "${id}": farba okraja nie je hex (${def.outline.color}).`);
      } else if (width === undefined) {
        // Dôvod už povedal `cleanValue`.
      } else if (def.outline.dash != null && !DASH_IDS.includes(def.outline.dash)) {
        problems.push(`${where}Vrstva "${id}": neznámy vzor okraja "${def.outline.dash}".`);
      } else {
        const opacity = Number(def.outline.opacity);
        clean.outline = {
          color: String(def.outline.color).toLowerCase(),
          width,
          dash: def.outline.dash && def.outline.dash !== "solid" ? def.outline.dash : undefined,
          opacity: Number.isFinite(opacity) ? Math.min(1, Math.max(0, opacity)) : 1
        };
        if (!clean.outline.dash) delete clean.outline.dash;
        // Tmavý variant okraja – tá istá otázka ako pri `paintDark`, len na
        // jednej farbe, ktorá nie je v `paint` (okraj je odvodená vrstva).
        if (def.outline.colorDark != null) {
          if (!isColor(def.outline.colorDark)) {
            problems.push(`${where}Vrstva "${id}": tmavá farba okraja nie je hex `
              + `(${def.outline.colorDark}).`);
          } else {
            clean.outline.colorDark = String(def.outline.colorDark).toLowerCase();
          }
        }
      }
    }

    // ---- rozlíšenie podľa atribútu OSM ----
    const variants = cleanVariants(def.variants, id, problems, where);
    if (variants.length) clean.variants = variants;

    if (Object.keys(clean).length) target[id] = clean;
  }
}

/**
 * Najviac variantov na jednu vrstvu. Nie je to technická medza – je to medza
 * ČITATEĽNOSTI mapy aj panela: každý variant je vlastná vrstva (a s obrysom
 * dve), takže osem rozlíšení nad poľnou cestou je šestnásť vrstiev, ktoré sa
 * kreslia cez seba a v ktorých sa už nedá povedať, ktorá je ktorá.
 */
export const MAX_VARIANTS = 4;

/** Najviac hodnôt v jednom variante (`surface` má v OSM desiatky, nie stovky). */
const MAX_VARIANT_VALUES = 24;

/**
 * Prečistí zoznam variantov jednej vrstvy (rozpis pri `variantLayers`).
 *
 * `attr` je meno tagu z dlaždice, takže sa kontroluje len TVAR – či taký
 * atribút vrstva naozaj nesie, vie povedať jedine mapa a hovorí to panel
 * (ponúka to, čo je v načítaných dlaždiciach). Vymyslený atribút nič nezhodí:
 * `str()` z neho spraví `""`, variant sa netrafí a všetko ostane v predlohe.
 */
function cleanVariants(raw, id, problems, where) {
  if (raw == null) return [];
  if (!Array.isArray(raw)) {
    problems.push(`${where}Vrstva "${id}": "variants" musí byť zoznam – preskakujem.`);
    return [];
  }
  if (raw.length > MAX_VARIANTS) {
    problems.push(`${where}Vrstva "${id}": ${raw.length} variantov, strop je ${MAX_VARIANTS}.`);
    return [];
  }
  const out = [];
  const uz = new Set();
  for (const [i, v] of raw.entries()) {
    const kde = `${where}Vrstva "${id}", variant ${i + 1}`;
    if (!v || typeof v !== "object") {
      problems.push(`${kde} nie je objekt – preskakujem.`);
      continue;
    }
    const attr = String(v.attr ?? "").trim();
    if (!/^[A-Za-z_][A-Za-z0-9_:]{0,40}$/.test(attr)) {
      problems.push(`${kde}: "${v.attr}" nie je meno atribútu z dlaždice.`);
      continue;
    }
    const values = [...new Set(
      (Array.isArray(v.values) ? v.values : [])
        .filter((x) => typeof x === "string" || typeof x === "number")
        .map((x) => String(x).trim())
        .filter(Boolean)
    )];
    if (!values.length) {
      problems.push(`${kde}: zoznam hodnôt je prázdny – variant bez hodnôt by `
        + `nenakreslil nič a z predlohy by nič neubral.`);
      continue;
    }
    if (values.length > MAX_VARIANT_VALUES) {
      problems.push(`${kde}: ${values.length} hodnôt, strop je ${MAX_VARIANT_VALUES}.`);
      continue;
    }
    // DVA VARIANTY NAD TOU ISTOU HODNOTOU sú tichá chyba: `variantTest` ich
    // z predlohy odoberie oba, ale nakreslia sa tiež oba – cez seba.
    const zrazka = values.find((x) => uz.has(`${attr}=${x}`));
    if (zrazka) {
      problems.push(`${kde}: hodnotu "${attr}=${zrazka}" už berie skorší variant `
        + `– kreslili by sa cez seba.`);
      continue;
    }
    for (const x of values) uz.add(`${attr}=${x}`);

    const clean = { attr, values };
    const label = String(v.label ?? "").trim();
    if (label) clean.label = label.slice(0, 40);

    const paint = {};
    for (const [prop, value] of Object.entries(v.paint || {})) {
      const c = cleanValue(prop, value, id, problems, `${where}variant ${i + 1}: `);
      if (c !== undefined) paint[prop] = c;
    }
    if (Object.keys(paint).length) clean.paint = paint;

    const layout = {};
    for (const [prop, value] of Object.entries(v.layout || {})) {
      const c = cleanValue(prop, value, id, problems, `${where}variant ${i + 1}: `,
                           cleanLayoutScalar);
      if (c !== undefined) layout[prop] = c;
    }
    if (Object.keys(layout).length) clean.layout = layout;

    if (v.dash != null) {
      if (!DASH_IDS.includes(v.dash)) problems.push(`${kde}: neznámy vzor čiary "${v.dash}".`);
      else clean.dash = v.dash;
    }
    if (v.icon != null) {
      const icon = String(v.icon).trim();
      if (!/^[A-Za-z0-9_.:-]{1,64}$/.test(icon)) {
        problems.push(`${kde}: neplatné meno ikony "${v.icon}".`);
      } else {
        clean.icon = icon;
      }
    }
    if (v.outline) {
      const w = cleanValue("line-width", v.outline.width, id, problems,
                           `${where}variant ${i + 1}: `, outlineWidthScalar, "šírka okraja");
      if (!isColor(v.outline.color)) {
        problems.push(`${kde}: farba okraja nie je hex (${v.outline.color}).`);
      } else if (w !== undefined) {
        const opacity = Number(v.outline.opacity);
        clean.outline = {
          color: String(v.outline.color).toLowerCase(),
          width: w,
          opacity: Number.isFinite(opacity) ? Math.min(1, Math.max(0, opacity)) : 1
        };
        if (v.outline.dash && v.outline.dash !== "solid") {
          if (!DASH_IDS.includes(v.outline.dash)) {
            problems.push(`${kde}: neznámy vzor okraja "${v.outline.dash}".`);
          } else {
            clean.outline.dash = v.outline.dash;
          }
        }
      }
    }
    out.push(clean);
  }
  return out;
}

/** `true`, ak sada úprav naozaj niečo mení. */
export function hasOverrides(o) {
  if (!o) return false;
  return (
    o.hillshade === true ||
    (o.icons || DEFAULT_ICON_SOURCE) !== DEFAULT_ICON_SOURCE ||
    Object.keys(o.palette || {}).length > 0 ||
    Object.keys(o.layers || {}).length > 0 ||
    (o.order || []).length > 0 ||
    Object.keys(o.trails?.gap || {}).length > 0 ||
    Object.keys(o.trails?.types || {}).length > 0 ||
    Object.keys(o.trails?.marks || {}).length > 0 ||
    Object.keys(o.shields || {}).length > 0 ||
    (o.iconSets || []).length > 0 ||
    (o.customIcons || []).length > 0 ||
    (o.poi?.hidden || []).length > 0 ||
    Object.keys(o.poi?.icons || {}).length > 0 ||
    Object.values(o.maps || {}).some(
      (m) => Object.keys(m.layers || {}).length > 0 || (m.poi?.hidden || []).length > 0
    )
  );
}

/**
 * Úpravy pre jeden typ mapy: spoločné (`layers`, `poi`) a nad nimi tie, čo
 * platia len preň (`maps[<typ>]`). Vracia objekt v tvare, aký očakáva zvyšok
 * generátora – teda ako keby žiadne typy máp neexistovali.
 *
 * Vlastnosť z konkrétnej mapy prebije spoločnú; `paint` sa mieša po
 * jednotlivých vlastnostiach, aby sa dala prepísať len jedna farba.
 */
export function resolveOverrides(overrides, mapType) {
  if (!overrides) return null;
  const own = overrides.maps?.[normalizeMapType(mapType)];
  if (!own) return overrides;

  const layers = { ...(overrides.layers || {}) };
  for (const [id, def] of Object.entries(own.layers || {})) {
    const base = layers[id];
    layers[id] = base
      ? {
          ...base,
          ...def,
          ...(base.paint || def.paint
            ? { paint: { ...(base.paint || {}), ...(def.paint || {}) } }
            : {}),
          // Tá istá otázka, čo `paint`, len pre jeho tmavý variant – bez
          // toho by mapová výnimka prepísala aj tmavé farby, ktoré nastavuje
          // len spoločná úprava.
          ...(base.paintDark || def.paintDark
            ? { paintDark: { ...(base.paintDark || {}), ...(def.paintDark || {}) } }
            : {}),
          // To isté, čo `paint`, aj pre `layout`: mieša sa po vlastnostiach,
          // aby sa dal na jednej mape prepísať len rozostup a veľkosť ikony
          // ostala spoločná. Bez toho by celý `layout` z konkrétnej mapy
          // prebil ten spoločný a ticho zahodil, čo v ňom nie je.
          ...(base.layout || def.layout
            ? { layout: { ...(base.layout || {}), ...(def.layout || {}) } }
            : {})
        }
      : def;
  }
  return {
    ...overrides,
    layers,
    poi: {
      hidden: [...new Set([...(overrides.poi?.hidden || []), ...(own.poi?.hidden || [])])].sort(),
      // Ikony kategórií sú spoločné pre všetky mapy (rozpis v normalizácii),
      // takže sa nezlievajú – len sa nesmú stratiť.
      icons: { ...(overrides.poi?.icons || {}) }
    }
  };
}

export { ICON_SOURCES, ICON_SOURCE_IDS, DEFAULT_ICON_SOURCE } from "./icon-sources.js";

/** Vybraná sada ikoniek (z úprav, inak predvolená). */
export function selectedIconSource(overrides) {
  const id = overrides?.icons;
  // Aj vlastná sada z úprav je platná odpoveď – inak by sa dala pridať, ale
  // nie zapnúť, a panel by ticho ukazoval predvolenú.
  return allIconSources(overrides).some((s) => s.id === id) ? id : DEFAULT_ICON_SOURCE;
}

/**
 * PREDPONA MIEN VLASTNÝCH IKON. Tá istá úvaha ako pri značkách (`mark-`)
 * a štítkoch (`shield-`): podľa mena musí byť vidieť, kto obrázok do spritu
 * dal – a vlastná ikona sa nesmie tichou zhodou mien dostať namiesto ikony
 * zo sady.
 */
export const CUSTOM_ICON_PREFIX = "own:";

/**
 * Strop na jednu vlastnú ikonu a na ich počet.
 *
 * Obrázok leží priamo v úpravách, takže sa nesie všade, kde sa nesú ony:
 * v prehliadači, v `poc/web/style-overrides.json` v repozitári a odtiaľ do
 * každého spritu. 64 kB je pri 64 × 64 px veľkorysé (bežná ikona má
 * jednotky kB) a dvadsať ikon sa do repozitára aj do atlasu zmestí bez toho,
 * aby si to niekto všimol.
 */
export const CUSTOM_ICON_MAX_BYTES = 64 * 1024;
export const CUSTOM_ICON_MAX_COUNT = 20;

/** Mená vlastných ikon z úprav (to, čo štýl smie použiť ako `icon-image`). */
export function customIconNames(overrides) {
  return (overrides?.customIcons || []).map((i) => i.name);
}

/** Farby témy po aplikovaní úprav z developer módu. */
export function mergedPalette(themeKey, overrides) {
  const base = THEMES[themeKey];
  if (!base) throw new Error(`Neznáma téma: ${themeKey}`);
  return { ...base, ...(overrides?.palette?.[themeKey] || {}) };
}

/**
 * PREŠKÁLUJE ČÍSLO PODĽA ZOOMU – `v × scale + add` – aj vtedy, keď je zadané
 * krivkou alebo pásmami. Aritmetika sa robí NA JEDNOTLIVÝCH STOPOCH, nie
 * výrazom `["*", …]` nad hotovou hodnotou: `["zoom"]` smie byť podľa
 * style-spec iba priamym vstupom najvrchnejšieho `interpolate`/`step`
 * (rozpis pri `zw`), takže obal navyše by MapLibre odmietol aj s celým štýlom.
 *
 * PREČO NÁSOBENIE, A NIE LEN PRIPOČÍTANIE. Konštanta pripočítaná ku krivke
 * mení pomer na každom zoome inak: obrys diaľnice s `+3` je pri z4 nad čiarou
 * 0,5 px sedemnásobný, pri z20 nad čiarou 60 px pridá päť percent a nie je ho
 * vidieť. To je presne to, čo na obrysoch vyzerá „rozbito na krajných zoomoch“.
 * Percento drží pomer všade rovnaký, konštanta sa hodí na jemný doplnok –
 * preto oboje naraz.
 *
 * PÁSMA (`step`) SÚ TU ZÁMERNE. Kým to vedela len krivka, okraj nad čiarou,
 * ktorej šírka je v pásmach, dostal výraz nezmenený – čiže bol presne taký
 * široký ako čiara, teda neviditeľný. Nič nespadlo, štýl bol platný.
 *
 * Výraz, ktorý nie je ani jedno (napr. `match` nad dátami), sa vráti tak, ako
 * prišiel – prepisovať dátami riadenú hodnotu naslepo by bola tichá zmena mapy.
 */
export function scaleExpr(expr, rel) {
  const { scale = 1, add = 0 } = rel || {};
  // Zaokrúhlenie: `0.5 * 1.4` je v plávajúcej čiarke `0.7000000000000001`
  // a to by šlo do štýlu aj do súboru úprav.
  const t = (v) =>
    typeof v === "number" ? Math.round((v * scale + add) * 1000) / 1000 : v;
  if (typeof expr === "number") return t(expr);
  if (!Array.isArray(expr)) return expr;
  // `["interpolate", <druh>, <vstup>, z1, v1, z2, v2, …]`
  if (expr[0] === "interpolate") {
    const out = expr.slice(0, 3);
    for (let i = 3; i < expr.length; i += 2) out.push(expr[i], t(expr[i + 1]));
    return out;
  }
  // `["step", <vstup>, <hodnota pod prvým zlomom>, z1, v1, z2, v2, …]` –
  // teda prvý výstup je na inom mieste než pri krivke.
  if (expr[0] === "step") {
    const out = [expr[0], expr[1], t(expr[2])];
    for (let i = 3; i < expr.length; i += 2) out.push(expr[i], t(expr[i + 1]));
    return out;
  }
  return expr;
}

/**
 * Spoločné vlastnosti, ktoré odvodená vrstva preberá od svojej predlohy.
 * Prípona je s dvoma podčiarkovníkmi, aby sa netrafila do už existujúcej
 * vrstvy – `park` + „okraj" by inak prepísalo `park-outline`.
 */
function derived(layer, suffix, label) {
  const out = {
    id: `${layer.id}__${suffix}`,
    source: layer.source,
    metadata: {
      ...(layer.metadata || {}),
      "frico:label": `${(layer.metadata || {})["frico:label"] || layer.id} – ${label}`,
      "frico:derived": layer.id
    }
  };
  // Prerušovanie si odvodená vrstva nesie vlastné (okraj má svoje, vzor
  // žiadne), takže zdedené `frico:dash` predlohy by o nej klamalo.
  delete out.metadata["frico:dash"];
  for (const key of ["source-layer", "filter", "minzoom", "maxzoom"]) {
    if (layer[key] !== undefined) out[key] = layer[key];
  }
  if ((layer.layout || {}).visibility === "none") out.layout = { visibility: "none" };
  return out;
}

/**
 * Je to vrstva so vzorom odvodená od inej? Vracia id predlohy alebo `null`.
 * Pýtajú sa na to dve miesta (skladanie úprav a profil typu mapy), takže
 * prípona `__pattern` je napísaná RAZ – v `derived` a tu.
 */
export function patternLayerFor(layer) {
  const parent = (layer?.metadata || {})["frico:derived"];
  return parent && layer.id === `${parent}__pattern` ? parent : null;
}

/**
 * Prerušovanie, ktoré má vrstva ZABUDOVANÉ V ŠTÝLE – teda to, na čo sa
 * v developer móde dá vrátiť. Vracia predvoľbu (`"rail"`), rovno pole čísel
 * (keď to žiadna predvoľba nie je) alebo `"solid"` pri plnej čiare.
 *
 * Číta sa z metadát, NIE z `paint`: panel dostáva štýl, na ktorom už úprava
 * sedí, takže v `paint` je to, čo je nastavené TERAZ. Bez tohto ukazoval
 * výber pri každej čiare „Plná“ (rozpis v `add`).
 */
export function builtinDash(layer) {
  const d = (layer?.metadata || {})["frico:dash"];
  return d === undefined ? "solid" : d;
}

/** Vrstva s opakujúcim sa vzorom nad plochou / pozdĺž čiary. */
function patternLayer(layer, pattern) {
  const name = patternImageName(pattern);
  const opacity = pattern.opacity ?? 1;
  if (layer.type === "fill" || layer.type === "fill-extrusion") {
    return {
      ...derived(layer, "pattern", "vzor"),
      type: "fill",
      paint: { "fill-pattern": name, "fill-opacity": opacity }
    };
  }
  if (layer.type === "line") {
    const base = derived(layer, "pattern", "vzor");
    return {
      ...base,
      type: "line",
      layout: { ...(layer.layout || {}), ...(base.layout || {}) },
      paint: {
        "line-pattern": name,
        "line-width": layer.paint["line-width"],
        "line-opacity": opacity
      }
    };
  }
  return null;
}

/**
 * ŠÍRKA OKRAJA – z tvaru, ktorý prišiel v úprave, a z druhu vrstvy.
 *
 * Sú to dve rôzne otázky podľa toho, čo sa obťahuje:
 *
 *   PLOCHA nemá vlastnú hrúbku, takže okraj je samostatná čiara a jej šírka
 *   je ABSOLÚTNA. Preto tu dávajú zmysel všetky tvary vrátane krivky a pásiem
 *   – práve tie sú odpoveď na „okraj, ktorý so zoomom nezhrubne do neslušna".
 *
 *   ČIARA hrúbku má, takže okraj je casing POD ŇOU a jeho šírka sa počíta
 *   OD NEJ. Skalár `w` znamená „`w` px na každej strane", teda `2w` na šírke
 *   (obrys je centrovaný); relatívna úprava znamená „toľkokrát hrubší".
 *   Oboje drží krivku čiary, takže okraj škáluje s ňou.
 *
 * Krivka ani pásma sa k šírke ČIARY pripočítať nedajú – „výraz + výraz" nad
 * `["zoom"]` MapLibre nepozná (rozpis pri `zw`) – takže tam sú, tak ako pri
 * ploche, absolútnou šírkou casingu. Je to jediné čítanie, ktoré nie je hádanie.
 */
function outlineWidth(layer, width) {
  // Pri ploche nie je čo škálovať, takže základ relatívnej úpravy je 1 px.
  const base = layer.type === "line" ? layer.paint["line-width"] : null;
  if (isRelative(width)) return scaleExpr(base ?? 1, width);
  const val = paintValue(width);
  if (base == null || typeof val !== "number") return val;
  return scaleExpr(base, { add: val * 2 });
}

/**
 * ROZLÍŠENIE PODĽA ATRIBÚTU OSM – „nespevnená poľná cesta bodkovane,
 * spevnená plnou čiarou s obrysom".
 *
 * PREČO TO NIE JE DRUHÁ VRSTVA V ZDROJÁKU. Dovtedy sa taká otázka dala
 * zodpovedať len tak, že sa do `themes.js` dopísala ďalšia `add(...)`
 * s ručne zloženým filtrom – teda commit, build a pol hodiny. Pritom je to
 * presne to, čo sa ladí okom nad mapou: ktoré hodnoty `surface` ešte znamenajú
 * „dá sa tadiaľ ísť autom" je otázka na kraj, nie na zdroják.
 *
 * PRVOK SA SMIE NAKRESLIŤ RAZ. Variant dostane filter predlohy A test
 * atribútu, predloha si k svojmu filtru pridá NEGÁCIU toho testu. Bez toho
 * druhého by sa čiara kreslila dvakrát cez seba: hrubšia, tmavšia a s
 * prerušovaním, ktoré sa navzájom vypĺňa – teda tichý omyl, ktorý na mape
 * vyzerá skoro dobre. (Tá istá úvaha, akú si o dvoch blokoch píše
 * `workers/roads/roads.yml`.)
 *
 * Prvok, ktorý atribút vôbec NEMÁ, ostáva v predlohe: `str()` z chýbajúceho
 * tagu spraví `""` a to sa v zozname hodnôt netrafí. Tak to má byť – „nevieme,
 * aký je povrch" nie je to isté ako „je nespevnený".
 */
function variantLayers(layer, variants, hasIcon) {
  const out = [];
  const koren = (layer.metadata || {})["frico:derived"] || layer.id;
  for (const [i, v] of variants.entries()) {
    const test = ["in", str(v.attr), ["literal", v.values]];
    const zaklad = derived(layer, `var${i + 1}`, v.label || v.attr);
    const vrstva = {
      ...zaklad,
      type: layer.type,
      filter: layer.filter ? ["all", layer.filter, test] : test,
      ...(layer.layout ? { layout: { ...layer.layout, ...(zaklad.layout || {}) } } : {}),
      paint: { ...(layer.paint || {}) },
      metadata: { ...zaklad.metadata, "frico:derived": koren, "frico:variant": layer.id }
    };
    for (const [prop, value] of Object.entries(v.paint || {})) {
      const nv = overrideValue(vrstva.paint[prop], value);
      if (nv !== undefined) vrstva.paint[prop] = nv;
    }
    if (v.layout && layer.type === "symbol") {
      vrstva.layout = { ...(vrstva.layout || {}) };
      for (const [prop, value] of Object.entries(v.layout)) {
        const nv = overrideValue(vrstva.layout[prop], value, LAYOUT_PROPS[prop]?.def);
        if (nv !== undefined) vrstva.layout[prop] = nv;
      }
    }
    // „Plná" nie je „nič" – rovnaká úvaha ako pri úprave vrstvy.
    if (v.dash && layer.type === "line") {
      const arr = dashArray(v.dash);
      if (arr) vrstva.paint["line-dasharray"] = arr;
      else delete vrstva.paint["line-dasharray"];
    }
    if (v.icon && layer.type === "symbol" && hasIcon(v.icon)) {
      vrstva.layout = { ...(vrstva.layout || {}), "icon-image": v.icon };
    }
    // Obrys variantu ide pod čiaru rovnako ako obrys vrstvy, a hlási sa ku
    // KOREŇU – inak by ho presun poradia nechal stáť tam, kde predloha už nie je.
    const obrys = v.outline ? outlineLayer(vrstva, v.outline) : null;
    if (obrys) {
      obrys.metadata = { ...obrys.metadata, "frico:derived": koren };
      if (layer.type === "line") out.push(obrys);
    }
    out.push(vrstva);
    if (obrys && layer.type !== "line") out.push(obrys);
  }
  return out;
}

/** Test „tento prvok patrí niektorému z variantov" – na zúženie predlohy. */
function variantTest(variants) {
  const testy = variants.map((v) => ["in", str(v.attr), ["literal", v.values]]);
  return testy.length === 1 ? testy[0] : ["any", ...testy];
}

/** Je to vrstva variantu? Vracia id predlohy alebo `null`. */
export function variantLayerFor(layer) {
  return (layer?.metadata || {})["frico:variant"] || null;
}

/**
 * Okraj. Pri ploche je to obrysová čiara nad ňou, pri čiare širšia čiara
 * pod ňou (klasický casing) – v oboch prípadoch „to, čo prvok ohraničuje".
 */
function outlineLayer(layer, outline) {
  const dash = outline.dash ? { "line-dasharray": dashArray(outline.dash) } : {};
  if (layer.type === "fill" || layer.type === "fill-extrusion") {
    return {
      ...derived(layer, "outline", "okraj"),
      type: "line",
      layout: { "line-join": "round" },
      paint: {
        "line-color": outline.color,
        "line-width": outlineWidth(layer, outline.width),
        "line-opacity": outline.opacity ?? 1,
        ...dash
      }
    };
  }
  if (layer.type === "line") {
    return {
      ...derived(layer, "outline", "okraj"),
      type: "line",
      layout: layer.layout || {},
      paint: {
        "line-color": outline.color,
        "line-width": outlineWidth(layer, outline.width),
        "line-opacity": outline.opacity ?? 1,
        ...dash
      }
    };
  }
  return null;
}

/**
 * Aplikuje úpravy vrstiev na hotový štýl: viditeľnosť, rozsah zoomu, farby,
 * ikonu, prerušovanie čiary a odvodené vrstvy (vzor, okraj).
 *
 * @param {(name: string) => boolean} [hasIcon] je taká ikona v sprite? Ikona,
 *        ktorú vybraná sada nemá, sa nenastaví – chýbajúci obrázok znamená
 *        nevykreslený symbol a v pipeline navyše zhodí kontrolu štýlu.
 * @param {string} [theme] kľúč aktuálnej témy – rozhoduje, či sa nad `paint`
 *        a `outline.color` naviac uplatní ich tmavý variant (`paintDark`,
 *        `outline.colorDark`, rozpis pri `cleanLayers`). Bez neho (staršie
 *        volania, kontroly) sa tmavý variant jednoducho nikdy nepoužije.
 */
function applyLayerOverrides(style, layerOverrides, hasIcon = () => true, theme) {
  if (!layerOverrides) return style;
  const out = [];

  for (const layer of style.layers) {
    // Vzor zabudovaný v štýle už jednu vrstvu má (pridal ju `add`). Zahodí sa
    // a poskladá znova z ÚČINNÉHO predpisu – inak by úprava vzoru vyrobila
    // druhú vrstvu s tým istým id a poistka proti duplicite by nechala tú
    // pôvodnú, čiže by sa v mape ticho nezmenilo nič.
    if (patternLayerFor(layer) || variantLayerFor(layer)) continue;

    const o = layerOverrides[layer.id];
    // Chýbajúci kľúč = „nechaj vzor zo štýlu", `null` = „vypni ho".
    const builtin = (layer.metadata || {})["frico:pattern"] || null;
    const pat = o && "pattern" in o ? o.pattern : builtin;

    // Vzor z vlastného obrázka sa nasadí len vtedy, keď ten obrázok naozaj
    // je (v sprite alebo aspoň v úpravách) – neznámy `fill-pattern` MapLibre
    // ticho preskočí a plocha ostane bez vzoru.
    const patOk = (p) => !p || !p.image || hasIcon(p.image);

    if (!o) {
      out.push(layer);
      if (pat && patOk(pat)) out.push(patternLayer(layer, pat));
      continue;
    }

    if (o.icon && layer.type === "symbol" && hasIcon(o.icon)) {
      layer.layout = { ...(layer.layout || {}), "icon-image": o.icon };
    }

    if (o.visible === false) {
      layer.layout = { ...(layer.layout || {}), visibility: "none" };
    } else if (o.visible === true && (layer.layout || {}).visibility === "none") {
      // Vrstvu vypnutú profilom typu mapy sa musí dať vrátiť späť.
      layer.layout = { ...layer.layout };
      delete layer.layout.visibility;
    }
    if (o.minzoom != null) layer.minzoom = o.minzoom;
    if (o.maxzoom != null) layer.maxzoom = o.maxzoom;
    // `background` nemá minzoom/maxzoom obmedzenia iné než štýl dovolí,
    // ostatné vrstvy áno – MapLibre by neplatný rozsah odmietol.
    if (layer.minzoom != null && layer.maxzoom != null && layer.maxzoom <= layer.minzoom) {
      delete layer.maxzoom;
    }
    // `paintValue` rozbalí to, čo úprava nesie: `none` na priehľadnú farbu
    // a pole zlomov na `interpolate` podľa zoomu.
    if (o.paint) {
      layer.paint = { ...(layer.paint || {}) };
      for (const [prop, value] of Object.entries(o.paint)) {
        const v = overrideValue(layer.paint[prop], value);
        // Percento nad vlastnosťou, ktorú vrstva nemá, nemá z čoho počítať –
        // `undefined` v `paint` by MapLibre odmietol aj s celým štýlom.
        if (v !== undefined) layer.paint[prop] = v;
      }
    }
    // Tmavý variant je vždy JEDNA farba (nikdy krivka, pásma ani percento –
    // rozpis pri `cleanLayers`), takže ide rovno na vrstvu, nie cez
    // `overrideValue`. Platí len v téme `tmava` a len navrch toho, čo už
    // nastavil `paint` (alebo štýl sám) – ostatné tri témy ho nevidia.
    if (theme === "tmava" && o.paintDark) {
      layer.paint = { ...(layer.paint || {}) };
      for (const [prop, value] of Object.entries(o.paintDark)) {
        layer.paint[prop] = paintValue(value);
      }
    }
    // `layout` len na SYMBOLOVEJ vrstve: `icon-size` na čiare je pre MapLibre
    // neznáma vlastnosť a taký štýl odmietne CELÝ (na rozdiel od `paint`,
    // kde neznáme len ignoruje). Developer mode ich inde než na symbole
    // neponúka, toto je poistka pre ručne upravený súbor.
    if (o.layout && layer.type === "symbol") {
      layer.layout = { ...(layer.layout || {}) };
      for (const [prop, value] of Object.entries(o.layout)) {
        // Rozostup ani veľkosť ikony vrstva nemusí mať nastavené – vtedy je
        // základom predvoľba MapLibre, nie nič (rozpis pri `overrideValue`).
        const v = overrideValue(layer.layout[prop], value, LAYOUT_PROPS[prop]?.def);
        if (v !== undefined) layer.layout[prop] = v;
      }
    }
    // „Plná" NIE JE „nič": vrstva, ktorá má prerušovanie zabudované v štýle
    // (železnica, brod, cesta vo výstavbe), sa musí dať vrátiť na plnú čiaru
    // – a to znamená vlastnosť ZMAZAŤ. `line-dasharray: null` by MapLibre
    // neprijal a `dashArray("solid")` je práve `null`.
    if (o.dash && layer.type === "line") {
      layer.paint = { ...(layer.paint || {}) };
      const arr = dashArray(o.dash);
      if (arr) layer.paint["line-dasharray"] = arr;
      else delete layer.paint["line-dasharray"];
    }

    // ROZLÍŠENIE PODĽA ATRIBÚTU. Vzniká z vrstvy, na ktorej UŽ SEDÍ jej vlastná
    // úprava, takže variant dedí doladený vzhľad a mení oproti nemu len to, čím
    // sa líši. Predloha si k filtru pridá negáciu – rozpis pri `variantLayers`.
    const varianty = (o.variants || []).length
      ? variantLayers(layer, o.variants, hasIcon)
      : [];
    if (varianty.length) {
      const nie = ["!", variantTest(o.variants)];
      layer.filter = layer.filter ? ["all", layer.filter, nie] : nie;
    }

    // Okraj čiary ide pod ňu, okraj plochy a vzor nad ňu. Tmavý variant jeho
    // farby je tá istá otázka ako pri `paintDark` vyššie, len na vlastnosti,
    // ktorá nesedí v `paint` (okraj je odvodená vrstva) – preto sa rieši tu,
    // pred `outlineLayer`, a nie v ňom.
    const outline = o.outline
      ? outlineLayer(layer, theme === "tmava" && o.outline.colorDark
          ? { ...o.outline, color: o.outline.colorDark }
          : o.outline)
      : null;
    if (outline && layer.type === "line") out.push(outline);
    out.push(layer);
    if (outline && layer.type !== "line") out.push(outline);
    out.push(...varianty);
    const pattern = pat && patOk(pat) ? patternLayer(layer, pat) : null;
    if (pattern) out.push(pattern);
  }

  // Poistka proti duplicitnému id – MapLibre by taký štýl odmietol.
  const seen = new Set();
  style.layers = out.filter((l) => {
    if (seen.has(l.id)) return false;
    seen.add(l.id);
    return true;
  });
  return style;
}

/**
 * PORADIE KRESLENIA: presuny „túto vrstvu kresli tesne pod tamtú".
 *
 * MapLibre kreslí vrstvy v tom poradí, v akom sú v štýle – posledná je
 * navrchu. Čo je nad čím, je teda rozhodnutie štýlu, lenže vidieť ho je až
 * v mape: násyp nad cestou, popisok pod tieňovaním, plot cez chodník. Kým sa
 * to dalo zmeniť len v zdrojáku, znamenala každá taká otázka commit a build.
 *
 * FORMÁT JE ZOZNAM PRESUNOV, NIE CELÉ PORADIE. Uložiť všetkých ~250 id by
 * znamenalo, že sa úpravy rozsypú pri prvej vrstve, ktorá v štýle pribudne
 * alebo zmizne (iná téma, iný typ mapy, chýbajúci `featuresUrl`) – a rozsypú
 * sa TICHO. Presun je oproti tomu odpoveď na jednu otázku, dá sa prečítať
 * (`{"id": "feature-embankment", "before": "road-motorway"}`) a vrstvu, ktorú
 * v tomto štýle nikto nepozná, jednoducho preskočí.
 *
 * PRESÚVA SA CELÁ RODINA. Vzor aj okraj sú vlastné vrstvy odvodené od
 * predlohy (`frico:derived`) a musia ostať pri nej – inak by šrafovanie
 * ostalo kresliť tam, kde plocha už nie je.
 *
 * MASKA REGIÓNU OSTÁVA POSLEDNÁ, nech si ju nikto nechtiac neprekryje:
 * vrstva za ňou by kreslila aj mimo stiahnutého regiónu a bola by to presne
 * tá tichá chyba, kvôli ktorej maska existuje (rozpis v CLAUDE.md, stráži to
 * `workers/lint/style.mjs`).
 *
 * @param {object} style   hotový štýl (už s úpravami vrstiev)
 * @param {{id: string, before: string|null}[]} order  presuny v poradí,
 *        v akom sa naklikali; `before: null` znamená „úplne navrch"
 */
export function applyLayerOrder(style, order) {
  if (!order?.length) return style;
  let layers = style.layers;
  const rodina = (id) => (l) => {
    const meta = l.metadata || {};
    return l.id === id || meta["frico:derived"] === id || meta["frico:with"] === id;
  };

  for (const { id, before } of order) {
    const blok = layers.filter(rodina(id));
    // Vrstva, ktorú tento štýl nemá (iná téma, iný typ mapy, vypnuté trasy),
    // nie je chyba – presun sa jednoducho netýka ničoho.
    if (!blok.length) continue;
    const zvysok = layers.filter((l) => !blok.includes(l));
    if (before == null) {
      layers = [...zvysok, ...blok];
      continue;
    }
    const kam = zvysok.findIndex((l) => l.id === before);
    if (kam < 0) continue;
    layers = [...zvysok.slice(0, kam), ...blok, ...zvysok.slice(kam)];
  }

  // Maska regiónu späť navrch – rozpis vyššie.
  const maska = layers.filter((l) => REGION_MASK_LAYERS.includes(l.id));
  if (maska.length) {
    layers = [...layers.filter((l) => !maska.includes(l)), ...maska];
  }
  style.layers = layers;
  return style;
}

/**
 * Vrstvy masky regiónu – tie, ktoré musia ostať úplne navrchu. Sú tu, a nie
 * ako reťazec v `applyLayerOrder`, lebo sa na ne pýta aj developer mode
 * (neponúka ich presúvať) a `workers/lint/style.mjs`.
 */
export const REGION_MASK_LAYERS = ["region-outside", "region-border"];

/**
 * Cesty: jeden riadok na triedu, ZORADENÉ OD NAJDÔLEŽITEJŠEJ.
 *
 * `[id, popis, triedy, farba výplne, farba obrysu, stopy šírky,
 *   prídavok obrysu, minzoom]`; šírky sú definované až po z20, aby
 * overzoomované dlaždice vyzerali správne.
 *
 * **PORADIE V TOMTO POLI JE PORADIE DÔLEŽITOSTI, NIE PORADIE KRESLENIA.**
 * MapLibre kreslí vrstvy tak, ako idú v štýle za sebou, takže navrchu skončí
 * TÁ POSLEDNÁ – vrstvy sa preto pridávajú OD KONCA tohto poľa (`roadPass`).
 * Kým sa pridávali v tomto poradí, kreslila sa účelová cesta cez diaľnicu:
 * na každej križovatke bol cez diaľničný pás prúžok vo farbe tej malej cesty
 * a vyzeralo to, akoby bola diaľnica prerušená. Je to tichá chyba – štýl je
 * platný, mapa sa načíta a nikto nič nepovie – takže na ňu je kontrola
 * (`workers/lint/style.mjs`). Toto pole je jej jediný zdroj pravdy o tom, čo
 * je dôležitejšie; export je práve preto.
 */
export const ROAD_DEFS = [
  ["motorway", "Diaľnice", ["motorway"], "motorway", "motorwayCasing",
    [[4, 0.5], [6, 0.9], [10, 3], [14, 8], [16, 18], [20, 60]], 3, 4],
  ["trunk", "Rýchlostné cesty", ["trunk"], "trunk", "roadCasing",
    [[5, 0.45], [7, 0.8], [10, 2.6], [14, 7], [16, 16], [20, 52]], 2.6, 5],
  ["primary", "Cesty I. triedy", ["primary"], "primary", "roadCasing",
    [[6, 0.4], [8, 0.75], [10, 2.2], [14, 6.5], [16, 15], [20, 48]], 2.4, 6],
  ["secondary", "Cesty II. triedy", ["secondary"], "secondary", "roadCasing",
    [[8, 0.4], [10, 0.7], [12, 2], [14, 5], [16, 12], [20, 40]], 2, 8],
  ["tertiary", "Cesty III. triedy", ["tertiary"], "secondary", "roadCasing",
    [[9, 0.35], [11, 0.6], [12, 1.6], [14, 4.2], [16, 10], [20, 34]], 1.8, 9],
  // `living_street` schéma nevydáva – `highway=living_street` mapuje na
  // `minor` rovnako ako `residential` a `unclassified`.
  ["minor", "Miestne cesty", ["minor", "raceway", "busway", "bus_guideway"], "minor", "roadCasing",
    [[11, 0.3], [12, 0.6], [14, 3.5], [16, 9], [20, 32]], 1.6, 11],
  ["service", "Účelové cesty", ["service"], "service", "roadCasing",
    [[12, 0.3], [13, 0.5], [14, 2], [16, 6], [20, 22]], 1.2, 12],
  ["pedestrian", "Pešie zóny", ["pedestrian"], "pedestrian", "roadCasing",
    [[12, 0.3], [13, 0.6], [14, 2.4], [16, 7], [20, 24]], 1.2, 12]
];

/** Prípony troch priechodov ciest (tunel → povrch → most) – pre kontrolu. */
export const ROAD_PASSES = ["-tunnel", "", "-bridge"];

/**
 * ŠTÍTKY S ČÍSLOM CESTY – „D1", „R1", „I/18", „II/537".
 *
 * `[id, popis, triedy OSM, kľúč palety podkladu, minzoom, tvar štítka]`
 *
 * Číslo cesty je iná vec než jej meno a preto je to iná vrstva: meno beží
 * pozdĺž cesty a je unikátne, číslo je ZNAČKA – opakuje sa po celej dĺžke,
 * je krátke a človek ho na mape HĽADÁ („kde je D1?"). Vrstva `road-name`
 * ho doteraz nekreslila vôbec: v jej `text-field` je meno a `ref` sa
 * v hlavných dlaždiciach nikde neobjavil.
 *
 * TRIEDY SÚ Z DLAŽDÍC, NIE Z ČÍSLA. Lákalo by rozlíšiť štítok podľa toho,
 * čím sa `ref` začína („D" = diaľnica, „R" = rýchlostná), ale to je pravidlo
 * o slovenskom číslovaní zapísané v štýle, ktorý sa dá postaviť nad
 * hocijakým regiónom – v Rakúsku je „A1" diaľnica a „B1" hlavná cesta, takže
 * by z toho vyšlo, že A1 je cesta I. triedy. `class` z dlaždíc hovorí to
 * isté a hovorí to všade rovnako.
 *
 * `D` a `R` majú JEDEN štítok. Sú to dve triedy OSM (`motorway`, `trunk`),
 * ale jedna sieť aj jedno značenie – rozlišuje ich samotné číslo.
 *
 * MINZOOM JE VYŠŠÍ NEŽ PRI ČIARE. Diaľnica sa kreslí od z4, ale štítok má
 * veľkosť v pixeloch, nie v metroch: na z4 by ich cez celé Slovensko bolo
 * niekoľko sto a mapa by bola z nich. Od z7 je ich toľko, koľko sa dá
 * prečítať.
 */
// `[id, popis, triedy, farba podkladu, minzoom, tvar, farba čísla, orámovanie]`
//
// FARBY SÚ PODĽA ŠTÍTKA S ČÍSLOM CESTY, nie podľa smerovej tabule. Je to
// rozdiel, na ktorom to predtým stálo zle: na diaľnici je ZELENÁ TABUĽA
// (a podľa nej boli štítky zelené), ale ČÍSLO cesty sa v československom
// značení píše do červeného štítka. Tabuľa a štítok sú dve rôzne veci a na
// mape je vidieť ten druhý.
//
//   D, R   červená, biele číslo      (motorway + trunk – R je v OSM `trunk`)
//   I.     modrá, biele číslo
//   II/III biela, TMAVÉ číslo a tmavý rámik
//
// Práve kvôli tomu poslednému má každý riadok vlastnú farbu čísla aj rámika:
// jedno spoločné biele číslo by na bielom štítku zmizlo a biely rámik okolo
// bieleho štítka by ho na svetlej mape nechal splynúť s podkladom.
/**
 * Sieť európskych ciest v dlaždiciach – hodnota `route_*_network`.
 *
 * ODKIAĽ SA BERIE ČÍSLO. `ref` na ceste je číslo NÁRODNÉ („D2"); európske
 * („E 65") visí na RELÁCII a OpenMapTiles ho dáva do párov
 * `route_1_network`/`route_1_ref` … `route_6_*`. Poradie nie je zaručené,
 * takže sa musí prejsť všetkých šesť a vziať ten, ktorého sieť je `e-road`.
 *
 * Overené na hotových dlaždiciach Bratislavského kraja: `route_*_network` má
 * hodnoty `sk:national` (138×), `e-road` (109×), `sk:primary` (45×),
 * turistické `rwn`/`nwn`/`iwn`/`lwn` a niekoľko maďarských; E-čísla prišli
 * ako `{network: "e-road", ref: "E 65"}` na `class: motorway` s `ref: "D2"`.
 * Ref má MEDZERU („E 65") – tak sa aj vypíše, tak to má aj tabuľa.
 */
export const EURO_NETWORK = "e-road";

/** Koľko `route_N_*` párov OpenMapTiles vydáva. */
export const ROUTE_SLOTS = 6;

export const SHIELD_DEFS = [
  ["motorway", "Štítky diaľnic a rýchlostných ciest", ["motorway", "trunk"],
    "shieldMotorway", 7, "shield", "shieldText", "shieldBorder"],
  ["primary", "Štítky ciest I. triedy", ["primary"],
    "shieldPrimary", 8, "shield", "shieldText", "shieldBorder"],
  ["secondary", "Štítky ciest II. a III. triedy", ["secondary", "tertiary"],
    "shieldSecondary", 10, "shield", "shieldTextDark", "shieldBorderDark"],
  // EURÓPSKA CESTA (E75, E65, E575) – zelený štítok s bielym číslom, tak ako
  // úradná značka (`E75-SVK-2020.svg`, odmerané #008c27).
  //
  // Je to INÉ ČÍSLO NEŽ NÁRODNÉ, nie jeho náhrada: cez ten istý úsek D2 vedie
  // E65, takže sa kreslia OBE – E-štítok pod národným. Preto tento riadok
  // nefiltruje podľa `class` (E-cesta ide po diaľnici aj po ceste I. triedy),
  // ale podľa siete v `route_*`, a číslo si berie odtiaľ. Rozpis pri
  // `EURO_NETWORK`.
  ["euro", "Štítky európskych ciest (E75)", null,
    "shieldEuro", 8, "shield", "shieldText", "shieldBorder", EURO_NETWORK]
];

/**
 * Vygeneruje kompletný MapLibre GL štýl.
 *
 * @param {object} opts
 * @param {string} opts.theme       kľúč témy z THEMES
 * @param {string} opts.tilesUrl    napr. "pmtiles://https://…/tiles/slovensko.pmtiles"
 * @param {string} opts.spriteUrl   absolútna URL spritu (bez prípony)
 * @param {string} opts.glyphsUrl   URL šablóna glyfov {fontstack}/{range}
 * @param {string} [opts.name]      názov štýlu
 * @param {string[]} [opts.icons]   mená ikon dostupných v sprite
 * @param {string} [opts.iconSet]   id sady ikoniek (určuje príponu mien)
 * @param {object} [opts.fonts]     {regular, bold, italic} – názvy fontstackov
 * @param {number} [opts.maxzoom]   najvyšší zoom dlaždíc (default MAX_TILE_Z)
 * @param {string} [opts.contoursUrl]     pmtiles:// URL s vrstevnicami (voliteľné)
 * @param {number} [opts.contoursMaxzoom] najvyšší zoom dlaždíc s vrstevnicami
 * @param {string} [opts.trailsUrl]       pmtiles:// URL so značenými trasami
 * @param {number} [opts.trailsMaxzoom]   najvyšší zoom dlaždíc s trasami
 * @param {string} [opts.featuresUrl]     pmtiles:// URL s krajinnými prvkami
 *                                        (línie a plochy), ktoré schéma
 *                                        OpenMapTiles nemá
 * @param {number} [opts.featuresMaxzoom] najvyšší zoom dlaždíc s prvkami
 * @param {string} [opts.pointsUrl]       pmtiles:// URL s bodmi v krajine
 *                                        (pramene, jaskyne, rozhľadne, …) –
 *                                        DRUHÝ výstup toho istého jobu ako
 *                                        `featuresUrl` (workers/features/points.yml)
 * @param {number} [opts.pointsMaxzoom]   najvyšší zoom dlaždíc s bodmi
 * @param {string} [opts.roadsUrl]        pmtiles:// URL s obmedzeniami na ceste,
 *                                        alebo null, keď ich beh nevyrobil
 * @param {number} [opts.roadsMaxzoom]    najvyšší zoom dlaždíc s obmedzeniami
 * @param {string} [opts.demSource]       zdroj výšok (kľúč z DEM_SOURCES) –
 *                                        určuje atribúciu vrstevníc a skál
 * @param {string|null} [opts.demTiles]   raster-dem dlaždice pre hillshade
 *                                        a 3D terén (null = bez nich)
 * @param {string} [opts.demTilesSource]  zdroj výšok pre tie dlaždice; odkedy
 *                                        má tieňovanie vo formulári vlastný
 *                                        výber, nemusí to byť ten istý model
 *                                        ako pri vrstevniciach (default: je)
 * @param {number} [opts.demMaxzoom]      najvyšší zoom výškových dlaždíc
 * @param {number[]|null} [opts.demBounds] kde vlastné výškové dlaždice vôbec
 *                                        sú (`[w,s,e,n]`) – pri rýchlom teste
 *                                        je to štvorec s pár km², nie celý kraj
 * @param {object|string|null} [opts.regionOutline] hranica stiahnutého regiónu
 *                                  (`_site/region.geojson`) – buď rovno dáta,
 *                                  alebo URL na ne. Za ňou štýl nekreslí nič.
 * @param {boolean} [opts.hillshade] zapnúť tieňovanie reliéfu (default nie)
 * @param {boolean} [opts.terrain3d] vyzdvihnúť mapu do 3D z tých istých
 *                                   výškových dlaždíc (default nie)
 * @param {number} [opts.terrainExaggeration] násobok prevýšenia (default 1.3)
 * @param {boolean} [opts.sdfIcons] sprite je SDF – ikonám sa dá nastaviť farba
 * @param {string} [opts.mapType]   typ mapy (turistická / lyžiarska / cestná /
 *                                  historická / základná) – určuje, ktoré
 *                                  vrstvy sa vôbec kreslia a od akého zoomu
 * @param {object|null} [opts.overrides]  úpravy z developer módu
 */
export function buildStyle({
  theme,
  tilesUrl,
  spriteUrl,
  glyphsUrl,
  name,
  icons,
  fonts,
  maxzoom = MAX_TILE_Z,
  contoursUrl = null,
  contoursMaxzoom = 14,
  rocksUrl = null,
  rocksMaxzoom = 16,
  trailsUrl = null,
  trailsMaxzoom = 14,
  featuresUrl = null,
  featuresMaxzoom = 15,
  pointsUrl = null,
  pointsMaxzoom = 15,
  roadsUrl = null,
  roadsMaxzoom = 15,
  demSource = DEFAULT_DEM_SOURCE,
  demTiles = DEFAULT_DEM_TILES,
  demTilesSource = null,
  demMaxzoom = DEFAULT_DEM_MAXZOOM,
  demBounds = null,
  regionOutline = null,
  sdfIcons = false,
  iconSet = null,
  hillshade = null,
  terrain3d = false,
  terrainExaggeration = DEFAULT_TERRAIN_EXAGGERATION,
  mapType = DEFAULT_MAP_TYPE,
  overrides: rawOverrides = null
}) {
  // Typ mapy určuje profil (čo sa kreslí) aj to, ktoré úpravy platia:
  // spoločné plus tie, čo si používateľ nastavil práve pre túto mapu.
  const mapTypeId = normalizeMapType(mapType);
  const overrides = resolveOverrides(rawOverrides, mapTypeId);
  // Tieňovanie reliéfu je vypnuté, kým ho niekto výslovne nezapne.
  const showHillshade = hillshade === null ? overrides?.hillshade === true : hillshade === true;
  // 3D sa dá zapnúť len tam, kde sú výškové dlaždice – bez zdroja `dem`
  // by `terrain` v štýle ukazoval na nič a MapLibre by ho odmietol.
  const show3d = terrain3d === true && Boolean(demTiles);
  const c = mergedPalette(theme, overrides);
  // Sada ikoniek určuje, ako sa mená skladajú (osm-liberty používa `_11`).
  const iconSetId = iconSet || selectedIconSource(overrides);
  const { suffix } = iconSourceIn(iconSetId, overrides);
  const SPECIAL = specialIcons(iconSetId, overrides);

  const f = { ...DEFAULT_FONTS, ...(fonts || {}) };
  const REG = [f.regular];
  const BOLD = [f.bold];
  const ITAL = [f.italic];

  const iconClasses = iconClassesOf(icons, suffix);
  // VLASTNÁ IKONA JE „V SPRITE" AJ VTEDY, KEĎ V ŇOM EŠTE NIE JE. Zoznam mien
  // sa berie z hotového spritu, takže práve pridaná ikona by v ňom nebola
  // a štýl by ju ticho vynechal – hoci v prehliadači ju mapa má hneď
  // (`map.addImage` v poc/web/app.js) a do spritu ju pri builde dopečie
  // `workers/assets/custom-icons.mjs`.
  const vlastne = new Set(customIconNames(overrides));
  const hasIcon = (n) =>
    vlastne.has(n) || (icons && icons.length ? icons.includes(n) : true);

  const nameExpr = [
    "coalesce",
    ["get", "name:sk"],
    ["get", "name"],
    ["get", "name:latin"],
    ""
  ];

  const style = {
    version: 8,
    name: name || `FricoMaps – ${c.label}`,
    metadata: {
      "frico:theme": theme,
      "frico:map-type": mapTypeId,
      "frico:icons": iconSetId,
      "frico:hillshade": showHillshade,
      "frico:terrain-3d": show3d,
      "frico:overrides": hasOverrides(rawOverrides)
    },
    sources: {
      omt: {
        type: "vector",
        url: tilesUrl,
        // Dlaždice končia na `maxzoom`; vyššie zoomy MapLibre dopočíta
        // overzoomom, takže mapa je použiteľná až po MAX_DISPLAY_Z.
        maxzoom,
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> prispievatelia'
      }
    },
    sprite: spriteUrl,
    glyphs: glyphsUrl,
    layers: []
  };

  // Vrstevnice sú samostatný .pmtiles – nezávislý od OSM buildu, lebo
  // závisia len od územia, nie od toho, čo sa v OSM zmenilo.
  if (contoursUrl) {
    style.sources.contours = {
      type: "vector",
      url: contoursUrl,
      maxzoom: contoursMaxzoom,
      attribution: (DEM_SOURCES[demSource] || DEM_SOURCES[DEFAULT_DEM_SOURCE])
        .attribution
    };
  }
  // Skaly majú od vrstevníc ODDELENÝ .pmtiles, a to kvôli maxzoomu: každý
  // súbor má jeden a tie dve vrstvy ho chcú úplne iný. Vrstevnice sú čiary
  // cez celý kraj a rozpočet stránky minú okolo z14; skaly sú plochy len
  // tam, kde je terén strmý, takže sa do z16 zmestia – a práve pri priblížení
  // je vidieť, či obrys sedí na terén. Nad `maxzoom` sa dlaždice naťahujú
  // overzoomom, takže sú skaly vidieť až do maximálneho zoomu mapy.
  if (rocksUrl) {
    style.sources.rocks = {
      type: "vector",
      url: rocksUrl,
      maxzoom: rocksMaxzoom,
      attribution: (DEM_SOURCES[demSource] || DEM_SOURCES[DEFAULT_DEM_SOURCE])
        .attribution
    };
  }
  // Značené trasy sú tiež samostatný .pmtiles: sú to `type=route` relácie,
  // ktoré schéma OpenMapTiles nepozná – v hlavných dlaždiciach je len cesta,
  // bez značenia. Robia sa z toho istého PBF, ale vlastným krokom pipeline.
  if (trailsUrl) {
    style.sources.trails = {
      type: "vector",
      url: trailsUrl,
      maxzoom: trailsMaxzoom,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> prispievatelia'
    };
  }
  // Krajinné prvky (línie a plochy), ktoré schéma OpenMapTiles nepozná
  // vôbec: násypy, zárezy, múry, ploty, vedenia, prieseky, parkoviská
  // a zjazdovky. V celom `planetiler-openmaptiles` sa `embankment` ani raz
  // nevyskytuje, takže sa tieto veci ťahajú z toho istého PBF druhýkrát
  // vlastnou schémou (workers/features/features.yml) do vlastného .pmtiles.
  if (featuresUrl) {
    style.sources.features = {
      type: "vector",
      url: featuresUrl,
      maxzoom: featuresMaxzoom,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> prispievatelia'
    };
  }
  // Body v krajine: pramene, jaskyne, rozhľadne, pamiatky, banské dedičstvo,
  // geodetické body. DRUHÝ výstup toho istého jobu ako krajinné prvky
  // vyššie – vlastná schéma (workers/features/points.yml), vlastný
  // .pmtiles, presne kvôli balíku „body“ na stiahnutie zvlášť od línií.
  if (pointsUrl) {
    style.sources.points = {
      type: "vector",
      url: pointsUrl,
      maxzoom: pointsMaxzoom,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> prispievatelia'
    };
  }
  // Obmedzenia na ceste (workers/roads/roads.yml) – výška podjazdov a tunelov,
  // šírka, hmotnosť, maximálna rýchlosť. Vrstva `transportation` OpenMapTiles
  // z toho nenesie ANI JEDNU hodnotu, takže je to – rovnako ako krajinné prvky
  // – druhé čítanie toho istého PBF do vlastného .pmtiles.
  if (roadsUrl) {
    style.sources.roads = {
      type: "vector",
      url: roadsUrl,
      maxzoom: roadsMaxzoom,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> prispievatelia'
    };
  }
  // Raster DEM pre tieňovanie reliéfu a 3D terén (funguje na webe aj iOS).
  // Vlastné dlaždice (workers/terrain/tiles.py) majú vo formulári vlastný
  // výber modelu, takže atribúcia ide podľa `demTilesSource` – a nie podľa
  // vrstevníc, ktoré môžu byť z iného. Keď ich pipeline nevyrobila, padá sa
  // na verejné AWS Terrain Tiles.
  if (demTiles) {
    const ownDem = demTiles !== DEFAULT_DEM_TILES;
    const tilesSource = demTilesSource || demSource;
    // Vlastné dlaždice chodia ako JEDEN `.pmtiles` (workers/terrain/pack.py),
    // verejné AWS ako šablóna `{z}/{x}/{y}.png`. Rozlišuje sa to podľa
    // protokolu, nie podľa druhého prepínača – dve polia o tej istej veci sa
    // vždy raz rozídu.
    const demIsArchive = demTiles.startsWith("pmtiles://");
    style.sources.dem = {
      type: "raster-dem",
      ...(demIsArchive ? { url: demTiles } : { tiles: [demTiles] }),
      encoding: "terrarium",
      tileSize: 256,
      maxzoom: demMaxzoom,
      attribution: ownDem
        ? (DEM_SOURCES[tilesSource] || DEM_SOURCES[DEFAULT_DEM_SOURCE]).attribution
        : '<a href="https://registry.opendata.aws/terrain-tiles/">AWS Terrain Tiles</a>'
    };
    // Vlastné dlaždice nemusia pokrývať celú mapu: rýchly test (switch `test`)
    // ich počíta len na štvorci s pár km², kým mapa je celý kraj. `bounds`
    // hovorí MapLibre, kde ich má vôbec pýtať – bez neho by z každého posunu
    // mapy padali stovky 404 a v konzole by sa stratilo všetko ostatné.
    //
    // PRI `.pmtiles` SA NEDOPISUJE: rozsah aj zoomy si archív nesie v hlavičke
    // a klient ich prečíta skôr, než si vypýta prvú dlaždicu. Dopísať ich sem
    // druhýkrát by znamenalo dve pravdy o jednej veci – a tá z formulára by
    // sa časom rozišla s tým, čo v archíve naozaj je.
    if (ownDem && !demIsArchive
        && Array.isArray(demBounds) && demBounds.length === 4) {
      style.sources.dem.bounds = demBounds.map(Number);
    }
    // 3D TERÉN PRIAMO V ŠTÝLE. Doteraz si ho zapínal len web za behu
    // (`map.setTerrain` v poc/web/app.js), takže všetko ostatné, čo tento
    // štýl číta – iOS cez MapLibre Native – dostávalo plochú mapu, hoci
    // výškové dlaždice v štýle boli. `terrain` je súčasť štýlu podľa
    // špecifikácie, takže ho každý klient zapne sám.
    if (show3d) {
      style.terrain = {
        source: "dem",
        exaggeration: Number(terrainExaggeration) || DEFAULT_TERRAIN_EXAGGERATION
      };
    }
  }

  // HRANICA STIAHNUTÉHO REGIÓNU. Mapa sa stavia z PBF kraja, ale dlaždice
  // vznikajú po celých dlaždiciach a Planetiler do nich kreslí vodstvo aj
  // Natural Earth, ktoré sú celosvetové – bez tejto vrstvy teda mapa
  // pokračuje aj tam, kde z nášho regiónu nie je nič, len podfarbené prázdno
  // bez ciest a sídel. V aplikácii, kde si používateľ región STIAHNE, to
  // vyzerá ako mapa, ktorá sa nedonačítala.
  //
  // Súbor vyrába `workers/deploy/region-mask.py` z toho istého `.poly`, ktorým
  // je orezaný PBF (a ktorý dostáva `-cutline` vrstevníc aj maska tieňovania),
  // takže hranica je jedna – nekreslí sa tu druhá (pravidlo 1).
  if (regionOutline) {
    style.sources.region = {
      type: "geojson",
      data: regionOutline
    };
  }

  const L = style.layers;

  /**
   * Pridá vrstvu spolu s metadátami pre developer mode.
   *
   * `paletteExtra` sú kľúče palety, ktoré vrstva používa vo **výraze**
   * (napr. farba pásika trasy sa vyberá podľa značky z OSM). Taká farba nie
   * je v `paint` obyčajným hexom, takže by ju developer mode v riadku vrstvy
   * nenašiel – odtiaľ sa potom ladí cez paletu.
   *
   * `pattern` je vzor ZABUDOVANÝ V ŠTÝLE – teda taký, ktorý má vrstva aj
   * bez toho, aby ho niekto naklikal v developer móde (kamienky v skalnej
   * ploche). Vzor sa v MapLibre nedá nakresliť do tej istej vrstvy ako
   * výplň, takže z neho vzniká vrstva navyše hneď nad predlohou; predpis
   * ostáva v metadátach, aby ho developer mode vedel ukázať, doladiť
   * a vypnúť (`pattern: null` v úprave vrstvy).
   *
   * @param {object} layer  vrstva podľa MapLibre style-spec
   * @param {[string,string,string,object?,string[]?,object?]} meta
   *        [skupina, popis, druh, {paintProp: kľúč palety},
   *         [kľúče palety vo výrazoch], {id,color,size,weight,opacity}]
   */
  const add = (layer, meta) => {
    const [group, label, kind, palette, paletteExtra, pattern] = meta;
    const l = { ...layer };
    if (l.type !== "background" && !l.source) l.source = "omt";
    const pat = pattern ? patternDef(pattern) : null;
    // ZABUDOVANÉ PRERUŠOVANIE do metadát – inak sa v developer móde nedá
    // ukázať ani vrátiť. Panel dostáva štýl, na ktorom už úpravy sedia,
    // takže z `paint` sa „aké to bolo pôvodne" prečítať nedá: kým tu tento
    // riadok nebol, ukazoval výber pri KAŽDEJ čiare „Plná" – aj pri
    // železnici, ktorá má `rail` – a voľba „Plná" sa navyše zahodila ako
    // „veď to je predvolené", takže čiarkovanie železnice sa nedalo ani
    // zmeniť, ani vypnúť. Ukladá sa PREDVOĽBA, a keď žiadna nesedí, rovno
    // to pole čísel – aby aj vlastné prerušovanie zo štýlu vedel panel
    // pomenovať a vrátiť.
    const dashBuiltin = (l.paint || {})["line-dasharray"];
    l.metadata = {
      "frico:group": group,
      "frico:label": label,
      "frico:kind": kind,
      "frico:palette": palette || {},
      ...(paletteExtra && paletteExtra.length
        ? { "frico:palette-extra": paletteExtra }
        : {}),
      ...(pat ? { "frico:pattern": pat } : {}),
      ...(Array.isArray(dashBuiltin)
        ? { "frico:dash": dashIdOf(dashBuiltin) || dashBuiltin }
        : {})
    };
    L.push(l);
    if (pat) {
      const p = patternLayer(l, pat);
      if (p) L.push(p);
    }
  };

  /**
   * „Táto vrstva patrí k tamtej a presúva sa s ňou."
   *
   * Niektoré prvky sú v štýle DVE vrstvy, lebo MapLibre inak nevie, čo od
   * nich chceme: hrana so zúbkami (druhá čiara odsunutá nabok) a železnica
   * (tmavá čiara a na nej svetlé čiarkovanie). Pri farbe a hrúbke sa ladia
   * zvlášť – to je v poriadku, sú to naozaj dve otázky –, ale PORADIE
   * KRESLENIA je pri nich jedna: keby sa dala presunúť len polovica, ostali
   * by zúbky nad cestou a hrana pod ňou. Zapisuje sa preto, ku ktorej vrstve
   * tá druhá patrí, a `applyLayerOrder` ich presúva spolu.
   */
  const spolu = (parent) => {
    L[L.length - 1].metadata["frico:with"] = parent;
  };

  add(
    {
      id: "background",
      type: "background",
      paint: { "background-color": c.background }
    },
    ["zaklad", "Pozadie mapy", "area", { "background-color": "background" }]
  );

  // ================= krajinná pokrývka =================
  // Trieda aj `subclass` naraz: schéma zlieva do `class=grass` úplne všetko
  // od lúky po kosodrevinu a od záhradky po golfové ihrisko. Rozlíšiť sa to
  // dá len cez `subclass`, ktorý pôvodnú hodnotu tagu nesie – preto tu sú
  // aj vrstvy, ktoré `class` vôbec nepoužívajú. Poradie je poradím kreslenia:
  // jemnejšie rozlíšenie ide navrch nad všeobecnejšiu triedu pod ním.
  const landcover = [
    ["wood", "Les", ["wood", "forest"], "forest", 0.9],
    ["grass", "Tráva a lúky", ["grass", "grassland", "meadow"], "grass", 0.7],
    // Kosodrevina, kroviny, vresovisko a holina. V dlaždiciach majú
    // `class=grass`, takže sa dovtedy kreslili ako lúka – v Tatrách je to
    // rozdiel medzi „dá sa prejsť" a „nedá".
    ["scrub", "Kroviny a kosodrevina", ["scrub", "shrubbery", "heath", "fell", "tundra"], "scrub", 0.85],
    ["farmland", "Polia", ["farmland"], "grass", 0.45],
    // Záhrady, sady a vinice. Boli vo vrstve `landuse`, kde ich schéma nikdy
    // nemá – `landuse` pozná len 26 tried a ani jedna z týchto medzi ne
    // nepatrí. Odtiaľto sa trafia.
    ["garden", "Záhrady a sady", ["garden", "allotments", "orchard", "vineyard", "plant_nursery"], "garden", 0.8],
    ["golf", "Golfové ihriská", ["golf_course", "recreation_ground", "village_green"], "pitch", 0.6],
    ["wetland", "Mokrade", ["wetland", "swamp", "marsh", "bog"], "wetland", 0.8],
    // SUŤ MÁ VZOR DROBNÝCH KAMEŇOV. `natural=scree` a `bare_rock` z OSM je
    // presne to, čo vzor kreslí: popadané kamene pod stenou, kamenné more,
    // holá skala. Papierová horská mapa ich takto značí odjakživa a plná
    // farba to nepovie – suť a lúka sú v nej rovnaká škvrna, len inak sfarbená.
    //
    // Vzor je JEMNÝ, nie ozdobný. Dlaždica sa zadáva v PIXELOCH OBRAZOVKY,
    // nie v metroch – vzor sa so zoomom nezväčšuje, takže 9 px je jeden
    // kamienok veľký dva-tri pixely na každom zoome. Vyskúšané aj 26 px
    // (pôvodná veľkosť na skalných plochách): v ploche z toho bola dlažba,
    // nie suť.
    //
    // Počítané skalné plochy (`rock-area` z DEM) vzor ZÁMERNE NEMAJÚ: to je
    // stena a strmý sklon, nie sypké kamene, a kresba drobných kameňov by
    // o tvare terénu klamala.
    ["rock", "Skaly a suť", ["rock", "scree", "bare_rock"], "rock", 0.8,
     { id: "rocks", color: "rockPattern", size: 9, weight: 0.6, opacity: 0.75 }],
    ["sand", "Piesok", ["sand", "beach"], "sand", 1],
    ["ice", "Ľadovec", ["ice", "glacier"], "ice", 1]
  ];
  for (const [id, label, classes, paletteKey, opacity, pattern] of landcover) {
    add(
      {
        id: `landcover-${id}`,
        type: "fill",
        "source-layer": "landcover",
        filter: [
          "any",
          ["in", str("class"), ["literal", classes]],
          ["in", str("subclass"), ["literal", classes]]
        ],
        paint: { "fill-color": c[paletteKey], "fill-opacity": opacity }
      },
      // Farba vzoru je v zozname ako KĽÚČ PALETY, nie hex – aby ju mala každá
      // téma svoju, rovnako ako výplň pod ňou.
      ["krajina", label, "area", { "fill-color": paletteKey }, null,
        pattern ? { ...pattern, color: c[pattern.color] } : null]
    );
  }

  // ================= využitie územia =================
  // Zoznam tried je presne ten, ktorý schéma naozaj vydáva (26 hodnôt,
  // Tables.java: osm_landuse_polygon). Triedy, ktoré tu boli navyše
  // (`warehouse`, `danger_area`, `sports_centre`, `landfill`, `grave_yard`,
  // celá vrstva `garden`), sa nemali ako trafiť – schéma ich do `landuse`
  // nedáva. Záhrady a golf sa presunuli do `landcover`, skládka do vlastných
  // dlaždíc s krajinnými prvkami; `grave_yard` schéma sama premapuje na
  // `cemetery`.
  const landuse = [
    ["residential", "Obytná zóna", ["residential", "suburb", "neighbourhood", "quarter"], "residential"],
    ["industrial", "Priemysel a obchod", ["industrial", "commercial", "retail", "garages"], "industrial"],
    ["railway", "Železničný areál", ["railway", "bus_station"], "industrial"],
    ["cemetery", "Cintorín", ["cemetery"], "cemetery"],
    ["hospital", "Nemocnica", ["hospital"], "hospital"],
    ["school", "Školstvo", ["school", "university", "college", "kindergarten", "library"], "school"],
    ["military", "Vojenský priestor", ["military"], "military"],
    ["quarry", "Lom", ["quarry"], "quarry"],
    ["playground", "Ihriská a zoo", ["playground", "theme_park", "zoo"], "playground"],
    ["pitch", "Športoviská", ["pitch", "stadium", "track"], "pitch"],
    // `waterway=dam` ako plocha – teleso priehrady. V dlaždiciach je od
    // začiatku, štýl ho nekreslil.
    ["dam", "Priehrada (plocha)", ["dam"], "dam"]
  ];
  for (const [id, label, classes, paletteKey] of landuse) {
    add(
      {
        id: `landuse-${id}`,
        type: "fill",
        "source-layer": "landuse",
        filter: ["in", str("class"), ["literal", classes]],
        paint: { "fill-color": c[paletteKey] }
      },
      ["uzemie", label, "area", { "fill-color": paletteKey }]
    );
  }

  // ---- plochy z vlastných dlaždíc ----
  // Parkovisko, skládka, halda, hospodársky dvor. Schéma OpenMapTiles ich
  // ako plochu nemá vôbec – `amenity=parking` je v nej len bod, `landfill`
  // ani `farmyard` nie sú ani to. Kreslia sa hneď za `landuse`, lebo patria
  // k tomu istému: čo sa s územím robí.
  if (featuresUrl) {
    const featureAreas = [
      ["parking", "Parkoviská", ["parking"], "parking", 0.9],
      ["landfill", "Skládky a haldy", ["landfill", "spoil_heap"], "quarry", 1],
      ["farmyard", "Hospodárske dvory", ["farmyard", "greenhouse_horticulture"], "farmyard", 1],
      ["brownfield", "Opustený priemysel", ["brownfield"], "industrial", 0.7],
      ["shingle", "Kamenné polia", ["shingle"], "rock", 0.8]
    ];
    for (const [id, label, classes, paletteKey, opacity] of featureAreas) {
      add(
        {
          id: `feature-${id}`,
          type: "fill",
          source: "features",
          "source-layer": "feature_area",
          filter: ["in", str("class"), ["literal", classes]],
          paint: { "fill-color": c[paletteKey], "fill-opacity": opacity }
        },
        ["prvky", label, "area", { "fill-color": paletteKey }]
      );
    }

    // ---- zjazdovky ----
    // Vleky v dlaždiciach sú (`transportation class=aerialway`), trate nie:
    // `piste:type` schéma nepozná. Na lyžiarskej mape tak boli vleky bez
    // toho, k čomu vedú. Plocha aj os sú tá istá vrstva – uzavretá cesta
    // vyjde ako plocha aj ako čiara, takže dostane výplň s obrysom.
    //
    // A práve preto tu MUSÍ byť `polygonOnly`: `workers/features/features.yml` púšťa do
    // vrstvy `piste` zámerne oba tvary, takže by táto výplň dostala aj os
    // zjazdovky – otvorenú čiaru, z ktorej MapLibre earcutom vyrobí nezmysel
    // (rozpis pri `POLYGON_ONLY`). Os kreslí `piste-line` o kus nižšie.
    add(
      {
        id: "piste-area",
        type: "fill",
        source: "features",
        "source-layer": "piste",
        filter: polygonOnly(),
        paint: { "fill-color": c.pisteArea, "fill-opacity": 0.8 }
      },
      ["prvky", "Zjazdovky (plocha)", "area", { "fill-color": "pisteArea" }]
    );
  }

  add(
    {
      id: "park",
      type: "fill",
      "source-layer": "park",
      // Vrstva `park` nesie aj bod pre popisok (Planetiler ho dáva ako
      // `pointOnSurface`), nie len obrys chráneného územia.
      filter: polygonOnly(),
      paint: { "fill-color": c.park, "fill-opacity": 0.55 }
    },
    ["uzemie", "Park (plocha)", "area", { "fill-color": "park" }]
  );
  add(
    {
      id: "park-outline",
      type: "line",
      "source-layer": "park",
      minzoom: 10,
      paint: {
        "line-color": c.parkOutline,
        "line-width": zl([[10, 0.6], [16, 1.6], [20, 3]]),
        "line-dasharray": [4, 2]
      }
    },
    ["uzemie", "Park (obrys)", "line", { "line-color": "parkOutline" }]
  );

  // ================= skalné plochy =================
  // SÚ TU, TESNE POD TIEŇOVANÍM, A NIE PRI VRSTEVNICIACH. Skala je tvar
  // terénu, nie kresba nad ním – a tieňovanie je to isté, len rastrom.
  // Keď ležala sivá plocha NAD tieňovaním, prekryla ho a stena bola v mape
  // plochá škvrna bez reliéfu presne tam, kde je terén najzaujímavejší.
  // Teraz cez ňu tieňovanie prejde a stena má tvar. Voda ostáva nad oboma:
  // tieňovaná vodná hladina vyzerá nesprávne a jazero na skalnej ploche je
  // jazero.
  //
  // JEDNA VRSTVA, JEDNA SIVOHNEDÁ, BEZ PRIEHĽADNOSTI. Predtým to boli dve
  // polopriehľadné vrstvy (`steep` a `cliff`) a tenký obrys. Priehľadnosť
  // ale znamená, že KAŽDÝ prekryv je vidieť – dve plochy cez seba vyjdú
  // tmavšie než jedna, a stačí na to plocha rozseknutá hranicou bloku
  // alebo `cliff` ležiaci vo vyplnenej diere `steep`u. Plná farba to rieši
  // na úrovni kreslenia: prekryv je neviditeľný, takže sa plochy nemusia
  // ani zlepovať, ani strážiť proti sebe.
  if (rocksUrl) {
    add(
      {
        id: "rock-area",
        type: "fill",
        source: "rocks",
        "source-layer": "rock",
        // Od z11 (`TERRAIN_MIN_Z`), nie od z1. Na prehľadovej mierke je zo skál
        // sivá škvrna, ktorá nič nepovie, a dlaždice s ňou sa aj tak sťahujú –
        // mapové podklady tým rástli za niečo, čo netreba. Pod tým zoomom teda
        // skaly v mape nie sú vôbec, presne ako vrstevnice; rozpis je pri tej
        // konštante.
        minzoom: TERRAIN_MIN_Z,
        paint: {
          "fill-color": c.rockArea,
          "fill-opacity": 1,
          // `fill-antialias` ostáva: hrana plochy má byť hladká. S plnou
          // farbou to nerobí ani prekryv navyše – vyhladzuje sa okraj,
          // nie výplň.
          "fill-antialias": true
        }
      },
      // BEZ VZORU, a je to rozdiel oproti suti v krajinnej pokrývke. Táto
      // plocha je počítaná zo SKLONU: hovorí „tu je terén strmý", teda stena
      // a bralo. Kresba drobných popadaných kameňov by tvrdila opak – že je
      // to sypká suť – a to je práve tá informácia, kvôli ktorej sa na skaly
      // v mape pozerá. Kamienky preto kreslí `landcover-rock` (scree z OSM).
      ["vrstevnice", "Skalné plochy", "area", { "fill-color": "rockArea" }]
    );
  }

  // ================= tieňovanie reliéfu =================
  // Ide nad krajinnú pokrývku a nad skaly, ale pod vodu – tieňovaná vodná
  // hladina vyzerá nesprávne. Zdroj `dem` zostáva v štýle aj keď je
  // tieňovanie vypnuté, lebo z neho žije 3D terén.
  if (demTiles && showHillshade) {
    add(
      {
        id: "hillshade",
        type: "hillshade",
        source: "dem",
        paint: {
          // SVETLO IDE OD SEVEROZÁPADU A DRŽÍ SA TERÉNU, NIE OBRAZOVKY.
          //
          // MapLibre má predvolene 335° – to je 25° od severu, takže SEVERNÉ
          // svahy dostávali skoro plné svetlo a boli v mape tou najsvetlejšou
          // plochou. 315° je kartografická konvencia (svetlo od severozápadu)
          // a severný svah je pri nej 45° od svetla, teda len spolu-osvetlený.
          //
          // `map` znamená, že svetlo je priviazané k TERÉNU. Predvolený
          // `viewport` ho drží pri hornom okraji obrazovky, takže sa
          // otočením mapy – a tá sa v teréne otáča s kompasom – prelieva
          // z jednej strany hrebeňa na druhú a to isté údolie raz vyzerá ako
          // údolie a raz ako chrbát. Na severne orientovanej mape sú obe
          // hodnoty to isté, rozdiel je vidieť až pri otáčaní.
          "hillshade-illumination-direction": 315,
          "hillshade-illumination-anchor": "map",
          // SILA TIEŇOVANIA RASTIE SO ZOOMOM, nie naopak.
          //
          // Krivka tu roky klesala (`[[6, 0.5], [12, 0.4], [16, 0.25]]`),
          // takže presne tam, kde má výškový model NAJVIAC detailu – DMR 5.0
          // má mriežku 5 m a dlaždice idú do z15 –, bolo tieňovanie
          // NAJSLABŠIE. Terénne nerovnosti, kvôli ktorým sa človek na mape
          // približuje (žľaby, terasy, rebrá, cestné zárezy), tým pri
          // priblížení miznú: na prehľade je vidieť hrubý tvar pohoria
          // a v detaile skoro plochá mapa. Odteraz je to obrátene – na
          // prehľadovom zoome stačí naznačiť tvar, v detaile má reliéf niesť
          // to hlavné.
          //
          // Nie je to celá jednotka: aj so stropom, ktorý drží alfa farieb
          // (nižšie), je 1,0 už len o tom, ako rýchlo krytie so sklonom
          // nabehne – a v detaile nabehne aj tak celé. 0,95 nechá miernym
          // svahom ešte odstupňovanie.
          //
          // A STROP DRŽÍ ALFA FARIEB, NIE TÁTO KRIVKA. Tieňovanie je
          // PREKRYVNÁ vrstva: krytie, ktorým prekrýva mapu pod sebou, je
          // `sin` zo sklonu (a ten sa prevýšením ešte natiahne), takže
          // s nepriehľadnou farbou je nad ~20° sklonu krytie 0,97–1,0 –
          // pod tieňovaním potom nie je vidieť mapu, ale samotnú farbu
          // tieňovania. Namerané na svetlej téme (z15, 49° s. š.,
          // prevýšenie 0,95, `workers/lint/hillshade.mjs` počíta ten istý
          // shader):
          //
          //   svah 30° privrátený k svetlu   les #b7d69f → #fcfcfb (biela)
          //   svah 30° odvrátený od svetla   les #b7d69f → #5c4c3c (hnedá)
          //
          // Teda: na privrátenej strane bola z lesa BIELA PLOCHA a na
          // odvrátenej tá istá hnedá ako z lúky – nad 20° sklonu mapa pod
          // tieňovaním zmizla a ostala z nej vytieňovaná reliéfna maketa.
          // Najviac to bilo do očí na severných svahoch, ktoré predvolené
          // svetlo (335°) osvetľovalo skoro kolmo.
          //
          // Preto majú všetky tri farby v témach ALFU (`#rrggbbaa`):
          //
          //   tieň      0,70   svah ostane zreteľne tmavý, ale je pod ním
          //                    vidieť les, cestu aj vrstevnicu
          //   svetlo    0,36   privrátený svah sa len jemne rozjasní
          //   akcent    0,22   akcent kreslí sklon bez ohľadu na svetlo;
          //                    kým bolo krytie vysoké, nebolo ho vidieť
          //                    vôbec, teraz ho vidieť je – a nesmie
          //                    prekričať zvyšok
          //
          // Po nej je z toho istého lesa na 30° svahu #cbdabb (privrátený)
          // a #757257 (odvrátený) – v oboch prípadoch stále les. Reliéf sa
          // tým NEstratí: rozdiel medzi privrátenou a odvrátenou stranou je
          // 41 jednotiek L*, čo je viac, než potrebuje oko na tvar. Ubudlo
          // len to, čo tvar nenieslo – vypálená biela a nasýtená hnedá,
          // pod ktorou nebolo nič. Že sa nepriehľadná farba nevráti, stráži
          // `workers/lint/hillshade.mjs`.
          //
          // Dá sa to doladiť: `hillshade-exaggeration` je bežná vlastnosť
          // úprav (developer mode → vrstva „Tieňovanie reliéfu"), takže na
          // zmenu sily netreba meniť tento súbor.
          "hillshade-exaggeration": zl([[6, 0.55], [10, 0.7], [12, 0.85], [16, 0.95]]),
          "hillshade-shadow-color": c.hillShadow,
          "hillshade-highlight-color": c.hillHighlight,
          "hillshade-accent-color": c.hillAccent
        }
      },
      [
        "zaklad",
        "Tieňovanie reliéfu",
        "raster",
        {
          "hillshade-shadow-color": "hillShadow",
          "hillshade-highlight-color": "hillHighlight",
          "hillshade-accent-color": "hillAccent"
        }
      ]
    );
  }

  // ================= voda =================
  add(
    {
      id: "water",
      type: "fill",
      "source-layer": "water",
      filter: ["!=", ["get", "brunnel"], "tunnel"],
      paint: {
        "fill-color": c.water,
        "fill-opacity": ["case", ["==", ["get", "intermittent"], 1], 0.6, 1]
      }
    },
    ["voda", "Vodné plochy", "area", { "fill-color": "water" }]
  );
  add(
    {
      id: "water-outline",
      type: "line",
      "source-layer": "water",
      minzoom: 12,
      filter: ["!=", ["get", "brunnel"], "tunnel"],
      paint: {
        "line-color": c.waterOutline,
        "line-width": zl([[12, 0.4], [16, 1.2], [20, 2.5]])
      }
    },
    ["voda", "Obrys vodných plôch", "line", { "line-color": "waterOutline" }]
  );
  add(
    {
      id: "waterway-river",
      type: "line",
      "source-layer": "waterway",
      filter: ["in", str("class"), ["literal", ["river", "canal"]]],
      paint: {
        "line-color": c.river,
        "line-width": zw([[8, 0.6], [12, 1.6], [16, 5], [20, 18]])
      }
    },
    ["voda", "Rieky a kanály", "line", { "line-color": "river" }]
  );
  add(
    {
      // Potoky, priekopy, odvodňovacie kanály – detail, ktorý sa objaví od z12.
      id: "waterway-minor",
      type: "line",
      "source-layer": "waterway",
      minzoom: 12,
      filter: ["in", str("class"), ["literal", ["stream", "ditch", "drain"]]],
      paint: {
        "line-color": c.river,
        "line-width": zw([[12, 0.5], [16, 2], [20, 7]]),
        "line-opacity": 0.85
      }
    },
    ["voda", "Potoky a priekopy", "line", { "line-color": "river" }]
  );

  // ================= vrstevnice =================
  // Kreslia sa nad vodou (pod hladinou nemajú čo robiť) a pod budovami
  // a cestami, aby neprekrývali dôležitejšie prvky. Nad tieňovaním aj nad
  // skalami: čiara vrstevnice musí ostať čitateľná aj cez sivú stenu,
  // inak je práve tam, kde je terén najstrmší, mapa bez výšok.
  if (contoursUrl) {
    const contourLine = (id, label, level, minzoom, width, paletteKey) =>
      add(
        {
          id: `contour-${id}`,
          type: "line",
          source: "contours",
          "source-layer": "contour",
          minzoom,
          filter: ["==", str("level"), level],
          paint: {
            "line-color": c[paletteKey],
            "line-width": zl(width),
            "line-opacity": zl([[minzoom, 0], [minzoom + 1, 0.55]])
          }
        },
        ["vrstevnice", label, "line", { "line-color": paletteKey }]
      );

    // Tri triedy sa NEZAPÍNAJÚ naraz, a to je celé to „zjednodušene na
    // malých mierkach": od z11 je v mape LEN hlavná vrstevnica (po 100 m pri
    // štandardnom intervale), od z12 pribudne polovičná a od z13 základná.
    // Čiara sa navyše na svojom prvom zoome vynára z nuly (`line-opacity`),
    // takže žiadna trieda „nenaskočí" naraz ako mreža.
    //
    // POD `TERRAIN_MIN_Z` NIE JE V MAPE ANI JEDNA. Na tej mierke sa nedá
    // prečítať žiadna, takže z nich je len sivý závoj – a dlaždice s nimi si
    // prehliadač aj tak stiahne, čiže sa za ten závoj platí. Rovnaké dno má aj
    // `rock-area`; rozpis je pri tej konštante.
    contourLine("minor", "Vrstevnice po 10 m", "minor", 13, [[13, 0.4], [16, 0.7], [20, 1.4]], "contour");
    contourLine("mid", "Vrstevnice po 50 m", "mid", 12, [[12, 0.5], [16, 0.9], [20, 1.8]], "contour");
    contourLine("major", "Vrstevnice po 100 m", "major", TERRAIN_MIN_Z,
                [[TERRAIN_MIN_Z, 0.5], [16, 1.4], [20, 2.6]], "contourMajor");

    // Popisky nadmorskej výšky pozdĺž hlavných vrstevníc.
    add(
      {
        id: "contour-label",
        type: "symbol",
        source: "contours",
        "source-layer": "contour",
        minzoom: 13,
        filter: ["in", str("level"), ["literal", ["major", "mid"]]],
        layout: {
          "symbol-placement": "line",
          // `ele` môže z GDALu prísť ako desatinné číslo – zaokrúhlime v štýle,
          // aby popisok nikdy nebol "810.0 m".
          "text-field": ["concat", ["to-string", ["round", num("ele", 0)]], " m"],
          "text-font": REG,
          "text-size": zl([[13, 9], [16, 11], [20, 13]]),
          "symbol-spacing": 320,
          "text-max-angle": 25,
          "text-padding": 8
        },
        paint: {
          "text-color": c.contourText,
          "text-halo-color": c.textHalo,
          "text-halo-width": 1.4
        }
      },
      [
        "vrstevnice",
        "Popisky nadmorskej výšky",
        "text",
        { "text-color": "contourText", "text-halo-color": "textHalo" }
      ]
    );
  }

  /**
   * Hrana so zúbkami – bralo, násyp, zárez. Kolmé čiarky MapLibre nevie,
   * takže sa robia druhou čiarou: široká, prerušovaná a odsunutá nabok
   * (`line-offset`), z čoho pri hrane ostanú krátke hrubé kúsky. Kladný
   * offset je vpravo v smere čiary a presne tam je podľa konvencie OSM
   * dolná strana – `natural=cliff` aj `man_made=embankment` sa kreslia
   * so zúbkami dole.
   */
  const hachure = ({ id, label, group, source, sourceLayer, filter,
                     paletteKey, minzoom, width, teeth, opacity = 1 }) => {
    const base = {
      type: "line",
      ...(source ? { source } : {}),
      "source-layer": sourceLayer,
      minzoom,
      filter
    };
    add(
      {
        ...base,
        id,
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: {
          "line-color": c[paletteKey],
          "line-width": zl(width),
          "line-opacity": opacity
        }
      },
      [group, label, "line", { "line-color": paletteKey }]
    );
    add(
      {
        ...base,
        id: `${id}-teeth`,
        layout: { "line-cap": "butt" },
        paint: {
          "line-color": c[paletteKey],
          "line-width": zl(teeth),
          // Polovica šírky zúbka: čiara sa odsunie presne tak, aby sa
          // dotýkala hrany a trčala z nej von.
          "line-offset": zl(teeth.map(([z, w]) => [z, w / 2])),
          "line-dasharray": [0.35, 2.2],
          "line-opacity": opacity
        }
      },
      [group, `${label} – zúbky`, "line", { "line-color": paletteKey }]
    );
    spolu(id);
  };

  // ================= bralné hrany a hrebene z OSM =================
  // Toto NIE SÚ skaly z výškového modelu (tie sú vyššie, vlastný .pmtiles).
  // `natural=cliff`, `ridge` a `arete` sú v základných dlaždiciach od
  // začiatku – Planetiler ich dáva ako línie do vrstvy `mountain_peak`
  // (MountainPeak.java, od z13). Štýl ich dovtedy nekreslil vôbec, a čo
  // horšie, symbolová vrstva „Vrcholy hôr" im dávala doprostred
  // trojuholníček vrcholu, lebo `cliff` nebol medzi vylúčenými triedami.
  hachure({
    id: "cliff-line",
    label: "Bralné hrany (OSM)",
    group: "vrstevnice",
    sourceLayer: "mountain_peak",
    filter: ["==", str("class"), "cliff"],
    paletteKey: "cliffLine",
    minzoom: 13,
    width: [[13, 0.6], [16, 1.4], [20, 3]],
    teeth: [[13, 2.2], [16, 4.5], [20, 10]]
  });
  add(
    {
      id: "ridge-line",
      type: "line",
      "source-layer": "mountain_peak",
      minzoom: 13,
      filter: ["in", str("class"), ["literal", ["ridge", "arete"]]],
      paint: {
        "line-color": c.ridgeLine,
        "line-width": zl([[13, 0.6], [16, 1.2], [20, 2.4]]),
        "line-dasharray": [5, 3],
        "line-opacity": 0.7
      }
    },
    ["vrstevnice", "Hrebene a arety (OSM)", "line", { "line-color": "ridgeLine" }]
  );

  // ================= letiská =================
  add(
    {
      id: "aeroway-area",
      type: "fill",
      "source-layer": "aeroway",
      // Vrstva `aeroway` má dráhy ako čiary a odbavovacie plochy ako polygóny;
      // `class` ich síce rozlíši, ale letisko býva na nízkom zoome bodom.
      filter: polygonOnly(
        ["in", str("class"), ["literal", ["apron", "aerodrome", "heliport"]]]),
      paint: { "fill-color": c.aeroway }
    },
    ["letiska", "Letiskové plochy", "area", { "fill-color": "aeroway" }]
  );
  add(
    {
      id: "aeroway-runway",
      type: "line",
      "source-layer": "aeroway",
      minzoom: 10,
      filter: ["==", ["get", "class"], "runway"],
      paint: {
        "line-color": c.aeroway,
        "line-width": zw([[10, 1], [14, 8], [16, 20], [20, 70]])
      }
    },
    ["letiska", "Vzletové dráhy", "line", { "line-color": "aeroway" }]
  );
  add(
    {
      id: "aeroway-taxiway",
      type: "line",
      "source-layer": "aeroway",
      minzoom: 11,
      filter: ["in", str("class"), ["literal", ["taxiway", "helipad"]]],
      paint: {
        "line-color": c.aeroway,
        "line-width": zw([[11, 0.6], [14, 3], [16, 8], [20, 26]])
      }
    },
    ["letiska", "Rolovacie dráhy", "line", { "line-color": "aeroway" }]
  );

  // ================= dopravné plochy =================
  // Vrstva `transportation` nesie aj POLYGÓNY – pešiu zónu a námestie
  // (`highway=pedestrian` + `area=yes`), mólo ako plochu a teleso mosta
  // (`man_made=bridge`). Štýl mal nad ňou len líniové vrstvy, takže sa
  // námestie nevyplnilo a plošné mólo zmizlo úplne.
  //
  // POZOR: „`fill` vrstva kreslí len plochy, takže `class` stačí na
  // rozlíšenie" NEPLATÍ – bol to práve ten omyl, z ktorého boli čudné
  // polygóny od zoomu 13. Vo `transportation` sú chodníky, mólo aj most
  // BEŽNE čiary, MapLibre ich do výplne pustí a earcutom z nich vyrobí
  // nezmysel. Rozpis je pri `POLYGON_ONLY`; každá výplň tu preto ide cez
  // `polygonOnly`.
  add(
    {
      id: "bridge-area",
      type: "fill",
      "source-layer": "transportation",
      minzoom: 13,
      filter: polygonOnly(["==", str("class"), "bridge"]),
      paint: { "fill-color": c.roadCasing, "fill-opacity": 0.5 }
    },
    ["cesty", "Teleso mosta (plocha)", "area", { "fill-color": "roadCasing" }]
  );
  add(
    {
      id: "pedestrian-area",
      type: "fill",
      "source-layer": "transportation",
      minzoom: 13,
      // `path` sú takmer výhradne čiary a od z13 ich je v dlaždiciach plno
      // (`--transportation_z13_paths=true`) – bez tejto stráže z nich bola tá
      // „prerezaná" plocha vo farbe podkladu. Viď `POLYGON_ONLY`.
      filter: polygonOnly(
        ["in", str("class"), ["literal", ["pedestrian", "path"]]]),
      paint: {
        "fill-color": c.pedestrian,
        "fill-outline-color": c.roadCasing
      }
    },
    [
      "cesty",
      "Námestia a pešie zóny (plocha)",
      "area",
      { "fill-color": "pedestrian", "fill-outline-color": "roadCasing" }
    ]
  );
  add(
    {
      id: "pier-area",
      type: "fill",
      "source-layer": "transportation",
      minzoom: 13,
      // `man_made=pier` býva mapované čiarou aspoň tak často ako plochou.
      filter: polygonOnly(["==", str("class"), "pier"]),
      paint: { "fill-color": c.pier }
    },
    ["doprava", "Móla (plocha)", "area", { "fill-color": "pier" }]
  );

  // ================= budovy =================
  // Do z16 ploché výplne, nad tým 3D bloky (render_height z OSM).
  add(
    {
      id: "building",
      type: "fill",
      "source-layer": "building",
      minzoom: 13,
      maxzoom: 16,
      paint: {
        "fill-color": c.building,
        "fill-outline-color": c.buildingOutline,
        "fill-opacity": zl([[13, 0.5], [15, 1]])
      }
    },
    [
      "budovy",
      "Budovy (ploché)",
      "area",
      { "fill-color": "building", "fill-outline-color": "buildingOutline" }
    ]
  );
  add(
    {
      id: "building-3d",
      type: "fill-extrusion",
      "source-layer": "building",
      minzoom: 16,
      filter: ["!=", ["get", "hide_3d"], true],
      paint: {
        "fill-extrusion-color": c.buildingTop,
        "fill-extrusion-opacity": 0.9,
        "fill-extrusion-height": num("render_height", 5),
        "fill-extrusion-base": num("render_min_height", 0)
      }
    },
    ["budovy", "Budovy 3D", "3d", { "fill-extrusion-color": "buildingTop" }]
  );

  // ================= doprava =================

  /**
   * Od tohto zoomu sa kreslia obrysy ciest. Nižšie by k vlasovej čiare
   * pridali niekoľkonásobne širší lem a z cestnej siete by bola kaša –
   * pri malých mierkach je čitateľnejšia tenká čiara bez obrysu.
   */
  const CASING_MIN_Z = 10;

  /**
   * Cesty sa kreslia v troch priechodoch: tunely → povrch → mosty.
   *
   * V každom priechode sa ide OD NAJMENEJ DÔLEŽITEJ CESTY, teda odzadu
   * `ROAD_DEFS`: MapLibre kreslí vrstvy v poradí, v akom sú v štýle, takže
   * navrchu skončí tá pridaná posledná. Kým sa pridávali od diaľnice,
   * kreslila sa účelová cesta CEZ diaľnicu – na každej križovatke prúžok
   * v jej farbe naprieč diaľničným pásom, čo vyzerá ako prerušená diaľnica.
   * To isté platí zvlášť pre obrysy: motorway casing musí byť nad service
   * casingom z toho istého dôvodu.
   */
  const roadPass = (suffix, passLabel, extraFilter, opts = {}) => {
    const layout = { "line-cap": opts.cap || "round", "line-join": "round" };
    const filterFor = (classes) => [
      "all",
      ["in", str("class"), ["literal", classes]],
      extraFilter
    ];
    const odNajmenejDolezitej = [...ROAD_DEFS].reverse();
    // obrysy (casing) idú celé pod výplne, inak by ich prekrývali križovatky
    for (const [id, label, classes, , casingKey, stops, extra, mz] of odNajmenejDolezitej) {
      add(
        {
          id: `road-${id}-casing${suffix}`,
          type: "line",
          "source-layer": "transportation",
          minzoom: Math.max(mz, CASING_MIN_Z),
          filter: filterFor(classes),
          layout,
          paint: {
            "line-color": c[casingKey],
            "line-width": zw(widen(stops, extra)),
            ...(opts.dash ? { "line-dasharray": opts.dash } : {})
          }
        },
        ["cesty", `${label} – obrys${passLabel}`, "line", { "line-color": casingKey }]
      );
    }
    for (const [id, label, classes, colorKey, , stops, , mz] of odNajmenejDolezitej) {
      add(
        {
          id: `road-${id}${suffix}`,
          type: "line",
          "source-layer": "transportation",
          minzoom: mz,
          filter: filterFor(classes),
          layout,
          paint: { "line-color": c[colorKey], "line-width": zw(stops) }
        },
        ["cesty", `${label}${passLabel}`, "line", { "line-color": colorKey }]
      );
    }
  };

  // --- tunely (prerušované, pod povrchom) ---
  roadPass("-tunnel", " (tunel)", isTunnel, { cap: "butt", dash: [3, 2] });

  // --- chodníky, cyklotrasy, schody, poľné cesty ---
  const pathDefs = [
    ["track", "Poľné a lesné cesty", ["==", str("class"), "track"], "track", [[11, 0.4], [13, 0.9], [14, 1.6], [16, 3.5], [20, 12]], [4, 2], 11],
    ["steps", "Schody", ["==", str("subclass"), "steps"], "steps", [[14, 1.2], [16, 3], [20, 10]], [1, 0.6], 14],
    ["cycleway", "Cyklotrasy", ["==", str("subclass"), "cycleway"], "cycleway", [[12, 0.4], [14, 1], [16, 2.2], [20, 8]], [3, 1.5], 12],
    // `platform` a `corridor` majú tiež `class=path`. Bez nich sa nástupište
    // ani chodba v podchode nenakreslili – filter ich prepúšťal len do
    // vrstvy „turistické chodníky", ktorá ich vylučovala.
    ["footway", "Chodníky, priechody a nástupištia", ["in", str("subclass"), ["literal", ["footway", "sidewalk", "crossing", "platform", "corridor"]]], "footway", [[13, 0.6], [16, 2], [20, 7]], [2, 1.5], 13],
    // `path` bez subclass (alebo path/bridleway) – ale nie `track`, ten má vlastnú vrstvu
    ["path", "Turistické chodníky", ["all", ["==", str("class"), "path"],
      ["in", str("subclass"), ["literal", ["path", "bridleway", ""]]]],
      "path", [[11, 0.4], [13, 0.9], [16, 2.2], [20, 8]], [2, 2], 11]
  ];
  for (const [id, label, filter, paletteKey, stops, dash, mz] of pathDefs) {
    add(
      {
        id: `road-${id}`,
        type: "line",
        "source-layer": "transportation",
        minzoom: mz,
        filter: [
          "all",
          ["in", str("class"), ["literal", ["path", "track"]]],
          filter,
          ["!=", ["get", "brunnel"], "tunnel"]
        ],
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: { "line-color": c[paletteKey], "line-width": zw(stops), "line-dasharray": dash }
      },
      ["chodniky", label, "line", { "line-color": paletteKey }]
    );
  }

  // --- povrchové cesty ---
  roadPass("", "", isSurface);

  // --- cesty vo výstavbe ---
  // Schéma pre ne má vlastné triedy (`motorway_construction` až
  // `track_construction`) a v dlaždiciach sú od začiatku. Štýl ich nemal
  // v žiadnom zozname, takže rozostavaná diaľnica bola v mape biele miesto.
  // Jedna vrstva pre všetky: šírka podľa dôležitosti, ale kresba rovnaká –
  // po tejto ceste sa zatiaľ ísť nedá a to je to podstatné.
  add(
    {
      id: "road-construction",
      type: "line",
      "source-layer": "transportation",
      minzoom: 11,
      filter: ["in", str("class"), ["literal", [
        "motorway_construction", "trunk_construction", "primary_construction",
        "secondary_construction", "tertiary_construction", "minor_construction",
        "service_construction", "path_construction", "track_construction",
        "raceway_construction"
      ]]],
      layout: { "line-cap": "butt", "line-join": "round" },
      paint: {
        "line-color": c.roadConstruction,
        "line-width": zw([[11, 0.8], [14, 3], [16, 7], [20, 22]]),
        "line-dasharray": [3, 2]
      }
    },
    ["cesty", "Cesty vo výstavbe", "line", { "line-color": "roadConstruction" }]
  );

  // --- brody ---
  // `brunnel=ford` je v dlaždiciach na ceste aj na chodníku. Bez tohto
  // vyzerá brod ako obyčajný úsek cesty – a pritom je to práve to miesto,
  // kde sa dá neprejsť.
  add(
    {
      id: "road-ford",
      type: "line",
      "source-layer": "transportation",
      minzoom: 14,
      filter: ["==", str("brunnel"), "ford"],
      layout: { "line-cap": "butt" },
      paint: {
        "line-color": c.water,
        "line-width": zw([[14, 2], [16, 5], [20, 16]]),
        "line-dasharray": [1, 1]
      }
    },
    ["cesty", "Brody", "line", { "line-color": "water" }]
  );

  // --- železnica ---
  // Dve vrstvy nad sebou: plná tmavá čiara a na nej čiarkovaná svetlá. Svetlé
  // diely majú byť ROVNAKO DLHÉ ako tmavé, čo drží vzor `rail` ([1, 1]
  // v násobkoch šírky) – a preto musí byť horná čiara ROVNAKO ŠIROKÁ ako
  // spodná: keby bola tenšia (bola, na tretinu), tmavá by po stranách
  // presvitala a z čiarkovanej čiary by boli priečky na tmavom páse.
  // Šírka je preto jedna a tá istá pre obe vrstvy.
  const railWidth = [[7, 0.4], [10, 0.8], [14, 2.4], [16, 4], [20, 12]];
  add(
    {
      id: "rail-bg",
      type: "line",
      "source-layer": "transportation",
      minzoom: 7,
      filter: ["in", str("class"), ["literal", ["rail", "transit"]]],
      paint: {
        "line-color": c.rail,
        "line-width": zw(railWidth)
      }
    },
    ["doprava", "Železnica", "line", { "line-color": "rail" }]
  );
  add(
    {
      id: "rail-hatch",
      type: "line",
      "source-layer": "transportation",
      // Až od z13: pod ním je čiara užšia než pixel a čiarkovanie by z nej
      // urobilo len prerušovanú šmuhu.
      minzoom: 13,
      filter: ["in", str("class"), ["literal", ["rail", "transit"]]],
      layout: { "line-cap": "butt" },
      paint: {
        "line-color": c.railHatch,
        "line-width": zw(railWidth),
        // Vzor z `patterns.js`, nie číslo tu: to isté prerušovanie ponúka
        // developer mode a ukladá sa do `style-overrides.json`, takže dve
        // kópie by sa raz rozišli.
        "line-dasharray": dashArray("rail")
      }
    },
    ["doprava", "Železnica – čiarkovanie", "line", { "line-color": "railHatch" }]
  );
  spolu("rail-bg");

  // --- mosty (nad všetkým ostatným) ---
  roadPass("-bridge", " (most)", isBridge, { cap: "butt" });

  // --- lanovky, kompy, móla ---
  add(
    {
      id: "aerialway",
      type: "line",
      "source-layer": "transportation",
      minzoom: 11,
      filter: ["==", ["get", "class"], "aerialway"],
      paint: {
        "line-color": c.aerialway,
        "line-width": zl([[11, 0.6], [16, 1.6], [20, 3]]),
        "line-dasharray": [6, 2]
      }
    },
    ["doprava", "Lanovky a vleky", "line", { "line-color": "aerialway" }]
  );
  add(
    {
      id: "ferry",
      type: "line",
      "source-layer": "transportation",
      minzoom: 8,
      filter: ["==", ["get", "class"], "ferry"],
      paint: {
        "line-color": c.ferry,
        "line-width": zl([[8, 0.8], [16, 2], [20, 4]]),
        "line-dasharray": [4, 3]
      }
    },
    ["doprava", "Kompy", "line", { "line-color": "ferry" }]
  );
  add(
    {
      id: "pier",
      type: "line",
      "source-layer": "transportation",
      minzoom: 13,
      filter: ["==", ["get", "class"], "pier"],
      paint: {
        "line-color": c.pier,
        "line-width": zw([[13, 1], [16, 4], [20, 14]])
      }
    },
    ["doprava", "Móla", "line", { "line-color": "pier" }]
  );

  // --- jednosmerky (len na veľkom detaile) ---
  if (hasIcon(SPECIAL.arrow)) {
    add(
      {
        id: "road-oneway",
        type: "symbol",
        "source-layer": "transportation",
        minzoom: 16,
        filter: ["in", num("oneway", 0), ["literal", [1, -1]]],
        layout: {
          "symbol-placement": "line",
          "symbol-spacing": 120,
          "icon-image": SPECIAL.arrow,
          "icon-size": zl([[16, 0.6], [20, 1.2]]),
          "icon-rotate": ["case", ["==", num("oneway", 0), -1], 180, 0],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true
        },
        paint: {
          "icon-opacity": 0.5,
          ...(sdfIcons ? { "icon-color": c.onewayIcon } : {})
        }
      },
      [
        "cesty",
        "Šípky jednosmeriek",
        "point",
        sdfIcons ? { "icon-color": "onewayIcon" } : {}
      ]
    );
  }

  // ================= krajinné prvky (línie) =================
  // Vlastný .pmtiles (workers/features/features.yml). Kreslia sa nad cestami, lebo
  // násyp aj zárez sú hrany PRI ceste – pod ňou by ich cesta prekryla.
  if (featuresUrl) {
    // Násyp a zárez majú zúbky ako bralo, len opačne: násyp klesá od hrany
    // von (zúbky vpravo v smere čiary, tak to OSM konvencia mapuje), zárez
    // stúpa – kreslí sa preto svetlejšie a s jemnejšími zúbkami.
    hachure({
      id: "feature-embankment",
      label: "Násypy",
      group: "prvky",
      source: "features",
      sourceLayer: "feature_line",
      filter: ["==", str("class"), "embankment"],
      paletteKey: "embankment",
      minzoom: 13,
      width: [[13, 0.7], [16, 1.5], [20, 3.2]],
      teeth: [[13, 2], [16, 4], [20, 9]]
    });
    hachure({
      id: "feature-cutting",
      label: "Zárezy",
      group: "prvky",
      source: "features",
      sourceLayer: "feature_line",
      filter: ["==", str("class"), "cutting"],
      paletteKey: "embankment",
      minzoom: 13,
      width: [[13, 0.6], [16, 1.2], [20, 2.6]],
      teeth: [[13, 1.6], [16, 3.2], [20, 7]],
      opacity: 0.75
    });

    // [id, popis, triedy, kľúč palety, stopy šírky, prerušovanie, minzoom]
    const featureLines = [
      ["power", "Elektrické vedenie", ["power_line"], "powerLine",
        [[11, 0.5], [14, 0.9], [16, 1.4], [20, 3]], null, 11],
      ["power-minor", "Vedenie nízkeho napätia", ["power_minor"], "powerLine",
        [[14, 0.4], [16, 0.8], [20, 1.8]], [4, 3], 14],
      ["cutline", "Prieseky", ["cutline"], "cutline",
        [[13, 0.9], [16, 2.2], [20, 6]], [6, 3], 13],
      ["pipeline", "Nadzemné potrubie", ["pipeline"], "powerLine",
        [[13, 0.6], [16, 1.4], [20, 3]], [8, 3], 13],
      ["dam", "Priehradné múry a hate", ["dam", "weir", "lock_gate"], "dam",
        [[13, 1], [16, 3], [20, 8]], null, 13],
      ["wall", "Múry a hradby", ["wall"], "wall",
        [[14, 0.7], [16, 1.6], [20, 4]], null, 14],
      ["hedge", "Živé ploty", ["hedge"], "hedge",
        [[15, 0.9], [17, 1.8], [20, 4]], null, 15],
      ["fence", "Ploty a zábradlia", ["fence"], "fence",
        [[15, 0.4], [17, 0.8], [20, 1.8]], null, 15],
      ["tree-row", "Stromoradia", ["tree_row"], "treeRow",
        [[14, 0.9], [16, 1.8], [20, 4]], [1, 1.5], 14],
      ["gully", "Výmole a zrázy", ["gully", "earth_bank"], "embankment",
        [[14, 0.6], [16, 1.2], [20, 3]], [3, 2], 14],
      // PLÁNOVANÁ CESTA (`highway=proposed`) – trasa, na ktorej sa ešte ani
      // nekope. Kreslí sa TU, medzi prvkami, a nie vedľa `road-construction`
      // v sekcii ciest, hoci by tam logicky patrila: ide z vlastných dlaždíc
      // (`features`), ktoré štýl pridáva len keď ten archív existuje.
      //
      // Bodkovaná a šedšia než rozostavaná cesta, ktorá je čiarkovaná
      // (`[3, 2]`) a farebná: rozdiel „stavia sa" proti „je to zatiaľ na
      // papieri" musí byť vidieť na prvý pohľad, nie až z popupu. Šírka je
      // schválne o dosť menšia než pri rozostavanej ceste – plánovanú
      // diaľnicu netreba kresliť ako diaľnicu.
      ["road-proposed", "Plánované cesty", ["road_proposed"], "roadProposed",
        [[11, 0.8], [14, 1.6], [16, 2.6], [20, 6]], [1, 2.5], 11]
    ];
    for (const [id, label, classes, paletteKey, stops, dash, mz] of featureLines) {
      add(
        {
          id: `feature-${id}`,
          type: "line",
          source: "features",
          "source-layer": "feature_line",
          minzoom: mz,
          filter: ["in", str("class"), ["literal", classes]],
          layout: { "line-cap": "butt", "line-join": "round" },
          paint: {
            "line-color": c[paletteKey],
            "line-width": zl(stops),
            ...(dash ? { "line-dasharray": dash } : {})
          }
        },
        ["prvky", label, "line", { "line-color": paletteKey }]
      );
    }

    // ---- zjazdovky a bežky ----
    // Farba podľa obťažnosti, ako na tabuli pri vleku. Odtiene sú tie isté
    // kľúče palety ako pri značkách trás – modrá zjazdovka má byť tá istá
    // modrá ako modrá značka, inak sa mapa rozpadne na dve sady farieb.
    const pisteColour = [
      "match",
      str("difficulty"),
      "novice", c.trailGreen,
      "easy", c.trailBlue,
      "intermediate", c.trailRed,
      "advanced", c.trailBlack,
      "expert", c.trailBlack,
      "freeride", c.trailOrange,
      c.pisteLine
    ];
    add(
      {
        id: "piste-line",
        type: "line",
        source: "features",
        "source-layer": "piste",
        minzoom: 11,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": pisteColour,
          "line-width": zw([[11, 0.8], [14, 1.8], [16, 3], [20, 8]]),
          "line-opacity": 0.9
        }
      },
      [
        "prvky",
        "Zjazdovky a bežky (čiara)",
        "line",
        {},
        ["pisteLine", "trailGreen", "trailBlue", "trailRed", "trailBlack", "trailOrange"]
      ]
    );
    add(
      {
        id: "piste-label",
        type: "symbol",
        source: "features",
        "source-layer": "piste",
        minzoom: 13,
        filter: ["any", ["has", "name"], ["has", "ref"]],
        layout: {
          "symbol-placement": "line",
          "text-field": [
            "case",
            ["all", ["has", "ref"], ["has", "name"]],
            ["concat", ["get", "ref"], " ", ["get", "name"]],
            ["has", "name"],
            ["get", "name"],
            ["get", "ref"]
          ],
          "text-font": REG,
          "text-size": zl([[13, 9], [16, 11], [20, 13]]),
          "symbol-spacing": 380,
          "text-max-angle": 30,
          "text-offset": [0, 0.8]
        },
        paint: {
          "text-color": pisteColour,
          "text-halo-color": c.textHalo,
          "text-halo-width": 1.6
        }
      },
      [
        "prvky",
        "Zjazdovky – názvy",
        "text",
        { "text-halo-color": "textHalo" },
        ["pisteLine", "trailGreen", "trailBlue", "trailRed", "trailBlack", "trailOrange"]
      ]
    );
  }

  // ================= značené trasy =================
  // Trasa nie je cesta. Je to `type=route` relácia, ktorá zbiera cudzie
  // cesty a nesie značenie (farbu pásika, sieť, názov) – v dlaždiciach
  // OpenMapTiles po nej nezostane ani stopa. Preto má vlastný zdroj a
  // kreslí sa ako farebný pásik **vedľa** cesty:
  //
  //     ── cesta ────────────    zostane vidieť, aká to je cesta
  //     ━━ červená (off 0,5) ━
  //     ━━ modrá   (off 1,5) ━   druhá trasa po tej istej ceste
  //
  // Pruh (`side` + `off`) prichádza z dát, `line-offset` ho prepočíta na
  // pixely – preto sa pásiky neprekrývajú ani vtedy, keď po ceste vedie päť
  // trás. Pešie trasy idú na jednu stranu, kolesové na druhú.
  if (trailsUrl) {
    // Farby značiek idú cez paletu, nie natvrdo z dát: „červená" značka má
    // v každej téme vyzerať ako červená značka, nie ako presne to `#ff0000`,
    // ktoré do OSM napísal ten, kto trasu zadával.
    const MARK_KEYS = TRAIL_MARK_COLOURS.map(([, key]) => key);

    /**
     * Farba pásika: pomenovaná značka → paleta, neznáma farba z OSM → tak,
     * ako je v dátach (atribút `hex`), žiadna farba → podľa druhu trasy.
     */
    const trailColour = (fallbackKey) => [
      "match",
      str("colour"),
      ...TRAIL_MARK_COLOURS.flatMap(([name, key]) => [name, c[key]]),
      ["coalesce", ["get", "hex"], c[fallbackKey]]
    ];

    // ---- posun pásika od osi cesty ----
    //
    //     line-offset = side × (odstup(po čom vedie) + poradie × rozostup)
    //
    // ODSTUP NIE JE JEDNO ČÍSLO. Asfaltka je v mape pri z16 široká deväť
    // pixelov plus obrys, chodník dva – odstup, pri ktorom sa pásik lepí na
    // chodník, leží uprostred cesty. Preto sú dva: pri ceste ide pásik tesne
    // ZA jej okraj (žiadna medzera, ale ani prekryv), pri chodníku a lesnej
    // ceste ostáva jemná medzera, nech je pod pásikom vidieť aj samotný
    // chodník aj s tým, že je prerušovaný. Po čom trasa vedie, hovoria dáta
    // (`way`) – tu je len to, koľko to v pixeloch znamená.
    //
    // ROZOSTUP DVOCH TRÁS je šírka pásika, teda druhá trasa je nalepená na
    // prvú bez medzery. Tri značky na jednom chodníku majú vyzerať ako jeden
    // trojfarebný pás, nie ako tri čiary rozhádzané do polovice obrazovky.
    // Preto je to tá istá krivka (`TRAIL_STRIPE`), ktorou sa o kus nižšie
    // kreslí `line-width` pásika, a interpoluje sa tak isto – inak by sa medzi
    // zlomami rozišli a medzi trasami by presvital ich podklad.
    //
    // Čísla sú pixely pri z16 (referenčný zoom, v ktorom sa to ladí) a celá
    // krivka sa škáluje pomerom voči nim, keď ich developer mode prepíše.
    const trailGaps = trailGapPx(overrides);
    const scaled = (stops, ref, want) =>
      stops.map(([z, v]) => [z, Math.round(((v * want) / ref) * 100) / 100]);
    const ROAD_STOPS = scaled(TRAIL_OFFSET_ROAD, TRAIL_GAP_DEFAULTS.road, trailGaps.road);
    const PATH_STOPS = scaled(TRAIL_OFFSET_PATH, TRAIL_GAP_DEFAULTS.path, trailGaps.path);
    const PITCH_STOPS = scaled(TRAIL_PITCH, TRAIL_GAP_DEFAULTS.pitch, trailGaps.pitch);

    // `["zoom"]` smie byť len vstupom najvrchnejšieho `interpolate`, preto sa
    // celý výpočet skladá až vo výstupoch stopov – `["*", ["interpolate", …]]`
    // by MapLibre odmietol. Stopy majú preto všetky tri krivky rovnaké.
    //
    // `exponential 1.5` je to isté, čím sa interpoluje `line-width` (`zw`):
    // rozostup JE šírka pásika, takže musí rásť rovnako. S lineárnou
    // interpoláciou sa medzi zlomami rozchádzali – pri z18 bola medzi
    // susednými pásikmi medzera 0,65 px a presvital cez ňu ich podklad.
    const trailOffset = [
      "interpolate",
      ["exponential", 1.5],
      ["zoom"],
      ...TRAIL_OFFSET_ZOOMS.flatMap((z, i) => [
        z,
        [
          "*",
          num("side", 1),
          [
            "+",
            ["case", ["==", str("way"), "path"], PATH_STOPS[i][1], ROAD_STOPS[i][1]],
            ["*", num("off", 0), PITCH_STOPS[i][1]]
          ]
        ]
      ])
    ];

    /**
     * Ikona podľa druhu trasy – prvá, ktorú vybraná sada naozaj má.
     *
     * Meno sa skúša aj s príponou sady, aj holé: zo zoznamu v `TRAIL_TYPES`
     * chodia holé mená (`bicycle`), z developer módu meno tak, ako je
     * v sprite (a to už príponu má). Ikona, ktorú sada nemá, sa nenastaví –
     * chýbajúci obrázok znamená nevykreslený symbol a v pipeline zhodí
     * kontrolu štýlu.
     */
    const pickIcon = (names) => {
      for (const n of names || []) {
        if (hasIcon(`${n}${suffix}`)) return `${n}${suffix}`;
        if (hasIcon(n)) return n;
      }
      return null;
    };

    /** Druhy trás už aj s tým, čo na nich prepísal developer mode. */
    const trailTypes = TRAIL_TYPES.map((t) => trailTypeDef(t, overrides));

    // Popisok: „0801 Chodník hrdinov SNP", inak čo z toho je.
    const trailLabel = [
      "case",
      ["all", ["has", "ref"], ["has", "name"]],
      ["concat", ["get", "ref"], " ", ["get", "name"]],
      ["has", "name"],
      ["get", "name"],
      ["has", "ref"],
      ["get", "ref"],
      ""
    ];
    // Diaľkové trasy sa popisujú prednostne – keď sa nezmestia všetky,
    // nech ostane na mape tá dôležitejšia.
    const trailSort = [
      "match",
      str("tier"),
      "international", 0,
      "national", 1,
      "regional", 2,
      3
    ];

    // Podklad pod všetkými pásikmi naraz: farebná čiara sama o sebe sa cez
    // les, vrstevnice a tieňovanie stráca.
    add(
      {
        id: "trail-halo",
        type: "line",
        source: "trails",
        "source-layer": "trail",
        minzoom: 11,
        // Ten istý spoj ako pásiky nad ním (rozpis pri `TRAIL_JOIN`) – inak
        // by sa podklad v zákrute rozišiel s tým, čo podkladá.
        layout: { "line-cap": "butt", ...TRAIL_JOIN },
        paint: {
          "line-color": c.trailHalo,
          "line-width": zw([[11, 2.4], [14, 3.4], [16, 4.8], [20, 10]]),
          "line-offset": trailOffset,
          "line-opacity": zl([[11, 0], [12, 0.45], [14, 0.65]])
        }
      },
      ["trasy", "Podklad pod pásikmi trás", "line", { "line-color": "trailHalo" }]
    );

    for (const { id, label, palette: paletteKey, dash } of trailTypes) {
      const filter = ["==", str("route"), id];
      add(
        {
          id: `trail-${id}`,
          type: "line",
          source: "trails",
          "source-layer": "trail",
          minzoom: 9,
          filter,
          layout: { "line-cap": "butt", ...TRAIL_JOIN },
          paint: {
            "line-color": trailColour(paletteKey),
            // Tá istá krivka, ktorá je aj rozostupom dvoch trás – pásiky sa
            // tak dotýkajú na každom zoome, nie len na zlomoch.
            "line-width": zw(TRAIL_STRIPE),
            "line-offset": trailOffset,
            "line-opacity": zl([[9, 0.75], [13, 0.95]]),
            ...(dashArray(dash) ? { "line-dasharray": dashArray(dash) } : {})
          }
        },
        ["trasy", label, "line", {}, [...MARK_KEYS, paletteKey]]
      );
    }

    // ---- ZNAČKA, AKO JE NA STROME ----
    //
    // Kreslí sa pozdĺž trasy v pravidelných intervaloch a je to obrázok
    // upečený do spritu (`poc/web/marks.js`): biely alebo žltý štvorec
    // s farebným pásom, trojuholník na vrchol, bicykel na cyklotrase. Ktorá
    // trasa akú značku má, je v dlaždiciach (`mark`, `mark_bg`, `mark_fg`
    // z `osmc:symbol` – rozpis vo `workers/trails/tags.py`), takže meno
    // obrázka sa skladá z DÁT, nie zo zoznamu tu.
    //
    // KEĎ ZNAČKY V SPRITE NIE SÚ (stará sada z cache, nepodarené dopečenie),
    // vrstva sa nepridá a pozdĺž trasy ostane ikonka druhu trasy – tak, ako
    // to bolo predtým. Je to horšie, ale je to vidieť; „značky zmizli" by
    // nikto nespozoroval.
    const marksBaked = hasIcon(markImage("white", "red", DEFAULT_MARK_SHAPE));
    const markPx = trailMarkPx(overrides);
    const markScale = (stops, ref, want) =>
      stops.map(([z, v]) => [z, Math.round(((v * want) / ref) * 1000) / 1000]);
    const markSize = zl(
      markScale(TRAIL_MARK_SIZE, TRAIL_MARK_DEFAULTS.size, markPx.size)
    );
    /** Kreslí sa tomuto druhu značka? („žiadna" z developer módu ju vypne.) */
    const drawsMark = (t) => marksBaked && t.markPick !== "";

    // Stĺpik značiek nad čiarou: koľká je trasa v rade (`off`) a na ktorej
    // strane cesty má pásik (`side`) – rozpis pri `TRAIL_MARK_STACK`. Záporné
    // `y` je nahor, takže pešie trasy (`side` +1) idú nad čiaru a kolesové
    // (−1) pod ňu.
    //
    // JE TO VYMENOVANÉ, A NIE JE TO Z LENIVOSTI: `icon-offset` je pole dvoch
    // čísel a výrazy MapLibre pole POČÍTAŤ nevedia – vyrobiť sa dá len
    // `["literal", …]`, teda konštanta. Preto je z toho `case` cez tie
    // dvojice `(side, off)`, ktoré sa v dátach reálne vyskytujú; nad
    // `TRAIL_MARK_STACK_MAX` je v rade toľko trás, že by stĺpik aj tak
    // prerástol obrazovku, a ďalšie sa preto kreslia na poslednú priečku.
    const stackOffset = (base, step) => {
      const expr = ["case"];
      for (const side of [1, -1]) {
        for (let off = 0; off <= TRAIL_MARK_STACK_MAX; off += 1) {
          expr.push(
            ["all", ["==", num("side", 1), side], ["==", num("off", 0), off]],
            ["literal", [0, -side * (base + step * off)]]
          );
        }
      }
      expr.push(["literal", [0, -base]]);
      return expr;
    };
    // Krok stĺpika je z developer módu (`overrides.trails.marks.step`), takže
    // sa dá doladiť tak isto ako rozostup po trase a veľkosť značky.
    const markOffset = stackOffset(TRAIL_MARK_STACK.base, markPx.step);
    for (const t of trailTypes) {
      if (!drawsMark(t)) continue;
      const { id, label, markPick } = t;
      add(
        {
          id: `trail-${id}-mark`,
          type: "symbol",
          source: "trails",
          "source-layer": "trail",
          minzoom: MARK_MINZOOM,
          filter: ["all", ["==", str("route"), id], ["has", "mark"]],
          layout: {
            "symbol-placement": "line",
            "symbol-spacing": zl(
              markScale(TRAIL_MARK_SPACING, TRAIL_MARK_DEFAULTS.spacing, markPx.spacing)
            ),
            // Značky dvoch trás na jednej ceste sa stavajú NAD SEBA – bez
            // toho by padli na to isté miesto a kolízia by všetky okrem
            // jednej zahodila (rozpis pri `TRAIL_MARK_STACK`).
            "icon-offset": markOffset,
            // Meno obrázka je zložené z dát; `markPick` je „vždy tento tvar"
            // z developer módu, inak platí tvar, ktorý je v `osmc:symbol`.
            "icon-image": [
              "concat",
              "mark-",
              ["get", "mark_bg"],
              "-",
              ["get", "mark_fg"],
              "-",
              markPick || ["get", "mark"]
            ],
            "icon-size": markSize,
            // Značka STOJÍ NAROVNO. Natočená podľa cesty už nie je tabuľka,
            // ale škvrna – a na serpentíne by stála na hlave.
            "icon-rotation-alignment": "viewport",
            "icon-pitch-alignment": "viewport",
            "icon-padding": TRAIL_MARK_PADDING,
            // STĹPIK SA KRESLÍ CELÝ. Značky v ňom stoja tesne na sebe, takže
            // sa im kolízne obdĺžniky o priehľadný okraj prekrývajú – bez
            // tohto by MapLibre všetky okrem prvej zahodila a z troch trás na
            // chodníku by bola v mape jedna (rozpis pri `TRAIL_MARK_STACK`).
            "icon-allow-overlap": true,
            // Poradie v rade rozhodujú dáta (`off`), nie to, kto sa zmestí
            // prvý; sort-key ostáva pre značky dvoch RÔZNYCH ciest, ktoré si
            // sadnú na to isté miesto.
            "symbol-sort-key": trailSort
          }
        },
        ["trasy", `${label} – značka`, "point", {}]
      );
    }

    // Ikony a popisky idú až za všetky pásiky, aby sa čiara jednej trasy
    // nekreslila cez popisok druhej.
    for (const t of trailTypes) {
      const { id, label, palette: paletteKey, iconPick } = t;
      const icon = pickIcon(iconPick);
      if (!icon) continue;
      add(
        {
          id: `trail-${id}-icon`,
          type: "symbol",
          source: "trails",
          "source-layer": "trail",
          minzoom: 13,
          // IKONKA JE NÁHRADA, NIE DRUHÝ SYMBOL. Kde je značka (a kreslí sa),
          // ikonka druhu trasy nemá čo pridať – dve ikony na jednej čiare si
          // len berú miesto navzájom. Ostáva tam, kde značka nie je: trasa
          // s neznámou farbou, ktorej by sme tabuľku vymysleli.
          filter: drawsMark(t)
            ? ["all", ["==", str("route"), id], ["!", ["has", "mark"]]]
            : ["==", str("route"), id],
          layout: {
            "symbol-placement": "line",
            "symbol-spacing": 260,
            "icon-image": icon,
            "icon-size": zl([[13, 0.5], [16, 0.75], [20, 1]]),
            "icon-rotation-alignment": "viewport",
            // TEN ISTÝ STĹPIK AKO PRI ZNAČKÁCH, a z toho istého dôvodu: trasy
            // majú v dlaždiciach tú istú geometriu, takže bez posunu padnú
            // ikonky všetkých trás na jedno miesto a kolízia nechá jednu.
            // `off` a `side` sú pri tom spoločné pre značky aj ikonky (číslujú
            // sa raz na cestu, `workers/trails/routes.py`), takže trasa so
            // značkou a trasa bez nej si navzájom priečku neberú.
            "icon-offset": markOffset,
            "icon-allow-overlap": true,
            "icon-padding": 0
          },
          paint: {
            "icon-opacity": 0.85,
            ...(sdfIcons
              ? {
                  "icon-color": trailColour(paletteKey),
                  "icon-halo-color": c.trailHalo,
                  "icon-halo-width": 1.2
                }
              : {})
          }
        },
        [
          "trasy",
          `${label} – ikona`,
          "point",
          sdfIcons ? { "icon-halo-color": "trailHalo" } : {},
          sdfIcons ? [...MARK_KEYS, paletteKey] : []
        ]
      );
    }

    for (const { id, label, palette: paletteKey } of trailTypes) {
      add(
        {
          id: `trail-${id}-label`,
          type: "symbol",
          source: "trails",
          "source-layer": "trail",
          minzoom: 12,
          filter: [
            "all",
            ["==", str("route"), id],
            ["any", ["has", "name"], ["has", "ref"]]
          ],
          layout: {
            "symbol-placement": "line",
            "text-field": trailLabel,
            "text-font": REG,
            "text-size": zl([[12, 9], [14, 10.5], [18, 13]]),
            "symbol-spacing": 420,
            "text-max-angle": 30,
            "text-padding": 6,
            // Popisok sa odsunie z čiary nabok, nech neleží na pásikoch.
            "text-offset": [0, 0.8],
            "symbol-sort-key": trailSort
          },
          paint: {
            // Názov trasy je vo farbe trasy – červená značka má červený nápis.
            "text-color": trailColour(paletteKey),
            "text-halo-color": c.textHalo,
            "text-halo-width": 1.6
          }
        },
        [
          "trasy",
          `${label} – názvy`,
          "text",
          { "text-halo-color": "textHalo" },
          [...MARK_KEYS, paletteKey]
        ]
      );
    }
  }

  // ================= hranice =================
  add(
    {
      id: "boundary-municipality",
      type: "line",
      "source-layer": "boundary",
      minzoom: 11,
      filter: [">=", num("admin_level", 99), 7],
      paint: {
        "line-color": c.boundaryLocal,
        "line-width": zl([[11, 0.5], [16, 1.2], [20, 2]]),
        "line-dasharray": [2, 2],
        "line-opacity": 0.5
      }
    },
    ["hranice", "Hranice obcí", "line", { "line-color": "boundaryLocal" }]
  );
  add(
    {
      id: "boundary-district",
      type: "line",
      "source-layer": "boundary",
      minzoom: 8,
      filter: ["all", [">=", num("admin_level", 99), 5], ["<=", num("admin_level", 99), 6]],
      paint: {
        "line-color": c.boundaryLocal,
        "line-width": zl([[8, 0.6], [16, 1.6], [20, 3]]),
        "line-dasharray": [3, 2],
        "line-opacity": 0.6
      }
    },
    ["hranice", "Hranice okresov", "line", { "line-color": "boundaryLocal" }]
  );
  add(
    {
      id: "boundary-region",
      type: "line",
      "source-layer": "boundary",
      filter: ["all", [">=", num("admin_level", 99), 3], ["<=", num("admin_level", 99), 4]],
      paint: {
        "line-color": c.boundary,
        "line-width": zl([[4, 0.8], [12, 2], [20, 4]]),
        "line-dasharray": [3, 2],
        "line-opacity": 0.7
      }
    },
    ["hranice", "Hranice krajov", "line", { "line-color": "boundary" }]
  );
  add(
    {
      id: "boundary-country",
      type: "line",
      "source-layer": "boundary",
      filter: ["<=", num("admin_level", 99), 2],
      paint: {
        "line-color": c.boundary,
        "line-width": zl([[4, 1], [12, 3], [20, 6]])
      }
    },
    ["hranice", "Štátne hranice", "line", { "line-color": "boundary" }]
  );

  // ================= popisky =================
  add(
    {
      id: "waterway-name",
      type: "symbol",
      "source-layer": "waterway",
      minzoom: 13,
      layout: {
        "symbol-placement": "line",
        "text-field": nameExpr,
        "text-font": ITAL,
        "text-size": zl([[13, 10], [18, 13]])
      },
      paint: {
        "text-color": c.waterText,
        "text-halo-color": c.textHalo,
        "text-halo-width": 1
      }
    },
    [
      "popisky",
      "Názvy vodných tokov",
      "text",
      { "text-color": "waterText", "text-halo-color": "textHalo" }
    ]
  );
  add(
    {
      id: "water-name",
      type: "symbol",
      "source-layer": "water_name",
      layout: {
        "text-field": nameExpr,
        "text-font": ITAL,
        "text-size": zl([[8, 10], [16, 14]]),
        "text-max-width": 8
      },
      paint: {
        "text-color": c.waterText,
        "text-halo-color": c.textHalo,
        "text-halo-width": 1
      }
    },
    [
      "popisky",
      "Názvy vodných plôch",
      "text",
      { "text-color": "waterText", "text-halo-color": "textHalo" }
    ]
  );

  add(
    {
      id: "park-name",
      type: "symbol",
      "source-layer": "park",
      minzoom: 11,
      layout: {
        "text-field": nameExpr,
        "text-font": REG,
        "text-size": zl([[11, 10], [16, 13]]),
        "text-max-width": 8
      },
      paint: {
        "text-color": c.poiText,
        "text-halo-color": c.textHalo,
        "text-halo-width": 1.2
      }
    },
    [
      "popisky",
      "Názvy parkov",
      "text",
      { "text-color": "poiText", "text-halo-color": "textHalo" }
    ]
  );

  // ================= štítky s číslom cesty =================
  // „D1", „R1", „I/18" – to, čo človek na mape hľadá, keď hľadá cestu.
  //
  // IDÚ PRED `road-name` A JE TO ROZHODNUTIE, NIE PORADIE V SÚBORE. MapLibre
  // umiestňuje popisky v poradí vrstiev a ten, kto je skôr, si miesto berie
  // prvý; keď sa na úsek nezmestí meno aj číslo, má ostať ČÍSLO. Meno ulice
  // sa dá zistiť ťuknutím, „ktorá je toto cesta" sa z mapy bez čísla nedozvie
  // nikto.
  //
  // PODKLAD JE ROZŤAHOVATEĽNÝ SDF OBRÁZOK zo spritu (`poc/web/shields.js`,
  // dopeká ho `workers/assets/shields.mjs`): `icon-text-fit` ho natiahne
  // podľa dĺžky čísla, `icon-color` mu dá farbu podľa triedy cesty
  // a `icon-halo-*` orámovanie. Keď ten obrázok v sprite NIE JE – stará
  // sada z cache, nepodarené dopečenie –, vrstva sa nevynechá: číslo sa
  // nakreslí s hrubým halom vo farbe štítka. Je to horšie, ale je to vidieť,
  // kým „štítky zmizli" by nikto nespozoroval.
  //
  // POPISKY STOJA NAROVNO (`text-rotation-alignment: viewport`). Značka
  // natočená podľa cesty už nie je značka, ale text – a na serpentíne by
  // stála na hlave.
  // `route_1_ref` … `route_6_ref` toho slotu, ktorého sieť je hľadaná – číslo
  // európskej cesty nie je v `ref`, ten nesie národné. Poradie slotov nie je
  // zaručené, tak sa prejdú všetky.
  const routeRef = (network) => {
    const vetvy = [];
    for (let i = 1; i <= ROUTE_SLOTS; i += 1) {
      vetvy.push(["==", ["get", `route_${i}_network`], network],
                 ["to-string", ["get", `route_${i}_ref`]]);
    }
    return ["case", ...vetvy, ""];
  };
  const routeFilter = (network) => {
    const vetvy = [];
    for (let i = 1; i <= ROUTE_SLOTS; i += 1) {
      vetvy.push(["all",
        ["==", ["get", `route_${i}_network`], network],
        ["has", `route_${i}_ref`]]);
    }
    return ["any", ...vetvy];
  };

  for (const [id, label, classes, colorKey, mz, shapeId, textKey, borderKey, network]
       of SHIELD_DEFS) {
    // Obrázok je upečený na TVAR × TRIEDU × TÉMU – farba je v ňom, nie
    // v `paint`. Tvar sa dá prepnúť v developer móde (`overrides.shields`):
    // v sprite sú všetky tvary naraz, takže je to zmena mena obrázka, nie
    // prebuildovanie spritu.
    const shieldName = `${shieldShapeFor(id, shapeId, overrides)}-${id}-${theme}`;
    const shieldIcon = hasIcon(shieldName) ? shieldName : null;
    add(
      {
        id: `road-shield-${id}`,
        type: "symbol",
        "source-layer": "transportation_name",
        minzoom: mz,
        filter: network
          ? routeFilter(network)
          : [
              "all",
              ["has", "ref"],
              ["in", str("class"), ["literal", classes]],
              // ZJAZDY VON. `subclass: junction` je mimoúrovňová križovatka
              // a jej `ref` je ČÍSLO VÝJAZDU („10", „6"), nie číslo cesty –
              // na diaľnici ich je viac než samotných štítkov. Kým tu tá
              // podmienka nebola, kreslili sa výjazdy ako diaľničné štítky:
              // po D1 sedeli červené značky „8" a „13" a vyzerali ako čísla
              // ciest, ktoré neexistujú.
              ["!=", ["get", "subclass"], "junction"]
            ],
        layout: {
          "symbol-placement": "line",
          // Ako často sa značka po ceste opakuje, v pixeloch obrazovky.
          // Číslo cesty je ZNAČKA – má sa dať prečítať kdekoľvek na nej, nie
          // len tam, kam padne jedna jediná. Preto hustejšie než predtým
          // (220/260/340): na dlhom úseku bez zjazdu bola medzi štítkami
          // obrazovka a pol.
          "symbol-spacing": zl([[7, 170], [12, 190], [16, 230]]),
          "text-field": network ? routeRef(network) : ["get", "ref"],
          "text-font": BOLD,
          "text-size": zl([[7, 9], [12, 10], [16, 12]]),
          "text-rotation-alignment": "viewport",
          "text-pitch-alignment": "viewport",
          "text-padding": 2,
          // E-štítok sedí POD národným: na tom istom úseku sú obe čísla
          // (D2 aj E 65) a bez posunu by si jedno druhé odhryzlo cez
          // kolízie – zmizlo by nepredvídateľne raz jedno, raz druhé.
          ...(network ? { "text-offset": [0, 1.5] } : {}),
          ...(shieldIcon
            ? {
                "icon-image": shieldIcon,
                "icon-text-fit": "both",
                // Hore/dole menej, po stranách viac – číslo má mať okolo seba
                // rovnako veľa miesta na oko, nie v pixeloch. Odkedy sa
                // obrázok škáluje CELÝ (bez rozťahovacích pásem, viď
                // `poc/web/shields.js`), je odsadenie jediné, čo drží číslo
                // od hrany – tak je o pixel väčšie než predtým.
                "icon-text-fit-padding": [3, 7, 3, 7],
                "icon-rotation-alignment": "viewport",
                "icon-pitch-alignment": "viewport"
              }
            : {})
        },
        paint: shieldIcon
          ? {
              // Žiadne `icon-color`/`icon-halo-*`: obrázok nie je SDF, farbu
              // aj oba prstence má v sebe. Zafarbiť sa dá len číslo.
              "text-color": c[textKey]
            }
          : {
              // Bez obrázka aspoň hrubé halo vo farbe štítka – je to kapsula
              // okolo písmen, nie značka, ale číslo ostane čitateľné.
              "text-color": c[textKey],
              "text-halo-color": c[colorKey],
              "text-halo-width": 2.5
            }
      },
      [
        "popisky",
        label,
        "text",
        shieldIcon
          ? { "text-color": textKey }
          : { "text-color": textKey, "text-halo-color": colorKey }
      ]
    );
  }

  // ================= obmedzenia na ceste =================
  // Vlastný .pmtiles (workers/roads/roads.yml). Kreslia sa ZA štítkami
  // s číslom cesty a PRED názvom ulice, a to poradie je rozhodnutie: MapLibre
  // umiestňuje popisky v poradí vrstiev a kto je skôr, berie si miesto prvý.
  // „Pod týmto mostom je 3,8 m" je pri hustej sieti dôležitejšie než meno
  // ulice, ale číslo cesty (`D1`, `I/18`) je to, čím vodič naviguje.
  //
  // TEXT JE HODNOTA Z OSM, BEZ DOPISOVANEJ JEDNOTKY, a je to zámer. Tag môže
  // mať jednotku už v sebe (`3.8 m`) aj byť v stopách (`12'6"`), takže
  // dopísanie „ m" by z časti hodnôt spravilo `3.8 m m` a z časti nezmysel.
  // Rozoznať to v štýle by chcelo `index-of`/`slice`, teda výrazy, na ktoré sa
  // v statických štýloch pre MapLibre Native spoliehať nechceme – a mapa
  // s číslom bez jednotky je presne to, čo je aj na tabuli. Číslo z tej
  // hodnoty potrebuje len smerovanie („zmestí sa vozidlo?"), a to si ju
  // parsuje samo (`docs/navigation.md`).
  if (roadsUrl) {
    // --- výška: to, kvôli čomu vrstva existuje ---
    // Od z12, lebo obmedzenie výšky rozhoduje o tom, či tam vozidlo vôbec
    // prejde – to sa má dať vidieť skôr, než človek dojde na križovatku.
    add(
      {
        id: "road-limit-height",
        type: "symbol",
        source: "roads",
        "source-layer": "road_limit",
        minzoom: 12,
        filter: ["any", ["has", "maxheight"], ["has", "maxheight_physical"]],
        layout: {
          "symbol-placement": "line",
          "symbol-spacing": 220,
          "text-field": ["coalesce",
            ["get", "maxheight"], ["get", "maxheight_physical"]],
          "text-font": REG,
          "text-size": zl([[12, 10], [16, 13], [20, 17]])
        },
        paint: {
          "text-color": c.roadLimit,
          "text-halo-color": c.textHalo,
          "text-halo-width": 1.6
        }
      },
      [
        "popisky",
        "Obmedzenie výšky (podjazd, tunel)",
        "text",
        { "text-color": "roadLimit", "text-halo-color": "textHalo" }
      ]
    );

    // --- hmotnosť a šírka ---
    // Od z14: je to tá istá trieda údaja, ale pýta sa na ňu menej ľudí a na
    // prehľadovom zoome by len brala miesto obmedzeniu výšky.
    add(
      {
        id: "road-limit-mass",
        type: "symbol",
        source: "roads",
        "source-layer": "road_limit",
        minzoom: 14,
        filter: ["all",
          ["!", ["has", "maxheight"]],
          ["!", ["has", "maxheight_physical"]],
          ["any", ["has", "maxweight"], ["has", "maxwidth"]]],
        layout: {
          "symbol-placement": "line",
          "symbol-spacing": 260,
          "text-field": ["coalesce", ["get", "maxweight"], ["get", "maxwidth"]],
          "text-font": REG,
          "text-size": zl([[14, 9], [16, 11], [20, 14]])
        },
        paint: {
          "text-color": c.roadLimit,
          "text-halo-color": c.textHalo,
          "text-halo-width": 1.4
        }
      },
      [
        "popisky",
        "Obmedzenie hmotnosti a šírky",
        "text",
        { "text-color": "roadLimit", "text-halo-color": "textHalo" }
      ]
    );

    // --- maximálna rýchlosť ---
    // Až od z15 a menším písmom: `maxspeed` je takmer na každej ceste, takže
    // na nižšom zoome by z nej bola šeď čísel cez celú mapu. Nie je to
    // obmedzenie prejazdu, je to informácia – preto je posledná z troch.
    add(
      {
        id: "road-maxspeed",
        type: "symbol",
        source: "roads",
        "source-layer": "road_limit",
        minzoom: 15,
        filter: ["has", "maxspeed"],
        layout: {
          "symbol-placement": "line",
          "symbol-spacing": 300,
          "text-field": ["get", "maxspeed"],
          "text-font": REG,
          "text-size": zl([[15, 9], [17, 10], [20, 13]])
        },
        paint: {
          "text-color": c.roadLimit,
          "text-halo-color": c.textHalo,
          "text-halo-width": 1.4,
          "text-opacity": 0.85
        }
      },
      [
        "popisky",
        "Maximálna rýchlosť",
        "text",
        { "text-color": "roadLimit", "text-halo-color": "textHalo" }
      ]
    );
  }

  add(
    {
      id: "road-name",
      type: "symbol",
      "source-layer": "transportation_name",
      minzoom: 13,
      layout: {
        "symbol-placement": "line",
        "text-field": nameExpr,
        "text-font": REG,
        "text-size": zl([[13, 10], [16, 12], [20, 16]])
      },
      paint: {
        "text-color": c.roadText,
        "text-halo-color": c.textHalo,
        "text-halo-width": 1.2
      }
    },
    [
      "popisky",
      "Názvy ulíc a ciest",
      "text",
      { "text-color": "roadText", "text-halo-color": "textHalo" }
    ]
  );

  // Súpisné/orientačné čísla – iba na najväčšom detaile.
  add(
    {
      id: "housenumber",
      type: "symbol",
      "source-layer": "housenumber",
      minzoom: 17,
      layout: {
        "text-field": ["get", "housenumber"],
        "text-font": REG,
        "text-size": zl([[17, 9], [20, 12]]),
        "text-allow-overlap": false
      },
      paint: {
        "text-color": c.houseText,
        "text-halo-color": c.textHalo,
        "text-halo-width": 1
      }
    },
    [
      "popisky",
      "Súpisné čísla",
      "text",
      { "text-color": "houseText", "text-halo-color": "textHalo" }
    ]
  );

  // ---- POI ----
  // Ikona sa vyberá podľa `subclass`, potom `class`. Ak pre ne sprite ikonu
  // nemá, nekreslí sa nič (prázdny reťazec) – žiadne náhradné kolieska.
  // IKONA VYBRANÁ V DEVELOPER MÓDE IDE PRVÁ. Je to jediná odpoveď na „tejto
  // kategórii chcem inú značku": `class`/`subclass` z dlaždíc sú stovky
  // hodnôt a sada ikoniek ich pokrýva menami, ktoré si nikto nevyberá –
  // dostane sa `restaurant_11`, aj keď by tam patrila vlastná ikona chaty.
  // Prázdny reťazec je platná voľba („tu žiadnu ikonu"), preto sa rozhoduje
  // podľa TOHO, ČI KĽÚČ EXISTUJE, nie podľa toho, či je hodnota pravdivá.
  //
  // Ikona, ktorú sprite nemá, sa nenasadí (`hasIcon`) – MapLibre by symbol
  // ticho nevykreslil a v mape by kategória zmizla aj s popiskom.
  const poiIconPicks = Object.entries(overrides?.poi?.icons || {})
    .filter(([, name]) => name === "" || hasIcon(name));
  const withPoiIcons = (base) => [
    "case",
    ...poiIconPicks.flatMap(([cls, name]) => [
      ["any", ["==", str("subclass"), cls], ["==", str("class"), cls]],
      name
    ]),
    ...base.slice(1)
  ];

  const iconExpr = withPoiIcons([
    "case",
    ["in", str("subclass"), ["literal", iconClasses]],
    ["concat", str("subclass"), suffix],
    ["in", str("class"), ["literal", iconClasses]],
    ["concat", str("class"), suffix],
    ""
  ]);

  // SDF sprite obsahuje samotný symbol bez kolieska, ktoré predtým vypĺňalo
  // celý štvorec ikony – aby ikony opticky nezmenšeli, sú o kúsok väčšie.
  const iconScale = sdfIcons ? 1.35 : 1;
  const scaled = (stops) => zl(stops.map(([z, s]) => [z, s * iconScale]));

  const poiLayout = {
    "icon-image": iconExpr,
    "icon-size": scaled([[14, 0.9], [18, 1.1], [20, 1.3]]),
    "icon-optional": true,
    "text-field": nameExpr,
    "text-font": REG,
    "text-size": zl([[14, 10], [18, 12], [20, 14]]),
    "text-offset": [0, 1.1],
    "text-anchor": "top",
    "text-optional": true,
    "text-max-width": 9,
    "symbol-sort-key": num("rank", 100)
  };
  // Farba ikon funguje len pri SDF sprite (pipeline ho vyrobí z osm-liberty).
  const poiPaint = {
    "text-color": c.poiText,
    "text-halo-color": c.textHalo,
    "text-halo-width": 1.2,
    ...(sdfIcons
      ? {
          "icon-color": c.poiIcon,
          "icon-halo-color": c.poiIconHalo,
          "icon-halo-width": 1
        }
      : {})
  };
  const poiPalette = {
    "text-color": "poiText",
    "text-halo-color": "textHalo",
    ...(sdfIcons ? { "icon-color": "poiIcon", "icon-halo-color": "poiIconHalo" } : {})
  };

  // Skryté POI triedy z developer módu – vypnú sa ako filter, nie zmazaním
  // vrstvy, takže sa dajú kedykoľvek vrátiť späť.
  const poiHidden = overrides?.poi?.hidden || [];
  const notHidden = poiHidden.length
    ? [
        "all",
        ["!", ["in", str("subclass"), ["literal", poiHidden]]],
        ["!", ["in", str("class"), ["literal", poiHidden]]]
      ]
    : null;
  const poiFilter = (base) =>
    notHidden ? (base ? ["all", base, notHidden] : notHidden) : base;

  // z14–16: len dôležitejšie POI, aby mapa nebola zahltená.
  add(
    {
      id: "poi-major",
      type: "symbol",
      "source-layer": "poi",
      minzoom: DETAIL_Z,
      maxzoom: 16,
      filter: poiFilter(["<=", num("rank", 100), 24]),
      layout: poiLayout,
      paint: poiPaint
    },
    ["poi", "POI – dôležité (z14–16)", "point", poiPalette]
  );
  // z16+: úplne všetko, bez filtra na rank.
  add(
    {
      id: "poi-all",
      type: "symbol",
      "source-layer": "poi",
      minzoom: 16,
      ...(poiFilter(null) ? { filter: poiFilter(null) } : {}),
      layout: { ...poiLayout, "text-allow-overlap": false },
      paint: poiPaint
    },
    ["poi", "POI – všetky (z16+)", "point", poiPalette]
  );

  // ---- body z vlastných dlaždíc ----
  // Prameň, jaskyňa, vodopád, rozhľadňa, útulňa, kríž pri ceste, štôlňa.
  // Schéma OpenMapTiles ich nemá: `natural=spring` prejde LEN ako plocha,
  // takže studnička mapovaná uzlom – teda prakticky každá – v mape chýbala;
  // `man_made=tower` schéma nepozná vôbec, takže rozhľadňa sa do dlaždíc
  // dostala jedine vtedy, keď mala navyše `tourism=viewpoint`.
  //
  // Ikona sa hľadá rovnako ako pri POI: podľa `class`, a keď ju sada nemá,
  // ostane len popisok – žiadne náhradné kolieska.
  //
  // VLASTNÝ ZDROJ (`points`, nie `features`): body sú vo vlastnom
  // `.pmtiles` (workers/features/points.yml) presne kvôli balíku „body“ na
  // stiahnutie zvlášť od línií a plôch – rozpis prečo je v hlavičke toho
  // súboru. Na to, čo je na mape VIDIEŤ, to nemá vplyv, len na to, z ktorého
  // súboru sa to číta.
  if (pointsUrl) {
    // Tá istá voľba ikony ako pri POI (`withPoiIcons`): triedy sú iné
    // (prameň, jaskyňa, rozhľadňa), ale otázka je jedna – „akú značku má
    // táto kategória" – a dve odpovede by sa raz rozišli.
    const featureIcon = withPoiIcons([
      "case",
      ["in", str("class"), ["literal", iconClasses]],
      ["concat", str("class"), suffix],
      ["in", str("subclass"), ["literal", iconClasses]],
      ["concat", str("subclass"), suffix],
      ""
    ]);
    add(
      {
        id: "feature-point",
        type: "symbol",
        source: "points",
        "source-layer": "feature_point",
        minzoom: 12,
        // Skryté kategórie platia aj tu. Zoznam v paneli je jeden pre POI aj
        // pre vlastné body, takže by odškrtnutie prameňa neurobilo nič –
        // a nikto by nepovedal prečo.
        ...(poiFilter(null) ? { filter: poiFilter(null) } : {}),
        layout: {
          ...poiLayout,
          "icon-image": featureIcon,
          // Výška patrí k prameňu aj k rozhľadni – je to prvé, čo človek
          // pri plánovaní túry hľadá.
          "text-field": [
            "case",
            ["has", "ele"],
            ["concat", nameExpr, " ", ["to-string", ["round", num("ele", 0)]], " m"],
            nameExpr
          ]
        },
        paint: {
          ...poiPaint,
          "text-color": c.featurePoi,
          ...(sdfIcons ? { "icon-color": c.featurePoi } : {})
        }
      },
      [
        "prvky",
        "Pramene, jaskyne, rozhľadne a útulne",
        "point",
        {
          "text-color": "featurePoi",
          "text-halo-color": "textHalo",
          ...(sdfIcons ? { "icon-color": "featurePoi", "icon-halo-color": "poiIconHalo" } : {})
        }
      ]
    );
  }

  // ---- tematické body ----
  // Každý typ mapy má skupinu bodov, ktorá je preň tá hlavná: hrady na
  // historickej, vleky na lyžiarskej, pumpy na cestnej. Sú to samostatné
  // vrstvy – väčšie, farebne odlíšené a s prednosťou pri umiestňovaní
  // popiskov (`symbol-sort-key`) – aby sa dali zapnúť skôr než ostatné POI
  // a v developer móde ladiť zvlášť. Profil typu mapy ich zapína; na mapách,
  // kam nepatria, sú vypnuté, inak by kreslili tie isté ikony druhýkrát.
  const topicPoi = (id, label, classes, paletteKey, minzoom) =>
    add(
      {
        id,
        type: "symbol",
        "source-layer": "poi",
        minzoom,
        filter: poiFilter([
          "any",
          ["in", str("subclass"), ["literal", classes]],
          ["in", str("class"), ["literal", classes]]
        ]),
        layout: {
          ...poiLayout,
          "icon-size": scaled([[10, 0.9], [14, 1.1], [18, 1.3], [20, 1.5]]),
          "text-size": zl([[10, 10], [14, 11.5], [18, 13], [20, 15]]),
          // Nižší kľúč = umiestňuje sa skôr, takže tematický bod prežije aj
          // tam, kde sa bežné POI už nezmestia.
          "symbol-sort-key": ["-", num("rank", 100), 100]
        },
        paint: {
          ...poiPaint,
          "text-color": c[paletteKey],
          ...(sdfIcons ? { "icon-color": c[paletteKey] } : {})
        }
      },
      [
        "poi",
        label,
        "point",
        {
          "text-color": paletteKey,
          "text-halo-color": "textHalo",
          ...(sdfIcons ? { "icon-color": paletteKey, "icon-halo-color": "poiIconHalo" } : {})
        }
      ]
    );

  topicPoi("poi-historic", "Pamiatky (historická mapa)", HISTORIC_CLASSES, "historicPoi", 10);
  topicPoi("poi-mining", "Bane, štôlne a haldy (historická mapa)", MINING_CLASSES, "miningPoi", 10);
  topicPoi("poi-ski", "Lyžiarske stredisko a vleky (lyžiarska mapa)", SKI_CLASSES, "skiPoi", 11);
  topicPoi("poi-road", "Pumpy, odpočívadlá a servis (cestná mapa)", ROAD_SERVICE_CLASSES, "servicePoi", 10);

  // ---- vrcholy hôr (dôležité pre outdoor mapu) ----
  add(
    {
      id: "mountain-peak",
      type: "symbol",
      "source-layer": "mountain_peak",
      minzoom: 9,
      // Vylúčené sú všetky triedy, ktoré prídu ako línia – hrebeň, areta
      // aj bralo. Pohoria a hrebene majú vlastnú popiskovú vrstvu (kurzíva,
      // verzálky), bralo vlastnú kresbu so zúbkami. `cliff` tu predtým
      // chýbal, takže každá bralná hrana dostala od z13 doprostred
      // trojuholníček vrcholu aj s popiskom.
      filter: ["!", ["in", str("class"), ["literal", PEAK_LINE_CLASSES]]],
      layout: {
        "icon-image": [
          "case",
          ["==", ["get", "class"], "volcano"],
          hasIcon(SPECIAL.volcano) ? SPECIAL.volcano : SPECIAL.peak,
          SPECIAL.peak
        ],
        "icon-size": 0.9 * iconScale,
        "icon-optional": true,
        "text-field": [
          "case",
          ["has", "ele"],
          ["concat", nameExpr, "\n", ["to-string", ["get", "ele"]], " m"],
          nameExpr
        ],
        "text-font": REG,
        "text-size": zl([[9, 9], [14, 11], [20, 14]]),
        "text-offset": [0, 0.9],
        "text-anchor": "top",
        "text-optional": true,
        "symbol-sort-key": num("rank", 100)
      },
      paint: {
        "text-color": c.peakText,
        "text-halo-color": c.textHalo,
        "text-halo-width": 1.4,
        ...(sdfIcons
          ? {
              "icon-color": c.peakIcon,
              "icon-halo-color": c.poiIconHalo,
              "icon-halo-width": 1
            }
          : {})
      }
    },
    [
      "poi",
      "Vrcholy hôr",
      "point",
      {
        "text-color": "peakText",
        "text-halo-color": "textHalo",
        ...(sdfIcons ? { "icon-color": "peakIcon", "icon-halo-color": "poiIconHalo" } : {})
      }
    ]
  );

  add(
    {
      id: "aerodrome-label",
      type: "symbol",
      "source-layer": "aerodrome_label",
      minzoom: 10,
      layout: {
        ...(hasIcon(SPECIAL.airport)
          ? { "icon-image": SPECIAL.airport, "icon-size": iconScale }
          : {}),
        "icon-optional": true,
        "text-field": nameExpr,
        "text-font": REG,
        "text-size": zl([[10, 10], [16, 13]]),
        "text-offset": [0, 1],
        "text-anchor": "top",
        "text-optional": true
      },
      paint: {
        "text-color": c.poiText,
        "text-halo-color": c.textHalo,
        "text-halo-width": 1.2,
        ...(sdfIcons && hasIcon(SPECIAL.airport)
          ? {
              "icon-color": c.aerodromeIcon,
              "icon-halo-color": c.poiIconHalo,
              "icon-halo-width": 1
            }
          : {})
      }
    },
    [
      "poi",
      "Letiská (popisky)",
      "point",
      {
        "text-color": "poiText",
        "text-halo-color": "textHalo",
        ...(sdfIcons && hasIcon(SPECIAL.airport)
          ? { "icon-color": "aerodromeIcon", "icon-halo-color": "poiIconHalo" }
          : {})
      }
    ]
  );

  // ---- pohoria a geografické oblasti ----
  // Kreslia sa od malých mierok a inak než sídla: kurzíva, verzálky a väčšie
  // rozpálenie písmen, aby čitateľ hneď videl, že ide o územie, nie o obec.
  // Nemajú ikonu ani bod – popisujú plochu, nie miesto.
  const geoLayout = (sizes) => ({
    "text-field": nameExpr,
    "text-font": ITAL,
    "text-transform": "uppercase",
    "text-letter-spacing": 0.18,
    "text-size": zl(sizes),
    "text-max-width": 8,
    "symbol-sort-key": num("rank", 100)
  });
  const geoPaint = {
    "text-color": c.geoText,
    "text-halo-color": c.textHalo,
    "text-halo-width": 1.6
  };
  const geoPalette = { "text-color": "geoText", "text-halo-color": "textHalo" };

  add(
    {
      id: "mountain-range",
      type: "symbol",
      "source-layer": "mountain_peak",
      minzoom: 6,
      filter: ["in", str("class"), ["literal", RANGE_CLASSES]],
      layout: geoLayout([[6, 12], [9, 16], [12, 19], [16, 22]]),
      paint: geoPaint
    },
    ["geo", "Pohoria a hrebene", "text", geoPalette]
  );

  add(
    {
      id: "place-geo",
      type: "symbol",
      "source-layer": "place",
      minzoom: 4,
      filter: ["in", str("class"), ["literal", GEO_PLACE_CLASSES]],
      layout: geoLayout([[4, 11], [7, 15], [11, 19], [16, 22]]),
      paint: geoPaint
    },
    ["geo", "Geografické oblasti a ostrovy", "text", geoPalette]
  );

  // ---- sídla ----
  const places = [
    ["neighbourhood", "Štvrte a samoty", ["neighbourhood", "isolated_dwelling", "farm", "quarter"], 13, REG, zl([[13, 9], [18, 13]])],
    ["hamlet", "Osady", ["hamlet"], 12, REG, zl([[12, 10], [18, 14]])],
    ["suburb", "Mestské časti", ["suburb"], 11, REG, zl([[11, 11], [18, 15]])],
    ["village", "Obce", ["village"], 9, REG, zl([[9, 10], [16, 15]])],
    ["town", "Mestá", ["town"], 7, REG, zl([[7, 11], [14, 18]])],
    ["city", "Veľké mestá", ["city"], 4, BOLD, zl([[4, 12], [13, 22]])],
    ["state", "Kraje a regióny", ["state", "province"], 4, BOLD, zl([[4, 11], [8, 15]])],
    ["country", "Štáty", ["country"], 2, BOLD, zl([[2, 11], [6, 18]])]
  ];
  for (const [id, label, classes, mz, font, size] of places) {
    add(
      {
        id: `place-${id}`,
        type: "symbol",
        "source-layer": "place",
        minzoom: mz,
        filter: ["in", str("class"), ["literal", classes]],
        layout: {
          "text-field": nameExpr,
          "text-font": font,
          "text-size": size,
          "text-max-width": 9,
          "symbol-sort-key": num("rank", 100)
        },
        paint: {
          "text-color": c.placeText,
          "text-halo-color": c.textHalo,
          "text-halo-width": 1.6
        }
      },
      ["sidla", label, "text", { "text-color": "placeText", "text-halo-color": "textHalo" }]
    );
  }

  // ---- hranica stiahnutého regiónu ----
  // ÚPLNE NAVRCHU, a je to podstatné: prekrýva sa VŠETKO vrátane popiskov,
  // tieňovania a vrstiev z vlastných .pmtiles. Vrstva pridaná za ňu by mimo
  // regiónu opäť kreslila – stráži to `workers/lint/style.mjs`.
  if (regionOutline) {
    add(
      {
        id: "region-outside",
        type: "fill",
        source: "region",
        filter: ["==", ["get", "kind"], "mimo"],
        paint: { "fill-color": c.regionOutside }
      },
      ["hranice", "Mimo stiahnutého regiónu", "area",
       { "fill-color": "regionOutside" }]
    );
    add(
      {
        id: "region-border",
        type: "line",
        source: "region",
        filter: ["==", ["get", "kind"], "hranica"],
        layout: { "line-join": "round" },
        paint: {
          "line-color": c.regionBorder,
          "line-width": zw([[4, 0.6], [8, 1], [12, 1.6], [16, 2.4]]),
          "line-opacity": 0.75
        }
      },
      ["hranice", "Okraj stiahnutého regiónu", "line",
       { "line-color": "regionBorder" }]
    );
  }

  // Najprv profil typu mapy (čo táto mapa vôbec ukazuje), až potom úpravy
  // z developer módu – tie musia vedieť profil prebiť.
  applyMapType(style, mapTypeId);
  // Poradie kreslenia sa mení až NAD hotovým štýlom: presúva sa aj vzor
  // a okraj, ktoré vznikli práve v `applyLayerOverrides`.
  return applyLayerOrder(
    applyLayerOverrides(style, overrides?.layers, hasIcon, theme),
    overrides?.order
  );
}

export {
  MAP_TYPES,
  MAP_TYPE_IDS,
  DEFAULT_MAP_TYPE,
  mapTypeDef,
  normalizeMapType,
  mapTypeHidden
} from "./map-types.js";

/** Vrstvy, na ktoré sa dá kliknúť (popup s detailom). */
export const CLICKABLE_LAYERS = [
  "poi-major",
  "poi-all",
  "poi-historic",
  "poi-mining",
  "poi-ski",
  "poi-road",
  "mountain-peak",
  "aerodrome-label",
  // Krajinné prvky z vlastných dlaždíc – popup povie, čo to je a v akej výške.
  "feature-point",
  // Plánovaná cesta: z čiary sa nedozvieš, či pôjde o diaľnicu alebo o lesnú
  // cestu, a to je pri nej to hlavné – popup povie meno, `ref` (napr. `D3`)
  // aj čo sa plánuje. Zbierať `subclass` do dlaždíc a nikde ho neukázať by
  // bolo to isté, čo sa stalo napätiu pri elektrickom vedení.
  "feature-road-proposed",
  "piste-line",
  // Značené trasy – po ceste ich vedie viac, popup povie, ktorá je ktorá.
  "trail-hiking",
  "trail-bicycle",
  "trail-mtb",
  "trail-ski",
  "trail-horse"
];
