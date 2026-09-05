/**
 * Farebné témy a generátor MapLibre štýlu pre schému OpenMapTiles.
 * Zdieľané medzi webom a pipeline (`workers/styles/build.mjs` z toho robí
 * statické `style.json` aj pre iOS).
 *
 * Do zoomu DETAIL_Z (14) sa mapa postupne oreže, aby bola čitateľná; vyššie sa
 * nefiltruje nič. Dlaždice končia na z16 (limit Planetileru), vyššie rieši
 * MapLibre overzoomom (po MAX_DISPLAY_Z = 20).
 *
 * Každá vrstva nesie `metadata` (`frico:group`, `frico:label`, `frico:kind`,
 * `frico:palette`), takže sa dá v developer móde vypísať, prepnúť a prefarbiť
 * bez druhého zoznamu vrstiev. Úpravy prichádzajú späť ako `overrides` a ten
 * istý objekt použije aj pipeline.
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
 * sivá škvrna, ale dlaždice si prehliadač aj tak sťahuje. Od tohto zoomu je
 * z vrstevníc len hlavná trieda, polovičná od z12 a základná od z13.
 *
 * To isté číslo je v schémach Planetilera (tam rozhoduje, čo sa vyrobí, tu čo
 * sa nakreslí) – rozídené znamená buď dlaždice, ktoré nikto nevidí, alebo
 * dieru v mape. Stráži to `workers/lint/zoom-floor.py`.
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
 * Zdroje výšok, z ktorých pipeline počíta vrstevnice, skaly a tieňovanie.
 * Kľúče sú tie isté ako vo `workers/data/dem-sources.json` a vo formulári –
 * každá vrstva môže mať iný model. Licencia každého vyžaduje uvedenie zdroja,
 * preto ide atribúcia priamo do zdroja v štýle.
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
    // licencia ÚGKK vyžaduje uvedenie zdroja
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
    // licencia ÚGKK vyžaduje uvedenie zdroja
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
 * Terénna trojica – odkiaľ sa berú `background`, `rock`/`rockArea`
 * a `contour*`. Sú to farby papierovej horskej mapy:
 *
 *   podklad     #f0efeb   bielosivá – holý terén nad lesom, sneh, kamenie
 *   skaly a suť #9c9286   teplá stredná sivohnedá
 *   vrstevnice  #8b8676   tenké olivovosivé línie
 *
 * Podklad je bielosivý, nie zelenkastý: zelená je vyhradená lesu – jediná sýta
 * zelená v mape. Lúka, kosodrevina či ihrisko sú odstupňované do olivovo-khaki.
 * Sivá pritom nie je neutrálna, má ten istý teplý zemitý nádych ako skaly
 * a vrstevnice; neutrálna sivá vedľa zemitých hnedých vyzerá domodra.
 *
 * Každá téma má svoj odtieň, len veľmi jemne iný – rozdiel je pár krokov, aby
 * sa dali rozoznať, ale aby žiadna nevyzerala ako iná mapa.
 *
 * Pozor na výplne, ktoré podklad dobieha: `rock` sa kreslí s krytím 0,8,
 * takže je hodnota tmavšia než to, čo je vidieť. Suť je sypká a svetlejšia
 * než stena – to je zámer.
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
    // za hranicou regiónu mapa končí – zámerne tá istá farba ako `background`
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
    // hlavná skupina bodov typu mapy, nech sa dá zvýrazniť zvlášť
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
    // prvky mimo schémy OpenMapTiles (workers/features/features.yml)
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
    // alfa je podstatná: MapLibre svah prekrýva, bez nej nad 20° mapu nevidno
    hillShadow: "#5a4a3ab3",
    hillHighlight: "#ffffff5c",
    hillAccent: "#8a7a6a38",
    // prvá desiatka sú farby značiek z OSM, zvyšok podľa druhu trasy
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
    // v svetlej téme sú priečky biele; tmavý variant sa počíta od podkladu
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
    // prvky mimo schémy OpenMapTiles (workers/features/features.yml)
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
    // v tmavej téme sú značky svetlejšie – čierna by na podklade zmizla
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
    // prvky mimo schémy OpenMapTiles (workers/features/features.yml)
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
    // outdoor: najsýtejšie značky, nech sa dajú rozoznať cez vrstevnice
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
    // prvky mimo schémy OpenMapTiles (workers/features/features.yml)
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
      // kosodrevina má v dlaždiciach `class: grass` – bez vlastnej farby by
      // vyzerala ako lúka
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
      // číslo cesty sa píše do červeného štítka (zelená je smerová tabuľa);
      // výplne ciest sú svetlé, takže farba čiary sa použiť nedá
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
      // v dlaždiciach sú to línie vo vrstve `mountain_peak`, nie plocha z DEM
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
  // vlastné dlaždice mimo schémy OpenMapTiles (workers/features/features.yml)
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
 * Funkcia, a nie riadok v `buildStyle`, lebo tú istú otázku si kladie aj
 * developer mode – inak by v paneli svietilo niečo iné, než je v mape. Čisto
 * geometrické tvary sa vynechávajú: POI bez vlastnej ikony nemá dostať kruh.
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
 * Ikona jednej kategórie – jedna otázka, jedna odpoveď.
 *
 * Poradie je to isté ako vo výraze v štýle: najprv `overrides.poi.icons`
 * (prázdny reťazec = „žiadna"), potom `<trieda><prípona>` zo sady, inak nič –
 * žiadne náhradné koliesko. Pýta sa na to štýl aj panel.
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
 * `["zoom"]` smie byť podľa style-spec iba priamym vstupom najvrchnejšieho
 * `interpolate`/`step`, preto sa šírky obrysov počítajú pripočítaním
 * k jednotlivým zlomom (`widen`), nie výrazom `["+", …]`.
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
 * Zoomové pásma: `zs([[9, 11, 2], [12, 12, 4], [13, 17, 6]])` – „od z9 do z11
 * takto, na z12 takto, od z13 vyššie takto".
 *
 * Krivka (`zw`/`zl`) odpovedá na „ako hodnota rastie", pásmo na „čo platí
 * v tomto rozsahu". Cez krivku by „od z9 do z11 hrúbka 2" znamenalo napísať
 * tú istú hodnotu dvakrát, na každej hranici pásma.
 *
 * Pásmo `[od, do, hodnota]` platí pre zoomy `od ≤ z < do + 1`, teda `do` je
 * vrátane aj s desatinami. Pásma musia ísť za sebou bez medzier a prekryvov
 * a zadávajú sa v celých zoomoch; pod prvým a nad posledným platí krajné.
 *
 * `step` a nie `interpolate`: vnútri pásma je hodnota konštantná a na hranici
 * skočí. Susedné pásma by potrebovali dva zlomy na tom istom zoome, a to
 * MapLibre odmietne aj s celým štýlom. Kto chce plynulý prechod, píše krivku.
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
 * Iba plochy – povinná stráž pre `fill` vrstvu nad vrstvou so zmiešanou
 * geometriou.
 *
 * MapLibre `fill` vrstve nepreskočí čiary: otvorenú lomenú čiaru pošle
 * earcutu, ako keby to bol uzavretý prstenec, a vypadne z toho
 * sebaprekrývajúci sa mnohouholník. `fill-outline-color` mu k tomu obtiahne
 * hrany, takže to vyzerá ako útvar prerezaný cez krajinu.
 *
 * Presne to boli tie čudné polygóny od z13: `pedestrian-area` je `fill` nad
 * `transportation`, kde sú chodníky čiary, a farba `pedestrian` je od
 * `background` na nerozoznanie – takže plocha prekryla les aj lúku pod sebou.
 *
 * Pri `fill` nad `transportation`, `aeroway`, `park` a `piste` teda `class`
 * nestačí, treba aj typ geometrie.
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
 * Triedy `mountain_peak`, ktoré prídu ako línia, nie ako bod.
 * `natural=cliff`, `ridge` a `arete` mapuje Planetiler do tej istej vrstvy ako
 * vrcholy, ale s líniovou geometriou. Bez tohto zoznamu dostane bralná hrana
 * doprostred trojuholníček vrcholu aj s popiskom.
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

// zlomy všetkých troch kriviek nižšie; hodnoty sa berú po indexoch, lebo
// `["zoom"]` smie byť len vstupom najvrchnejšieho `interpolate`
export const TRAIL_OFFSET_ZOOMS = [9, 11, 13, 14, 16, 20];

/**
 * Šírka pásika – a zároveň rozostup dvoch trás na tej istej ceste.
 *
 * Jedna krivka naschvál: rozostup nie je vlastné číslo, je to šírka pásika.
 * Kým to boli dve krivky, rozišli sa medzi zlomami – šírka sa interpolovala
 * `exponential 1.5`, rozostup lineárne, takže pri z18 bola medzi pásikmi
 * sedmina pixela, v ktorej presvital ich podklad.
 */
export const TRAIL_STRIPE = [
  [9, 0.9], [11, 1.11], [13, 1.54], [14, 1.9], [16, 2.6], [20, 6]
];
/** Rozostup dvoch trás = šírka pásika. Tá istá krivka, nie kópia. */
export const TRAIL_PITCH = TRAIL_STRIPE;

// odstup osi pásika od osi cesty v px: polovica čiary + polovica pásika.
// Pod z16 rozhodujú metre, nie šírka čiary – pásik by inak obiehal vlásenku
// oblúkom širším než zákruta a v mape by z neho bola plocha.
// Stráži to `workers/lint/trails.mjs`.
export const TRAIL_OFFSET_ROAD = [
  [9, 0.06], [11, 0.24], [13, 0.95], [14, 1.9], [16, 6.6], [20, 19.8]
];
export const TRAIL_OFFSET_PATH = [
  [9, 0.04], [11, 0.16], [13, 0.63], [14, 1.27], [16, 3.6], [20, 11.0]
];

/** Koľko metrov od cesty smie pásik najviac ísť (rozpis vyššie). */
export const TRAIL_OFFSET_LIMIT_M = { road: 12, path: 8 };

/**
 * Spoj pásika v zákrute: `miter`, nie `round`.
 *
 * MapLibre kreslí `line-offset` tak, že každý vrchol posunie po osi zlomu:
 *
 *   `round`  posunie o odstup po normále každého ramena zvlášť, takže sa
 *            rovnobežky nestretnú – na vonkajšej strane ostane biely klin,
 *            na vnútornej sa prekryjú;
 *   `miter`  posunie po osi zlomu o `odstup / cos(zlom/2)`, čo je presne roh
 *            rovnobežky – pásik má rovnakú hrúbku ako na rovine.
 *
 * `line-miter-limit` je poistka pre vlásenky: `odstup / cos(zlom/2)` rastie
 * nad všetky medze, takže nad dvojnásobok (zlom 120°) MapLibre spoj zreže.
 * Je to predvolená hodnota, ale píše sa sem naschvál – je to poistka.
 *
 * Geometria sa pritom neupravuje: pásik má presne tie body, ktoré má cesta
 * v OSM.
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
    // nula je platná odpoveď („nalep to na čiaru"), záporná nie
    if (Number.isFinite(n) && n >= 0 && n <= 60) out[key] = n;
  }
  return out;
}

// značka trasy sa kreslí zo spritu (`poc/web/marks.js`), nie ako ikonka druhu

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
 * Značky dvoch trás na jednej ceste sa stavajú nad seba, nie na seba.
 *
 * Po chodníku vedie bežne červená aj modrá a k tomu cyklotrasa – a všetky majú
 * v dlaždiciach tú istú geometriu (pásiky robí až `line-offset`, ktorý na
 * symboly neplatí). Kým bola značka priamo na čiare, padli všetky na to isté
 * miesto a kolízia nechala vždy tú istú (z troch trás bolo vidieť dve).
 *
 * Značka sa preto posunie `icon-offset`-om podľa toho, koľká je trasa v rade
 * (`off`) a na ktorej strane je jej pásik (`side`): pešie nahor, kolesové
 * nadol. Vzniká z toho stĺpik značiek nad rozcestím, ako sú na strome.
 *
 * `icon-offset` je v pixeloch obrázka, ktoré MapLibre násobí `icon-size` –
 * stĺpik sa teda škáluje sám, ale zadáva sa v pixeloch, nie vo výškach značky.
 *
 * `base` je odstup prvej značky od čiary, `step` rozostup v stĺpiku. Značky
 * stoja tesne na sebe: obrázok je `MARK_BOX` plus priehľadný pixel na každej
 * strane, takže krok `MARK_BOX` položí viditeľné štvorce presne na seba.
 *
 * Cena je `icon-allow-overlap`, a bez nej to nejde: kolízny obdĺžnik je celý
 * obrázok vrátane priehľadného okraja, takže by MapLibre druhú značku zahodil.
 * Pri stĺpiku je to bezpečné – rad je krátky, stojí kolmo na trasu a čo si
 * prekrýva, je jeho vlastná priečka. Stráži to `workers/lint/marks.mjs`.
 */
export const TRAIL_MARK_STACK = { base: MARK_BOX + 4, step: MARK_BOX };

/**
 * Miesto okolo značky, ktoré si drží voľné (v pixeloch obrazovky).
 *
 * Nula, lebo stĺpik má stáť na sebe – a padding sa na rozdiel od odstupu
 * neškáluje s `icon-size`, takže by pri malej značke vážil dvojnásobne.
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
 * Medze tých troch čísel – jedno miesto pre normalizáciu, štýl aj políčka
 * v paneli; inak by panel pustil hodnotu, ktorú zápis potom odmietne.
 *
 * Rozostup nesmie byť nula (to nie je „žiadne značky", ale nekonečne veľa na
 * čiare), odstup v stĺpiku nulu smie – vtedy sedia značky presne na sebe.
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
 * Druhy značených trás. Jeden zoznam pre štýl, developer mode aj popup vo
 * viewri.
 *
 * `palette` je farba pre trasu bez vlastnej; `icons` sú kandidáti v poradí,
 * prvý existujúci v sade vyhráva. `dash` je id predvoľby z `patterns.js`, nie
 * pole čísel – tú istú predvoľbu ponúka panel.
 *
 * `side` je strana cesty (+1 / −1) a musí sedieť so `SIDE_BY_ROUTE` vo
 * `workers/trails/routes.py`; tu je len na to, aby panel vedel povedať, čo kde
 * uvidíš – posúva sa podľa dát.
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
    // vlastný druh: po ferrate sa nedá ísť bez výstroja
    id: "ferrata",
    label: "Ferraty",
    short: "ferrata",
    palette: "trailFerrata",
    icons: ["climbing", "mountain", "triangle"],
    dash: "dashed-fine",
    side: 1
  },
  {
    // značka v teréne farbu nemá, tak je naša; kolesové idú na opačnú stranu
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
 * mode. Pýtajú sa naň štýl aj panel, tak je odpoveď na jednom mieste.
 *
 * Farba tu zámerne nie je – ide cez paletu, lebo z nej žije aj pásik, aj
 * ikona, aj názov trasy.
 */
export function trailTypeDef(type, overrides) {
  const own = overrides?.trails?.types?.[type.id] || {};
  const icon = typeof own.icon === "string" ? own.icon.trim() : "";
  // tvar značky má tri odpovede: `undefined` = ako v OSM, "" = žiadna,
  // meno tvaru = vždy tento
  const mark = typeof own.mark === "string" ? own.mark.trim() : null;
  return {
    ...type,
    dash: DASH_IDS.includes(own.dash) ? own.dash : type.dash,
    // prázdny reťazec je „žiadna", nie „vezmi predvolenú"
    iconPick: "icon" in own ? (icon ? [icon] : []) : type.icons,
    markPick: mark === null ? null : (MARK_SHAPE_IDS.includes(mark) ? mark : "")
  };
}

/**
 * Tvar štítka s číslom cesty pre jednu triedu, aj s tým, čo naň prepísal
 * developer mode.
 *
 * Prepnúť sa dá preto, že sprite nesie všetky tvary naraz – v prehliadači sa
 * mení len meno obrázka. Neznámy tvar sa ticho ignoruje: obrázok, ktorý
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

/**
 * Prázdna sada úprav z developer módu.
 *
 * `layers` a `poi` platia pre všetky typy máp, `maps[<typ>]` len pre jeden –
 * takže sa dá povedať aj „táto farba všade", aj „na cestnej mape toto nechcem".
 */
export function emptyOverrides() {
  return {
    version: 2,
    icons: DEFAULT_ICON_SOURCE,
    hillshade: false,
    palette: {},
    layers: {},
    // zoznam presunov „kresli tesne pod tamtú" – viď `applyLayerOrder`
    order: [],
    // trasy majú vlastnú položku: jeden druh má v štýle tri vrstvy a odstup
    // od cesty je vlastnosť všetkých naraz
    trails: { gap: {}, types: {}, marks: {} },
    // štítok je tvar obrázka zo spritu, nie `paint` vlastnosť jednej vrstvy
    shields: {},
    // sada je „iné ikony na všetko", vlastná ikona „túto jednu vec inak"
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
 * „Bez výplne" – plocha, ktorá nemá farbu pozadia, ale ostane jej vzor aj okraj.
 *
 * Nie `krytie 0`: `fill-opacity` násobí všetko, čo vrstva kreslí, teda aj obrys
 * z `fill-outline-color` – nulou by z budovy zmizla aj jej hrana. Priehľadná
 * farba vypne len výplň. A nie je to ani `visible: false`: tým by zmizla celá
 * vrstva vrátane vzoru, ktorý na nej visí.
 *
 * V súbore úprav je to čitateľné slovo, nie `#00000000`, aby bolo jasné, že je
 * to zámer.
 */
export const NO_FILL = "none";
/** Kde má „bez výplne" zmysel – čiara sa vypína cez `visible`, nie farbou. */
const NO_FILL_PROPS = new Set(["fill-color", "fill-extrusion-color"]);
/** Strop počtu zoomových zlomov na jednu vlastnosť. */
export const MAX_PAINT_STOPS = 8;

/**
 * Vlastnosti z `layout`, ktoré sa dajú prepísať – a ich medze.
 *
 * `paint` je „ako to vyzerá", `layout` „ako to je rozložené", a MapLibre ich
 * drží zvlášť: veľkosť ikony ani rozostup symbolov po čiare v `paint` nie sú.
 * Práve tie dve pritom rozhodujú, ako husto sedia značky po trase.
 *
 * Je to vymenovaný zoznam, nie „čokoľvek z layoutu": `symbol-placement` je
 * rozhodnutie štýlu, nie ladenie.
 *
 * Všetky sú zo symbolovej vrstvy – neznáma vlastnosť v `layout` je tvrdá
 * chyba a MapLibre by odmietol celý štýl, takže `applyLayerOverrides` ich
 * inde než na `symbol` nenasadí.
 *
 * `def` je predvoľba MapLibre, teda to, čo platí, keď vlastnosť v štýle nie je.
 * Bez nej sa dala vlastnosť len zmeniť, nie zaviesť. Čísla sú zo style-spec.
 */
export const LAYOUT_PROPS = {
  "icon-size": { min: 0.05, max: 8, step: 0.05, def: 1, label: "veľkosť ikony" },
  "symbol-spacing": { min: 1, max: 2000, step: 5, def: 250, label: "rozostup po čiare" },
  "icon-padding": { min: 0, max: 40, step: 1, def: 2, label: "miesto okolo ikony" },
  "text-size": { min: 1, max: 60, step: 0.5, def: 16, label: "veľkosť písma" }
};
export const LAYOUT_PROP_IDS = Object.keys(LAYOUT_PROPS);

/**
 * Predvoľby MapLibre pre `paint` čísla – to isté, čo `def` pri `LAYOUT_PROPS`,
 * len pre druhú policu.
 *
 * Vlastnosť, ktorú štýl nenastavil, nie je „nič": `line-opacity` je 1,
 * `text-halo-width` 0. Bez toho nemalo percento nad takou vlastnosťou čo
 * násobiť a úprava sa uložila, v paneli svietila a v mape nespravila nič.
 */
export const PAINT_DEFAULTS = {
  "line-width": 1,
  "line-opacity": 1,
  "fill-opacity": 1,
  "fill-extrusion-opacity": 1,
  "text-opacity": 1,
  "icon-opacity": 1,
  "text-halo-width": 0,
  "icon-halo-width": 0,
  "circle-stroke-width": 0,
  "hillshade-exaggeration": 0.5
};

/**
 * Zoradí zoomové zlomy podľa zoomu. Jedna funkcia pre všetky tri cesty, ktoré
 * ich vyrábajú (import, developer mode, skladanie štýlu).
 *
 * `interpolate` vyžaduje stopy v striktne rastúcom poradí a MapLibre pri
 * porušení odmietne celý štýl, nie len tú vlastnosť. V paneli pritom zlomy
 * vznikajú v poradí, v akom ich niekto naklikal – nezoradené je normálny stav.
 */
export const sortStops = (list) => [...list].sort((a, b) => a[0] - b[0]);

/**
 * To isté pre zoomové pásma `[[od, do, hodnota], …]` – zoraďuje sa podľa `od`.
 *
 * Vlastná funkcia, hoci by `sortStops` zoradila to isté: pásmo a zlom sú dva
 * rôzne tvary a jedna funkcia by na oboch spravila to, čo je pravda o jednom.
 */
export const sortBands = (list) => [...list].sort((a, b) => a[0] - b[0]);

/**
 * Je to zoznam pásiem (trojice), alebo zlomov (dvojice)?
 *
 * Rozlišuje sa počtom prvkov v riadku, nie obalom navyše – v JSON súbore úprav
 * je to vidieť bez legendy. Miešať sa nesmú a `cleanPaintZoom` to povie nahlas.
 */
export const isBandList = (list) =>
  Array.isArray(list) && list.length > 0 &&
  list.every((row) => Array.isArray(row) && row.length === 3);

/**
 * Relatívna hodnota `{ "scale": 1.4, "add": 0.5 }` – „nechaj, čo štýl počíta,
 * a preškáluj to".
 *
 * Štvrtý tvar vedľa skaláru, krivky a pásiem: tie tri hovoria „hodnota je
 * takáto", teda zahodia to, čo štýl o vlastnosti vie. „Cesty o štvrtinu
 * hrubšie" sa tak nedalo povedať inak než prepísaním celej krivky ručne.
 *
 * Preto sa nedá zadať „podľa zoomu" – to by boli dve odpovede na tú istú
 * otázku. A len na čísla: `{scale: 1.4}` nad hexom by bola farba, ktorá sa
 * nezmenila.
 */
export const isRelative = (v) =>
  !!v && typeof v === "object" && !Array.isArray(v) &&
  ("scale" in v || "add" in v);

/** Medze relatívnej hodnoty – rovnaké pre `paint` aj `layout`. */
const REL_LIMITS = { scale: [0.1, 10], add: [-20, 40] };

/**
 * Percento v pásme – „na z15–z20 nech je to 110 % toho, čo počíta štýl".
 *
 * Vlastný tvar preto, že `{scale}` nad celou krivkou nevie „až od z15"
 * a pásma s číslom zahodia krivku zo štýlu. Toto je oboje naraz: rozsah
 * zoomov + mierka nad tým, čo v štýle už je.
 */
export const hasRelativeBand = (list) =>
  isBandList(list) && list.some((row) => isRelative(row[2]));

/** Je to hodnota, ktorú formát úprav unesie ako skalár? */
export const isScalarValue = (v) =>
  typeof v === "number" || (typeof v === "string" && v.startsWith("#")) || v === NO_FILL;

/**
 * Hodnota vlastnosti na danom zoome.
 *
 * Pozná číslo, `interpolate` aj `step` podľa zoomu a oba tvary zo súboru úprav.
 * Na výraz podľa atribútu prvku vráti `null` – „to sa jedným číslom povedať
 * nedá" je poctivejšie než vymyslený priemer.
 *
 * Farbu neinterpoluje, vráti spodnú: miešať hex v sRGB by dalo inú farbu, než
 * kreslí MapLibre, a tu ide o to, s čím začať.
 *
 * Je tu, a nie v `layer-style.js`, lebo tú istú odpoveď potrebuje aj skladanie
 * štýlu (percento v pásme sa počíta z toho, čo je na tom zoome v štýle).
 */
export function valueAtZoom(value, zoom) {
  if (isScalarValue(value)) return value;
  if (!Array.isArray(value)) return null;

  // zoomové pásma `[[od, do, hodnota], …]`; pod prvým a nad posledným krajné
  if (isBandList(value)) return bandAt(sortBands(value), zoom);

  // Zoomové zlomy z úprav: `[[zoom, hodnota], …]`.
  if (Array.isArray(value[0])) {
    const stops = sortStops(value.filter((s) => Array.isArray(s) && s.length === 2));
    if (!stops.length) return null;
    return stopsAt(stops, zoom);
  }

  // `step` podľa zoomu – to, čo zo zoomových pásiem vyrobí `paintValue`.
  if (value[0] === "step") {
    const bands = stepToBands(value);
    return bands ? bandAt(bands, zoom) : null;
  }

  if (value[0] !== "interpolate") return null;
  const [, curve, input, ...rest] = value;
  // interpolácia podľa niečoho iného než zoomu sa jedným zoomom nezodpovie
  if (!Array.isArray(input) || input[0] !== "zoom") return null;
  const stops = [];
  for (let i = 0; i + 1 < rest.length; i += 2) {
    if (typeof rest[i] !== "number" || !isScalarValue(rest[i + 1])) return null;
    stops.push([rest[i], rest[i + 1]]);
  }
  if (!stops.length) return null;
  const base = Array.isArray(curve) && curve[0] === "exponential" ? Number(curve[1]) || 1 : 1;
  return stopsAt(stops, zoom, base);
}

/** Hodnota pásma, v ktorom daný zoom leží (krajné pásma platia aj za okraj). */
function bandAt(bands, zoom) {
  if (!bands.length) return null;
  for (const [od, doZ, v] of bands) if (zoom >= od && zoom < doZ + 1) return v;
  return zoom < bands[0][0] ? bands[0][2] : bands[bands.length - 1][2];
}

/**
 * `["step", ["zoom"], v0, z1, v1, …]` → pásma `[[od, do, hodnota], …]`.
 *
 * Prvý výstup platí od z0 a posledný po strop zobrazenia, takže pásma
 * pokrývajú celý rozsah. `null` = nie je to schodisko podľa zoomu.
 */
export function stepToBands(value) {
  const [, input, base, ...rest] = value;
  if (!Array.isArray(input) || input[0] !== "zoom") return null;
  if (!isScalarValue(base)) return null;
  const hranice = [];
  for (let i = 0; i + 1 < rest.length; i += 2) {
    if (typeof rest[i] !== "number" || !isScalarValue(rest[i + 1])) return null;
    hranice.push([rest[i], rest[i + 1]]);
  }
  const bands = [];
  let od = 0;
  let v = base;
  for (const [z, next] of hranice) {
    if (z <= od) return null;
    bands.push([od, z - 1, v]);
    od = z;
    v = next;
  }
  bands.push([od, Math.max(od, MAX_DISPLAY_Z), v]);
  return bands;
}

/** Hodnota medzi zlomami; farby sa nemiešajú (vráti sa spodný zlom). */
function stopsAt(stops, zoom, base = 1) {
  if (zoom <= stops[0][0]) return stops[0][1];
  const last = stops[stops.length - 1];
  if (zoom >= last[0]) return last[1];
  for (let i = 0; i + 1 < stops.length; i += 1) {
    const [z0, v0] = stops[i];
    const [z1, v1] = stops[i + 1];
    if (zoom < z0 || zoom > z1) continue;
    if (typeof v0 !== "number" || typeof v1 !== "number") return v0;
    // rovnaký vzorec ako MapLibre pre `exponential` (base 1 = lineárna)
    const t =
      base === 1
        ? (zoom - z0) / (z1 - z0)
        : (base ** (zoom - z0) - 1) / (base ** (z1 - z0) - 1);
    return Math.round((v0 + (v1 - v0) * t) * 100) / 100;
  }
  return last[1];
}

/**
 * Hodnota z úprav → to, čo ide do štýlu.
 *
 * Skalár ostane skalárom, `none` sa zmení na priehľadnú farbu, pole zlomov na
 * `interpolate` a pole pásiem na `step`. Jeden zlom nie je krivka a jedno
 * pásmo nie je schodisko, takže z nich vyjde obyčajná hodnota.
 *
 * Zoradenie je tu zámerne, hoci ho robí aj import a panel: toto je posledné
 * miesto pred štýlom a jediný nevzostupný pár tu zhodí celú mapu.
 */
export function paintValue(value) {
  if (value === NO_FILL) return "rgba(0,0,0,0)";
  if (!Array.isArray(value)) return value;
  // zoomové pásma → `step`: v pásme konštanta, na hranici skok. Jediné pásmo
  // nie je schodisko, tak z neho vyjde obyčajná hodnota.
  if (isBandList(value)) {
    // percento v pásme potrebuje základ, ktorý pozná až `overrideValue`;
    // objekt v `paint` by MapLibre odmietol aj s celým štýlom
    if (hasRelativeBand(value)) return undefined;
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
 * Úprava nad tým, čo v štýle už je.
 *
 * `paintValue` nestačí, lebo relatívna hodnota potrebuje základ – a ten pozná
 * až miesto, kde je po ruke vrstva.
 *
 * `fallback` je hodnota, ktorú by MapLibre použil, keby vlastnosť v štýle
 * nebola; bez nej by percento nad nenastaveným rozostupom nespravilo nič.
 */
export function overrideValue(base, value, fallback) {
  if (hasRelativeBand(value)) return bandsOverBase(base, value, fallback);
  if (!isRelative(value)) return paintValue(value);
  const z = base === undefined ? fallback : base;
  if (z === undefined) return undefined;
  return scaleExpr(z, value);
}

/**
 * Pásma s percentom → jedna krivka podľa zoomu.
 *
 * Percento v pásme sa jedným `step` ani `interpolate` nad pôvodnou krivkou
 * povedať nedá: `["zoom"]` smie byť len priamym vstupom najvrchnejšieho
 * výrazu. Preto sa hodnota vyčísli na každom celom zoome.
 *
 * `collapse` z nej vyhodí zlomy na spojnici susedov, takže z nezmeneného
 * úseku ostanú dva body. Na hranici pásiem z toho vyjde prechod cez jeden
 * zoom namiesto skoku – to je zámer.
 *
 * Dátami riadenú hodnotu vyčísliť nemožno; vtedy `undefined`.
 */
function bandsOverBase(base, bands, fallback, apply = relApply) {
  const zaklad = base === undefined ? fallback : base;
  if (zaklad === undefined) return undefined;
  const zoradene = sortBands(bands);
  const stops = [];
  for (let z = 0; z <= MAX_DISPLAY_Z; z += 1) {
    const raw = valueAtZoom(zaklad, z);
    if (typeof raw !== "number") return undefined;
    const band = zoradene.find(([od, doZ]) => z >= od && z <= doZ);
    const v = band ? apply(raw, band[2]) : raw;
    if (!Number.isFinite(v)) return undefined;
    stops.push([z, Math.round(v * 1000) / 1000]);
  }
  const zlomy = collapseStops(stops);
  if (zlomy.length === 1) return zlomy[0][1];
  return ["interpolate", ["linear"], ["zoom"], ...zlomy.flatMap(([z, v]) => [z, v])];
}

/** Čo pásmo robí s hodnotou zo štýlu: percento ju škáluje, číslo ju nahradí. */
const relApply = (raw, v) =>
  isRelative(v) ? raw * (v.scale ?? 1) + (v.add ?? 0) : v;

/** Vyhodí zlomy, ktoré ležia na spojnici susedov – rovná časť nepotrebuje tretí bod. */
function collapseStops(stops) {
  if (stops.every(([, v]) => Math.abs(v - stops[0][1]) <= 0.001)) return [stops[0]];
  const out = [stops[0]];
  for (let i = 1; i + 1 < stops.length; i += 1) {
    const [z0, v0] = out[out.length - 1];
    const [z1, v1] = stops[i];
    const [z2, v2] = stops[i + 1];
    const na = v0 + ((v2 - v0) * (z1 - z0)) / (z2 - z0);
    if (Math.abs(na - v1) > 0.001) out.push(stops[i]);
  }
  out.push(stops[stops.length - 1]);
  return out;
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
  // sila tieňovania je jediná vlastnosť mimo trojice farba/krytie/hrúbka;
  // menuje sa celá, `line-exaggeration` z preklepu by zhodilo celý štýl
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
    // nulová hrúbka čiary je ticho zmiznutá vrstva – šípky číselného políčka
    // ju zhasnú jedným ťuknutím. Vypína sa cez `visible`. Halo a obrys nie:
    // tam nula znamená „žiadny lem".
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
 * Tmavý variant jednej farby (`paintDark`, `outline.colorDark`).
 *
 * Vlastný čistič: tmavý variant pozná len farbu (nikdy krivku, pásma ani
 * percento), takže vlastnosť, ktorá nekončí na „-color", je tu vždy chyba –
 * kým `cleanPaintScalar` na tom istom mene prijme aj krytie či hrúbku.
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
 * Oddelené od `cleanPaintScalar`: `paint` pozná farbu, krytie a hrúbku podľa
 * prípony mena, kým `layout` má vymenovaný zoznam aj s medzami – „rozostup 0"
 * je nekonečne veľa symbolov na čiare a „veľkosť 0" neviditeľná ikona.
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
 * Skontroluje relatívnu hodnotu `{ scale, add }` (rozpis pri `isRelative`).
 *
 * `popis` je meno vlastnosti do hlásenia – pri okraji to nie je `line-width`,
 * ale „šírka okraja", a hláška o vlastnosti, ktorú nikto nenapísal, by
 * hľadanie chyby predĺžila.
 */
function cleanRelative(prop, value, id, problems, where, popis = prop, allowNoop = false) {
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
  // `{scale: 1}` ani `{add: 0}` nie sú úprava. V pásme to platí naopak
  // (`allowNoop`): prvé pásmo JE tá stovka percent, inak sa dolná polovica
  // rozsahu musí prepísať pevnými číslami.
  if ((out.scale ?? 1) === 1 && (out.add ?? 0) === 0) {
    if (allowNoop) return { scale: 1 };
    problems.push(`${kde}: "scale" 1 a "add" 0 nič nemenia – vynechávam.`);
    return undefined;
  }
  return out;
}

/**
 * Jedna hodnota vlastnosti v ktoromkoľvek z tvarov, ktoré úpravy poznajú:
 * relatívna, zoznam podľa zoomu, alebo obyčajný skalár.
 *
 * Jedna brána, lebo tá otázka je jedna a odpovedá sa na ňu na troch miestach.
 * Rozišli by sa ticho – každý tvar je sám o sebe platný vstup toho druhého.
 */
function cleanValue(prop, value, id, problems, where, scalar = cleanPaintScalar, popis) {
  if (isRelative(value)) return cleanRelative(prop, value, id, problems, where, popis);
  if (Array.isArray(value)) return cleanPaintZoom(prop, value, id, problems, where, scalar);
  return scalar(prop, value, id, problems, where);
}

/**
 * Zoznam podľa zoomu – krivka alebo pásma. Jedna brána pre oba tvary.
 *
 * Miešanie je tvrdá chyba: `[[9, 2], [12, 13, 4]]` sa dá prečítať dvoma
 * spôsobmi a ktorúkoľvek stranu by sme uhádli, tá druhá by ticho zmizla.
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
 * Skontroluje pole zoomových pásiem `[[od, do, hodnota], …]`.
 *
 * Pásma musia pokrývať svoj rozsah súvisle (`ďalšie od = predošlé do + 1`).
 * Medzera aj prekryv sú tvrdá chyba: „od 9 do 11" je sľub, že pásmo tam
 * naozaj končí – dopĺňanie medzery predošlou hodnotou by ho zrušilo
 * a prekryv by nechal o jednom zoome rozhodovať dve pásma naraz.
 *
 * Zoomy sú celé čísla; desatina je otázka pre krivku.
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
    // percento v pásme: nie „hodnota JE takáto", ale „to, čo počíta štýl,
    // krát toľkoto" (viď `hasRelativeBand`)
    const v = isRelative(hodnota)
      ? cleanRelative(prop, hodnota, id, problems, where,
                      `${prop} v pásme z${od}–z${doZ}`, true)
      : scalar(prop, hodnota, id, problems, where, ` v pásme z${od}–z${doZ}`);
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
 * Zoomy musia rásť a nesmú sa opakovať: `interpolate` s neusporiadanými stopmi
 * MapLibre odmietne aj s celým štýlom. Namiesto odmietnutia sa zoradia –
 * z panela môžu prísť v poradí, v akom ich niekto naklikal.
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
 * Prečistí (a skontroluje) objekt úprav – tá istá funkcia beží v prehliadači
 * pri importe aj v pipeline pred zápisom, takže sa do repa nedostane nezmysel.
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

  // tieňovanie je defaultne vypnuté: kazí farby plôch a pri malých mierkach šumí
  out.hillshade = raw.hillshade === true;

  // vlastné sady musia byť skôr než výber sady – inak by sa práve pridaná
  // sada tvárila ako neznáma
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
    // sprite je dvojica `<url>.json` + `<url>.png`, tak sa URL zadáva bez prípony
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

  // obrázok sa nesie priamo v úpravách ako `data:` PNG – odkaz na cudzí server
  // by v mape bez internetu nebol ničím a sprite sa skladá pri builde
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

  if (raw.icons != null) {
    const znama = ICON_SOURCE_IDS.includes(raw.icons)
      || out.iconSets.some((s2) => s2.id === raw.icons);
    if (znama) out.icons = raw.icons;
    else problems.push(`Neznáma sada ikoniek "${raw.icons}" – použije sa predvolená.`);
  }

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
      // rovnakú farbu ako má téma netreba zapisovať
      if (value.toLowerCase() === String(THEMES[themeKey][key]).toLowerCase()) continue;
      clean[key] = value.toLowerCase();
    }
    if (Object.keys(clean).length) out.palette[themeKey] = clean;
  }

  // odstupy sú v px pri z16 (TRAIL_GAP_ZOOM); zapisuje sa len odchýlka
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
      // prázdny reťazec je platná odpoveď: „na tejto trase žiadnu ikonu"
      if (icon && !/^[A-Za-z0-9_.:-]{1,64}$/.test(icon)) {
        problems.push(`Trasa "${id}": neplatné meno ikony "${def.icon}".`);
      } else {
        clean.icon = icon;
      }
    }
    if (def.mark != null) {
      const mark = String(def.mark).trim();
      // "" = žiadna značka, meno tvaru = vždy tento; chýbajúci kľúč = ako v OSM
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

  // zapisuje sa len odchýlka od predvoleného
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

  // jeden presun na vrstvu a vyhráva posledný: inak by ich pri opakovanom
  // klikaní pribúdali stovky a nedalo by sa prečítať, kde vrstva skončí
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
    // predvolený tvar netreba zapisovať
    if (shape !== trieda[5]) out.shields[id] = { shape };
  }

  // vlastné ikony sú prečistené vyššie, takže je známe, ktoré vzory sa smú použiť
  const vlastneObrazky = out.customIcons.map((i) => i.name);
  cleanLayers(raw.layers, out.layers, problems, "", vlastneObrazky);

  // to isté id vrstvy môže mať iné nastavenie na turistickej a iné na cestnej mape
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

  const hidden = Array.isArray(raw.poi?.hidden) ? raw.poi.hidden : [];
  out.poi.hidden = [
    ...new Set(hidden.filter((v) => typeof v === "string" && v && v.length < 64))
  ].sort();

  // prázdny reťazec je platná hodnota, tak sa rozhoduje podľa existencie kľúča.
  // Ikony sú spoločné pre všetky typy máp – akou značkou sa kreslí studnička,
  // je vlastnosť kategórie, nie mapy.
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
    // `visible: true` nie je „nič": vrstvu vypnutú profilom treba vedieť vrátiť
    if (typeof def.visible === "boolean") clean.visible = def.visible;
    const mn = def.minzoom == null ? null : clampZoom(def.minzoom);
    const mx = def.maxzoom == null ? null : clampZoom(def.maxzoom);
    if (mn != null) clean.minzoom = mn;
    if (mx != null) clean.maxzoom = mx;
    if (mn != null && mx != null && mx <= mn) {
      problems.push(`${where}Vrstva "${id}": maxzoom (${mx}) musí byť väčší ako minzoom (${mn}).`);
      delete clean.maxzoom;
    }
    // hodnota smie byť skalár, zoznam podľa zoomu (krivka `[[zoom, h], …]`
    // alebo pásma `[[od, do, h], …]`) alebo relatívna úprava `{scale, add}`,
    // ktorá to, čo počíta štýl, len preškáluje. Farba plochy aj `none`.
    const paint = {};
    for (const [prop, value] of Object.entries(def.paint || {})) {
      const clean = cleanValue(prop, value, id, problems, where);
      if (clean !== undefined) paint[prop] = clean;
    }
    if (Object.keys(paint).length) clean.paint = paint;

    // tmavý variant farieb: druhá, nezávislá vrstva nad tou istou vlastnosťou,
    // platná len v téme `tmava`. Počíta sa od tmavého podkladu, nie stlmením
    // svetlej farby – stlmená biela ulica proti tmavému podkladu svieti.
    // Váhu dvojice stráži `workers/lint/overrides.mjs` (bod 4).
    const paintDark = {};
    for (const [prop, value] of Object.entries(def.paintDark || {})) {
      const c = cleanDarkColor(prop, value, id, problems, where);
      if (c !== undefined) paintDark[prop] = c;
    }
    if (Object.keys(paintDark).length) clean.paintDark = paintDark;

    // rozloženie: ten istý tvar hodnoty ako `paint`, len iný čistič skalárov
    const layout = {};
    for (const [prop, value] of Object.entries(def.layout || {})) {
      const c = cleanValue(prop, value, id, problems, where, cleanLayoutScalar);
      if (c !== undefined) layout[prop] = c;
    }
    if (Object.keys(layout).length) clean.layout = layout;

    // tu len tvar mena; či ikona v sprite je, rieši `applyLayerOverrides`
    if (def.icon != null) {
      const icon = String(def.icon).trim();
      if (!/^[A-Za-z0-9_.:-]{1,64}$/.test(icon)) {
        problems.push(`${where}Vrstva "${id}": neplatné meno ikony "${def.icon}".`);
      } else {
        clean.icon = icon;
      }
    }

    // aj „solid" je úprava: prerušovanie zabudované v štýle sa musí dať vypnúť.
    // Zapisuje sa len vtedy, keď ho vrstva naozaj má (`frico:dash`).
    if (def.dash != null) {
      if (!DASH_IDS.includes(def.dash)) {
        problems.push(`${where}Vrstva "${id}": neznámy vzor čiary "${def.dash}".`);
      } else {
        clean.dash = def.dash;
      }
    }

    // `null` nie je „nič": zabudovaný vzor (`frico:pattern`) sa musí dať vypnúť.
    // Chýbajúci kľúč = „nechaj, čo je v štýle".
    if (def.pattern === null) {
      clean.pattern = null;
    } else if (def.pattern?.image) {
      // vlastný obrázok ako vzor musí byť vlastná ikona z týchto úprav – inú
      // by pipeline nedopiekla do spritu a MapLibre ju ticho preskočí
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

    if (def.outline) {
      // šírka okraja pozná tie isté tvary ako hrúbka čiary; čo z ktorého vyjde,
      // rozhoduje `outlineWidth` – tam je vidieť druh vrstvy
      const width = cleanValue(
        "line-width", def.outline.width, id, problems, where,
        outlineWidthScalar, "šírka okraja"
      );
      if (!isColor(def.outline.color)) {
        problems.push(`${where}Vrstva "${id}": farba okraja nie je hex (${def.outline.color}).`);
      } else if (width === undefined) {
        // dôvod už povedal `cleanValue`
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
        // tmavý variant okraja – to isté ako `paintDark`, len na odvodenej vrstve
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
 * `attr` je meno tagu z dlaždice, takže sa kontroluje len tvar. Vymyslený
 * atribút nič nezhodí: `str()` z neho spraví `""`, variant sa netrafí
 * a všetko ostane v predlohe.
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
    // dva varianty nad tou istou hodnotou sa nakreslia oba, cez seba
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
 * platia len preň. Vracia objekt v tvare, aký očakáva zvyšok generátora.
 *
 * Vlastnosť z konkrétnej mapy prebije spoločnú; `paint` sa mieša po
 * vlastnostiach, aby sa dala prepísať len jedna farba.
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
          // bez toho by mapová výnimka prepísala aj tmavé farby zo spoločnej úpravy
          ...(base.paintDark || def.paintDark
            ? { paintDark: { ...(base.paintDark || {}), ...(def.paintDark || {}) } }
            : {}),
          // `layout` sa mieša po vlastnostiach, inak by mapa zahodila, čo v ňom nie je
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
      // ikony kategórií sú spoločné pre všetky mapy, len sa nesmú stratiť
      icons: { ...(overrides.poi?.icons || {}) }
    }
  };
}

export { ICON_SOURCES, ICON_SOURCE_IDS, DEFAULT_ICON_SOURCE } from "./icon-sources.js";

/** Vybraná sada ikoniek (z úprav, inak predvolená). */
export function selectedIconSource(overrides) {
  const id = overrides?.icons;
  // aj vlastná sada je platná odpoveď – inak by sa dala pridať, ale nie zapnúť
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
 * Obrázok leží priamo v úpravách, takže sa nesie všade, kde sa nesú ony.
 * 64 kB je pri 64 × 64 px veľkorysé a dvadsať ikon sa do repozitára aj do
 * atlasu zmestí bez toho, aby si to niekto všimol.
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
 * Preškáluje číslo podľa zoomu (`v × scale + add`) aj vtedy, keď je zadané
 * krivkou alebo pásmami. Aritmetika sa robí na jednotlivých stopoch, nie
 * výrazom nad hotovou hodnotou: `["zoom"]` smie byť len priamym vstupom
 * najvrchnejšieho `interpolate`/`step`, takže obal navyše by MapLibre odmietol.
 *
 * Násobenie, nie len pripočítanie: konštanta mení pomer na každom zoome inak
 * (`+3` je pri z4 nad čiarou 0,5 px sedemnásobok, pri z20 nad 60 px päť
 * percent). Percento drží pomer všade, konštanta sa hodí na jemný doplnok.
 *
 * Pásma (`step`) sú tu zámerne: kým to vedela len krivka, dostal okraj nad
 * pásmovou čiarou výraz nezmenený, čiže bol presne taký široký ako čiara.
 *
 * Výraz, ktorý nie je ani jedno (`match` nad dátami), sa vráti tak, ako
 * prišiel – prepisovať dátami riadenú hodnotu naslepo je tichá zmena mapy.
 */
export function scaleExpr(expr, rel) {
  const { scale = 1, add = 0 } = rel || {};
  // `0.5 * 1.4` je v plávajúcej čiarke `0.7000000000000001`
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
  // `["step", <vstup>, <hodnota pod prvým zlomom>, z1, v1, …]` – prvý výstup inde
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
  // odvodená vrstva má prerušovanie vlastné, zdedené `frico:dash` by klamalo
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
 * Prerušovanie, ktoré má vrstva zabudované v štýle – to, na čo sa dá vrátiť.
 * Vracia predvoľbu, rovno pole čísel, alebo `"solid"` pri plnej čiare.
 *
 * Číta sa z metadát, nie z `paint`: panel dostáva štýl, na ktorom už úprava
 * sedí. Bez toho ukazoval výber pri každej čiare „Plná".
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
 * Šírka okraja – z tvaru, ktorý prišiel v úprave, a z druhu vrstvy.
 *
 * Plocha nemá vlastnú hrúbku, takže okraj je samostatná čiara a jeho šírka je
 * absolútna; dávajú tam zmysel všetky tvary vrátane krivky a pásiem.
 *
 * Čiara hrúbku má, takže okraj je casing pod ňou a počíta sa od nej: skalár
 * `w` znamená „`w` px na každej strane", relatívna úprava „toľkokrát hrubší".
 *
 * Krivka ani pásma sa k šírke čiary pripočítať nedajú („výraz + výraz" nad
 * `["zoom"]` MapLibre nepozná), takže sú tam absolútnou šírkou casingu.
 */
function outlineWidth(layer, width) {
  // Pri ploche nie je čo škálovať, takže základ relatívnej úpravy je 1 px.
  const base = layer.type === "line" ? layer.paint["line-width"] : null;
  if (isRelative(width)) return scaleExpr(base ?? 1, width);
  // pásma s percentom sa vyčíslia nad hrúbkou čiary (viď `bandsOverBase`);
  // percento je „toľkokrát hrubší než čiara", číslo „toľko px na každej strane"
  if (hasRelativeBand(width)) {
    return bandsOverBase(base ?? 1, width, 1, (raw, v) =>
      isRelative(v)
        ? raw * (v.scale ?? 1) + (v.add ?? 0)
        : base == null
          ? v
          : raw + v * 2);
  }
  const val = paintValue(width);
  if (base == null || typeof val !== "number") return val;
  return scaleExpr(base, { add: val * 2 });
}

/**
 * Rozlíšenie podľa atribútu OSM – „nespevnená poľná cesta bodkovane,
 * spevnená plnou čiarou s obrysom".
 *
 * Dovtedy sa taká otázka dala zodpovedať len ďalšou `add(...)` v zdrojáku,
 * teda commitom a buildom – pritom ktoré hodnoty `surface` ešte znamenajú
 * „dá sa tadiaľ ísť autom" je otázka na kraj.
 *
 * Prvok sa smie nakresliť raz: variant dostane filter predlohy a test
 * atribútu, predloha si k svojmu filtru pridá negáciu toho testu. Bez toho
 * druhého by sa čiara kreslila dvakrát cez seba.
 *
 * Prvok bez toho atribútu ostáva v predlohe: `str()` z chýbajúceho tagu spraví
 * `""`. „Nevieme, aký je povrch" nie je to isté ako „je nespevnený".
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
      const nv = overrideValue(vrstva.paint[prop], value, PAINT_DEFAULTS[prop]);
      if (nv !== undefined) vrstva.paint[prop] = nv;
    }
    if (v.layout && layer.type === "symbol") {
      vrstva.layout = { ...(vrstva.layout || {}) };
      for (const [prop, value] of Object.entries(v.layout)) {
        const nv = overrideValue(vrstva.layout[prop], value, LAYOUT_PROPS[prop]?.def);
        if (nv !== undefined) vrstva.layout[prop] = nv;
      }
    }
    // „plná" nie je „nič" – rovnaká úvaha ako pri úprave vrstvy
    if (v.dash && layer.type === "line") {
      const arr = dashArray(v.dash);
      if (arr) vrstva.paint["line-dasharray"] = arr;
      else delete vrstva.paint["line-dasharray"];
    }
    if (v.icon && layer.type === "symbol" && hasIcon(v.icon)) {
      vrstva.layout = { ...(vrstva.layout || {}), "icon-image": v.icon };
    }
    // obrys variantu sa hlási ku koreňu, inak by ho presun poradia nechal stáť
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
 *        ktorú sada nemá, sa nenastaví – chýbajúci obrázok znamená
 *        nevykreslený symbol a v pipeline zhodí kontrolu štýlu.
 * @param {string} [theme] kľúč témy – rozhoduje, či sa nad `paint` uplatní aj
 *        tmavý variant. Bez neho sa tmavý variant nikdy nepoužije.
 */
function applyLayerOverrides(style, layerOverrides, hasIcon = () => true, theme) {
  if (!layerOverrides) return style;
  const out = [];

  for (const layer of style.layers) {
    // zabudovaný vzor už jednu vrstvu má; poskladá sa znova z účinného predpisu,
    // inak by poistka proti duplicite nechala tú pôvodnú
    if (patternLayerFor(layer) || variantLayerFor(layer)) continue;

    const o = layerOverrides[layer.id];
    // Chýbajúci kľúč = „nechaj vzor zo štýlu", `null` = „vypni ho".
    const builtin = (layer.metadata || {})["frico:pattern"] || null;
    const pat = o && "pattern" in o ? o.pattern : builtin;

    // neznámy `fill-pattern` MapLibre ticho preskočí a plocha ostane bez vzoru
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
    // MapLibre by neplatný rozsah zoomov odmietol
    if (layer.minzoom != null && layer.maxzoom != null && layer.maxzoom <= layer.minzoom) {
      delete layer.maxzoom;
    }
    // `paintValue` rozbalí `none` na priehľadnú a pole zlomov na `interpolate`
    if (o.paint) {
      layer.paint = { ...(layer.paint || {}) };
      for (const [prop, value] of Object.entries(o.paint)) {
        // vlastnosť, ktorú štýl nenastavil, má predvoľbu MapLibre; `undefined`
        // v `paint` by MapLibre odmietol aj s celým štýlom
        const v = overrideValue(layer.paint[prop], value, PAINT_DEFAULTS[prop]);
        if (v !== undefined) layer.paint[prop] = v;
      }
    }
    // tmavý variant je vždy jedna farba, tak ide rovno na vrstvu
    if (theme === "tmava" && o.paintDark) {
      layer.paint = { ...(layer.paint || {}) };
      for (const [prop, value] of Object.entries(o.paintDark)) {
        layer.paint[prop] = paintValue(value);
      }
    }
    // `layout` len na symbolovej vrstve: `icon-size` na čiare zhodí celý štýl
    if (o.layout && layer.type === "symbol") {
      layer.layout = { ...(layer.layout || {}) };
      for (const [prop, value] of Object.entries(o.layout)) {
        // základom je predvoľba MapLibre, nie nič (viď `overrideValue`)
        const v = overrideValue(layer.layout[prop], value, LAYOUT_PROPS[prop]?.def);
        if (v !== undefined) layer.layout[prop] = v;
      }
    }
    // „plná" znamená vlastnosť zmazať: `line-dasharray: null` by MapLibre neprijal
    if (o.dash && layer.type === "line") {
      layer.paint = { ...(layer.paint || {}) };
      const arr = dashArray(o.dash);
      if (arr) layer.paint["line-dasharray"] = arr;
      else delete layer.paint["line-dasharray"];
    }

    // variant vzniká z vrstvy, na ktorej už sedí jej úprava; predloha si
    // k filtru pridá negáciu – viď `variantLayers`
    const varianty = (o.variants || []).length
      ? variantLayers(layer, o.variants, hasIcon)
      : [];
    if (varianty.length) {
      const nie = ["!", variantTest(o.variants)];
      layer.filter = layer.filter ? ["all", layer.filter, nie] : nie;
    }

    // okraj čiary ide pod ňu, okraj plochy a vzor nad ňu; tmavá farba okraja
    // sa rieši tu, pred `outlineLayer`
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

  // MapLibre by štýl s duplicitným id odmietol
  const seen = new Set();
  style.layers = out.filter((l) => {
    if (seen.has(l.id)) return false;
    seen.add(l.id);
    return true;
  });
  return style;
}

/**
 * Poradie kreslenia: presuny „túto vrstvu kresli tesne pod tamtú".
 *
 * MapLibre kreslí vrstvy v poradí, v akom sú v štýle. Čo je nad čím, je
 * rozhodnutie štýlu, ale vidieť ho je až v mape – a kým sa to dalo zmeniť len
 * v zdrojáku, znamenala každá taká otázka commit a build.
 *
 * Formát je zoznam presunov, nie celé poradie: uložiť ~250 id by znamenalo,
 * že sa úpravy ticho rozsypú pri prvej vrstve, ktorá v štýle pribudne alebo
 * zmizne. Presun je odpoveď na jednu otázku a neznámu vrstvu preskočí.
 *
 * Presúva sa celá rodina: vzor aj okraj sú odvodené vrstvy a musia ostať pri
 * predlohe, inak by šrafovanie kreslilo tam, kde plocha už nie je.
 *
 * Maska regiónu ostáva posledná – vrstva za ňou by kreslila aj mimo
 * stiahnutého regiónu. Stráži to `workers/lint/style.mjs`.
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
    // vrstva, ktorú tento štýl nemá, nie je chyba – presun sa netýka ničoho
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
 * Cesty: jeden riadok na triedu, zoradené od najdôležitejšej.
 *
 * `[id, popis, triedy, farba výplne, farba obrysu, stopy šírky, prídavok
 * obrysu, minzoom]`; šírky sú definované až po z20, aby overzoomované
 * dlaždice vyzerali správne.
 *
 * Poradie v tomto poli je poradie dôležitosti, nie kreslenia: navrchu skončí
 * posledná vrstva v štýle, takže sa pridávajú od konca poľa (`roadPass`).
 * Kým sa pridávali v tomto poradí, kreslila sa účelová cesta cez diaľnicu.
 * Je to tichá chyba, tak je na ňu kontrola (`workers/lint/style.mjs`) – toto
 * pole je jej jediný zdroj pravdy a preto je exportované.
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
 * Štítky s číslom cesty – „D1", „R1", „I/18", „II/537".
 *
 * `[id, popis, triedy OSM, kľúč palety podkladu, minzoom, tvar štítka]`
 *
 * Číslo je iná vec než meno a preto je to iná vrstva: meno beží pozdĺž cesty
 * a je unikátne, číslo je značka – opakuje sa, je krátke a človek ho hľadá.
 *
 * Triedy sú z dlaždíc, nie z čísla: rozlíšenie podľa písmena v `ref` je
 * pravidlo o slovenskom číslovaní zapísané v štýle, ktorý sa dá postaviť nad
 * hocijakým regiónom (v Rakúsku je „B1" hlavná cesta, nie rýchlostná).
 *
 * `D` a `R` majú jeden štítok: dve triedy OSM, ale jedna sieť aj jedno
 * značenie – rozlišuje ich samotné číslo.
 *
 * Minzoom je vyšší než pri čiare: štítok má veľkosť v pixeloch, nie
 * v metroch, takže na z4 by ich cez celé Slovensko boli stovky.
 */
// `[id, popis, triedy, farba podkladu, minzoom, tvar, farba čísla, orámovanie]`
//
// Farby sú podľa štítka s číslom cesty, nie podľa smerovej tabule: D/R červená,
// I. trieda modrá, II./III. biela s tmavým číslom. Preto má každý riadok
// vlastnú farbu čísla aj rámika.
/**
 * Sieť európskych ciest v dlaždiciach – hodnota `route_*_network`.
 *
 * `ref` na ceste je číslo národné („D2"); európske („E 65") visí na relácii
 * a OpenMapTiles ho dáva do párov `route_1_network`/`route_1_ref` …
 * `route_6_*`. Poradie nie je zaručené, tak sa prejde všetkých šesť.
 * Ref má medzeru („E 65") – tak sa aj vypíše, tak to má aj tabuľa.
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
  // európska cesta je iné číslo než národné, nie jeho náhrada – kreslia sa
  // obe. Preto sa nefiltruje podľa `class`, ale podľa siete v `route_*`.
  ["euro", "Štítky európskych ciest (E75)", null,
    "shieldEuro", 8, "shield", "shieldText", "shieldBorder", EURO_NETWORK]
];

/**
 * Vygeneruje kompletný MapLibre GL štýl.
 *
 * @param {object} opts
 * @param {string} opts.theme       kľúč témy z THEMES
 * @param {string} opts.tilesUrl    pmtiles:// URL základných dlaždíc
 * @param {string} opts.spriteUrl   absolútna URL spritu (bez prípony)
 * @param {string} opts.glyphsUrl   URL šablóna glyfov {fontstack}/{range}
 * @param {string} [opts.name]      názov štýlu
 * @param {string[]} [opts.icons]   mená ikon dostupných v sprite
 * @param {string} [opts.iconSet]   id sady ikoniek (určuje príponu mien)
 * @param {object} [opts.fonts]     {regular, bold, italic}
 * @param {number} [opts.maxzoom]   najvyšší zoom dlaždíc (default MAX_TILE_Z)
 * @param {string} [opts.contoursUrl] pmtiles:// URL s vrstevnicami
 * @param {number} [opts.contoursMaxzoom]
 * @param {string} [opts.trailsUrl]   pmtiles:// URL so značenými trasami
 * @param {number} [opts.trailsMaxzoom]
 * @param {string} [opts.featuresUrl] krajinné prvky (línie a plochy), ktoré
 *                                    schéma OpenMapTiles nemá
 * @param {number} [opts.featuresMaxzoom]
 * @param {string} [opts.pointsUrl]   body v krajine – druhý výstup toho istého
 *                                    jobu ako `featuresUrl`
 * @param {number} [opts.pointsMaxzoom]
 * @param {string} [opts.transportUrl] dopravná sieť (balík `cesty`); štýl z nej
 *                                    kreslí len obmedzenia na ceste
 * @param {number} [opts.transportMaxzoom]
 * @param {string} [opts.demSource]   zdroj výšok – určuje atribúciu
 * @param {string|null} [opts.demTiles] raster-dem dlaždice (null = bez nich)
 * @param {string} [opts.demTilesSource] zdroj výšok pre tie dlaždice; nemusí
 *                                    to byť ten istý model ako pri vrstevniciach
 * @param {number} [opts.demMaxzoom]
 * @param {number[]|null} [opts.demBounds] kde vlastné výškové dlaždice sú –
 *                                    pri rýchlom teste je to pár km²
 * @param {object|string|null} [opts.regionOutline] hranica regiónu (dáta alebo
 *                                    URL); za ňou štýl nekreslí nič
 * @param {boolean} [opts.hillshade]  tieňovanie reliéfu (default nie)
 * @param {boolean} [opts.terrain3d]  3D z tých istých dlaždíc (default nie)
 * @param {number} [opts.terrainExaggeration] násobok prevýšenia (default 1.3)
 * @param {boolean} [opts.sdfIcons]   sprite je SDF – ikonám sa dá dať farba
 * @param {string} [opts.mapType]     typ mapy – určuje, ktoré vrstvy sa kreslia
 * @param {object|null} [opts.overrides] úpravy z developer módu
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
  transportUrl = null,
  transportMaxzoom = 14,
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
  // typ mapy určuje profil aj to, ktoré úpravy platia
  const mapTypeId = normalizeMapType(mapType);
  const overrides = resolveOverrides(rawOverrides, mapTypeId);
  // Tieňovanie reliéfu je vypnuté, kým ho niekto výslovne nezapne.
  const showHillshade = hillshade === null ? overrides?.hillshade === true : hillshade === true;
  // bez zdroja `dem` by `terrain` ukazoval na nič a MapLibre by ho odmietol
  const show3d = terrain3d === true && Boolean(demTiles);
  const c = mergedPalette(theme, overrides);
  // sada ikoniek určuje, ako sa mená skladajú (osm-liberty používa `_11`)
  const iconSetId = iconSet || selectedIconSource(overrides);
  const { suffix } = iconSourceIn(iconSetId, overrides);
  const SPECIAL = specialIcons(iconSetId, overrides);

  const f = { ...DEFAULT_FONTS, ...(fonts || {}) };
  const REG = [f.regular];
  const BOLD = [f.bold];
  const ITAL = [f.italic];

  const iconClasses = iconClassesOf(icons, suffix);
  // vlastná ikona je „v sprite" aj vtedy, keď v ňom ešte nie je: mapa ju má
  // hneď (`map.addImage`) a do spritu ju pri builde dopečie pipeline
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
        // vyššie zoomy MapLibre dopočíta overzoomom až po MAX_DISPLAY_Z
        maxzoom,
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> prispievatelia'
      }
    },
    sprite: spriteUrl,
    glyphs: glyphsUrl,
    layers: []
  };

  // vrstevnice sú samostatný .pmtiles – závisia len od územia, nie od OSM
  if (contoursUrl) {
    style.sources.contours = {
      type: "vector",
      url: contoursUrl,
      maxzoom: contoursMaxzoom,
      attribution: (DEM_SOURCES[demSource] || DEM_SOURCES[DEFAULT_DEM_SOURCE])
        .attribution
    };
  }
  // skaly majú oddelený .pmtiles kvôli maxzoomu: vrstevnice minú rozpočet
  // okolo z14, skaly sa do z16 zmestia. Nad `maxzoom` sa naťahujú overzoomom.
  if (rocksUrl) {
    style.sources.rocks = {
      type: "vector",
      url: rocksUrl,
      maxzoom: rocksMaxzoom,
      attribution: (DEM_SOURCES[demSource] || DEM_SOURCES[DEFAULT_DEM_SOURCE])
        .attribution
    };
  }
  // značené trasy sú `type=route` relácie, ktoré schéma OpenMapTiles nepozná
  if (trailsUrl) {
    style.sources.trails = {
      type: "vector",
      url: trailsUrl,
      maxzoom: trailsMaxzoom,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> prispievatelia'
    };
  }
  // krajinné prvky mimo schémy: násypy, zárezy, múry, ploty, vedenia,
  // prieseky, parkoviská, zjazdovky (workers/features/features.yml)
  if (featuresUrl) {
    style.sources.features = {
      type: "vector",
      url: featuresUrl,
      maxzoom: featuresMaxzoom,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> prispievatelia'
    };
  }
  // body v krajine – druhý výstup toho istého jobu, vlastný .pmtiles kvôli
  // balíku „body" na stiahnutie zvlášť
  if (pointsUrl) {
    style.sources.points = {
      type: "vector",
      url: pointsUrl,
      maxzoom: pointsMaxzoom,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> prispievatelia'
    };
  }
  // dopravná sieť (balík `cesty`): štýl z nej kreslí len obmedzenia na ceste
  // (výška, šírka, hmotnosť, rýchlosť). Čiary ciest sú v základnej mape.
  if (transportUrl) {
    style.sources.transport = {
      type: "vector",
      url: transportUrl,
      maxzoom: transportMaxzoom,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> prispievatelia'
    };
  }
  // raster DEM pre tieňovanie a 3D. Atribúcia ide podľa `demTilesSource` –
  // vrstevnice môžu byť z iného modelu. Bez vlastných sa padá na AWS.
  if (demTiles) {
    const ownDem = demTiles !== DEFAULT_DEM_TILES;
    const tilesSource = demTilesSource || demSource;
    // vlastné dlaždice chodia ako jeden `.pmtiles`, verejné AWS ako šablóna;
    // rozlišuje to protokol, nie druhý prepínač
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
    // vlastné dlaždice nemusia pokrývať celú mapu (rýchly test), `bounds`
    // hovorí MapLibre, kde ich má pýtať. Pri `.pmtiles` sa nedopisuje –
    // rozsah aj zoomy si archív nesie v hlavičke.
    if (ownDem && !demIsArchive
        && Array.isArray(demBounds) && demBounds.length === 4) {
      style.sources.dem.bounds = demBounds.map(Number);
    }
    // 3D terén patrí do štýlu podľa špecifikácie, nech si ho každý klient
    // zapne sám – nielen web cez `map.setTerrain`
    if (show3d) {
      style.terrain = {
        source: "dem",
        exaggeration: Number(terrainExaggeration) || DEFAULT_TERRAIN_EXAGGERATION
      };
    }
  }

  // hranica stiahnutého regiónu: dlaždice vznikajú celé a Planetiler do nich
  // kreslí celosvetové vodstvo, takže mapa inak pokračuje do prázdna.
  // Súbor robí `workers/deploy/region-mask.py` z toho istého `.poly` ako PBF.
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
   * `paletteExtra` sú kľúče palety, ktoré vrstva používa vo výraze (farba
   * pásika trasy sa vyberá podľa značky z OSM) – taká farba nie je v `paint`
   * obyčajným hexom, takže by ju panel v riadku vrstvy nenašiel.
   *
   * `pattern` je vzor zabudovaný v štýle. Vzor sa nedá nakresliť do tej istej
   * vrstvy ako výplň, takže z neho vzniká vrstva navyše hneď nad predlohou;
   * predpis ostáva v metadátach, aby ho panel vedel ukázať a vypnúť.
   *
   * @param {object} layer  vrstva podľa MapLibre style-spec
   * @param {[string,string,string,object?,string[]?,object?]} meta
   *        [skupina, popis, druh, {paintProp: kľúč palety},
   *         [kľúče palety vo výrazoch], {id,color,size,weight,opacity},
   *         id vrstvy, ktorú táto obťahuje]
   *
   * Posledná položka je `frico:border-of`: obrys je vlastná vrstva, ale nie
   * samostatná vec – jeho hrúbka aj viditeľnosť sa čítajú od čiary, ktorú
   * obťahuje.
   */
  const add = (layer, meta) => {
    const [group, label, kind, palette, paletteExtra, pattern, borderOf] = meta;
    const l = { ...layer };
    if (l.type !== "background" && !l.source) l.source = "omt";
    const pat = pattern ? patternDef(pattern) : null;
    // zabudované prerušovanie do metadát: panel dostáva štýl, na ktorom už
    // úpravy sedia, takže „aké to bolo pôvodne" sa z `paint` prečítať nedá.
    // Ukladá sa predvoľba, a keď žiadna nesedí, rovno to pole čísel.
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
        : {}),
      ...(borderOf ? { "frico:border-of": borderOf } : {})
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
   * Niektoré prvky sú v štýle dve vrstvy (hrana so zúbkami, železnica). Pri
   * farbe a hrúbke sa ladia zvlášť, ale poradie kreslenia je pri nich jedna
   * otázka – inak by ostali zúbky nad cestou a hrana pod ňou.
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

  // krajinná pokrývka: schéma zlieva do `class=grass` všetko od lúky po
  // kosodrevinu, rozlíši to len `subclass`. Poradie je poradím kreslenia.
  const landcover = [
    ["wood", "Les", ["wood", "forest"], "forest", 0.9],
    ["grass", "Tráva a lúky", ["grass", "grassland", "meadow"], "grass", 0.7],
    // v dlaždiciach majú `class=grass`; v Tatrách je to rozdiel medzi
    // „dá sa prejsť" a „nedá"
    ["scrub", "Kroviny a kosodrevina", ["scrub", "shrubbery", "heath", "fell", "tundra"], "scrub", 0.85],
    ["farmland", "Polia", ["farmland"], "grass", 0.45],
    // boli vo vrstve `landuse`, kde ich schéma nikdy nemá
    ["garden", "Záhrady a sady", ["garden", "allotments", "orchard", "vineyard", "plant_nursery"], "garden", 0.8],
    ["golf", "Golfové ihriská", ["golf_course", "recreation_ground", "village_green"], "pitch", 0.6],
    ["wetland", "Mokrade", ["wetland", "swamp", "marsh", "bog"], "wetland", 0.8],
    // suť má vzor drobných kameňov – plná farba nepovie rozdiel medzi suťou
    // a lúkou. Dlaždica sa zadáva v pixeloch obrazovky, takže sa vzor so
    // zoomom nezväčšuje; 26 px vyzeralo ako dlažba. Počítané skalné plochy
    // z DEM vzor zámerne nemajú: to je stena, nie sypké kamene.
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
      // farba vzoru je kľúč palety, nie hex – nech ju má každá téma svoju
      ["krajina", label, "area", { "fill-color": paletteKey }, null,
        pattern ? { ...pattern, color: c[pattern.color] } : null]
    );
  }

  // využitie územia: presne tie triedy, ktoré schéma naozaj vydáva (26 hodnôt,
  // Tables.java: osm_landuse_polygon)
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
    // `waterway=dam` ako plocha; v dlaždiciach je od začiatku, štýl ho nekreslil
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

  // plochy z vlastných dlaždíc: schéma ich ako plochu nemá vôbec. Kreslia sa
  // hneď za `landuse` – patria k tomu istému, čo sa s územím robí.
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

    // zjazdovky: vleky v dlaždiciach sú, trate nie (`piste:type` schéma nepozná).
    // Plocha aj os sú tá istá vrstva, preto `polygonOnly` – inak by výplň
    // dostala aj os a MapLibre z nej earcutom vyrobí nezmysel.
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
      // vrstva `park` nesie aj bod pre popisok, nie len obrys
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

  // skalné plochy sú tesne pod tieňovaním, nie pri vrstevniciach: skala je tvar
  // terénu. Nad tieňovaním by z nej bola plochá škvrna bez reliéfu.
  // Jedna vrstva, jedna sivohnedá, bez priehľadnosti – priehľadnosťou je vidieť
  // každý prekryv, takže by sa plochy museli zlepovať a strážiť proti sebe.
  if (rocksUrl) {
    add(
      {
        id: "rock-area",
        type: "fill",
        source: "rocks",
        "source-layer": "rock",
        // od z11: na prehľadovej mierke je zo skál len sivá škvrna a dlaždice
        // s ňou sa aj tak sťahujú
        minzoom: TERRAIN_MIN_Z,
        paint: {
          "fill-color": c.rockArea,
          "fill-opacity": 1,
          // hrana plochy má byť hladká; s plnou farbou to nerobí prekryv navyše
          "fill-antialias": true
        }
      },
      // bez vzoru, na rozdiel od suti: táto plocha je počítaná zo sklonu, teda
      // stena a bralo. Kamienky kreslí `landcover-rock` (scree z OSM).
      ["vrstevnice", "Skalné plochy", "area", { "fill-color": "rockArea" }]
    );
  }

  // tieňovanie ide nad krajinnú pokrývku a skaly, ale pod vodu. Zdroj `dem`
  // ostáva v štýle aj pri vypnutom tieňovaní – žije z neho 3D terén.
  if (demTiles && showHillshade) {
    add(
      {
        id: "hillshade",
        type: "hillshade",
        source: "dem",
        paint: {
          // 315° je kartografická konvencia; predvolených 335° osvetľovalo
          // severné svahy skoro kolmo. `map` priväzuje svetlo k terénu – pri
          // `viewport` sa otočením mapy prelieva z jednej strany hrebeňa na druhú.
          "hillshade-illumination-direction": 315,
          "hillshade-illumination-anchor": "map",
          // sila rastie so zoomom, nie naopak: krivka tu roky klesala, takže
          // práve tam, kde má model najviac detailu, bolo tieňovanie najslabšie.
          // Strop drží alfa farieb, nie táto krivka – s nepriehľadnou farbou
          // nad ~20° sklonu zmizne mapa a ostane samotná farba tieňovania.
          // Stráži to `workers/lint/hillshade.mjs`.
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
      // potoky, priekopy, kanály – detail od z12
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

  // vrstevnice sú nad vodou a pod budovami a cestami, ale nad tieňovaním
  // aj skalami: čiara musí ostať čitateľná aj cez sivú stenu
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

    // triedy sa nezapínajú naraz: od z11 hlavná, od z12 polovičná, od z13
    // základná, a každá sa vynára z nuly (`line-opacity`).
    // Pod `TERRAIN_MIN_Z` nie je ani jedna – na tej mierke je z nich sivý závoj.
    contourLine("minor", "Vrstevnice po 10 m", "minor", 13, [[13, 0.4], [16, 0.7], [20, 1.4]], "contour");
    contourLine("mid", "Vrstevnice po 50 m", "mid", 12, [[12, 0.5], [16, 0.9], [20, 1.8]], "contour");
    contourLine("major", "Vrstevnice po 100 m", "major", TERRAIN_MIN_Z,
                [[TERRAIN_MIN_Z, 0.5], [16, 1.4], [20, 2.6]], "contourMajor");

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
          // `ele` môže z GDALu prísť ako desatinné číslo
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
   * Hrana so zúbkami – bralo, násyp, zárez. Kolmé čiarky MapLibre nevie, tak
   * sa robia druhou čiarou: širokou, prerušovanou a odsunutou nabok, z čoho
   * ostanú krátke hrubé kúsky. Kladný offset je vpravo v smere čiary a presne
   * tam je podľa konvencie OSM dolná strana.
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
          // polovica šírky zúbka: čiara sa dotýka hrany a trčí z nej von
          "line-offset": zl(teeth.map(([z, w]) => [z, w / 2])),
          "line-dasharray": [0.35, 2.2],
          "line-opacity": opacity
        }
      },
      [group, `${label} – zúbky`, "line", { "line-color": paletteKey }]
    );
    spolu(id);
  };

  // bralné hrany a hrebene z OSM – nie skaly z DEM. `natural=cliff/ridge/arete`
  // sú v dlaždiciach ako línie vo vrstve `mountain_peak` (od z13).
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
      // `aeroway` má dráhy ako čiary a odbavovacie plochy ako polygóny
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

  // vrstva `transportation` nesie aj polygóny – pešiu zónu, mólo, teleso mosta.
  // Pozor: `class` na rozlíšenie nestačí, chodníky a mólo sú bežne čiary
  // a MapLibre z nich earcutom vyrobí nezmysel. Preto všade `polygonOnly`.
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
      // `man_made=pier` býva mapované čiarou aspoň tak často ako plochou
      filter: polygonOnly(["==", str("class"), "pier"]),
      paint: { "fill-color": c.pier }
    },
    ["doprava", "Móla (plocha)", "area", { "fill-color": "pier" }]
  );

  // do z16 ploché výplne, nad tým 3D bloky (render_height z OSM)
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
   * V každom sa ide od najmenej dôležitej cesty, teda odzadu `ROAD_DEFS`:
   * navrchu skončí tá pridaná posledná. Kým sa pridávali od diaľnice, kreslila
   * sa účelová cesta cez diaľnicu. To isté platí zvlášť pre obrysy.
   */
  const roadPass = (suffix, passLabel, extraFilter, opts = {}) => {
    const layout = { "line-cap": opts.cap || "round", "line-join": "round" };
    const filterFor = (classes) => [
      "all",
      ["in", str("class"), ["literal", classes]],
      extraFilter
    ];
    const odNajmenejDolezitej = [...ROAD_DEFS].reverse();
    // obrysy idú celé pod výplne, inak by ich prekrývali križovatky
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
        ["cesty", `${label} – obrys${passLabel}`, "line", { "line-color": casingKey },
         null, null, `road-${id}${suffix}`]
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
    // `platform` a `corridor` majú tiež `class=path`
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

  // cesty vo výstavbe: schéma pre ne má vlastné triedy a v dlaždiciach sú od
  // začiatku. Jedna vrstva pre všetky – po tejto ceste sa zatiaľ ísť nedá.
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

  // brody: bez tohto vyzerá brod ako obyčajný úsek cesty
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

  // železnica: plná tmavá čiara a na nej čiarkovaná svetlá. Obe musia byť
  // rovnako široké, inak tmavá po stranách presvitá.
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
      // až od z13: pod ním je čiara užšia než pixel
      minzoom: 13,
      filter: ["in", str("class"), ["literal", ["rail", "transit"]]],
      layout: { "line-cap": "butt" },
      paint: {
        "line-color": c.railHatch,
        "line-width": zw(railWidth),
        // vzor z `patterns.js`, nie číslo tu – to isté ponúka developer mode
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

  // krajinné prvky (línie) z vlastného .pmtiles; nad cestami, lebo násyp
  // aj zárez sú hrany pri ceste
  if (featuresUrl) {
    // násyp klesá od hrany von, zárez stúpa – kreslí sa svetlejšie a jemnejšie
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
      // plánovaná cesta je tu, medzi prvkami, lebo ide z vlastných dlaždíc.
      // Bodkovaná a šedšia než rozostavaná: „stavia sa" proti „je to na papieri".
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

    // farba podľa obťažnosti, tie isté kľúče palety ako pri značkách trás
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

  // trasa nie je cesta: `type=route` relácia so značením, v dlaždiciach
  // OpenMapTiles po nej nezostane stopa. Kreslí sa ako farebný pásik vedľa
  // cesty; pruh (`side` + `off`) prichádza z dát, `line-offset` ho prepočíta
  // na pixely. Pešie trasy idú na jednu stranu, kolesové na druhú.
  if (trailsUrl) {
    // farby značiek idú cez paletu, nie natvrdo z dát
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

    //     line-offset = side × (odstup(po čom vedie) + poradie × rozostup)
    //
    // Odstupy sú dva: pri ceste ide pásik tesne za jej okraj, pri chodníku
    // ostáva jemná medzera. Rozostup dvoch trás je šírka pásika, teda tá istá
    // krivka (`TRAIL_STRIPE`) a tá istá interpolácia – inak by medzi trasami
    // presvital podklad. Čísla sú pixely pri z16.
    const trailGaps = trailGapPx(overrides);
    const scaled = (stops, ref, want) =>
      stops.map(([z, v]) => [z, Math.round(((v * want) / ref) * 100) / 100]);
    const ROAD_STOPS = scaled(TRAIL_OFFSET_ROAD, TRAIL_GAP_DEFAULTS.road, trailGaps.road);
    const PATH_STOPS = scaled(TRAIL_OFFSET_PATH, TRAIL_GAP_DEFAULTS.path, trailGaps.path);
    const PITCH_STOPS = scaled(TRAIL_PITCH, TRAIL_GAP_DEFAULTS.pitch, trailGaps.pitch);

    // `["zoom"]` smie byť len vstupom najvrchnejšieho `interpolate`, tak sa
    // výpočet skladá až vo výstupoch stopov. `exponential 1.5` je to isté, čím
    // sa interpoluje `line-width` – rozostup JE šírka pásika.
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
     * Meno sa skúša aj s príponou sady, aj holé: zo `TRAIL_TYPES` chodia holé
     * mená, z panela meno tak, ako je v sprite. Ikona, ktorú sada nemá, sa
     * nenastaví – v pipeline by zhodila kontrolu štýlu.
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
    // diaľkové trasy sa popisujú prednostne
    const trailSort = [
      "match",
      str("tier"),
      "international", 0,
      "national", 1,
      "regional", 2,
      3
    ];

    // podklad pod všetkými pásikmi: farebná čiara sa cez les a tieňovanie stráca
    add(
      {
        id: "trail-halo",
        type: "line",
        source: "trails",
        "source-layer": "trail",
        minzoom: 11,
        // ten istý spoj ako pásiky nad ním, inak by sa v zákrute rozišli
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
            // tá istá krivka, ktorá je aj rozostupom – pásiky sa dotýkajú vždy
            "line-width": zw(TRAIL_STRIPE),
            "line-offset": trailOffset,
            "line-opacity": zl([[9, 0.75], [13, 0.95]]),
            ...(dashArray(dash) ? { "line-dasharray": dashArray(dash) } : {})
          }
        },
        ["trasy", label, "line", {}, [...MARK_KEYS, paletteKey]]
      );
    }

    // značka, ako je na strome: obrázok zo spritu (`poc/web/marks.js`).
    // Meno obrázka sa skladá z dát (`mark`, `mark_bg`, `mark_fg`), nie zo
    // zoznamu tu. Keď značky v sprite nie sú, vrstva sa nepridá a ostane
    // ikonka druhu trasy – horšie, ale vidieť.
    const marksBaked = hasIcon(markImage("white", "red", DEFAULT_MARK_SHAPE));
    const markPx = trailMarkPx(overrides);
    const markScale = (stops, ref, want) =>
      stops.map(([z, v]) => [z, Math.round(((v * want) / ref) * 1000) / 1000]);
    const markSize = zl(
      markScale(TRAIL_MARK_SIZE, TRAIL_MARK_DEFAULTS.size, markPx.size)
    );
    /** Kreslí sa tomuto druhu značka? („žiadna" z developer módu ju vypne.) */
    const drawsMark = (t) => marksBaked && t.markPick !== "";

    // stĺpik značiek nad čiarou podľa `off` a `side`; záporné `y` je nahor.
    // Vymenované preto, že `icon-offset` je pole a výrazy MapLibre pole
    // počítať nevedia – nad `TRAIL_MARK_STACK_MAX` sa kreslí posledná priečka.
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
    // krok stĺpika je z developer módu, tak ako rozostup a veľkosť značky
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
            // značky dvoch trás sa stavajú nad seba, inak ich kolízia zahodí
            "icon-offset": markOffset,
            // meno obrázka je z dát; `markPick` je „vždy tento tvar"
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
            // značka stojí narovno – natočená podľa cesty by na serpentíne
            // stála na hlave
            "icon-rotation-alignment": "viewport",
            "icon-pitch-alignment": "viewport",
            "icon-padding": TRAIL_MARK_PADDING,
            // stĺpik sa kreslí celý: značky v ňom majú prekryté kolízne
            // obdĺžniky a MapLibre by nechala jedinú
            "icon-allow-overlap": true,
            // poradie v rade rozhodujú dáta (`off`); sort-key je pre značky
            // dvoch rôznych ciest na jednom mieste
            "symbol-sort-key": trailSort
          }
        },
        ["trasy", `${label} – značka`, "point", {}]
      );
    }

    // ikony a popisky až za pásikmi, nech sa čiara nekreslí cez popisok
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
          // ikonka je náhrada, nie druhý symbol: ostáva tam, kde značka nie je
          filter: drawsMark(t)
            ? ["all", ["==", str("route"), id], ["!", ["has", "mark"]]]
            : ["==", str("route"), id],
          layout: {
            "symbol-placement": "line",
            "symbol-spacing": 260,
            "icon-image": icon,
            "icon-size": zl([[13, 0.5], [16, 0.75], [20, 1]]),
            "icon-rotation-alignment": "viewport",
            // ten istý stĺpik ako pri značkách; `off` a `side` sú spoločné,
            // takže si trasa so značkou a bez nej priečku neberú
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
            // popisok sa odsunie nabok, nech neleží na pásikoch
            "text-offset": [0, 0.8],
            "symbol-sort-key": trailSort
          },
          paint: {
            // názov trasy je vo farbe trasy
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

  // štítky s číslom cesty. Idú pred `road-name` zámerne: MapLibre umiestňuje
  // popisky v poradí vrstiev a keď sa nezmestí meno aj číslo, má ostať číslo.
  // Podklad je rozťahovateľný SDF obrázok zo spritu; keď v sprite nie je,
  // číslo sa nakreslí s hrubým halom. Číslo E-cesty nie je v `ref`, tak sa
  // prejdú všetky sloty `route_*_ref`.
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
    // obrázok je upečený na tvar × triedu × tému, farba je v ňom. V sprite sú
    // všetky tvary naraz, takže prepnutie je zmena mena, nie nový sprite.
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
              // `subclass: junction` je mimoúrovňová križovatka a jej `ref` je
              // číslo výjazdu, nie cesty
              ["!=", ["get", "subclass"], "junction"]
            ],
        layout: {
          "symbol-placement": "line",
          // číslo cesty je značka – má sa dať prečítať kdekoľvek na nej
          "symbol-spacing": zl([[7, 170], [12, 190], [16, 230]]),
          "text-field": network ? routeRef(network) : ["get", "ref"],
          "text-font": BOLD,
          "text-size": zl([[7, 9], [12, 10], [16, 12]]),
          "text-rotation-alignment": "viewport",
          "text-pitch-alignment": "viewport",
          "text-padding": 2,
          // E-štítok sedí pod národným: na tom istom úseku sú obe čísla
          ...(network ? { "text-offset": [0, 1.5] } : {}),
          ...(shieldIcon
            ? {
                "icon-image": shieldIcon,
                "icon-text-fit": "both",
                // hore/dole menej, po stranách viac – rovnako miesta na oko
                "icon-text-fit-padding": [3, 7, 3, 7],
                "icon-rotation-alignment": "viewport",
                "icon-pitch-alignment": "viewport"
              }
            : {})
        },
        paint: shieldIcon
          ? {
              // obrázok nie je SDF, farbu má v sebe; zafarbiť sa dá len číslo
              "text-color": c[textKey]
            }
          : {
              // bez obrázka aspoň hrubé halo vo farbe štítka
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

  // obmedzenia na ceste z vlastného .pmtiles. Kreslia sa za štítkami s číslom
  // a pred názvom ulice – poradie vrstiev rozhoduje, kto si vezme miesto.
  // Text je hodnota z OSM bez dopisovanej jednotky: tag ju môže mať v sebe
  // (`3.8 m`) aj byť v stopách. Číslo si parsuje smerovanie samo.
  if (transportUrl) {
    // od z12: obmedzenie výšky rozhoduje, či tam vozidlo prejde
    add(
      {
        id: "road-limit-height",
        type: "symbol",
        source: "transport",
        "source-layer": "transport",
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

    // od z14: tá istá trieda údaja, ale pýta sa na ňu menej ľudí
    add(
      {
        id: "road-limit-mass",
        type: "symbol",
        source: "transport",
        "source-layer": "transport",
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

    // až od z15 a menším písmom: `maxspeed` je takmer na každej ceste
    add(
      {
        id: "road-maxspeed",
        type: "symbol",
        source: "transport",
        "source-layer": "transport",
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

  // súpisné a orientačné čísla – iba na najväčšom detaile
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

  // ikona sa vyberá podľa `subclass`, potom `class`; keď ju sprite nemá,
  // nekreslí sa nič. Ikona z developer módu ide prvá a prázdny reťazec je
  // platná voľba, tak sa rozhoduje podľa existencie kľúča.
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

  // SDF sprite nesie symbol bez kolieska, tak sú ikony o kúsok väčšie
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
  // farba ikon funguje len pri SDF sprite
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

  // skryté POI sa vypnú filtrom, nie zmazaním vrstvy – nech sa dajú vrátiť
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

  // z14–16: len dôležitejšie POI
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
  // z16+: všetko, bez filtra na rank
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

  // body z vlastných dlaždíc (prameň, jaskyňa, rozhľadňa, štôlňa): schéma
  // OpenMapTiles ich nemá – `natural=spring` prejde len ako plocha a
  // `man_made=tower` nepozná vôbec. Vlastný zdroj `points` kvôli balíku „body".
  if (pointsUrl) {
    // tá istá voľba ikony ako pri POI: otázka je jedna, dve odpovede by sa rozišli
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
        // skryté kategórie platia aj tu – zoznam v paneli je jeden
        ...(poiFilter(null) ? { filter: poiFilter(null) } : {}),
        layout: {
          ...poiLayout,
          "icon-image": featureIcon,
          // výška patrí k prameňu aj k rozhľadni
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

  // tematické body: hrady na historickej mape, vleky na lyžiarskej, pumpy na
  // cestnej. Samostatné vrstvy, nech sa dajú zapnúť skôr než ostatné POI;
  // profil typu mapy ich zapína, inde sú vypnuté.
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
          // nižší kľúč = umiestňuje sa skôr
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
      // von idú všetky triedy, čo prídu ako línia – hrebeň, areta aj bralo;
      // `cliff` tu chýbal, takže každá hrana dostala trojuholníček vrcholu
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

  // pohoria a oblasti: kurzíva, verzálky a väčšie rozpálenie písmen, nech je
  // vidieť, že ide o územie, nie o obec. Nemajú ikonu ani bod.
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

  // hranica regiónu úplne navrchu: vrstva pridaná za ňu by mimo regiónu opäť
  // kreslila – stráži to `workers/lint/style.mjs`
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

  // najprv profil typu mapy, až potom úpravy – tie musia vedieť profil prebiť
  applyMapType(style, mapTypeId);
  // poradie sa mení nad hotovým štýlom: presúva sa aj vzor a okraj
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
  // plánovaná cesta: z čiary sa nedozvieš, či pôjde o diaľnicu alebo o lesnú
  "feature-road-proposed",
  "piste-line",
  // Značené trasy – po ceste ich vedie viac, popup povie, ktorá je ktorá.
  "trail-hiking",
  "trail-bicycle",
  "trail-mtb",
  "trail-ski",
  "trail-horse"
];
