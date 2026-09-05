/**
 * Typy máp – čo mapa ukazuje (téma rieši, ako to vyzerá).
 *
 * Jedna mapa nemôže byť dobrá turistická aj cestná naraz, tak sa z jedného
 * zoznamu vrstiev vyrába niekoľko máp – každá má profil, teda sadu pravidiel,
 * ktoré vrstvy vypnú, posunú im zoom alebo ich stlmia.
 *
 * Profil je len predvolený stav; úpravy z developer módu idú nad neho, zvlášť
 * pre každý typ mapy:
 *
 *     vrstvy štýlu → profil typu mapy → úpravy pre všetky mapy → úpravy tejto
 *
 * Pravidlo má tvar `{ match, ...akcie }`:
 *   match: { id: string | string[] | RegExp, group, kind }  (voliteľné)
 *   akcie: visible, minzoom, maxzoom, minzoomFloor (zdvihne, neznižuje),
 *          opacity (vynásobí krytie)
 * Neskoršie pravidlo prepíše skoršie.
 */

/**
 * Triedy POI (`class`/`subclass` z OpenMapTiles) pre tematické vrstvy.
 * Schéma nesie v `subclass` pôvodnú hodnotu tagu z OSM, takže sa dá filtrovať
 * priamo na ňu. Zoznamy sú zámerne štedré – trieda, ktorú dlaždice neobsahujú,
 * nič nepokazí, len sa nikdy netrafí.
 */
export const HISTORIC_CLASSES = [
  "castle", "fort", "fortress", "city_gate", "manor", "palace", "chateau",
  "ruins", "monument", "memorial", "monastery", "archaeological_site",
  "battlefield", "tomb", "tumulus", "wayside_cross", "wayside_shrine",
  "bunker", "tower", "watchtower", "museum", "attraction", "historic",
  "heritage", "milestone", "boundary_stone", "aqueduct", "citywalls"
];

/** Bane, štôlne, haldy a lomy – ťažobné dedičstvo v krajine. */
export const MINING_CLASSES = [
  "mine", "mineshaft", "mine_shaft", "adit", "quarry", "landfill",
  "spoil_heap", "slag_heap", "mineral_shaft", "mining", "pithead"
];

/** Lyžiarske stredisko a všetko okolo neho. */
export const SKI_CLASSES = [
  "ski", "skiing", "ski_school", "ski_rental", "ski_jumping", "piste",
  "winter_sports", "chair_lift", "gondola", "drag_lift", "platter", "t-bar",
  "j-bar", "magic_carpet", "cable_car", "station"
];

/** Čo hľadá vodič: pumpa, nabíjačka, odpočívadlo, servis, parkovisko. */
export const ROAD_SERVICE_CLASSES = [
  "fuel", "charging_station", "rest_area", "services", "parking",
  "parking_space", "car_repair", "car_wash", "car", "car_parts",
  "motorcycle", "tyres", "picnic_site", "toilets", "drinking_water"
];

/** Vrstvy značených trás okrem lyžiarskych. */
import { MARK_MINZOOM } from "./marks.js";

const OTHER_TRAILS = /^trail-(hiking|bicycle|mtb|horse)(-icon|-mark|-label)?$/;
/** Vrstvy lyžiarskych trás. */
const SKI_TRAILS = /^trail-ski(-icon|-mark|-label)?$/;
/** Všetky značené trasy vrátane podkladu pod pásikmi. */
const ALL_TRAILS = /^trail-/;
/**
 * Značky trás (biely či žltý štvorec s farebným pásom). Vlastný vzor preto,
 * že pravidlá, ktoré púšťajú PÁSIKY nižšie („trasy vidieť už z prehľadu"),
 * na ne neplatia: značka je tabuľka, nie čiara – pod z12 je z nej škvrna
 * a je ich toľko, koľko trás, takže by z mapy spravili šum.
 */
const TRAIL_MARKS = /^trail-.*-mark$/;
/** Tematické vrstvy – každá patrí len niektorým mapám. */
const TOPIC_LAYERS = ["poi-historic", "poi-mining", "poi-ski", "poi-road"];
/** Skalné plochy z vrstevnicových dlaždíc. */
const ROCKS = /^rock-/;
/** Zjazdovky a bežky z vlastných dlaždíc (workers/features/features.yml). */
const PISTES = /^piste-/;
/** Prekážky: múry, ploty, živé ploty, zábradlia. */
const BARRIERS = /^feature-(wall|fence|hedge)$/;
/** Technická infraštruktúra: vedenia, potrubia, prieseky. */
const INFRA = /^feature-(power|power-minor|pipeline|cutline)$/;

export const MAP_TYPES = [
  {
    id: "turisticka",
    label: "Turistická",
    short: "turistika",
    note:
      "Skaly, turistické chodníky a čo najviac detailu. Lyžiarske trasy ani " +
      "strediská neukazuje.",
    rules: [
      // Nič, čo patrí inej mape.
      { match: { id: TOPIC_LAYERS }, visible: false },
      { match: { id: SKI_TRAILS }, visible: false },
      { match: { id: PISTES }, visible: false },
      { match: { id: "aerialway" }, minzoom: 12 },
      // Násypy, zárezy, bralné hrany a vedenia sú v teréne orientačné body –
      // na turistickej mape patria k tomu najužitočnejšiemu, takže ostávajú
      // tak, ako ich dáva štýl. Ploty naopak až celkom zblízka, inak by
      // z okrajov obcí bola šeď.
      { match: { id: BARRIERS }, minzoomFloor: 16 },
      // Chodníky sa objavia skôr než na základnej mape. Skaly tu pravidlo
      // NEMAJÚ: štýl ich kreslí od z11 (a pod ním pre ne nie sú ani dlaždice),
      // takže `minzoom: 8` by ich nezobrazilo skôr – len by tichým spôsobom
      // prepisovalo číslo, ktoré má byť na jednom mieste. Zoom skál je
      // v themes.js a v contours-rocks/rocks.yml, a tie dve sa musia rovnať.
      { match: { id: "road-path" }, minzoom: 10 },
      { match: { id: "road-track" }, minzoom: 10 },
      { match: { id: "road-cycleway" }, minzoom: 11 },
      { match: { id: "road-footway" }, minzoom: 12 },
      { match: { id: ALL_TRAILS }, minzoom: 8 },
      // …ale značky nie: pásik má zmysel aj ako čiara z prehľadu, značka až
      // vtedy, keď je z nej vidieť, čo na nej je.
      { match: { id: TRAIL_MARKS }, minzoomFloor: MARK_MINZOOM },
      { match: { id: "trail-halo" }, minzoom: 10 },
      // Vrcholy, chaty a studničky sú tu to hlavné.
      { match: { id: "poi-major" }, minzoom: 13 },
      { match: { id: "mountain-peak" }, minzoom: 8 }
    ]
  },
  {
    id: "lyziarska",
    label: "Lyžiarska",
    short: "lyžovanie",
    note:
      "Lyžiarske a bežkárske trasy, strediská, vleky a skaly. Ostatné značené " +
      "trasy sa objavia až na veľkom detaile, aby neprekážali.",
    rules: [
      { match: { id: TOPIC_LAYERS }, visible: false },
      { match: { id: "poi-ski" }, visible: true, minzoom: 11 },
      // Zjazdovky sú tu hlavná kresba, nie doplnok – vidieť ich má byť
      // z toho istého zoomu ako vleky, ku ktorým patria.
      { match: { id: PISTES }, visible: true, minzoom: 9 },
      { match: { id: BARRIERS }, visible: false },
      // Lyžiarske trasy a vleky sú tu hlavná kresba.
      { match: { id: SKI_TRAILS }, minzoom: 8 },
      { match: { id: TRAIL_MARKS }, minzoomFloor: MARK_MINZOOM },
      { match: { id: "trail-ski-label" }, minzoom: 11 },
      { match: { id: "trail-halo" }, minzoom: 9 },
      { match: { id: "aerialway" }, minzoom: 9 },
      // Ostatné trasy až zblízka – inak by zo zjazdovky spravili spleť.
      { match: { id: OTHER_TRAILS }, minzoomFloor: 14, opacity: 0.7 },
      { match: { id: "road-path" }, minzoomFloor: 13 },
      { match: { id: "poi-major" }, minzoom: 13 },
      { match: { id: "mountain-peak" }, minzoom: 8 }
    ]
  },
  {
    id: "cestna",
    label: "Cestná",
    short: "cesty",
    note:
      "Cesty, pumpy, odpočívadlá a servis. Vrstevnice len jemné (po 50 m), " +
      "bez skál, chodníkov a značených trás.",
    rules: [
      { match: { id: TOPIC_LAYERS }, visible: false },
      { match: { id: "poi-road" }, visible: true, minzoom: 10 },
      // Vrstevnice len naznačia kopec: 10 m preč, zvyšok stlmený.
      { match: { id: "contour-minor" }, visible: false },
      { match: { id: "contour-mid" }, opacity: 0.5 },
      { match: { id: "contour-major" }, opacity: 0.65 },
      { match: { id: "contour-label" }, minzoom: 14 },
      { match: { id: ROCKS }, visible: false },
      { match: { id: ALL_TRAILS }, visible: false },
      { match: { id: PISTES }, visible: false },
      { match: { id: "hillshade" }, visible: false },
      // Vodičovi je múr aj priesek jedno; parkovisko a cesta vo výstavbe
      // naopak patria k tomu hlavnému, čo hľadá.
      { match: { id: BARRIERS }, visible: false },
      { match: { id: INFRA }, visible: false },
      { match: { id: /^(cliff-line|ridge-line|feature-embankment|feature-cutting|feature-gully|feature-tree-row)/ }, visible: false },
      { match: { id: "feature-parking" }, minzoom: 12 },
      { match: { id: "road-construction" }, minzoom: 9 },
      // Číslo cesty je na cestnej mape to hlavné – štítky idú skôr než inde.
      { match: { id: "road-shield-primary" }, minzoom: 8 },
      { match: { id: "road-shield-secondary" }, minzoom: 10 },
      // Chodníky a cestičky nie sú to, kadiaľ sa dá ísť autom.
      { match: { id: ["road-path", "road-steps", "road-footway"] }, visible: false },
      { match: { id: "road-cycleway" }, minzoomFloor: 15 },
      { match: { id: "road-track" }, minzoomFloor: 14 },
      // Krajina ide do pozadia, nech je cestná sieť čitateľná.
      { match: { group: "krajina" }, opacity: 0.55 },
      { match: { group: "uzemie" }, opacity: 0.7 },
      // Bežné POI až zblízka – prednosť majú služby pri ceste.
      { match: { id: "poi-major" }, minzoomFloor: 15 },
      { match: { id: "mountain-peak" }, minzoomFloor: 11 }
    ]
  },
  {
    id: "historicka",
    label: "Historická",
    short: "história",
    note:
      "Maximum pamätihodností: hrady, zámky, pamiatky, bane, štôlne, haldy " +
      "a lomy. Bez turistických chodníkov a značených trás.",
    rules: [
      { match: { id: TOPIC_LAYERS }, visible: false },
      { match: { id: ["poi-historic", "poi-mining"] }, visible: true, minzoom: 9 },
      // „Podobne ako turistická, ale bez chodníkov" – terén ostáva, kresba
      // chodníkov a trás nie.
      { match: { id: ALL_TRAILS }, visible: false },
      { match: { id: ["road-path", "road-steps"] }, visible: false },
      { match: { id: "road-footway" }, minzoomFloor: 15 },
      { match: { id: "road-cycleway" }, visible: false },
      { match: { id: PISTES }, visible: false },
      // Hradby, staré štôlne a haldy sú tu pamiatka, nie prekážka –
      // preto sú vidieť skôr než na ostatných mapách.
      { match: { id: "feature-wall" }, minzoom: 13 },
      { match: { id: "feature-landfill" }, minzoom: 10 },
      { match: { id: ["feature-fence", "feature-hedge"] }, visible: false },
      { match: { id: INFRA }, visible: false },
      // Lom a halda sú tu pamiatka, nie priemysel – nech sú vidieť zavčasu.
      { match: { id: "landuse-quarry" }, minzoom: 8 },
      { match: { id: "poi-major" }, minzoom: 12 },
      { match: { id: "mountain-peak" }, minzoom: 9 }
    ]
  },
  {
    id: "zakladna",
    label: "Základná (všetko)",
    short: "všetko",
    note:
      "Nič sa neoreže – všetky vrstvy tak, ako ich generuje štýl. Hodí sa na " +
      "ladenie: je vidieť, čo vôbec v dlaždiciach je.",
    rules: [
      // Tematické vrstvy sú zámerne vypnuté aj tu: kreslili by ikony druhýkrát
      // nad `poi-major` / `poi-all`.
      { match: { id: TOPIC_LAYERS }, visible: false }
    ]
  }
];

export const MAP_TYPE_IDS = MAP_TYPES.map((t) => t.id);

/** Predvolený typ mapy – FricoMaps je predovšetkým turistická mapa. */
export const DEFAULT_MAP_TYPE = "turisticka";

/** Typ mapy podľa id; pri neznámom id vráti predvolený. */
export function mapTypeDef(id) {
  return MAP_TYPES.find((t) => t.id === id) || MAP_TYPES.find((t) => t.id === DEFAULT_MAP_TYPE);
}

/** Platné id typu mapy (neznáme spadne na predvolené). */
export function normalizeMapType(id) {
  return MAP_TYPE_IDS.includes(id) ? id : DEFAULT_MAP_TYPE;
}

/**
 * Sedí vrstva na `match` pravidla? Prázdny match sedí na všetko.
 *
 * Odvodená vrstva sa pýta za svoju predlohu: vzor nad plochou má vlastné id,
 * takže by ho pravidlo `id: ROCKS` minulo a na cestnej mape by ostali
 * kamienky bez skál.
 */
function matchesLayer(layer, match = {}) {
  const meta = layer.metadata || {};
  const has = (value, want) => {
    if (want == null) return true;
    if (want instanceof RegExp) return want.test(String(value));
    if (Array.isArray(want)) return want.includes(value);
    return want === value;
  };
  return (
    has(meta["frico:derived"] || layer.id, match.id) &&
    has(meta["frico:group"], match.group) &&
    has(meta["frico:kind"], match.kind)
  );
}

/**
 * Vynásobí krytie vrstvy. `["zoom"]` smie byť len priamym vstupom
 * najvrchnejšieho `interpolate`, takže sa násobia výstupy jednotlivých stopov –
 * `["*", ["interpolate", …], k]` by MapLibre odmietol. Zložitejšie výrazy
 * (`case`, `match`) sa nechajú tak: nedá sa v nich rozumne určiť, čo je krytie.
 */
function scaleOpacity(value, k) {
  if (value === undefined) return k;
  if (typeof value === "number") return Math.round(value * k * 1000) / 1000;
  if (Array.isArray(value) && value[0] === "interpolate") {
    const out = value.slice(0, 3);
    for (let i = 3; i < value.length; i += 2) {
      const v = value[i + 1];
      out.push(value[i], typeof v === "number" ? Math.round(v * k * 1000) / 1000 : v);
    }
    return out;
  }
  return value;
}

/** Vlastnosti krytia podľa druhu vrstvy. */
const OPACITY_PROPS = {
  fill: ["fill-opacity"],
  line: ["line-opacity"],
  symbol: ["icon-opacity", "text-opacity"],
  circle: ["circle-opacity"],
  "fill-extrusion": ["fill-extrusion-opacity"],
  raster: ["raster-opacity"]
};

/**
 * Aplikuje profil typu mapy na hotový zoznam vrstiev. Mení vrstvy na mieste
 * (štýl sa práve poskladal, nikto iný ho zatiaľ nedrží).
 *
 * @param {object} style  MapLibre štýl
 * @param {string} id     id typu mapy
 */
export function applyMapType(style, id) {
  const type = mapTypeDef(id);
  if (!type) return style;

  for (const layer of style.layers) {
    for (const rule of type.rules) {
      if (!matchesLayer(layer, rule.match)) continue;

      if (rule.visible === false) {
        layer.layout = { ...(layer.layout || {}), visibility: "none" };
      } else if (rule.visible === true && (layer.layout || {}).visibility === "none") {
        layer.layout = { ...layer.layout };
        delete layer.layout.visibility;
      }
      if (rule.minzoom != null) layer.minzoom = rule.minzoom;
      if (rule.minzoomFloor != null) {
        layer.minzoom = Math.max(layer.minzoom ?? 0, rule.minzoomFloor);
      }
      if (rule.maxzoom != null) layer.maxzoom = rule.maxzoom;
      if (rule.opacity != null) {
        for (const prop of OPACITY_PROPS[layer.type] || []) {
          // Popisku sa krytie nastavuje len vtedy, keď ho vrstva už má –
          // inak by sa `text-opacity` objavilo aj tam, kde vrstva žiadny
          // text nekreslí.
          const cur = (layer.paint || {})[prop];
          if (layer.type === "symbol" && cur === undefined) continue;
          layer.paint = { ...(layer.paint || {}), [prop]: scaleOpacity(cur, rule.opacity) };
        }
      }
      // Neplatný rozsah by MapLibre odmietol.
      if (layer.minzoom != null && layer.maxzoom != null && layer.maxzoom <= layer.minzoom) {
        delete layer.maxzoom;
      }
    }
  }
  return style;
}

/**
 * Ktoré vrstvy vypína samotný profil (bez úprav z developer módu) – vďaka
 * tomu vie panel rozoznať „vypnuté profilom" od „vypnuté mnou".
 *
 * @param {object[]} layers  vrstvy štýlu (stačí id a metadata)
 * @returns {Set<string>}
 */
export function mapTypeHidden(layers, id) {
  const type = mapTypeDef(id);
  const hidden = new Set();
  if (!type) return hidden;
  for (const layer of layers) {
    for (const rule of type.rules) {
      if (rule.visible == null || !matchesLayer(layer, rule.match)) continue;
      if (rule.visible === false) hidden.add(layer.id);
      else hidden.delete(layer.id);
    }
  }
  return hidden;
}
