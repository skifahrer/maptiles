/**
 * Developer mode – ladenie mapy priamo v prehliadači.
 *
 * Čo vie:
 *   - vypísať **všetky** vrstvy štýlu po skupinách, s druhom (plocha / línia /
 *     bod / popisok / 3D / reliéf) a filtrom, zapnúť/vypnúť ich a nastaviť im
 *     rozsah zoomu – teda presne definovať, čo sa kedy zobrazuje,
 *   - robiť to **zvlášť pre každý typ mapy** (turistická, lyžiarska, cestná,
 *     historická, základná): prepínač *len táto mapa / všetky mapy* hovorí,
 *     kam sa úprava zapíše, takže „na cestnej mape toto nechcem" nemusí
 *     znamenať „nikde to nechcem",
 *   - prezerať mapu po zoomoch: nastavíš zoom a zoznam ukáže, ktoré vrstvy
 *     sú na ňom naozaj povolené a ktoré sa orežú – a jedným klikom sa dá na
 *     tom zoome vrstva zapnúť či vypnúť (pásik zoomov z0–z20 v detaile
 *     vrstvy, alebo štítok s rozsahom priamo v riadku),
 *   - kliknúť do mapy a dostať **všetko, čo je pod kurzorom** – každý prvok
 *     zo všetkých vrstiev naraz, aj so všetkými atribútmi z dlaždice, plus
 *     zoznam značených trás, ktoré tadiaľ vedú (ich pásiky sú posunuté vedľa
 *     cesty, takže do nich klik netrafí),
 *   - nastaviť **čokoľvek podľa zoomu jedným editorom**: každé číslo aj farba
 *     má pod sebou zoznam pásiem („z0–z13 takto, z14–z20 inak"), ktorý vždy
 *     pokrýva celý rozsah, a jedinú otázku navyše – či je hodnota **percentom
 *     z toho, čo počíta štýl** (zoomová krivka ostane, mení sa jej mierka:
 *     „na z19 nech je prvok o desatinu väčší, obrys o desatinu tenší"), alebo
 *     **pevnou hodnotou**. Jedno pásmo cez celý rozsah je to, čo bývalo
 *     „pevné číslo" a „× a +",
 *   - zmeniť farbu ktoréhokoľvek prvku: jedna farba je jeden riadok aj s jej
 *     tmavým variantom, „bez výplne" a rozpisom po zoomoch; farby celej palety
 *     naraz, vrátane hromadnej editácie výberu a kopírovania hodnôt – a to aj
 *     tam, kde si vrstva farbu vyberá **výrazom** (pásik trasy podľa značky
 *     z OSM): tie sa ladia z palety priamo v riadku vrstvy,
 *   - vymeniť **ikonu** symbolovej vrstvy za ktorúkoľvek zo sady – a to aj
 *     len pre prvky s konkrétnym `kľúč = hodnota` z OSM (studnička inak než
 *     prameň), spolu s ich vlastnou farbou, hrúbkou a okrajom,
 *   - ladiť **obrys** oboma cestami rovnako: či je obrys samostatná vrstva zo
 *     štýlu („Miestne cesty – obrys"; panel povie, čo obťahuje a koľko z neho
 *     na každej strane vidieť), alebo si ho vrstva pridá sama,
 *   - dať ploche alebo čiare opakujúci sa **vzor** a ľubovoľný **okraj**,
 *     čiare aj prerušovanie,
 *   - skryť konkrétne triedy POI a prepnúť celú sadu ikoniek,
 *   - **vrátiť vrstvu do pôvodného stavu celú** – nie len farbu po farbe:
 *     jedno tlačidlo v detaile vrstvy zahodí viditeľnosť, zoomy, farby,
 *     hrúbky, ikonu, vzor aj okraj (v tom rozsahu, ktorý je práve zvolený),
 *   - **skopírovať vzhľad jednej vrstvy do druhej** („nech sú múry ako
 *     ploty"): odfotí sa to, čo je v štýle NAOZAJ, nie len úprava nad ním,
 *     takže kopírovať sa dá aj z vrstvy, ktorú nikto neladil. Čo sa na cieľ
 *     nezmestí (obrys výplne na čiaru), sa nevloží a povie sa to,
 *   - všetko priebežne ukladá do prehliadača (localStorage), vie to
 *     exportovať do `style-overrides.json` a znovu načítať.
 *
 * Ten istý JSON potom prevezme workflow „Mapa · úpravy štýlu",
 * uloží ho do repozitára a pipeline ho zapečie do mapy pre web aj iOS.
 */
import {
  THEMES,
  PALETTE_GROUPS,
  PALETTE_LABELS,
  LAYER_GROUPS,
  LAYER_KINDS,
  MAX_DISPLAY_Z,
  MAX_PAINT_STOPS,
  NO_FILL,
  builtinDash,
  REGION_MASK_LAYERS,
  sortStops,
  sortBands,
  isBandList,
  isRelative,
  emptyOverrides,
  normalizeOverrides,
  hasOverrides,
  mergedPalette,
  selectedIconSource,
  iconClassesOf,
  poiIconName,
  TRAIL_TYPES,
  TRAIL_MARK_COLOURS,
  LAYOUT_PROPS,
  LAYOUT_PROP_IDS,
  PAINT_DEFAULTS,
  MAX_VARIANTS,
  CUSTOM_ICON_PREFIX,
  CUSTOM_ICON_MAX_COUNT,
  CUSTOM_ICON_MAX_BYTES,
  TRAIL_GAP_DEFAULTS,
  TRAIL_GAP_ZOOM,
  TRAIL_MARK_DEFAULTS,
  TRAIL_MARK_RANGES,
  TRAIL_MARK_ZOOM,
  SHIELD_DEFS,
  trailGapPx,
  trailMarkPx,
  trailTypeDef,
  shieldShapeFor,
  DEFAULT_MAP_TYPE,
  mapTypeDef,
  mapTypeHidden,
  normalizeMapType
} from "./themes.js";
import { PATTERNS, DASH_PRESETS, dashPreview, dashLabel } from "./patterns.js";
import {
  patternPreview,
  patternPicker,
  IMAGE_PATTERN_SIZES,
  IMAGE_PATTERN_SIZE
} from "./dev-patterns.js";
import { CUSTOM_SET_PREFIX } from "./icon-sources.js";
import { MARK_SHAPES } from "./marks.js";
import { SHIELD_SHAPES } from "./shields.js";
import { snapshotStyle, pasteStyle, valueAtZoom } from "./layer-style.js";
import { el } from "./dom.js";
import {
  iconPicker,
  iconPreview,
  fileToIconPng,
  iconNameFromFile,
  CUSTOM_ICON_MAX_PX
} from "./dev-icons.js";

/**
 * Atribúty, ktorými sa rozlišovať NEDÁ, hoci v dlaždici sú.
 *
 * Meno, číslo cesty ani id prvku nie sú kategórie – variant nad nimi by bol
 * jedna vrstva na jednu cestu. Zvyšok sa nefiltruje: čo v dlaždiciach naozaj
 * je, ponúkne `scanAttrs` aj s počtami, a atribút s jedinou hodnotou z ponuky
 * vypadne sám (nerozlíšil by nič).
 */
const SKIP_ATTRS = new Set([
  "id", "osm_id", "ref", "ref_length", "network", "rel",
  "ele", "ele_ft", "render_height", "render_min_height", "area", "length"
]);

const STORAGE_KEY = "fricomaps.overrides";
const SCOPE_KEY = "fricomaps.devscope";
const KIND_LABELS = Object.fromEntries(LAYER_KINDS.map((k) => [k.id, k.label]));
const GROUP_LABELS = Object.fromEntries(LAYER_GROUPS.map((g) => [g.id, g.label]));
/**
 * MENÁ FARIEB PO ĽUDSKY – jedno miesto pre celý panel.
 *
 * `line-color` v riadku nepovie nič navyše oproti tomu, že vrstva je čiara,
 * a pri symbole stáli vedľa seba `text`, `text-halo` a `icon-halo`, čo je
 * trikrát to isté slovo. Meno vlastnosti ostáva v bublinke, v zozname je to,
 * čo tá farba v mape naozaj zafarbí.
 */
const COLOR_LABELS = {
  "fill-color": "výplň",
  "fill-outline-color": "obrys výplne",
  "fill-extrusion-color": "steny",
  "line-color": "čiara",
  "text-color": "text",
  "text-halo-color": "lem textu",
  "icon-color": "ikona",
  "icon-halo-color": "lem ikony",
  "circle-color": "bod",
  "circle-stroke-color": "obrys bodu",
  "background-color": "podklad",
  "hillshade-shadow-color": "tieň",
  "hillshade-highlight-color": "prisvetlenie",
  "hillshade-accent-color": "hrany"
};

/**
 * ČÍSLA, KTORÉ SA DAJÚ LADIŤ, a ich medze – jedna tabuľka pre celý panel.
 *
 * Bývali to dva zoznamy: zopár blokov ručne napísaných v detaile vrstvy
 * (hrúbka a krytie čiary, krytie plochy, sila tieňovania) a vedľa nich
 * `PAINT_RANGES` pre záložky Trasy a Štítky. Rozišli sa presne tak, ako sa
 * dva zoznamy toho istého rozísť musia: lem písma sa dal ladiť pri trasách,
 * ale nie v zozname vrstiev.
 *
 * `on` je druh vrstvy, ktorý tú vlastnosť pozná – nedá sa uhádnuť predponou
 * (`fill-extrusion-opacity` sa začína rovnako ako `fill-opacity`, a nie sú to
 * tie isté vrstvy). `core` znamená „ponúkni to aj vtedy, keď to štýl
 * nenastavil": krytie má každá plocha, aj keď v `paint` nie je – bez toho by
 * sa nedalo zaviesť.
 */
const NUM_PROPS = {
  // NIE 0: nulová hrúbka je zmiznutá čiara, nie vypnutá vrstva (na to je 👁).
  "line-width": { on: "line", core: true, min: 0.1, max: 40, step: 0.5, label: "hrúbka čiary", unit: " px" },
  "line-opacity": { on: "line", core: true, min: 0, max: 1, step: 0.05, label: "krytie" },
  "fill-opacity": { on: "fill", core: true, min: 0, max: 1, step: 0.05, label: "krytie" },
  "fill-extrusion-opacity": { on: "fill-extrusion", core: true, min: 0, max: 1, step: 0.05, label: "krytie" },
  "text-opacity": { on: "symbol", min: 0, max: 1, step: 0.05, label: "krytie písma" },
  "text-halo-width": { on: "symbol", min: 0, max: 8, step: 0.5, label: "lem písma", unit: " px" },
  "icon-opacity": { on: "symbol", min: 0, max: 1, step: 0.05, label: "krytie ikony" },
  "icon-halo-width": { on: "symbol", min: 0, max: 8, step: 0.5, label: "lem ikony", unit: " px" },
  "circle-stroke-width": { on: "circle", min: 0, max: 10, step: 0.5, label: "obrys bodu", unit: " px" },
  "hillshade-exaggeration": {
    on: "hillshade", core: true, min: 0, max: 1, step: 0.05, label: "sila tieňovania"
  }
};

/**
 * Ktoré čísla má zmysel ponúknuť na tejto vrstve: tie, ktoré štýl nastavil,
 * plus tie, ktoré k jej druhu patria vždy. Vlastnosť, ktorú druh vrstvy
 * nepozná, by bola políčko, ktoré nič nerobí.
 */
const numPropsFor = (layer) =>
  Object.keys(NUM_PROPS).filter((prop) => {
    const m = NUM_PROPS[prop];
    if (m.on !== layer.type) return false;
    return m.core === true || (layer.paint || {})[prop] !== undefined;
  });

/** Meno značky z dlaždíc → kľúč palety (rovnako ako v štýle). */
const TRAIL_MARK_KEYS = Object.fromEntries(TRAIL_MARK_COLOURS);

/**
 * Obrázky, ktoré si do spritu pečieme sami – značky trás (`mark-…`), podklady
 * štítkov ciest (`shield-…`) a vzory plôch (`pat:…`, tie sú zároveň svojím
 * vlastným predpisom a nastavujú sa ako vzor, nie ako ikona). V zoznamoch „vyber ikonu" nemajú čo robiť: nie sú
 * to symboly, ale hotové farebné obrázky konkrétnej veci, a je ich viac než
 * samotných ikoniek (154 značiek proti pár stovkám ikon). Prepínajú sa tam, kam
 * patria – v záložke „Trasy" a „Štítky".
 */
const BAKED_IMAGE = /^(mark-|shield-|pat:)/;
const pickableIcons = (set, extra) => {
  const vsetky = (set?.icons || []).filter((n) => !BAKED_IMAGE.test(n));
  // SADA MÁ TÚ ISTÚ IKONU DVAKRÁT: `aerialway` aj `aerialway_11`. Štýl
  // používa tú s príponou (`specialIcons`, `iconClasses`), takže tá bez nej
  // je v zozname len dvojička, ktorá vyzerá rovnako a nedá sa od nej odlíšiť.
  const s = set?.suffix;
  const maPriponu = new Set(s ? vsetky.filter((n) => n.endsWith(s)) : []);
  const bezDvojiciek = s
    ? vsetky.filter((n) => n.endsWith(s) || !maPriponu.has(`${n}${s}`))
    : vsetky;
  return [...new Set([...(extra ? [extra] : []), ...bezDvojiciek])].sort();
};

/** Načíta úpravy uložené v prehliadači. */
export function loadOverrides() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return emptyOverrides();
    return normalizeOverrides(JSON.parse(raw)).overrides;
  } catch {
    return emptyOverrides();
  }
}

/** Kam sa naposledy zapisovali úpravy: `map` (len táto mapa) alebo `all`. */
function loadScope() {
  try {
    return localStorage.getItem(SCOPE_KEY) === "all" ? "all" : "map";
  } catch {
    return "map";
  }
}

/** Uloží úpravy do prehliadača (používa aj hlavný panel viewra). */
export function saveOverrides(overrides) {
  try {
    if (hasOverrides(overrides)) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    /* súkromný režim – úpravy zostanú len do zatvorenia karty */
  }
}

/** JSON tak, ako sa ukladá do súboru aj do zdrojáku. */
export function serializeOverrides(overrides) {
  return JSON.stringify(
    { ...overrides, updated_at: new Date().toISOString() },
    null,
    2
  );
}


const isHex6 = (v) => /^#[0-9a-f]{6}$/i.test(v);
/** Farba, akú berie štýl: `#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa`. */
const isHexColor = (v) =>
  /^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(String(v || "").trim());
/** `input[type=color]` vie iba 6-miestny hex – kratšie zápisy dopočítame. */
const toHex6 = (v) => {
  const s = String(v || "").trim();
  if (isHex6(s)) return s.toLowerCase();
  const m = /^#([0-9a-f])([0-9a-f])([0-9a-f])([0-9a-f])?$/i.exec(s);
  if (m) return `#${m[1]}${m[1]}${m[2]}${m[2]}${m[3]}${m[3]}`.toLowerCase();
  const m8 = /^#([0-9a-f]{6})[0-9a-f]{2}$/i.exec(s);
  if (m8) return `#${m8[1]}`.toLowerCase();
  return "#000000";
};

/**
 * ALFA FARBY, ODDELENE OD ODTIEŇA – a je to kvôli tieňovaniu reliéfu.
 *
 * `hillShadow`, `hillHighlight` a `hillAccent` sú `#rrggbbaa` (prečo, je
 * v `themes.js` pri vrstve `hillshade`) a `input[type=color]` alfu nepozná:
 * vrátil by `#rrggbb`. Kým sa alfa nedržala bokom, stačilo ťuknúť do
 * farby tieňa a alfa TICHO zmizla – v mape z toho bola nepriehľadná plocha
 * cez celý svah a v `style-overrides.json` farba, ktorá vyzerá ako drobná
 * úprava odtieňa. Preto je alfa vlastná hodnota: pipetka mení odtieň
 * a alfu nesie ďalej, textové políčko ukazuje a berie celý zápis.
 */
const alphaOf = (v) => {
  const s = String(v || "").trim();
  const m8 = /^#[0-9a-f]{6}([0-9a-f]{2})$/i.exec(s);
  if (m8) return parseInt(m8[1], 16) / 255;
  const m4 = /^#[0-9a-f]{3}([0-9a-f])$/i.exec(s);
  if (m4) return parseInt(m4[1] + m4[1], 16) / 255;
  return 1;
};
/** Odtieň + alfa späť do jedného zápisu; pri plnej alfe ostáva `#rrggbb`. */
const withAlpha = (hex6, alpha) => {
  const a = Math.min(1, Math.max(0, Number(alpha)));
  if (!(a < 1)) return toHex6(hex6);
  return `${toHex6(hex6)}${Math.round(a * 255).toString(16).padStart(2, "0")}`;
};
/** Zápis farby, ako sa má uložiť do úprav (malými písmenami, bez medzier). */
const normColor = (v) => withAlpha(toHex6(v), alphaOf(v));

/** Stmaví farbu – použité ako predvolená farba vzoru a okraja. */
const darken = (hex, factor = 0.55) => {
  const h = toHex6(hex);
  const ch = (i) =>
    Math.round(parseInt(h.slice(1 + i * 2, 3 + i * 2), 16) * factor)
      .toString(16)
      .padStart(2, "0");
  return `#${ch(0)}${ch(1)}${ch(2)}`;
};

async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Bez HTTPS/oprávnenia clipboard API nefunguje – fallback cez výber textu.
    const ta = el("textarea", { class: "dev-clip" });
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } catch {
      /* nedá sa – používateľ si text skopíruje ručne z exportu */
    }
    ta.remove();
  }
  if (button) {
    const old = button.textContent;
    button.textContent = "✓";
    setTimeout(() => {
      button.textContent = old;
    }, 900);
  }
}

/** Rozsah zoomu vrstvy ako text. */
const zoomRangeText = (layer) => {
  const mn = layer.minzoom ?? 0;
  const mx = layer.maxzoom ?? MAX_DISPLAY_Z + 4;
  // Nad MAX_DISPLAY_Z sa priblížiť nedá, takže „do z21" a „bez hornej hranice"
  // je pre čitateľa to isté.
  const noTop = mx > MAX_DISPLAY_Z;
  if (mn <= 0 && noTop) return "vždy";
  if (noTop) return `z${mn}+`;
  return `z${mn}–${mx}`;
};

/** Kreslí sa vrstva na danom zoome? */
const activeAt = (layer, z) => {
  if ((layer.layout || {}).visibility === "none") return false;
  return z >= (layer.minzoom ?? 0) && z < (layer.maxzoom ?? 25);
};

/** Je vrstva vypnutá (nie orezaná zoomom)? */
const isHiddenLayer = (layer) => (layer.layout || {}).visibility === "none";

/**
 * Aký rozsah zoomu má vrstva mať, keď sa na zoome `z` má (ne)kresliť.
 *
 * Rozsah je jeden súvislý interval `<minzoom, maxzoom)`, takže „na tomto
 * zoome áno / nie" znamená posunúť jeho koniec:
 *   - zapnutie mimo rozsahu natiahne bližší koniec až po `z`,
 *   - vypnutie vnútri rozsahu ustúpi tým koncom, ktorý je bližšie.
 * Keď by z rozsahu nič neostalo, vráti `{ hide: true }` – vtedy je poctivejšie
 * vrstvu vypnúť než jej nastaviť prázdny interval.
 *
 * @returns {{minzoom?: number|undefined, maxzoom?: number|undefined, hide?: boolean, show?: boolean}}
 */
function zoomRangeFor(layer, z, on) {
  const mn = layer.minzoom ?? 0;
  const mx = layer.maxzoom ?? MAX_DISPLAY_Z + 1;
  const top = MAX_DISPLAY_Z + 1;

  if (on) {
    const patch = { show: true };
    if (z < mn) patch.minzoom = z;
    // `maxzoom` je horná hranica bez rovnosti – aby sa vrstva kreslila aj na
    // `z`, musí siahať o krok vyššie. Hodnotu treba zapísať aj na samom
    // vrchu: vrstva môže mať vlastný `maxzoom` zo štýlu (POI má 16), takže
    // „zmazať úpravu" by ju na z20 nezaplo.
    if (z >= mx) patch.maxzoom = Math.min(z + 1, top);
    return patch;
  }

  // Vrstva sa na tom zoome aj tak nekreslí – netreba nič meniť.
  if (z < mn || z >= mx) return {};
  // Bližší koniec ustúpi; pri rovnakej vzdialenosti sa oreže zospodu, lebo
  // mapa sa častejšie ladí smerom „od akého zoomu sa to objaví".
  if (z - mn <= mx - 1 - z) {
    return z + 1 >= mx ? { hide: true } : { minzoom: z + 1 };
  }
  return z <= mn ? { hide: true } : { maxzoom: z };
}

/**
 * @param {object} opts
 * @param {HTMLElement} opts.root      prázdny kontajner pre panel
 * @param {() => object} opts.getStyle aktuálny (už upravený) MapLibre štýl
 * @param {() => string} opts.getTheme kľúč aktuálnej témy
 * @param {(theme: string) => void} [opts.setTheme] prepne tému (hlavička
 *        panela ňou ponúka rýchly prepínač svetlá/tmavá, nech sa dá ladiť
 *        tmavý variant farieb bez toho, aby sa zatváral developer mode)
 * @param {() => string} [opts.getMapType] id práve zobrazeného typu mapy
 * @param {() => object} opts.getMap   inštancia mapy
 * @param {() => object[]} [opts.getIconSets] nasadené sady ikoniek
 * @param {(overrides: object) => void} opts.onChange  prekresli mapu
 */
export function initDevMode({
  root,
  getStyle,
  getTheme,
  setTheme,
  getMapType,
  getMap,
  getIconSets,
  onChange
}) {
  let overrides = loadOverrides();
  let tab = "layers";
  let search = "";
  let kindFilter = new Set();
  let onlyActive = false;
  /** Ktorý typ mapy sa práve ladí (a teda kam patria úpravy „len táto mapa"). */
  const mapTypeId = () => normalizeMapType(getMapType ? getMapType() : DEFAULT_MAP_TYPE);
  /**
   * Kam sa zapisujú úpravy vrstiev a POI: `map` = len do práve zobrazeného
   * typu mapy, `all` = do spoločných, ktoré platia pre všetky.
   */
  let editScope = loadScope();
  let zoomView = getMap()?.getZoom?.() ?? 10;
  const selectedLayers = new Set();
  const selectedPaletteKeys = new Set();
  const collapsed = new Set();
  const expanded = new Set();
  /** Pri ktorých vrstvách je rozbalená mriežka vzorov. */
  const patternOpen = new Set();
  const setPatternPickerOpen = (id, open) => {
    if (open) patternOpen.add(id);
    else patternOpen.delete(id);
  };
  /**
   * Rozpísané rozlíšenie podľa atribútu: ktorý atribút je vybraný a ktoré
   * hodnoty sú naklikané, kým sa nepotvrdí „Pridať rozlíšenie".
   *
   * NIE JE TO ÚPRAVA, a preto to nie je v `overrides`: polovica naklikaného
   * variantu je stav panela, nie mapy – uložený by sa vyviezol do repozitára
   * a pipeline by ho zahodila ako variant bez hodnôt.
   */
  const variantAttr = new Map();
  const variantValues = new Map();
  let poiClasses = [];
  let applyTimer = null;
  let zoomTimer = null;
  /** Posledný výber z mapy (záložka Prvky) – `null`, kým sa neklikne. */
  let picked = null;
  /** Polomer výberu v pixeloch – čiara má šírku 2 px, trafiť ju treba vedieť. */
  let pickRadius = 6;
  const pickOpen = new Set();
  /**
   * Odfotený vzhľad vrstvy, ktorý čaká na vloženie do inej („kopírovať štýl
   * z jedného prvku do druhého"). Žije len v tejto relácii panelu – do
   * `style-overrides.json` nepatrí, je to schránka, nie nastavenie.
   */
  let styleClip = null;
  /**
   * Krátka správa do stavového riadku („ikona pridaná", „adresa chýba").
   * Ten istý riadok, ktorý hlási, čo sa nepodarilo preniesť pri kopírovaní
   * štýlu – nech nie sú dve miesta, kam sa panel prihovára.
   */
  const poznamka = (text) => {
    clipNote = text;
    renderStatus();
  };

  /** Ktoré druhy trás majú v záložke „Trasy" rozbalené zoomy a pásma. */
  const trailOpen = new Set();

  /** Ktoré kategórie majú v záložke „POI" rozbalený výber ikony. */
  const poiOpen = new Set();

  /** Ktorú vrstvu práve ťaháme v stohu (záložka „Poradie"). */
  let dragId = null;
  /** Hľadanie v stohu – kým je zadané, ťahanie nedáva zmysel (rozpis v `renderStack`). */
  let stackSearch = "";

  /** Čo sa pri poslednom vložení nedalo preniesť – vypíše to stavový riadok. */
  let clipNote = "";

  // ---------- základná kostra ----------
  const body = el("div", { class: "dev-body" });
  const status = el("div", { class: "dev-status" });
  const tabsBar = el("div", { class: "dev-tabs" });

  const TABS = [
    ["layers", "Vrstvy"],
    ["stack", "Poradie"],
    ["pick", "Prvky"],
    ["palette", "Paleta"],
    ["trails", "Trasy"],
    ["shields", "Štítky"],
    ["icons", "Ikony"],
    ["poi", "POI"],
    ["file", "Súbor"]
  ];

  /** Bitmapy spritov pre náhľad ikoniek – načítajú sa raz. */
  const spriteImages = new Map();

  // Rýchly prepínač svetlá/tmavá – bez neho by ladenie tmavého variantu farby
  // (`paintDark`, záložka „Vrstvy") znamenalo zatvoriť developer mode, prepnúť
  // tému v paneli nastavení a otvoriť ho znova. Prepína len medzi týmito
  // dvoma: ostatné dve témy (Outdoor, Retro) ostávajú vo výbere pod ⚙,
  // lebo tmavý variant patrí len téme „tmava" (rozpis pri `applyLayerOverrides`
  // v themes.js).
  const themeToggle = setTheme
    ? el("button", {
        class: "dev-mini dev-themetoggle",
        type: "button",
        onclick: () => setTheme(getTheme() === "tmava" ? "svetla" : "tmava")
      })
    : null;
  function renderThemeToggle() {
    if (!themeToggle) return;
    const dark = getTheme() === "tmava";
    themeToggle.textContent = dark ? "☀️ svetlá" : "🌙 tmavá";
    themeToggle.title = dark
      ? "Prepnúť náhľad na svetlú tému"
      : "Prepnúť náhľad na tmavú tému – tu sa ladí jej vlastná farba (🌙)";
  }

  root.appendChild(
    el("div", { class: "dev-head" }, [
      el("b", { text: "🛠 Developer mode" }),
      ...(themeToggle ? [themeToggle] : []),
      el("button", {
        class: "dev-x",
        type: "button",
        title: "Zavrieť",
        text: "✕",
        onclick: () => root.dispatchEvent(new CustomEvent("dev-close", { bubbles: true }))
      })
    ])
  );
  root.appendChild(tabsBar);
  root.appendChild(body);
  root.appendChild(status);

  // Posuvník zoomu sleduje mapu, takže zoznam vždy ukazuje, čo je naozaj
  // povolené na tom zoome, na ktorom sa práve pozeráme.
  const map = getMap();
  if (map) {
    map.on("zoomend", () => {
      zoomView = map.getZoom();
      if (tab !== "layers") return;
      if (zoomTimer) clearTimeout(zoomTimer);
      zoomTimer = setTimeout(renderBody, 120);
    });

    // Inšpektor berie klik len s otvorenou záložkou „Prvky" – inak by
    // developer mode potichu zobral kliknutie popupu s POI.
    map.on("click", (ev) => {
      if (tab !== "pick") return;
      pickAt(ev.point, ev.lngLat);
    });

    // Po každej zmene štýlu (farba, vrstva, prepnutie témy) sa vrstvy
    // zvýraznenia stratia – `setStyle` zmaže všetko, čo v novom štýle nie je.
    // Doplnenie ide cez timeout, aby prebehlo až po dokončení zmeny; podmienka
    // `getLayer` v `restoreHighlight` zároveň bráni zacykleniu (`addLayer`
    // vyvolá `styledata` znova).
    let restoreTimer = null;
    map.on("styledata", () => {
      if (!picked || map.getLayer(`${HL_PREFIX}-line`)) return;
      if (restoreTimer) clearTimeout(restoreTimer);
      restoreTimer = setTimeout(restoreHighlight, 60);
    });
  }

  // ---------- výber prvkov v mape (záložka Prvky) ----------
  // Mapa je poskladaná z desiatok vrstiev nad sebou: na jednom mieste býva
  // plocha, cesta, jej obrys, vrstevnica, pásik trasy aj popisok. Inšpektor
  // vypíše **všetko**, čo je pod kurzorom, aj so všetkými atribútmi – takže
  // je vidieť, z ktorej vrstvy to je a čo v dlaždici naozaj stojí.
  const HL_SOURCE = "__dev-pick";
  const HL_PREFIX = "__dev-pick";
  const EMPTY_FC = { type: "FeatureCollection", features: [] };

  /** Vrstvy zvýraznenia. Nie sú v štýle – pridávajú sa priamo do mapy. */
  const HL_LAYERS = [
    {
      id: `${HL_PREFIX}-fill`,
      type: "fill",
      source: HL_SOURCE,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": "#ff7a00", "fill-opacity": 0.25 }
    },
    {
      id: `${HL_PREFIX}-line`,
      type: "line",
      source: HL_SOURCE,
      filter: ["!=", ["geometry-type"], "Point"],
      paint: { "line-color": "#ff7a00", "line-width": 3.5, "line-opacity": 0.9 }
    },
    {
      id: `${HL_PREFIX}-point`,
      type: "circle",
      source: HL_SOURCE,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": 7,
        "circle-color": "#ff7a00",
        "circle-opacity": 0.35,
        "circle-stroke-color": "#ff7a00",
        "circle-stroke-width": 2
      }
    }
  ];

  /**
   * Zvýraznenie musí prežiť prekreslenie štýlu: `setStyle` porovná starý
   * a nový štýl a čokoľvek, čo v novom nie je (teda aj tieto vrstvy), zmaže.
   */
  function ensureHighlight(m) {
    if (!m.getSource(HL_SOURCE)) {
      m.addSource(HL_SOURCE, { type: "geojson", data: EMPTY_FC });
    }
    for (const layer of HL_LAYERS) if (!m.getLayer(layer.id)) m.addLayer(layer);
  }

  /** @returns {boolean} podarilo sa? (počas prekresľovania štýlu nie) */
  function setHighlight(features) {
    const m = getMap();
    if (!m) return false;
    try {
      ensureHighlight(m);
      m.getSource(HL_SOURCE).setData({
        type: "FeatureCollection",
        features: features.map((f) => ({
          type: "Feature",
          geometry: f.geometry,
          properties: {}
        }))
      });
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Vráti zvýraznenie po prekreslení štýlu. Keď mapa práve nie je v stave, kedy
   * sa dá pridať vrstva (plné načítanie štýlu je asynchrónne), skúsi to znova,
   * až keď sa mapa upokojí.
   */
  function restoreHighlight() {
    const m = getMap();
    if (!m || !picked || m.getLayer(`${HL_PREFIX}-line`)) return;
    if (!setHighlight(picked.features)) m.once("idle", restoreHighlight);
  }

  /** Ktoré vrstvy v mape patria danému zdroju (a naozaj v nej sú). */
  const layersOfSource = (m, source, type) =>
    (getStyle()?.layers || [])
      .filter((l) => l.source === source && (!type || l.type === type) && m.getLayer(l.id))
      .map((l) => l.id);

  /** Poradie vrstvy v štýle – podľa neho sa výsledky radia zhora nadol. */
  function layerOrder() {
    const order = new Map();
    (getStyle()?.layers || []).forEach((l, i) => order.set(l.id, i));
    return order;
  }

  function pickAt(point, lngLat) {
    const m = getMap();
    if (!m) return;
    const r = pickRadius;
    const box = [
      [point.x - r, point.y - r],
      [point.x + r, point.y + r]
    ];
    let all = [];
    try {
      all = m.queryRenderedFeatures(box);
    } catch {
      all = [];
    }
    all = all.filter((f) => !String(f.layer?.id || "").startsWith(HL_PREFIX));

    // Ten istý prvok býva v niekoľkých dlaždiciach (rozrezaný na hranici),
    // takže by sa v zozname zopakoval.
    const seen = new Set();
    const feats = [];
    for (const f of all) {
      const key = `${f.layer.id}|${f.id ?? ""}|${JSON.stringify(f.properties)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      feats.push(f);
    }

    // Pásiky značených trás sú posunuté VEDĽA cesty (`line-offset`), takže
    // klik do cesty ich netrafí. Hľadajú sa preto v širšom okolí a vypisujú
    // sa zvlášť: „ktoré trasy tadiaľto vedú" je iná otázka než „na čo som
    // presne klikol".
    const trailIds = layersOfSource(m, "trails", "line");
    const wide = r + 18;
    let trails = [];
    if (trailIds.length) {
      try {
        trails = m.queryRenderedFeatures(
          [
            [point.x - wide, point.y - wide],
            [point.x + wide, point.y + wide]
          ],
          { layers: trailIds }
        );
      } catch {
        trails = [];
      }
    }
    const byRel = new Map();
    for (const f of trails) {
      const p = f.properties || {};
      const key = p.rel ?? `${p.route}|${p.colour}|${p.name}|${p.ref}`;
      if (!byRel.has(key)) byRel.set(key, p);
    }

    const order = layerOrder();
    feats.sort((a, b) => (order.get(b.layer.id) ?? 0) - (order.get(a.layer.id) ?? 0));

    pickOpen.clear();
    picked = {
      lngLat: { lng: lngLat.lng, lat: lngLat.lat },
      zoom: m.getZoom(),
      features: feats,
      trails: [...byRel.values()]
    };
    setHighlight(feats);
    if (tab === "pick") renderBody();
  }

  function clearPick() {
    picked = null;
    pickOpen.clear();
    setHighlight([]);
    renderBody();
  }

  function renderTabs() {
    tabsBar.replaceChildren(
      ...TABS.map(([id, label]) =>
        el("button", {
          type: "button",
          class: `dev-tab${tab === id ? " on" : ""}`,
          text: label,
          onclick: () => {
            tab = id;
            render();
          }
        })
      )
    );
  }

  // ---------- ukladanie a prekreslenie ----------
  function apply({ rerender = true, immediate = false } = {}) {
    saveOverrides(overrides);
    renderStatus();
    const run = () => {
      applyTimer = null;
      onChange(overrides);
      if (rerender) render();
    };
    // Aj „okamžité" použitie ide cez timeout: zmeny prichádzajú z change/blur
    // handlerov a prekresliť panel priamo v nich Chromium neznesie.
    if (applyTimer) clearTimeout(applyTimer);
    applyTimer = setTimeout(run, immediate ? 0 : 90);
  }

  function renderStatus() {
    const nPalette = Object.values(overrides.palette).reduce(
      (n, c) => n + Object.keys(c).length,
      0
    );
    const nLayers = Object.keys(overrides.layers).length;
    const nPoi = overrides.poi.hidden.length;
    const nTrails =
      Object.keys(overrides.trails.gap).length +
      Object.keys(overrides.trails.marks).length +
      Object.keys(overrides.trails.types).length;
    const nShields = Object.keys(overrides.shields).length;
    const nIkony = (overrides.customIcons || []).length;
    const nSady = (overrides.iconSets || []).length;
    const perMap = Object.entries(overrides.maps)
      .map(([id, m]) => `${mapTypeDef(id).label} ${Object.keys(m.layers).length}`)
      .join(", ");
    status.textContent =
      (hasOverrides(overrides)
        ? `Zmeny: ${nPalette} farieb palety · ${nLayers} vrstiev (všetky mapy) · ` +
          `${nPoi} skrytých POI · ${nTrails} úprav trás · ` +
          `${nShields} štítkov · ` +
          (nIkony || nSady
            ? `${nIkony} vlastných ikon${nSady ? `, ${nSady} vlastných sád` : ""} · `
            : "") +
          `ikony ${selectedIconSource(overrides)}` +
          (perMap ? ` · po mapách: ${perMap}` : "") +
          " · uložené v prehliadači"
        : "Žiadne zmeny – mapa beží na pôvodnom štýle.") +
      // Čo sa pri kopírovaní štýlu neprenieslo, musí byť vidieť: polovičný
      // vklad bez slova vyzerá ako pokazené kopírovanie.
      (clipNote ? ` — ${clipNote}` : "");
  }

  // ---------- pomocníci nad overrides ----------
  // Úpravy sú v dvoch priečinkoch: spoločné (`overrides.layers`) a pre jeden
  // typ mapy (`overrides.maps[<typ>].layers`). Čítanie ich mieša rovnako ako
  // generátor štýlu, zápis ide do toho, ktorý je práve zvolený.

  /** Priečinok pre daný typ mapy; `create` ho v prípade potreby založí. */
  function mapBucket(create = false) {
    const id = mapTypeId();
    if (!overrides.maps[id] && create) {
      overrides.maps[id] = { layers: {}, poi: { hidden: [] } };
    }
    return overrides.maps[id];
  }

  /** Prázdne priečinky sa nemajú vláčiť do `style-overrides.json`. */
  function pruneMaps() {
    for (const [id, m] of Object.entries(overrides.maps)) {
      if (!Object.keys(m.layers || {}).length && !(m.poi?.hidden || []).length) {
        delete overrides.maps[id];
      }
    }
  }

  const baseLayerOverride = (id) => overrides.layers[id];
  const mapLayerOverride = (id) => mapBucket()?.layers?.[id];

  /** Úprava vrstvy tak, ako ju vidí mapa: spoločná a nad ňou tá pre túto mapu. */
  function layerOverride(id) {
    const base = baseLayerOverride(id);
    const own = mapLayerOverride(id);
    if (!base) return own;
    if (!own) return base;
    return {
      ...base,
      ...own,
      ...(base.paint || own.paint
        ? { paint: { ...(base.paint || {}), ...(own.paint || {}) } }
        : {}),
      // Tá istá otázka, čo `paint`, len pre jeho tmavý variant (rozpis pri
      // `setLayerPaintDark`) – bez toho by úprava „len táto mapa" v paneli
      // ukazovala tmavú farbu zo spoločnej úpravy, ale zlúčenie by ju stratilo.
      ...(base.paintDark || own.paintDark
        ? { paintDark: { ...(base.paintDark || {}), ...(own.paintDark || {}) } }
        : {}),
      ...(base.layout || own.layout
        ? { layout: { ...(base.layout || {}), ...(own.layout || {}) } }
        : {})
    };
  }

  /** Úprava v tom priečinku, do ktorého sa práve zapisuje. */
  const scopedOverride = (id) =>
    editScope === "all" ? baseLayerOverride(id) : mapLayerOverride(id);

  function setLayerOverride(id, patch) {
    const bucket = editScope === "all" ? overrides.layers : mapBucket(true).layers;
    const cur = { ...(bucket[id] || {}) };
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) delete cur[k];
      else cur[k] = v;
    }
    if (cur.paint && !Object.keys(cur.paint).length) delete cur.paint;
    if (cur.paintDark && !Object.keys(cur.paintDark).length) delete cur.paintDark;
    if (cur.layout && !Object.keys(cur.layout).length) delete cur.layout;
    if (Object.keys(cur).length) bucket[id] = cur;
    else delete bucket[id];
    pruneMaps();
  }

  function setLayerPaint(id, prop, value) {
    const cur = { ...((scopedOverride(id) || {}).paint || {}) };
    if (value === undefined) delete cur[prop];
    else cur[prop] = value;
    setLayerOverride(id, { paint: Object.keys(cur).length ? cur : undefined });
  }

  /**
   * Tmavý variant jednej farby vrstvy – tá istá zápisová logika ako
   * `setLayerPaint`, len do vlastného priečinka `paintDark`. Vlastná funkcia,
   * a nie `setLayerPaint` s iným kľúčom: tmavý variant platí len v téme
   * `tmava` (`applyLayerOverrides` v themes.js), takže sa nesmie zliať s
   * farbou, ktorú vidia aj ostatné tri témy.
   */
  function setLayerPaintDark(id, prop, value) {
    const cur = { ...((scopedOverride(id) || {}).paintDark || {}) };
    if (value === undefined) delete cur[prop];
    else cur[prop] = value;
    setLayerOverride(id, { paintDark: Object.keys(cur).length ? cur : undefined });
  }

  /**
   * To isté pre `layout` (veľkosť ikony, rozostup po čiare, veľkosť písma).
   * Je to vlastná vetva, a nie „paint s iným menom": MapLibre drží `paint`
   * a `layout` zvlášť a neznáma vlastnosť v `layout` zhodí celý štýl.
   */
  function setLayerLayout(id, prop, value) {
    const cur = { ...((scopedOverride(id) || {}).layout || {}) };
    if (value === undefined) delete cur[prop];
    else cur[prop] = value;
    setLayerOverride(id, { layout: Object.keys(cur).length ? cur : undefined });
  }

  /**
   * Zmení jednu vlastnosť vzoru / okraja bez toho, aby zmazala ostatné.
   * Vychádza sa zo zlúčenej úpravy, takže doladenie vzoru v jednej mape
   * prevezme, čo je nastavené spoločne, a nezačne od nuly.
   */
  function patchSub(id, key, patch, base) {
    // `base` je to, čo má vrstva zabudované v štýle (napr. kamienky v skalnej
    // ploche). Bez neho by prvá zmena farby vzoru zahodila jeho veľkosť
    // a hrúbku – úprava by vznikla z prázdna, nie z toho, čo je vidieť.
    const cur = { ...(base || {}), ...((layerOverride(id) || {})[key] || {}) };
    setLayerOverride(id, { [key]: { ...cur, ...patch } });
  }

  /**
   * Zahodí VŠETKY úpravy jednej vrstvy – nie len farbu.
   *
   * Rozsah je ten istý, aký hovorí prepínač hore: „len táto mapa" vyčistí
   * priečinok tejto mapy, „všetky mapy" vyčistí spoločný AJ výnimky vo
   * všetkých typoch máp. To druhé je rovnaké pravidlo ako pri `setVisible`:
   * keď povieš „všetky", nesmie ostať mapa, v ktorej to platí inak.
   *
   * Farby z palety sa NEMAŽÚ – tie sú vlastnosťou témy, nie vrstvy (jednu
   * farbu zdieľa aj desať vrstiev) a majú vlastné `⟲` priamo pri sebe.
   */
  /**
   * PORADIE KRESLENIA. Ukladá sa ako presun „túto vrstvu kresli tesne pod
   * tamtú" (`overrides.order`, rozpis pri `applyLayerOrder`), a to JEDEN NA
   * VRSTVU: pri každom ďalšom ťuknutí sa ten predošlý zahodí, takže sa
   * zoznam nenafukuje a je z neho vidieť, kde vrstva skončí.
   *
   * Poradie je SPOLOČNÉ pre všetky typy máp, aj keď sa práve zapisuje do
   * priečinka jednej mapy: čo je nad čím, je stavba mapy, nie jej téma –
   * a keby si každá mapa niesla vlastné poradie, ten istý presun by sa musel
   * naklikať štyrikrát.
   */
  function setLayerOrder(id, before) {
    overrides.order = (overrides.order || []).filter((m) => m.id !== id);
    if (before !== undefined) overrides.order.push({ id, before });
  }

  /** Vrstvy, ktoré sa dajú presúvať – v poradí, v akom sa kreslia. */
  function drawOrder() {
    return (getStyle()?.layers || []).filter((l) => {
      const meta = l.metadata || {};
      // Odvodené vrstvy (vzor, okraj) aj druhá polovica dvojice (zúbky,
      // čiarkovanie železnice) sa presúvajú so svojou predlohou.
      if (meta["frico:derived"] || meta["frico:with"]) return false;
      // Maska regiónu ostáva navrchu vždy – rozpis pri `applyLayerOrder`.
      return !REGION_MASK_LAYERS.includes(l.id);
    });
  }

  /** Ktorá vrstva sa pri presune naozaj hýbe (polovica dvojice ťahá predlohu). */
  const orderHead = (layer) =>
    (layer.metadata || {})["frico:with"] ||
    (layer.metadata || {})["frico:derived"] ||
    layer.id;

  function resetLayer(id) {
    if (editScope === "all") {
      delete overrides.layers[id];
      for (const m of Object.values(overrides.maps)) delete m.layers?.[id];
      // Aj presun v poradí kreslenia: ten je spoločný pre všetky mapy, takže
      // v rozsahu „len táto mapa" ho zrušiť nemožno – tak ako spoločnú úpravu.
      setLayerOrder(id, undefined);
    } else {
      delete mapBucket()?.layers?.[id];
    }
    pruneMaps();
  }

  /** Čo po resete v rozsahu „len táto mapa" na vrstve ešte ostane. */
  function resetLeftovers(id) {
    if (editScope === "all") return "";
    const base = baseLayerOverride(id);
    return base ? " Spoločná úprava (všetky mapy) ostane." : "";
  }

  /** Ľudské mená toho, čo sa vkladá – „paint" v stavovom riadku nikomu nepomôže. */
  const PATCH_LABELS = {
    dash: "prerušovanie čiary",
    pattern: "vzor",
    outline: "okraj",
    icon: "ikona"
  };

  /** Čo presne z odfoteného štýlu do vrstvy sadne, po ľudsky. */
  const patchText = (patch) =>
    Object.entries(patch)
      .flatMap(([key, value]) => (key === "paint" ? Object.keys(value) : [PATCH_LABELS[key] || key]))
      .join(", ");

  /** „do 1 vrstvy" / „do 3 vrstiev" – kmeň sa mení, lepiť príponu nestačí. */
  const vrstiev = (n) => (n === 1 ? "1 vrstvy" : `${n} vrstiev`);

  /** Odfotí vzhľad vrstvy do schránky panelu. */
  function copyStyle(layer) {
    styleClip = snapshotStyle(layer, layerOverride(layer.id) || {});
    clipNote = styleClip.dropped.length
      ? `Skopírované z „${styleClip.label}"; ` +
        `${styleClip.dropped.join(", ")} sa do úprav zapísať nedá ` +
        `(hodnota podľa atribútu prvku alebo vlastné prerušovanie) – ` +
        `to sa nekopíruje.`
      : `Skopírované z „${styleClip.label}".`;
  }

  /** Vloží schránku do vrstiev a povie, čo sa na ne nezmestilo. */
  function pasteStyleInto(ids) {
    if (!styleClip) return;
    const style = getStyle();
    const skipped = new Set();
    let done = 0;
    for (const id of ids) {
      const target = style.layers.find((l) => l.id === id);
      // Vrstva, z ktorej sa kopírovalo, sa preskočí: vznikla by z toho úprava
      // presne s tým, čo v štýle aj tak je – teda „zmena", ktorá nič nemení.
      if (!target || target.id === styleClip.from) continue;
      const { patch, skipped: miss } = pasteStyle(styleClip, target);
      for (const m of miss) skipped.add(m);
      if (!Object.keys(patch).length) continue;
      // `paint` sa dopĺňa po vlastnostiach, aby vloženie nezmazalo farbu,
      // ktorú si tam niekto nastavil zvlášť; ostatné kľúče sa prepíšu.
      const cur = { ...((scopedOverride(id) || {}).paint || {}) };
      setLayerOverride(id, {
        ...patch,
        ...(patch.paint ? { paint: { ...cur, ...patch.paint } } : {})
      });
      done += 1;
    }
    clipNote =
      `Vložený štýl z „${styleClip.label}" do ${vrstiev(done)}` +
      (skipped.size ? ` · neprenieslo sa: ${[...skipped].join(", ")}` : "");
  }

  /** Koľko úprav drží daný priečinok (do popisku prepínača rozsahu). */
  const countScope = (scope) =>
    scope === "all"
      ? Object.keys(overrides.layers).length + overrides.poi.hidden.length
      : Object.keys(mapBucket()?.layers || {}).length +
        (mapBucket()?.poi?.hidden || []).length;

  function setPaletteColor(key, value) {
    const theme = getTheme();
    const cur = { ...(overrides.palette[theme] || {}) };
    if (value === undefined || value.toLowerCase() === THEMES[theme][key]) delete cur[key];
    else cur[key] = value.toLowerCase();
    if (Object.keys(cur).length) overrides.palette[theme] = cur;
    else delete overrides.palette[theme];
  }

  /** Farebné vlastnosti vrstvy = všetko, čo v paint končí na `-color`. */
  const colorProps = (layer) =>
    Object.entries(layer.paint || {})
      .filter(([k, v]) => k.endsWith("-color") && typeof v === "string")
      .map(([k, v]) => [k, v]);

  const primaryColorProp = (layer) => {
    const props = colorProps(layer);
    const main = props.find(([k]) => !k.includes("halo") && !k.includes("outline"));
    return (main || props[0] || [null])[0];
  };

  const primaryColor = (layer) => {
    const prop = primaryColorProp(layer);
    return prop ? layer.paint[prop] : "#888888";
  };

  /** Podporuje vrstva vzor a okraj? (plochy a čiary áno, popisky nie) */
  const canDecorate = (layer) =>
    layer.type === "fill" || layer.type === "line" || layer.type === "fill-extrusion";

  // ---------- ovládacie prvky ----------
  function colorControl({ value, onInput, onReset, changed, note }) {
    const hex = toHex6(value);
    // Alfu drží políčko, nie pipetka – rozpis pri `alphaOf` vyššie.
    let alpha = alphaOf(value);
    const picker = el("input", { type: "color", class: "dev-color", value: hex });
    const text = el("input", {
      type: "text",
      class: "dev-hex",
      value: withAlpha(hex, alpha),
      spellcheck: "false",
      title: "#rrggbb, alebo #rrggbbaa aj s krytím"
    });
    picker.addEventListener("input", () => {
      text.value = withAlpha(picker.value, alpha);
      onInput(text.value);
    });
    text.addEventListener("change", () => {
      // Nezrozumiteľný zápis nemá prepísať farbu na čiernu: vrátime sa
      // k tomu, čo v políčku bolo, a alfa ostane, kde bola.
      if (!isHexColor(text.value)) {
        text.value = withAlpha(picker.value, alpha);
        return;
      }
      const v = normColor(text.value);
      alpha = alphaOf(v);
      text.value = v;
      picker.value = toHex6(v);
      onInput(v);
    });
    return el("div", { class: `dev-colorrow${changed ? " changed" : ""}` }, [
      picker,
      text,
      el("button", {
        type: "button",
        class: "dev-mini",
        title: "Kopírovať farbu",
        text: "⧉",
        onclick: (ev) => copyText(text.value, ev.currentTarget)
      }),
      onReset
        ? el("button", {
            type: "button",
            class: "dev-mini",
            title: "Späť na pôvodnú farbu",
            text: "⟲",
            onclick: onReset
          })
        : null,
      note ? el("span", { class: "dev-note", text: note }) : null
    ]);
  }

  /**
   * Číselné políčko.
   *
   * `stepFrom` je tá istá vec ako „auto" v placeholderi, len pre ŠÍPKY:
   * prázdne políčko typu `number` skočí šípkou dole na spodnú medzu, čiže
   * `line-width` na nulu – a vrstva ticho zmizne z mapy. Prvé stlačenie šípky
   * preto políčko naplní tým, čo tá vlastnosť práve v mape má, a ďalej sa už
   * kroky rátajú odtiaľ. (Natívne šípky myšou sa zachytiť nedajú, preto ich
   * `.dev-num` v `index.html` nemá vôbec – ostávajú klávesové, tie prejdú
   * cez tento handler.)
   */
  function numberField({ label, value, min, max, step, onChange, placeholder, stepFrom, title }) {
    const input = el("input", {
      type: "number",
      class: "dev-num",
      min,
      max,
      step,
      value: value ?? "",
      placeholder: placeholder || "",
      title: title || null
    });
    input.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowUp" && ev.key !== "ArrowDown") return;
      if (input.value !== "" || stepFrom == null) return;
      ev.preventDefault();
      input.value = String(stepFrom);
      input.dispatchEvent(new Event("change"));
    });
    input.addEventListener("change", () =>
      onChange(input.value === "" ? undefined : Number(input.value))
    );
    return el("label", { class: "dev-field" }, [el("span", { text: label }), input]);
  }

  function selectField({ label, value, options, onChange }) {
    const select = el("select", { class: "dev-select" });
    for (const [val, text] of options) {
      const opt = new Option(text, val);
      opt.selected = val === value;
      select.add(opt);
    }
    select.addEventListener("change", () => onChange(select.value));
    return el("label", { class: "dev-field" }, [el("span", { text: label }), select]);
  }

  // ---------- tab: vrstvy ----------
  /** Vrstvy, ktoré vypisujeme – odvodené (vzor, okraj) patria pod svoju predlohu. */
  function listedLayers() {
    return getStyle().layers.filter((l) => !(l.metadata || {})["frico:derived"]);
  }

  function visibleLayers() {
    const q = search.trim().toLowerCase();
    return listedLayers().filter((l) => {
      const meta = l.metadata || {};
      const kind = meta["frico:kind"] || "line";
      if (kindFilter.size && !kindFilter.has(kind)) return false;
      if (onlyActive && !activeAt(l, zoomView)) return false;
      if (!q) return true;
      const hay = `${l.id} ${meta["frico:label"] || ""} ${l["source-layer"] || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }

  function isHidden(layer) {
    return isHiddenLayer(layer);
  }

  /**
   * Zapnutie a vypnutie vrstvy.
   *
   * Zapnutie nie je vždy len „prestaň ju vypínať": vrstvu môže vypínať profil
   * typu mapy (lyžiarske trasy na turistickej mape) alebo spoločná úprava –
   * vtedy treba do tejto mapy zapísať výslovné `visible: true`, inak by sa
   * odstránením úpravy nič nezmenilo.
   */
  function setVisible(ids, visible) {
    const byProfile = mapTypeHidden(getStyle()?.layers || [], mapTypeId());
    for (const id of ids) {
      // „Všetky mapy" musí znamenať naozaj všetky: výnimka nastavená
      // v niektorej mape by inak spoločné rozhodnutie potichu prebila.
      if (editScope === "all") clearMapVisibility(id);

      if (!visible) {
        setLayerOverride(id, { visible: false });
        continue;
      }
      const forcedOff =
        byProfile.has(id) ||
        (editScope === "map" && baseLayerOverride(id)?.visible === false);
      setLayerOverride(id, { visible: forcedOff ? true : undefined });
    }
  }

  /** Zahodí výnimku „zobraziť/skryť" tejto vrstvy vo všetkých typoch máp. */
  function clearMapVisibility(id) {
    for (const m of Object.values(overrides.maps)) {
      const own = m.layers?.[id];
      if (!own || own.visible === undefined) continue;
      delete own.visible;
      if (!Object.keys(own).length) delete m.layers[id];
    }
    pruneMaps();
  }

  /**
   * „Na tomto zoome áno / nie" – to hlavné, čo od prehliadania po zoomoch
   * človek chce. Rozsah vrstvy sa posunie tak, aby zoom `z` do neho patril
   * (alebo nepatril); keď by z rozsahu nič neostalo, vrstva sa rovno vypne.
   */
  function setZoomAt(layer, z, on) {
    const patch = zoomRangeFor(layer, z, on);
    if (patch.hide) {
      setVisible([layer.id], false);
      return;
    }
    if (patch.show && isHidden(layer)) setVisible([layer.id], true);
    const { minzoom, maxzoom } = patch;
    if ("minzoom" in patch || "maxzoom" in patch) {
      setLayerOverride(layer.id, {
        ...("minzoom" in patch ? { minzoom } : {}),
        ...("maxzoom" in patch ? { maxzoom } : {})
      });
    }
  }

  /** Prepínač, do ktorého priečinka idú úpravy (a čo je práve na obrazovke). */
  function scopeBar() {
    const type = mapTypeDef(mapTypeId());
    const chip = (id, label, title) =>
      el("button", {
        type: "button",
        class: `dev-chip${editScope === id ? " on" : ""}`,
        text: `${label} (${countScope(id)})`,
        title,
        onclick: () => {
          editScope = id;
          try {
            localStorage.setItem(SCOPE_KEY, id);
          } catch {
            /* súkromný režim – rozsah sa jednoducho nezapamätá */
          }
          renderBody();
        }
      });

    return el("div", { class: "dev-scope" }, [
      el("div", { class: "dev-scoperow" }, [
        el("span", { class: "dev-bulklabel", text: `Mapa: ${type.label}` }),
        chip("map", "len táto mapa", `Úpravy sa zapíšu len pre mapu „${type.label}".`),
        chip("all", "všetky mapy", "Úpravy sa zapíšu spoločne pre všetky typy máp.")
      ]),
      el("p", { class: "dev-note", text: type.note })
    ]);
  }

  /** Celé číslo zoomu, s ktorým sa pracuje pri „na tomto zoome áno/nie". */
  const zoomCell = () => Math.min(MAX_DISPLAY_Z, Math.max(0, Math.floor(zoomView)));

  function goToZoom(z) {
    zoomView = Math.min(MAX_DISPLAY_Z, Math.max(0, Number(z)));
    getMap()?.jumpTo({ zoom: zoomView });
    // Prekreslenie ide o tik neskôr, nie priamo tu. Volá sa to totiž
    // z `change` handlera číselného políčka a Chromium neznesie, keď sa
    // uprostred spracovania udalosti vymení podstrom, v ktorom ten input
    // leží: `replaceChildren` skončí výnimkou „The node to be removed is no
    // longer a child of this node". Tá istá obchádzka je v `apply()` a bola
    // tam napísaná presne z tohto dôvodu – tu chýbala.
    setTimeout(renderBody, 0);
  }

  /**
   * Posuvník zoomu + prehľad, koľko vrstiev je na ňom povolených.
   *
   * Zoom je tu hlavný nástroj, nie len informácia: nastav zoom a potom
   * jedným klikom (štítok s rozsahom v riadku, pásik v detaile, alebo
   * hromadne pre vybrané vrstvy) povedz, čo na ňom má a nemá byť.
   */
  function zoomBar() {
    const all = listedLayers();
    const active = all.filter((l) => activeAt(l, zoomView)).length;
    const z = zoomCell();

    const slider = el("input", {
      type: "range",
      class: "dev-slider",
      min: "0",
      max: String(MAX_DISPLAY_Z),
      step: "0.5",
      value: String(Math.round(zoomView * 2) / 2)
    });
    const number = el("input", {
      type: "number",
      class: "dev-num",
      min: "0",
      max: String(MAX_DISPLAY_Z),
      step: "0.5",
      value: String(Math.round(zoomView * 10) / 10)
    });

    slider.addEventListener("input", () => {
      number.value = slider.value;
    });
    slider.addEventListener("change", () => goToZoom(slider.value));
    number.addEventListener("change", () => goToZoom(number.value));

    // Skoky na zoomy, kde sa mapa naozaj láme (prehľad → okres → mesto →
    // ulica → detail), nech sa nemusí trafovať posuvníkom.
    const jumps = [4, 8, 10, 12, 14, 16, 18, 20].map((zz) =>
      el("button", {
        type: "button",
        class: `dev-chip${z === zz ? " on" : ""}`,
        text: `z${zz}`,
        onclick: () => goToZoom(zz)
      })
    );

    return el("div", { class: "dev-zoombar" }, [
      el("div", { class: "dev-zoomrow" }, [
        el("span", { class: "dev-zoomlabel", text: `Zoom ${zoomView.toFixed(1)}` }),
        slider,
        number
      ]),
      el("div", { class: "dev-chips" }, jumps),
      el("div", { class: "dev-zoominfo" }, [
        el("span", {
          text: `Na z${z} kreslí mapa ${active} zo ${all.length} vrstiev.`
        }),
        el("button", {
          type: "button",
          class: `dev-chip${onlyActive ? " on" : ""}`,
          text: "len aktívne",
          onclick: () => {
            onlyActive = !onlyActive;
            renderBody();
          }
        })
      ]),
      el("p", {
        class: "dev-note",
        text:
          `Štítok s rozsahom v riadku (napr. z13–16) je prepínač: klik povie, ` +
          `či sa vrstva na z${z} kresliť má, alebo nie. Celý rozsah sa dá ` +
          `naklikať v pásiku v detaile vrstvy.`
      })
    ]);
  }

  /**
   * Pásik zoomov z0–z20: jedna bunka = jeden zoom, zvýraznené sú tie, na
   * ktorých sa vrstva kreslí. Klik do bunky ju zapne alebo vypne – rozsah
   * ostáva súvislý, takže z pásika je rovno vidieť, čo vrstva robí.
   */
  function zoomStrip(layer) {
    const now = zoomCell();
    const cells = [];
    for (let z = 0; z <= MAX_DISPLAY_Z; z++) {
      const on = activeAt(layer, z);
      cells.push(
        el("button", {
          type: "button",
          class: `dev-cell${on ? " on" : ""}${z === now ? " now" : ""}`,
          title: `z${z}: ${on ? "kreslí sa – klik vypne" : "nekreslí sa – klik zapne"}`,
          onclick: () => {
            setZoomAt(layer, z, !on);
            apply({ immediate: true });
          }
        })
      );
    }
    return el("div", { class: "dev-stripwrap" }, [
      el("div", { class: "dev-strip" }, cells),
      el("div", { class: "dev-striplabels" }, [
        el("span", { text: "z0" }),
        el("span", { text: "z5" }),
        el("span", { text: "z10" }),
        el("span", { text: "z15" }),
        el("span", { text: "z20" })
      ])
    ]);
  }

  function renderLayers() {
    const layers = visibleLayers();

    const searchInput = el("input", {
      type: "search",
      class: "dev-search",
      placeholder: "Hľadať vrstvu (napr. les, road-motorway…)",
      value: search
    });
    searchInput.addEventListener("input", () => {
      search = searchInput.value;
      renderBody();
      const next = body.querySelector(".dev-search");
      if (next) {
        next.focus();
        next.setSelectionRange(next.value.length, next.value.length);
      }
    });

    const chips = el("div", { class: "dev-chips" }, [
      el("button", {
        type: "button",
        class: `dev-chip${kindFilter.size ? "" : " on"}`,
        text: "Všetko",
        onclick: () => {
          kindFilter.clear();
          renderBody();
        }
      }),
      ...LAYER_KINDS.map((k) =>
        el("button", {
          type: "button",
          class: `dev-chip${kindFilter.has(k.id) ? " on" : ""}`,
          text: k.label,
          onclick: () => {
            if (kindFilter.has(k.id)) kindFilter.delete(k.id);
            else kindFilter.add(k.id);
            renderBody();
          }
        })
      )
    ]);

    // ----- hromadné operácie -----
    const bulkColor = el("input", { type: "color", class: "dev-color", value: "#ff0000" });
    const bulk = el("div", { class: `dev-bulk${selectedLayers.size ? " on" : ""}` }, [
      el("span", { class: "dev-bulklabel", text: `Vybraných: ${selectedLayers.size}` }),
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Vybrať zobrazené",
        onclick: () => {
          for (const l of visibleLayers()) selectedLayers.add(l.id);
          renderBody();
        }
      }),
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Zrušiť výber",
        onclick: () => {
          selectedLayers.clear();
          renderBody();
        }
      }),
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Zobraziť",
        onclick: () => {
          setVisible(selectedLayers, true);
          apply();
        }
      }),
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Skryť",
        onclick: () => {
          setVisible(selectedLayers, false);
          apply();
        }
      }),
      // Hromadné „na tomto zoome áno/nie": vyber vrstvy, nastav zoom a jedným
      // tlačidlom povedz, čo na ňom má byť vidieť.
      el("button", {
        type: "button",
        class: "dev-btn",
        text: `Zobraziť od z${zoomCell()}`,
        title: `Vybraným vrstvám nastaví minzoom na ${zoomCell()}`,
        onclick: () => {
          for (const id of selectedLayers) {
            setLayerOverride(id, { minzoom: zoomCell() });
          }
          setVisible(selectedLayers, true);
          apply();
        }
      }),
      el("button", {
        type: "button",
        class: "dev-btn",
        text: `Skryť na z${zoomCell()}`,
        title: `Vybrané vrstvy sa na z${zoomCell()} kresliť nebudú`,
        onclick: () => {
          const style = getStyle();
          for (const id of selectedLayers) {
            const layer = style.layers.find((l) => l.id === id);
            if (layer) setZoomAt(layer, zoomCell(), false);
          }
          apply();
        }
      }),
      bulkColor,
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Zafarbiť výber",
        onclick: () => {
          const style = getStyle();
          for (const id of selectedLayers) {
            const layer = style.layers.find((l) => l.id === id);
            const prop = layer && primaryColorProp(layer);
            if (prop) setLayerPaint(id, prop, bulkColor.value);
          }
          apply();
        }
      }),
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Kopírovať farby",
        onclick: (ev) => {
          const style = getStyle();
          const out = {};
          for (const id of selectedLayers) {
            const layer = style.layers.find((l) => l.id === id);
            if (layer) out[id] = Object.fromEntries(colorProps(layer));
          }
          copyText(JSON.stringify(out, null, 2), ev.currentTarget);
        }
      }),
      // Schránka na štýl je z detailu vrstvy, ale vložiť sa dá aj hromadne –
      // „nech všetky múry vyzerajú ako plot" je jedno zadanie, nie desať.
      styleClip
        ? el("button", {
            type: "button",
            class: "dev-btn",
            text: `⤵ Vložiť štýl z „${styleClip.label}"`,
            title: "Vloží skopírovaný štýl do všetkých vybraných vrstiev; "
              + "čo sa na ne nezmestí, povie stavový riadok",
            onclick: () => {
              pasteStyleInto([...selectedLayers]);
              apply();
            }
          })
        : null,
      el("button", {
        type: "button",
        class: "dev-btn danger",
        text: editScope === "all" ? "Reset (všetky mapy)" : "Reset (táto mapa)",
        title: "Zahodí úpravy vybraných vrstiev v tom priečinku, do ktorého sa práve zapisuje",
        onclick: () => {
          for (const id of selectedLayers) resetLayer(id);
          apply();
        }
      })
    ]);

    // ----- zoznam po skupinách -----
    const byGroup = new Map();
    for (const layer of layers) {
      const g = (layer.metadata || {})["frico:group"] || "ostatne";
      if (!byGroup.has(g)) byGroup.set(g, []);
      byGroup.get(g).push(layer);
    }
    const order = [...LAYER_GROUPS.map((g) => g.id), ...byGroup.keys()];
    const seen = new Set();
    const groups = [];

    for (const gid of order) {
      if (seen.has(gid) || !byGroup.has(gid)) continue;
      seen.add(gid);
      const list = byGroup.get(gid);
      const ids = list.map((l) => l.id);
      const nHidden = list.filter(isHidden).length;
      const nActive = list.filter((l) => activeAt(l, zoomView)).length;
      const open = !collapsed.has(gid);

      groups.push(
        el("div", { class: "dev-group" }, [
          el("button", {
            type: "button",
            class: "dev-groupname",
            text: `${open ? "▾" : "▸"} ${GROUP_LABELS[gid] || gid} (${nActive}/${list.length})`,
            title: `Na zoome ${zoomView.toFixed(1)} je aktívnych ${nActive} z ${list.length}`,
            onclick: () => {
              if (open) collapsed.add(gid);
              else collapsed.delete(gid);
              renderBody();
            }
          }),
          el("button", {
            type: "button",
            class: "dev-mini",
            title: nHidden === list.length ? "Zobraziť celú skupinu" : "Skryť celú skupinu",
            text: nHidden === list.length ? "🚫" : "👁",
            onclick: () => {
              setVisible(ids, nHidden === list.length);
              apply();
            }
          }),
          el("button", {
            type: "button",
            class: "dev-mini",
            title: "Vybrať skupinu",
            text: "☑",
            onclick: () => {
              const allSelected = ids.every((id) => selectedLayers.has(id));
              for (const id of ids) {
                if (allSelected) selectedLayers.delete(id);
                else selectedLayers.add(id);
              }
              renderBody();
            }
          })
        ])
      );

      if (open) for (const layer of list) groups.push(layerRow(layer));
    }

    return el("div", {}, [
      scopeBar(),
      zoomBar(),
      searchInput,
      chips,
      bulk,
      el("div", { class: "dev-list" }, groups)
    ]);
  }

  // ---------- tab: poradie (stoh vrstiev) ----------
  /**
   * CELÝ STOH VRSTIEV NARAZ – odhora nadol tak, ako sa kreslia.
   *
   * Záložka „Vrstvy" ich radí PO SKUPINÁCH (cesty, vodstvo, popisky), lebo
   * tam sa hľadá „kde sa nastaví hrúbka chodníka". Poradie kreslenia je ale
   * iná otázka – „čo je nad čím" – a v zozname po skupinách sa odpovedať
   * nedá: násyp a cesta sú v ňom na dvoch rôznych miestach a z ničoho nie je
   * vidieť, že násyp je vyššie. Tu je preto jeden dlhý zoznam v tom poradí,
   * v akom MapLibre kreslí: PRVÝ RIADOK JE NAVRCHU.
   *
   * Presúva sa ťahaním (myšou aj prstom cez `draggable`) alebo šípkami; oboje
   * zapisuje to isté, čo sekcia „Poradie kreslenia" v detaile vrstvy –
   * `overrides.order`, teda presun „kresli tesne pod tamtú" (rozpis pri
   * `applyLayerOrder`).
   */
  function renderStack() {
    const poradie = drawOrder();
    // Odhora nadol: prvý riadok je posledná vrstva štýlu, teda tá navrchu.
    const zhora = [...poradie].reverse();
    const q = stackSearch.trim().toLowerCase();
    const presuny = new Set((overrides.order || []).map((m) => m.id));

    const hladanie = el("input", {
      type: "search",
      class: "dev-search",
      placeholder: "Hľadať vrstvu v stohu (napr. násyp, road-motorway…)",
      value: stackSearch
    });
    hladanie.addEventListener("input", () => {
      stackSearch = hladanie.value;
      renderBody();
      const next = body.querySelector(".dev-search");
      if (next) {
        next.focus();
        next.setSelectionRange(next.value.length, next.value.length);
      }
    });

    /** Kam presun zapíše `before`, keď má vrstva skončiť tesne NAD `cielom`. */
    const nadCiel = (cielIndex) => {
      // „Nad" v zozname zhora nadol znamená „kreslí sa neskôr", teda tesne
      // pred vrstvu, ktorá je nad cieľom. Nad prvým riadkom už nič nie je –
      // vtedy je to „úplne navrch" (`null`).
      const vyssie = zhora[cielIndex - 1];
      return vyssie ? vyssie.id : null;
    };

    const presun = (id, before) => {
      setLayerOrder(id, before);
      apply({ immediate: true });
    };

    const riadok = (layer, i) => {
      const meta = layer.metadata || {};
      const kind = meta["frico:kind"] || "line";
      const hidden = isHidden(layer);
      const inactive = !activeAt(layer, zoomView);
      const zmeneny = presuny.has(layer.id);
      // Vzor, okraj a druhá polovica dvojice sa presúvajú s ňou – nech je
      // vidieť, že sa nehýbe jedna vrstva, ale prvok.
      const rodina = (getStyle()?.layers || []).filter(
        (l) => (l.metadata || {})["frico:derived"] === layer.id ||
               (l.metadata || {})["frico:with"] === layer.id
      ).length;

      const row = el("div", {
        class:
          `dev-stackrow${zmeneny ? " changed" : ""}${hidden ? " off" : ""}` +
          `${inactive && !hidden ? " inactive" : ""}`,
        // Reťazec, nie `true`: `draggable` je vymenovaný atribút a prázdna
        // hodnota znamená „auto", teda NEŤAHATEĽNÉ – riadok by sa chytiť
        // nedal a nikde by to nezasvietilo.
        draggable: q ? null : "true",
        title: `${layer.id} · ${zhora.length - i}. odspodku`
      }, [
        el("span", { class: "dev-grip", text: q ? "·" : "⠿" }),
        el("button", {
          type: "button",
          class: "dev-mini",
          title: hidden ? "Zobraziť vrstvu" : "Skryť vrstvu",
          text: hidden ? "🚫" : "👁",
          onclick: () => {
            setVisible([layer.id], hidden);
            apply();
          }
        }),
        el("span", { class: `dev-kind k-${kind}`, text: KIND_LABELS[kind] || kind }),
        el("span", { class: "dev-swatch", style: `background:${primaryColor(layer)}` }),
        el("button", {
          type: "button",
          class: "dev-name",
          title: "Otvoriť túto vrstvu v záložke Vrstvy",
          onclick: () => {
            tab = "layers";
            search = layer.id;
            expanded.add(layer.id);
            collapsed.delete(meta["frico:group"]);
            render();
          }
        }, [
          el("span", { text: meta["frico:label"] || layer.id }),
          el("small", {
            text:
              `${layer.id}` +
              `${rodina ? ` +${rodina}` : ""}` +
              ` · ${GROUP_LABELS[meta["frico:group"]] || meta["frico:group"] || ""}`
          })
        ]),
        el("button", {
          type: "button",
          class: "dev-mini",
          text: "▲",
          disabled: i === 0 ? true : null,
          title: i === 0 ? "Vyššie to už nejde" : `Kresliť nad „${zhora[i - 1].metadata["frico:label"] || zhora[i - 1].id}"`,
          onclick: () => presun(layer.id, nadCiel(i - 1))
        }),
        el("button", {
          type: "button",
          class: "dev-mini",
          text: "▼",
          disabled: i === zhora.length - 1 ? true : null,
          title:
            i === zhora.length - 1
              ? "Nižšie to už nejde"
              : `Kresliť pod „${zhora[i + 1].metadata["frico:label"] || zhora[i + 1].id}"`,
          onclick: () => presun(layer.id, zhora[i + 1].id)
        }),
        zmeneny
          ? el("button", {
              type: "button",
              class: "dev-mini",
              text: "⟲",
              title: "Späť na poradie zo štýlu",
              onclick: () => presun(layer.id, undefined)
            })
          : null
      ]);

      // ŤAHANIE. Kam vrstva padne, hovorí polovica riadka, nad ktorou kurzor
      // je: horná = nad tento riadok, dolná = pod neho. Bez toho by sa nedalo
      // povedať, či ide o „pred" alebo „za" – a jedna z tých dvoch odpovedí
      // by vždy chýbala (napr. úplne navrch).
      row.addEventListener("dragstart", (ev) => {
        dragId = layer.id;
        ev.dataTransfer.effectAllowed = "move";
        // Bez `setData` Firefox ťahanie vôbec nespustí.
        ev.dataTransfer.setData("text/plain", layer.id);
        row.classList.add("dragging");
      });
      row.addEventListener("dragend", () => {
        dragId = null;
        row.classList.remove("dragging");
      });
      row.addEventListener("dragover", (ev) => {
        if (!dragId || dragId === layer.id) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
        const r = row.getBoundingClientRect();
        const hore = ev.clientY < r.top + r.height / 2;
        row.classList.toggle("drop-above", hore);
        row.classList.toggle("drop-below", !hore);
      });
      row.addEventListener("dragleave", () => {
        row.classList.remove("drop-above", "drop-below");
      });
      row.addEventListener("drop", (ev) => {
        ev.preventDefault();
        row.classList.remove("drop-above", "drop-below");
        if (!dragId || dragId === layer.id) return;
        const r = row.getBoundingClientRect();
        const hore = ev.clientY < r.top + r.height / 2;
        presun(dragId, hore ? nadCiel(i) : layer.id);
        dragId = null;
      });
      return row;
    };

    const rows = zhora
      .map((layer, i) => [layer, i])
      .filter(([layer]) =>
        !q ||
        layer.id.toLowerCase().includes(q) ||
        String((layer.metadata || {})["frico:label"] || "").toLowerCase().includes(q))
      .map(([layer, i]) => riadok(layer, i));

    return el("div", {}, [
      el("p", {
        class: "dev-hint",
        html:
          "Celý stoh vrstiev tak, ako sa kreslia: <b>prvý riadok je navrchu</b>. " +
          "Presuň vrstvu ťahaním za <b>⠿</b> alebo šípkami – napríklad násyp " +
          "(<code>feature-embankment</code>) pod cesty. Vzor, okraj aj druhá " +
          "polovica dvojice (zúbky hrany, čiarkovanie železnice) idú s ňou; " +
          "maska regiónu ostáva navrchu vždy. Poradie platí pre všetky typy máp " +
          "a ukladá sa do <code>style-overrides.json</code>."
      }),
      zoomBar(),
      hladanie,
      q
        ? el("p", {
            class: "dev-hint",
            text:
              "Kým je zadané hľadanie, ťahať sa nedá – v prefiltrovanom zozname " +
              "nie je vidieť, medzi ktoré dve vrstvy by vrstva padla. Šípky " +
              "fungujú ďalej a posúvajú po skutočnom poradí."
          })
        : null,
      el("div", { class: "dev-bulk on" }, [
        el("span", {
          class: "dev-bulklabel",
          text: `${zhora.length} vrstiev · ${presuny.size} presunutých`
        }),
        presuny.size
          ? el("button", {
              type: "button",
              class: "dev-btn danger",
              text: "Späť na pôvodné poradie",
              title: "Zahodí všetky presuny; farby, zoomy a ostatné úpravy ostanú",
              onclick: () => {
                overrides.order = [];
                apply({ immediate: true });
              }
            })
          : null
      ]),
      el("div", { class: "dev-stack" }, rows)
    ]);
  }

  function layerRow(layer) {
    const meta = layer.metadata || {};
    const kind = meta["frico:kind"] || "line";
    const o = layerOverride(layer.id);
    const hidden = isHidden(layer);
    const open = expanded.has(layer.id);
    const inactive = !activeAt(layer, zoomView);

    const check = el("input", { type: "checkbox", class: "dev-check" });
    check.checked = selectedLayers.has(layer.id);
    check.addEventListener("change", () => {
      if (check.checked) selectedLayers.add(layer.id);
      else selectedLayers.delete(layer.id);
      const label = body.querySelector(".dev-bulklabel");
      if (label) label.textContent = `Vybraných: ${selectedLayers.size}`;
    });

    // Riadok rozlišuje „mám to upravené v tejto mape" od „mám to upravené
    // spoločne" – inak by sa nedalo poznať, kde úprava vlastne sedí.
    const scoped = scopedOverride(layer.id);
    const cls =
      `dev-row${o ? " changed" : ""}${scoped ? " scoped" : ""}` +
      `${hidden ? " off" : ""}${inactive && !hidden ? " inactive" : ""}`;
    const head = el("div", { class: cls }, [
      check,
      el("button", {
        type: "button",
        class: "dev-mini",
        title: hidden
          ? `Zobraziť vrstvu (${editScope === "all" ? "vo všetkých mapách" : "v tejto mape"})`
          : `Skryť vrstvu (${editScope === "all" ? "vo všetkých mapách" : "v tejto mape"})`,
        text: hidden ? "🚫" : "👁",
        onclick: () => {
          setVisible([layer.id], hidden);
          apply();
        }
      }),
      el("span", { class: `dev-kind k-${kind}`, text: KIND_LABELS[kind] || kind }),
      // ČO MÁ VRSTVA NAVYŠE, MUSÍ BYŤ VIDIEŤ AJ ZATVORENÉ. Rozlíšenie podľa
      // `kľúč = hodnota` je samostatná vrstva s vlastnou ikonou a farbou –
      // kým sa o ňom dalo dozvedieť len rozbalením detailu, dalo sa naklikať
      // a zabudnúť naň. To isté platí o obryse: „Miestne cesty – obrys" a
      // „Miestne cesty" sú v zozname vedľa seba a líšia sa jedným slovom.
      (o?.variants || []).length
        ? el("span", {
            class: "dev-varbadge",
            text: `${o.variants.length}×`,
            title: o.variants
              .map((v) => `${v.attr} = ${v.values.join(", ")}: ${variantSummary(v) || "bez štýlu"}`)
              .join("\n")
          })
        : null,
      (layer.metadata || {})["frico:border-of"]
        ? el("span", { class: "dev-borderbadge", text: "obrys" })
        : null,
      el("button", {
        type: "button",
        class: "dev-name",
        title: `${layer.id} – klikni pre detaily`,
        onclick: () => {
          if (open) expanded.delete(layer.id);
          else expanded.add(layer.id);
          renderBody();
        }
      }, [
        el("span", { text: `${open ? "▾ " : "▸ "}${meta["frico:label"] || layer.id}` }),
        el("small", { text: layer.id })
      ]),
      // Štítok s rozsahom je zároveň prepínač „na tomto zoome áno / nie" –
      // to je pri prezeraní po zoomoch tá najčastejšia úprava vôbec.
      el("button", {
        type: "button",
        class: `dev-zrange${inactive ? " off" : ""}`,
        text: zoomRangeText(layer),
        title: inactive
          ? `Na z${zoomCell()} sa nekreslí – klikni, nech sa kreslí`
          : `Na z${zoomCell()} sa kreslí – klikni, nech sa nekreslí`,
        onclick: () => {
          setZoomAt(layer, zoomCell(), inactive);
          apply({ immediate: true });
        }
      })
    ]);

    return el("div", { class: "dev-item" }, [head, open ? layerDetails(layer) : null]);
  }

  /** Nadpis sekcie v detaile vrstvy – aby bolo vidieť, čo sa kde nastavuje. */
  const sectionTitle = (text, note) =>
    el("div", { class: "dev-h5" }, [
      el("span", { text }),
      note ? el("small", { text: note }) : null
    ]);

  /**
   * Výber prerušovania čiary s náhľadom. Samotný názov („Čiarkovaná") o čiare
   * veľa nepovie – vedľa výberu sa preto rovno kreslí, ako bude vyzerať.
   *
   * `builtin` je to, čo má vrstva zo štýlu (`frico:dash` – predvoľba alebo
   * rovno pole čísel). Keď je zadané, pribudne prvá položka „zo štýlu": to je
   * odpoveď na „nechaj, ako to bolo", ktorú sa menom predvoľby povedať nedá –
   * železnica má `rail`, brod vlastné `[1, 1]` a zúbky brala `[0.35, 2.2]`,
   * ktoré medzi predvoľbami vôbec nie sú.
   */
  function dashField({ label, value, onChange, builtin }) {
    const preview = el("span", { class: "dev-dash" });
    const draw = (id) => {
      const d = dashPreview(id === "" ? builtin : id, 2);
      preview.innerHTML =
        `<svg width="54" height="10" viewBox="0 0 54 10" aria-hidden="true">` +
        `<line x1="1" y1="5" x2="53" y2="5" stroke="currentColor" stroke-width="2"` +
        (d ? ` stroke-dasharray="${d}"` : "") +
        `/></svg>`;
    };
    draw(value);
    const field = selectField({
      label,
      value,
      options: [
        ...(builtin !== undefined ? [["", `— zo štýlu (${dashLabel(builtin)}) —`]] : []),
        ...DASH_PRESETS.map((d) => [d.id, d.label])
      ],
      onChange: (v) => {
        draw(v);
        onChange(v);
      }
    });
    return el("span", { class: "dev-dashrow" }, [field, preview]);
  }

  /**
   * „OD ZOOMU PO ZOOM TOTO" – JEDEN editor pre každé číslo aj farbu vrstvy.
   *
   * PREČO JEDEN. Tá istá otázka („čo má vrstva robiť na ktorom zoome") mala
   * v paneli ŠTYRI ovládania vedľa seba: pevné číslo, `× a +` hneď za ním,
   * krivku zoomových zlomov a zoomové pásma – každé s vlastným tvarom
   * hodnoty aj vlastným tlačidlom. Ktoré z nich použiť, sa nedalo uhádnuť
   * a dve si priamo protirečili (pevné číslo zahodí krivku), takže sa jedno
   * muselo ZAMYKAŤ, keď bolo vyplnené druhé. Panel tak mal štyri páky na
   * jednu vec a tri z nich boli väčšinu času zhasnuté.
   *
   * TERAZ JE TO JEDEN ZOZNAM PÁSIEM, ktorý vždy pokrýva celý rozsah zoomov:
   *
   *     z0 – z13    100 %
   *     z14 – z20   110 %
   *
   * a k nemu jediná otázka navyše: či sa hodnota zadáva ako PERCENTO z toho,
   * čo počíta štýl (zoomová krivka zo štýlu ostáva, mení sa jej mierka –
   * „na z19 nech je to o desatinu väčšie"), alebo ako PEVNÁ hodnota. Jedno
   * pásmo cez celý rozsah je presne to, čo bývalo „pevné číslo" a „× a +",
   * takže sa nestratilo nič – len sa to prestalo pýtať štyrikrát.
   *
   * `smooth` je posledný zvyšok krivky: pri pevných hodnotách sa dá povedať,
   * či sa medzi pásmami hodnota LÁME (schodisko, `step`), alebo PRECHÁDZA
   * (krivka, `interpolate`). Je to zaškrtávacie políčko pod zoznamom, nie
   * prepínač tvaru: riadky sú v oboch prípadoch tie isté. Percento je vždy
   * plynulé – preškálovaná krivka je stále krivka.
   */

  /** Otvorené rozpisy podľa zoomu – kľúč je `${vrstva}:${kde}:${vlastnosť}`. */
  const zoomOpen = new Set();

  /** Číslo do políčka – bez zbytočných desatín. */
  const fmtNum = (v) => (typeof v === "number" ? Math.round(v * 100) / 100 : v);

  /** Percento, ako ho vidí človek (`{scale: 1.1}` → 110). */
  const pctOf = (v) => Math.round((v?.scale ?? 1) * 100);

  /**
   * Percento späť do uloženej hodnoty. `add` sa NESIE ĎALEJ, hoci ho panel
   * neponúka: ručne upravený súbor ho dovoliť môže a tichý zánik konštanty
   * pri prvom ťuknutí do percenta by bola zmena mapy, ktorú nikto nechcel.
   */
  const relWithPct = (rel, percento) => ({
    scale: Math.round(Math.min(1000, Math.max(10, percento))) / 100,
    ...(rel && rel.add != null ? { add: rel.add } : {})
  });

  /**
   * Uložená hodnota → riadky editora `[[od, do, hodnota], …]`.
   *
   * `rows: null` znamená „úprava nie je" – vtedy platí, čo počíta štýl.
   * Zoznam vždy vyjde SÚVISLÝ: `do` každého riadku je `od` nasledujúceho
   * mínus jedna, posledný siaha po strop zobrazenia. Vďaka tomu sa medzera
   * ani prekryv nedajú naklikať (`cleanPaintBands` by ich odmietol a s nimi
   * celú vlastnosť).
   */
  function readRows(value) {
    if (value === undefined) return { rows: null, mode: null, smooth: false };
    if (isRelative(value)) {
      return { rows: [[0, MAX_DISPLAY_Z, value]], mode: "rel", smooth: false };
    }
    if (Array.isArray(value) && value.length && Array.isArray(value[0])) {
      if (isBandList(value)) {
        const b = sortBands(value);
        return {
          rows: b.map(([od, doZ, v], i) => [
            od,
            i + 1 < b.length ? b[i + 1][0] - 1 : Math.max(doZ, MAX_DISPLAY_Z),
            v
          ]),
          mode: b.some(([, , v]) => isRelative(v)) ? "rel" : "abs",
          smooth: false
        };
      }
      // KRIVKA (zoomové zlomy) sa ukazuje tými istými riadkami: zlom je
      // začiatok pásma a „plynulý prechod" je zaškrtnutý. Tak sa dá doladiť
      // aj to, čo vzniklo kopírovaním štýlu z inej vrstvy (`snapshotStyle`
      // krivku zo štýlu odfotí ako zlomy), bez druhého ovládania.
      const st = sortStops(value.filter((s) => Array.isArray(s) && s.length === 2));
      if (st.length) {
        return {
          rows: st.map(([z, v], i) => [
            z,
            i + 1 < st.length ? st[i + 1][0] - 1 : MAX_DISPLAY_Z,
            v
          ]),
          mode: "abs",
          smooth: true
        };
      }
    }
    return { rows: [[0, MAX_DISPLAY_Z, value]], mode: "abs", smooth: false };
  }

  /** Riadky späť do tvaru, ktorý pozná súbor úprav. */
  function writeRows(rows, mode, smooth) {
    if (!rows || !rows.length) return undefined;
    if (rows.length === 1) {
      const v = rows[0][2];
      // Sto percent nie je úprava, je to „nechaj, čo počíta štýl" – a takú
      // vetu netreba ukladať (`cleanRelative` by ju aj tak zahodila).
      if (isRelative(v) && (v.scale ?? 1) === 1 && (v.add ?? 0) === 0) return undefined;
      return v;
    }
    if (mode === "abs" && smooth) return rows.map(([od, , v]) => [od, v]);
    return rows.map(([od, doZ, v]) => [od, doZ, v]);
  }

  /**
   * @param {object} opts
   * @param {string} opts.key         kde to je (drží si „rozbalené")
   * @param {string} opts.label       meno vlastnosti po ľudsky
   * @param {"number"|"color"} opts.kind
   * @param {*} opts.styleValue       čo tú vlastnosť počíta štýl (základ percenta)
   * @param {*} opts.value            úprava, ako je uložená
   * @param {(next: *) => void} opts.onChange  `undefined` = späť na štýl
   */
  function zoomValueEditor({
    key, label, kind = "number", min, max, step, unit = "",
    styleValue, value, onChange, allowPercent = kind !== "color", note
  }) {
    const stav = readRows(value);
    const mode = stav.mode || (allowPercent ? "rel" : "abs");
    const smooth = stav.smooth;
    const zNow = zoomCell();
    // `styleAt` je to, čo na tom zoome počíta štýl (farba aj číslo), `baseAt`
    // je to isté len pre čísla – percento sa nedá počítať z hexu a `null`
    // z neho je poctivejšia odpoveď než nula.
    const styleAt = (z) => valueAtZoom(styleValue, z);
    const baseAt = (z) => {
      const v = styleAt(z);
      return typeof v === "number" ? v : null;
    };
    const vychodzia = () =>
      mode === "rel"
        ? { scale: 1 }
        : styleAt(zNow) ?? (kind === "color" ? "#888888" : min ?? 1);
    const rows = stav.rows || [[0, MAX_DISPLAY_Z, vychodzia()]];
    const zmenene = value !== undefined;
    const rozbalene = rows.length > 1 || zoomOpen.has(key);

    const zapis = (next, m = mode, s = smooth) => {
      onChange(writeRows(next, m, s));
      apply({ immediate: true });
    };

    /** Riadky s dopočítaným `do` – hranicu drží `od` nasledujúceho. */
    const zosuvisli = (list) => {
      const zoradene = [...list].sort((a, b) => a[0] - b[0]);
      return zoradene.map(([od, doZ, v], i) => [
        od,
        i + 1 < zoradene.length ? zoradene[i + 1][0] - 1 : Math.max(od, MAX_DISPLAY_Z),
        v
      ]);
    };

    const setRow = (i, patch) =>
      zapis(zosuvisli(rows.map((r, j) => (j === i ? [patch.od ?? r[0], r[1], "v" in patch ? patch.v : r[2]] : r))));

    /** Ovládanie hodnoty jedného riadku. */
    const valueCell = (i) => {
      const v = rows[i][2];
      if (kind === "color") {
        return colorControl({
          value: typeof v === "string" ? v : "#888888",
          changed: zmenene,
          onInput: (c) => {
            onChange(writeRows(rows.map((r, j) => (j === i ? [r[0], r[1], c] : r)), mode, smooth));
            apply({ rerender: false });
          }
        });
      }
      if (mode === "rel") {
        const input = el("input", {
          type: "number", class: "dev-num dev-pct",
          min: "10", max: "1000", step: "5",
          value: String(pctOf(isRelative(v) ? v : null)),
          title: `${label}: percento z toho, čo na tomto zoome počíta štýl. `
            + `100 % = bez zmeny.`
        });
        input.addEventListener("change", () =>
          setRow(i, { v: relWithPct(isRelative(v) ? v : null, Number(input.value)) })
        );
        const zoStyle = baseAt(rows[i][0]);
        return el("span", { class: "dev-valcell" }, [
          input,
          el("span", { class: "dev-unit", text: "%" }),
          zoStyle == null
            ? null
            : el("small", {
                class: "dev-note",
                text: `= ${fmtNum(zoStyle * (isRelative(v) ? v.scale ?? 1 : 1) + (isRelative(v) ? v.add ?? 0 : 0))}${unit}`
              })
        ]);
      }
      const input = el("input", {
        type: "number", class: "dev-num",
        min, max, step,
        value: typeof v === "number" ? String(fmtNum(v)) : "",
        placeholder: String(fmtNum(baseAt(rows[i][0]) ?? "")),
        title: `${label}: pevná hodnota na týchto zoomoch`
      });
      input.addEventListener("change", () =>
        setRow(i, { v: input.value === "" ? baseAt(rows[i][0]) ?? min ?? 0 : Number(input.value) })
      );
      return el("span", { class: "dev-valcell" }, [
        input,
        unit ? el("span", { class: "dev-unit", text: unit }) : null
      ]);
    };

    /** Jeden riadok pásma: `z od – do`, hodnota, kôš. */
    const rowEl = (i) => {
      const [od, doZ] = rows[i];
      // Hranica sa smie posunúť len tam, kde ostane pásmo aj susedovi – inak
      // by z posunu vypadol prázdny rozsah. Prvé pásmo smie začínať aj nad
      // z0: to, čo je pod ním, drží jeho hodnotu (`step` aj `interpolate`
      // pod prvým zlomom nič neinterpolujú). Práve tak vyzerá krivka
      // odfotená z inej vrstvy – prvý zlom má tam, kde ho má štýl.
      const dolna = i === 0 ? 0 : rows[i - 1][0] + 1;
      const horna = doZ;
      const zInput = el("input", {
        type: "number", class: "dev-num dev-num-z",
        min: String(dolna), max: String(horna), step: "1", value: String(od),
        title: `Od tohto zoomu platí riadok (${dolna}–${horna})`
      });
      zInput.addEventListener("change", () =>
        setRow(i, { od: Math.min(Math.max(Number(zInput.value), dolna), horna) })
      );
      return el("div", { class: `dev-zrow${od <= zNow && zNow <= doZ ? " now" : ""}` }, [
        el("span", { class: "dev-stopz", text: "z" }),
        zInput,
        el("span", { class: "dev-stopz", text: `– z${doZ}` }),
        valueCell(i),
        rows.length > 1
          ? el("button", {
              type: "button", class: "dev-mini",
              title: "Zrušiť toto pásmo – pohltí ho susedné, aby nevznikla medzera",
              text: "×",
              onclick: () => {
                const zvysok = rows.filter((_, j) => j !== i);
                if (i === 0) zvysok[0] = [0, zvysok[0][1], zvysok[0][2]];
                zapis(zosuvisli(zvysok));
              }
            })
          : null
      ]);
    };

    // ---- hlavička: meno, hodnota (pri jedinom pásme), prepínač %, reset ----
    const modeBtn = (id, text, title) =>
      el("button", {
        type: "button",
        class: `dev-mini dev-modebtn${mode === id ? " on" : ""}`,
        text,
        title,
        onclick: () => {
          if (mode === id) return;
          // PREPNUTIE NIČ NEZAHODÍ: percento sa vyčísli nad tým, čo počíta
          // štýl na začiatku pásma, a pevná hodnota sa naopak prepočíta na
          // percento. Presné to byť nemôže (percento drží krivku, pevná
          // hodnota ju zahadzuje), ale prázdny zoznam by bol horší.
          const next = rows.map(([od, doZ, v]) => {
            const zaklad = baseAt(od);
            if (id === "rel") {
              const pomer = zaklad && typeof v === "number" ? v / zaklad : 1;
              return [od, doZ, relWithPct(null, Math.round(pomer * 100))];
            }
            const cislo = isRelative(v)
              ? (zaklad ?? 1) * (v.scale ?? 1) + (v.add ?? 0)
              : v;
            return [od, doZ, fmtNum(typeof cislo === "number" ? cislo : zaklad ?? 1)];
          });
          zapis(next, id, smooth);
        }
      });

    const head = el("div", { class: `dev-zvhead${zmenene ? " changed" : ""}` }, [
      el("span", { class: "dev-propname", text: label }),
      ...(rows.length === 1 ? [valueCell(0)] : []),
      ...(allowPercent && kind !== "color"
        ? [
            el("span", { class: "dev-modes" }, [
              modeBtn("rel", "% štýlu", "Percento z toho, čo počíta štýl – zoomová krivka "
                + "zo štýlu ostane, mení sa len jej mierka"),
              modeBtn("abs", "pevná", "Pevná hodnota – zoomová krivka zo štýlu sa zahodí")
            ])
          ]
        : []),
      zmenene
        ? el("button", {
            type: "button", class: "dev-mini",
            title: `Späť na to, čo počíta štýl (${label})`,
            text: "⟲",
            onclick: () => {
              zoomOpen.delete(key);
              onChange(undefined);
              apply({ immediate: true });
            }
          })
        : el("button", {
            type: "button", class: "dev-mini",
            title: "Rozpísať hodnotu po zoomoch",
            text: rozbalene ? "▾ zoom" : "▸ zoom",
            onclick: () => {
              if (zoomOpen.has(key)) zoomOpen.delete(key);
              else zoomOpen.add(key);
              renderBody();
            }
          })
    ]);

    if (!rozbalene) {
      return el("div", { class: "dev-zv" }, [head, note ? el("small", { class: "dev-note", text: note }) : null]);
    }

    const plno = rows.length >= MAX_PAINT_STOPS;
    const uzTam = rows.some(([od]) => od === zNow) || zNow === 0;
    const split = el("button", {
      type: "button",
      class: "dev-mini dev-addstop",
      text: `+ rozdeliť pri z${zNow}`,
      disabled: plno || uzTam || null,
      title: plno
        ? `Viac než ${MAX_PAINT_STOPS} pásiem sa do úprav nezmestí`
        : uzTam
          ? `Na z${zNow} už pásmo začína – zmeň ho v riadku vyššie`
          : `Rozdelí pásmo na zoome, kde práve stojí mapa`,
      onclick: () => {
        const i = rows.findIndex(([od, doZ]) => zNow > od && zNow <= doZ);
        if (i < 0) return;
        const [, doZ, v] = rows[i];
        zapis(zosuvisli([
          ...rows.slice(0, i),
          [rows[i][0], zNow - 1, v],
          [zNow, doZ, isRelative(v) ? { ...v } : v],
          ...rows.slice(i + 1)
        ]));
      }
    });

    const plynule = el("input", { type: "checkbox", class: "dev-check" });
    plynule.checked = smooth;
    plynule.addEventListener("change", () => zapis(rows, mode, plynule.checked));

    return el("div", { class: "dev-zv" }, [
      head,
      ...(rows.length > 1 ? rows.map((_, i) => rowEl(i)) : []),
      el("div", { class: "dev-zvfoot" }, [
        split,
        mode === "abs" && rows.length > 1
          ? el("label", { class: "dev-inline" }, [
              plynule,
              el("span", { text: "plynulý prechod medzi pásmami" })
            ])
          : null,
        note ? el("small", { class: "dev-note", text: note }) : null
      ])
    ]);
  }

  /**
   * Editor nad jednou vlastnosťou VRSTVY (`paint` alebo `layout`) – tenká
   * obálka nad `zoomValueEditor`, aby sa čítanie a zápis nepísali na desiatich
   * miestach znova.
   */
  function layerValueEditor(layer, prop, opts = {}) {
    const where = opts.where || "paint";
    const o = layerOverride(layer.id) || {};
    const zapisVlastnost = where === "layout" ? setLayerLayout : setLayerPaint;
    // Vlastnosť, ktorú štýl nenastavil, nie je „nič" – pri `layout` platí
    // predvoľba MapLibre, a bez nej by percento nemalo čo násobiť.
    const vStyle = (layer[where] || {})[prop];
    const styleValue =
      vStyle !== undefined
        ? vStyle
        : where === "layout"
          ? LAYOUT_PROPS[prop]?.def
          : PAINT_DEFAULTS[prop];
    return zoomValueEditor({
      key: `${layer.id}:${where}:${prop}`,
      label: opts.label || prop,
      kind: opts.kind || "number",
      min: opts.min,
      max: opts.max,
      step: opts.step,
      unit: opts.unit || "",
      note: opts.note,
      styleValue,
      value: (o[where] || {})[prop],
      onChange: (next) => zapisVlastnost(layer.id, prop, next)
    });
  }

  /**
   * KTORÉ `layout` VLASTNOSTI SA NA TEJTO VRSTVE DAJÚ LADIŤ.
   *
   * Nie „tie, ktoré už má". Kým sa ponúkali len tie, ktoré štýl NASTAVIL,
   * nedala sa žiadna zaviesť – rozostup šípok jednosmeriek sa zmeniť dal
   * (štýl mu dáva 120), ale miesto okolo ikony nie, lebo ho štýl nechal na
   * predvolenom. Vyzeralo to, že tá páka neexistuje, hoci chýbal len riadok.
   *
   * Ponúka sa preto to, čo na vrstve niečo ZNAMENÁ – a to sa dá prečítať
   * z jej `layout`: veľkosť a odsadenie ikony má zmysel tam, kde ikona je,
   * veľkosť písma tam, kde je text, a rozostup len pri symboloch kladených
   * POZDĹŽ ČIARY (pri bodovom umiestnení je `symbol-spacing` bez účinku, teda
   * by to bolo políčko, ktoré vyzerá, že niečo robí, a nerobí nič).
   */
  function layoutPropsFor(layer) {
    const L = layer.layout || {};
    const maIkonu = L["icon-image"] !== undefined;
    const maText = L["text-field"] !== undefined;
    const poCiare = L["symbol-placement"] === "line" || L["symbol-placement"] === "line-center";
    return LAYOUT_PROP_IDS.filter((prop) => {
      if (prop === "text-size") return maText;
      if (prop === "icon-size" || prop === "icon-padding") return maIkonu;
      if (prop === "symbol-spacing") return poCiare;
      return false;
    });
  }

  /**
   * Panel nad detailom vrstvy: schránka na štýl a reset.
   *
   * Sú tu spolu naschvál – oboje je o CELEJ vrstve, nie o jednej vlastnosti,
   * a oboje dovtedy chýbalo: vrátiť sa dala len farba (každá zvlášť), takže
   * „daj to naspäť, ako to bolo" znamenalo prejsť všetky sekcie po jednej,
   * a „nech to vyzerá ako tamto" sa nedalo povedať vôbec.
   */
  function layerTools(layer) {
    const o = layerOverride(layer.id);
    const scoped = scopedOverride(layer.id);
    const kam = editScope === "all" ? "všetkých mapách" : `mape „${mapTypeDef(mapTypeId()).label}"`;
    const row = [
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "⧉ Skopírovať štýl",
        title: "Odfotí, ako táto vrstva vyzerá (farby, hrúbky, prerušovanie, "
          + "vzor, okraj), a ponúkne to na vloženie do inej vrstvy",
        onclick: () => {
          copyStyle(layer);
          renderBody();
          renderStatus();
        }
      })
    ];

    if (styleClip && styleClip.from !== layer.id) {
      const { patch, skipped } = pasteStyle(styleClip, layer);
      const moze = Object.keys(patch).length > 0;
      row.push(
        el("button", {
          type: "button",
          class: "dev-btn",
          text: `⤵ Vložiť štýl z „${styleClip.label}"`,
          disabled: moze ? null : true,
          title: moze
            ? `Vloží ${patchText(patch)} do tejto vrstvy (v ${kam})`
              + (skipped.length ? ` · neprenesie sa: ${skipped.join(", ")}` : "")
            : `Z „${styleClip.label}" (${styleClip.type}) sa na vrstvu typu `
              + `${layer.type} nedá preniesť nič`,
          onclick: () => {
            pasteStyleInto([layer.id]);
            apply({ immediate: true });
          }
        })
      );
    }

    if (o) {
      // Rozsah rozhoduje aj o tom, či je čo zahodiť: v „len táto mapa" sa
      // spoločná úprava zrušiť NEDÁ a tlačidlo, ktoré po stlačení nič
      // neurobí, je horšie než zhasnuté – povie prečo.
      const mozeReset = editScope === "all" || !!scoped;
      row.push(
        el("button", {
          type: "button",
          class: "dev-btn danger",
          text: editScope === "all" ? "⟲ Reset (všetky mapy)" : "⟲ Reset (táto mapa)",
          disabled: mozeReset ? null : true,
          title: mozeReset
            ? `Zahodí VŠETKY úpravy tejto vrstvy v ${kam} – viditeľnosť, `
              + `zoomy, farby, hrúbky, ikonu, vzor, okraj`
              + `${editScope === "all" ? " aj poradie kreslenia" : ""}.`
              + `${resetLeftovers(layer.id)} `
              + `Farby z palety ostávajú, tie patria téme.`
            : "Úprava tejto vrstvy je spoločná pre všetky mapy – zrušiť sa dá "
              + `len v rozsahu „všetky mapy" (prepínač hore).`,
          onclick: () => {
            resetLayer(layer.id);
            apply({ immediate: true });
          }
        })
      );
    }

    return el("div", { class: "dev-tools" }, row);
  }

  /**
   * DETAIL VRSTVY – zhora nadol tak, ako sa mapa ladí: čo je vidieť (zoom),
   * akou farbou, aké hrubé, s akým obrysom a vzorom, a nakoniec výnimky
   * podľa toho, čo je v OSM napísané.
   *
   * Každé číslo aj farba idú tým istým editorom (`layerValueEditor`), takže
   * „na týchto zoomoch inak" sa všade pýta rovnako a nikde nie sú dve páky
   * na jednu vlastnosť.
   */
  function layerDetails(layer) {
    const o = layerOverride(layer.id) || {};
    const parts = [layerTools(layer)];

    // ---- toto je obrys inej vrstvy ----
    parts.push(...borderLayerBanner(layer));

    // ---- rozsah zoomu ----
    // Zoom je prvý, lebo „čo je vidieť kedy" je najčastejšia otázka: pásik
    // ukáže celý rozsah naraz a klikom sa mení, čísla sú na jemné doladenie.
    const zoomField = (prop, label) =>
      numberField({
        label,
        value: layer[prop],
        min: 0,
        max: 24,
        step: 0.5,
        placeholder: prop === "minzoom" ? "0" : "24",
        // Šípka na prázdnom políčku by inak skočila na spodnú medzu, čiže
        // „do z0" – teda rozsah, v ktorom vrstva nie je nikde.
        stepFrom: prop === "minzoom" ? 0 : MAX_DISPLAY_Z,
        onChange: (v) => {
          setLayerOverride(layer.id, { [prop]: v });
          apply({ immediate: true });
        }
      });
    parts.push(
      sectionTitle("Zobrazené od–do", "klik do pásika = na tom zoome áno / nie")
    );
    parts.push(zoomStrip(layer));
    parts.push(
      el("div", { class: `dev-fields${o.minzoom != null || o.maxzoom != null ? " changed" : ""}` }, [
        zoomField("minzoom", "od z"),
        zoomField("maxzoom", "do z"),
        el("button", {
          type: "button",
          class: "dev-btn",
          text: `od z${zoomCell()}`,
          title: `Vrstva sa začne kresliť až od z${zoomCell()}`,
          onclick: () => {
            setLayerOverride(layer.id, { minzoom: zoomCell() });
            apply({ immediate: true });
          }
        }),
        el("button", {
          type: "button",
          class: "dev-btn",
          text: `do z${zoomCell()}`,
          title: `Vrstva sa nad z${zoomCell()} kresliť prestane`,
          onclick: () => {
            setLayerOverride(layer.id, { maxzoom: zoomCell() });
            apply({ immediate: true });
          }
        }),
        o.minzoom != null || o.maxzoom != null
          ? el("button", {
              type: "button",
              class: "dev-mini",
              title: "Späť na pôvodný rozsah",
              text: "⟲",
              onclick: () => {
                setLayerOverride(layer.id, { minzoom: undefined, maxzoom: undefined });
                apply({ immediate: true });
              }
            })
          : null
      ])
    );

    // ---- poradie kreslenia ----
    parts.push(orderSection(layer));

    // ---- farby ----
    parts.push(...colorSection(layer));

    // ---- ikona ----
    parts.push(...iconSection(layer));

    // ---- čísla (hrúbka, krytie, veľkosť ikony, sila tieňovania) ----
    parts.push(...numberSection(layer));

    if (!canDecorate(layer)) {
      parts.push(...variantSection(layer, o));
      return el("div", { class: "dev-details" }, parts);
    }

    // ---- prerušovanie čiary ----
    if (layer.type === "line") {
      // ČO JE V TOM VÝBERE VIDIEŤ, MUSÍ BYŤ TO, ČO JE V MAPE: prvou položkou
      // je prerušovanie zo štýlu (`frico:dash`), takže pri železnici tam
      // nesvieti „Plná". „Plná" je plnohodnotná úprava (rozpis v `cleanLayers`).
      parts.push(sectionTitle("Prerušovanie", "plná, čiarkovaná, bodkovaná…"));
      parts.push(
        el("div", { class: `dev-sub${o.dash ? " changed" : ""}` }, [
          dashField({
            label: "vzor",
            value: o.dash || "",
            builtin: builtinDash(layer),
            onChange: (v) => {
              setLayerOverride(layer.id, { dash: v || undefined });
              apply({ immediate: true });
            }
          })
        ])
      );
    }

    // ---- opakujúci sa vzor ----
    parts.push(...patternSection(layer, o));

    // ---- okraj ----
    parts.push(...outlineSection(layer, o));

    // ---- rozlíšenie podľa atribútu OSM ----
    parts.push(...variantSection(layer, o));

    return el("div", { class: "dev-details" }, parts);
  }

  /**
   * FARBY VRSTVY NA JEDNOM MIESTE.
   *
   * Kým to bolo rozsypané, mala jedna farba až päť rôznych ovládaní na
   * rôznych miestach detailu: pipetku v „Farbách", vlastný riadok „🌙 v tmavej
   * téme", zaškrtávacie políčko „bez výplne", ďalší editor „podľa zoomu"
   * a k tomu ešte raz tú istú pipetku dole pri vzore ako „Podklad" – dva
   * ovládacie prvky nad tou istou vlastnosťou, každý s vlastným tlačidlom
   * späť. Teraz je jedna farba jeden riadok: pipetka, jej tmavý variant,
   * „bez výplne" tam, kde to má zmysel, a rozpis po zoomoch pod tým istým
   * `▸ zoom`, aký majú čísla.
   */
  function colorSection(layer) {
    const props = colorProps(layer);
    const extraKeys = (layer.metadata || {})["frico:palette-extra"] || [];
    if (!props.length && !extraKeys.length) return [];
    const parts = [
      sectionTitle("Farby", "🌙 je tmavý variant tej istej farby, ▸ zoom ju rozpíše po zoomoch")
    ];
    const paletteMap = (layer.metadata || {})["frico:palette"] || {};
    for (const [prop, value] of props) parts.push(...colorRow(layer, prop, value, paletteMap[prop]));

    // FARBY, KTORÉ SI VRSTVA VYBERÁ VÝRAZOM (pásik trasy podľa značky z OSM).
    // Tie sa na vrstve prepísať nedajú – menia sa v palete a platia pre celú
    // tému. Ovládanie je aj tak tu, nech sa farba ladí tam, kde je vidieť,
    // čo mení.
    if (extraKeys.length) {
      const colors = mergedPalette(getTheme(), overrides);
      const changedPalette = overrides.palette[getTheme()] || {};
      parts.push(
        el("div", { class: "dev-prop dev-prophead" }, [
          el("span", { class: "dev-propname", text: "z palety (platia pre celú tému)" })
        ])
      );
      for (const key of extraKeys) {
        parts.push(
          el("div", { class: "dev-prop" }, [
            el("span", { class: "dev-propname", text: PALETTE_LABELS[key] || key }),
            colorControl({
              value: colors[key],
              changed: key in changedPalette,
              onInput: (v) => {
                setPaletteColor(key, v);
                apply({ rerender: false });
              },
              onReset:
                key in changedPalette
                  ? () => {
                      setPaletteColor(key, undefined);
                      apply({ immediate: true });
                    }
                  : null
            })
          ])
        );
      }
    }
    return parts;
  }

  /** Jedna farba vrstvy: svetlá, tmavá, „bez výplne" a rozpis po zoomoch. */
  function colorRow(layer, prop, value, paletteKey) {
    const o = layerOverride(layer.id) || {};
    const uprava = (o.paint || {})[prop];
    const bezVyplne = uprava === NO_FILL;
    // BEZ VÝPLNE má zmysel len na ploche: plocha stratí farbu pozadia, ale
    // vzor aj okraj na nej ostanú. Nie je to krytie 0 (to zhasne aj obrys
    // z `fill-outline-color`) ani vypnutie vrstvy (tým by zmizol aj vzor).
    const canNoFill = prop === "fill-color" || prop === "fill-extrusion-color";
    const label = COLOR_LABELS[prop] || prop.replace(/-color$/, "");
    const darkValue = (o.paintDark || {})[prop];
    const parts = [];

    parts.push(
      bezVyplne
        ? el("div", { class: "dev-zv" }, [
            el("div", { class: "dev-zvhead changed" }, [
              el("span", { class: "dev-propname", text: label }),
              el("span", { class: "dev-note", text: "bez výplne – vidno mapu pod vrstvou" }),
              el("button", {
                type: "button",
                class: "dev-mini",
                title: "Vrátiť výplň",
                text: "⟲",
                onclick: () => {
                  setLayerPaint(layer.id, prop, undefined);
                  apply({ immediate: true });
                }
              })
            ])
          ])
        : layerValueEditor(layer, prop, { kind: "color", label })
    );

    // Riadok navyše len vtedy, keď je čo ponúknuť – tmavý variant a „bez
    // výplne". Pri priehľadnej farbe nemá tmavý variant čo prepísať.
    if (!bezVyplne) {
      const extras = [];
      extras.push(
        darkValue !== undefined
          ? colorControl({
              value: darkValue,
              changed: true,
              note: "🌙 v tmavej téme",
              onInput: (v) => {
                setLayerPaintDark(layer.id, prop, v);
                apply({ rerender: false });
              },
              onReset: () => {
                setLayerPaintDark(layer.id, prop, undefined);
                apply({ immediate: true });
              }
            })
          : el("button", {
              type: "button",
              class: "dev-mini",
              text: "🌙 tmavá téma",
              title: "Vlastná farba pre tmavú tému – tá istá vlastnosť, len keď je "
                + "zapnutá téma tmavá",
              onclick: () => {
                setLayerPaintDark(layer.id, prop, typeof value === "string" ? value : "#888888");
                apply({ immediate: true });
              }
            })
      );
      if (canNoFill) {
        extras.push(
          el("button", {
            type: "button",
            class: "dev-mini",
            text: "bez výplne",
            title: "Plocha bez farby pozadia – vzor a okraj na nej ostanú "
              + "(nie je to krytie 0 ani vypnutá vrstva)",
            onclick: () => {
              setLayerPaint(layer.id, prop, NO_FILL);
              apply({ immediate: true });
            }
          })
        );
      }
      if (paletteKey) {
        extras.push(
          el("span", {
            class: "dev-note",
            text: `paleta: ${PALETTE_LABELS[paletteKey] || paletteKey}`
          })
        );
      }
      parts.push(el("div", { class: "dev-zvextras" }, extras));
    }
    return parts;
  }

  /**
   * ČÍSLA VRSTVY – hrúbka, krytie, lem, veľkosť ikony, sila tieňovania.
   *
   * Je to JEDEN zoznam podľa druhu vrstvy (`NUM_PROPS`), nie štyri bloky
   * napísané zvlášť pre čiaru, plochu, symbol a reliéf. Kým to boli bloky,
   * pribudla vlastnosť vždy len do toho jedného, na ktorý sa vtedy pozeralo:
   * lem písma sa dal ladiť v záložke Trasy, ale nie v zozname vrstiev.
   */
  function numberSection(layer) {
    const parts = [];
    const paintProps = numPropsFor(layer);
    const layoutProps = layer.type === "symbol" ? layoutPropsFor(layer) : [];
    if (!paintProps.length && !layoutProps.length) return parts;
    parts.push(sectionTitle("Čísla", "„% štýlu\" drží zoomovú krivku, „pevná\" ju nahradí"));
    for (const prop of paintProps) parts.push(layerValueEditor(layer, prop, NUM_PROPS[prop]));
    for (const prop of layoutProps) {
      const m = LAYOUT_PROPS[prop];
      parts.push(
        layerValueEditor(layer, prop, {
          where: "layout",
          label: m.label,
          min: m.min,
          max: m.max,
          step: m.step
        })
      );
    }
    return parts;
  }

  /** Ikona symbolovej vrstvy – len tam, kde je jej meno v štýle napevno. */
  function iconSection(layer) {
    const iconNow = (layer.layout || {})["icon-image"];
    if (layer.type !== "symbol" || typeof iconNow !== "string") return [];
    const o = layerOverride(layer.id) || {};
    const set = (getIconSets?.() || []).find(
      (s) => s.id === selectedIconSource(overrides)
    ) || (getIconSets?.() || [])[0];
    // Súčasná ikona je v zozname vždy, aj keby ju nasadená sada nemala –
    // inak by výber ticho ukázal prvú položku a tvrdil, že je vybraná.
    return [
      sectionTitle("Ikona", "ikona celej vrstvy; podľa kľúč = hodnota sa mení nižšie"),
      el("div", { class: `dev-sub${o.icon ? " changed" : ""}` }, [
        el("span", { class: "dev-note", text: `teraz: ${iconNow}` }),
        o.icon
          ? el("button", {
              type: "button",
              class: "dev-mini",
              title: "Späť na pôvodnú ikonu",
              text: "⟲",
              onclick: () => {
                setLayerOverride(layer.id, { icon: undefined });
                apply({ immediate: true });
              }
            })
          : null
      ]),
      iconGrid({
        kluc: `layer:${layer.id}`,
        value: iconNow,
        names: pickableIcons(set, iconNow),
        onPick: (v) => {
          setLayerOverride(layer.id, { icon: v === iconNow && !o.icon ? undefined : v });
          apply({ immediate: true });
        }
      })
    ];
  }

  /**
   * OPAKUJÚCI SA VZOR. Vzor môže mať vrstva ZABUDOVANÝ V ŠTÝLE
   * (`frico:pattern` – kamienky v skalnej ploche), takže ovládanie pracuje
   * s ÚČINNÝM vzorom, nie s úpravou: bez toho by rozbaľovačka nad skalami
   * tvrdila „žiadny", hoci v mape vzor je.
   *
   * Tri stavy, ktoré sa musia dať rozlíšiť:
   *   kľúč chýba  … platí to, čo je v štýle
   *   `null`      … vzor zo štýlu je VYPNUTÝ (nie „nič nezmenené")
   *   predpis     … vlastný vzor
   */
  function patternSection(layer, o) {
    const builtinPattern = (layer.metadata || {})["frico:pattern"] || null;
    const patChanged = "pattern" in o;
    const pat = patChanged ? o.pattern : builtinPattern;
    // ČO JE POD VZOROM. Vzor je vždy DRUHÁ vrstva nad plochou, takže sám
    // o sebe nehovorí nič: šrafovanie nad tmavozeleným lesom vyzerá inak než
    // nad svetlou lúkou. Farba podkladu je preto v náhľade – ovládať sa dá
    // hore vo „Farbách", kde je aj tak (druhá pipetka na to isté bola len
    // druhé miesto, kde tú istú vec vrátiť späť).
    const podkladProp = primaryColorProp(layer);
    const podklad =
      o.paint && o.paint[podkladProp] === NO_FILL ? "none" : primaryColor(layer);

    const vyber = () => {
      setPatternPickerOpen(layer.id, !patternOpen.has(layer.id));
      renderBody();
    };
    const parts = [sectionTitle("Vzor", "šrafovanie, kamienky, vlastný obrázok")];
    const patternRow = [
      // NÁHĽAD, NIE MENO. „Šupiny (skaly)" nepovie ani ako hustý ten vzor je,
      // ani ako vyzerá nad farbou tejto plochy – a práve to sú tie dve veci,
      // kvôli ktorým sa vzor prepína.
      el("button", {
        type: "button",
        class: "dev-patbtn",
        title: "Vybrať vzor (kreslený alebo vlastný obrázok)",
        onclick: vyber
      }, [
        patternPreview({ spec: pat, background: podklad, custom: overrides.customIcons || [] })
      ]),
      el("button", {
        type: "button",
        class: "dev-name",
        title: "Vybrať vzor",
        onclick: vyber
      }, [
        el("span", { text: `${patternOpen.has(layer.id) ? "▾ " : "▸ "}Vzor` }),
        el("small", {
          text: pat
            ? pat.image
              ? `vlastný obrázok ${pat.image}`
              : (PATTERNS.find((p) => p.id === pat.id) || {}).label || pat.id
            : "žiadny"
        })
      ]),
      pat
        ? el("button", {
            type: "button",
            class: "dev-mini",
            text: "×",
            title: builtinPattern && !patChanged
              ? "Vypnúť vzor, ktorý má vrstva zo štýlu"
              : "Bez vzoru",
            onclick: () => {
              // „Žiadny" nad vrstvou so vzorom zo štýlu musí vzor VYPNÚŤ
              // (`null`), nie len zahodiť úpravu – tá by ho vrátila späť.
              setLayerOverride(layer.id, { pattern: builtinPattern ? null : undefined });
              apply({ immediate: true });
            }
          })
        : null
    ];
    if (pat) {
      // Doladenie vychádza z ÚČINNÉHO vzoru (`pat`), nie z prázdna – inak by
      // posun veľkosti nad skalnou plochou zabudol jej farbu aj krytie.
      const patch = (p) => {
        patchSub(layer.id, "pattern", p, pat);
        apply({ immediate: true });
      };
      // FARBA, VEĽKOSŤ A HRÚBKA PLATIA LEN NA KRESLENÝ VZOR. Vlastný obrázok
      // ich má zapečené v sebe (prevzorkoval sa pri nahratí), takže ponúkať
      // ich pri ňom by boli tri políčka, ktoré nič nerobia.
      if (!pat.image) {
        patternRow.push(
          colorControl({
            value: pat.color,
            changed: patChanged,
            onInput: (v) => {
              patchSub(layer.id, "pattern", { color: v }, pat);
              apply({ rerender: false });
            }
          }),
          numberField({
            label: "veľkosť",
            value: pat.size,
            min: 4,
            max: 64,
            step: 1,
            onChange: (v) => patch({ size: v ?? 16 })
          }),
          numberField({
            label: "hrúbka",
            value: pat.weight,
            min: 0.5,
            max: 8,
            step: 0.5,
            onChange: (v) => patch({ weight: v ?? 1 })
          })
        );
      }
      patternRow.push(
        numberField({
          label: "krytie",
          value: pat.opacity,
          min: 0,
          max: 1,
          step: 0.1,
          onChange: (v) => patch({ opacity: v ?? 1 })
        })
      );
    }
    // „Zmenené" je úprava vzoru, nie vzor samotný: kamienky zo štýlu sú
    // predvolený stav mapy, nie niečo, čo v tejto relácii niekto naklikal.
    parts.push(el("div", { class: `dev-sub${patChanged ? " changed" : ""}` }, patternRow));

    if (patternOpen.has(layer.id)) {
      parts.push(
        patternPicker({
          spec: pat,
          background: podklad,
          custom: overrides.customIcons || [],
          onPick: (next) => {
            setLayerOverride(layer.id, {
              pattern: next
                ? {
                    // Kreslený vzor si nesie farbu, veľkosť a hrúbku – keď ich
                    // vrstva ešte nemá, začne sa tmavším odtieňom vlastnej
                    // výplne, nie čiernou: vzor má plochu kresliť, nie prebiť.
                    ...(next.image
                      ? {}
                      : { size: 16, weight: 1, color: darken(primaryColor(layer)) }),
                    opacity: pat?.opacity ?? 1,
                    ...(pat && !pat.image && !next.image ? pat : {}),
                    ...next
                  }
                : builtinPattern
                ? null
                : undefined
            });
            apply({ immediate: true });
          }
        })
      );
      parts.push(patternUpload(layer));
    }
    return parts;
  }

  /**
   * OBRYS AKO SAMOSTATNÁ VRSTVA – „Miestne cesty – obrys".
   *
   * V mape sú obrysy dvoma spôsobmi a treba ich vedieť rozlíšiť. Buď je obrys
   * VLASTNÁ VRSTVA zo štýlu (širšia čiara pod cestou, `frico:border-of`),
   * alebo si ho vrstva pridá sama (`outline` v úprave, nižšie). Ovládanie je
   * v oboch prípadoch to isté – farba, šírka, prerušovanie, krytie – a šírka
   * ide v oboch tým istým editorom, aby „obrys na 90 %" znamenalo to isté bez
   * ohľadu na to, ktorou z tých dvoch ciest obrys vznikol.
   *
   * Čo pri samostatnej vrstve treba povedať nahlas: jej hrúbka je CELÁ šírka
   * aj s čiarou, ktorú obťahuje, nie prídavok k nej. Bez toho vyzerá „obrys
   * 10,6 px pod cestou 9 px" ako preklep, hoci je to 0,8 px na každej strane.
   */
  function borderLayerBanner(layer) {
    const of = (layer.metadata || {})["frico:border-of"];
    if (!of) return [];
    const predloha = getStyle().layers.find((l) => l.id === of);
    const z = zoomCell();
    const sirkaObrysu = valueAtZoom((layer.paint || {})["line-width"], z);
    const sirkaCiary = predloha ? valueAtZoom((predloha.paint || {})["line-width"], z) : null;
    const presah =
      typeof sirkaObrysu === "number" && typeof sirkaCiary === "number"
        ? Math.round(((sirkaObrysu - sirkaCiary) / 2) * 100) / 100
        : null;
    return [
      el("div", { class: "dev-border" }, [
        el("span", { class: "dev-borderbadge", text: "obrys" }),
        el("span", {
          class: "dev-note",
          text:
            `Obrys vrstvy „${(predloha?.metadata || {})["frico:label"] || of}". ` +
            `Kreslí sa POD ňou, takže jeho hrúbka je celá šírka aj s čiarou` +
            (presah != null
              ? ` – na z${z} má čiara ${sirkaCiary} px, obrys ${sirkaObrysu} px, ` +
                `teda ${presah} px vidieť na každej strane.`
              : ".")
        }),
        predloha
          ? el("button", {
              type: "button",
              class: "dev-mini",
              text: "otvoriť čiaru",
              title: `Otvoriť detail vrstvy "${of}"`,
              onclick: () => {
                expanded.add(of);
                renderBody();
              }
            })
          : null
      ])
    ];
  }

  /** Okraj, ktorý si vrstva pridá sama (`outline` v úprave). */
  function outlineSection(layer, o) {
    const out = o.outline;
    const isArea = layer.type !== "line";
    const parts = [
      sectionTitle(
        "Okraj",
        isArea
          ? "obrysová čiara nad plochou"
          : "širší obrys pod čiarou; % je násobok hrúbky čiary"
      )
    ];
    const outlineRow = [
      selectField({
        label: "Okraj",
        value: out ? "on" : "off",
        options: [
          ["off", "žiadny"],
          ["on", isArea ? "obrys plochy" : "obrys pod čiarou"]
        ],
        onChange: (v) => {
          setLayerOverride(layer.id, {
            outline:
              v === "on"
                ? out || { color: darken(primaryColor(layer)), width: isArea ? 1.5 : 1, opacity: 1 }
                : undefined
          });
          apply({ immediate: true });
        }
      })
    ];
    if (out) {
      outlineRow.push(
        colorControl({
          value: out.color,
          changed: true,
          onInput: (v) => {
            patchSub(layer.id, "outline", { color: v });
            apply({ rerender: false });
          }
        }),
        // Tmavý variant farby okraja – tá istá otázka ako pri `paintDark`,
        // len na vlastnosti, ktorá nesedí v `paint` (okraj je odvodená vrstva).
        out.colorDark !== undefined
          ? colorControl({
              value: out.colorDark,
              changed: true,
              note: "🌙 v tmavej téme",
              onInput: (v) => {
                patchSub(layer.id, "outline", { colorDark: v });
                apply({ rerender: false });
              },
              onReset: () => {
                patchSub(layer.id, "outline", { colorDark: undefined });
                apply({ immediate: true });
              }
            })
          : el("button", {
              type: "button",
              class: "dev-mini",
              text: "🌙 tmavá téma",
              onclick: () => {
                patchSub(layer.id, "outline", { colorDark: out.color });
                apply({ immediate: true });
              }
            }),
        dashField({
          label: "prerušovanie",
          value: out.dash || "solid",
          onChange: (v) => {
            patchSub(layer.id, "outline", { dash: v === "solid" ? undefined : v });
            apply({ immediate: true });
          }
        }),
        numberField({
          label: "krytie",
          value: out.opacity,
          min: 0,
          max: 1,
          step: 0.1,
          onChange: (v) => {
            patchSub(layer.id, "outline", { opacity: v ?? 1 });
            apply({ immediate: true });
          }
        })
      );
    }
    parts.push(el("div", { class: `dev-sub${out ? " changed" : ""}` }, outlineRow));
    if (out) {
      // ŠÍRKA OKRAJA ZNAMENÁ PRI PLOCHE A PRI ČIARE NIEČO INÉ (rozpis pri
      // `outlineWidth` v themes.js): plocha vlastnú hrúbku nemá, takže číslo
      // je absolútna šírka obrysovej čiary a percento by nemalo z čoho
      // počítať. Čiara hrúbku má, takže percento je „toľkokrát hrubší než
      // čiara" a číslo „toľko px na každej strane".
      parts.push(
        zoomValueEditor({
          key: `${layer.id}:outline:width`,
          label: "šírka okraja",
          min: 0.5,
          max: 40,
          step: 0.5,
          unit: " px",
          allowPercent: !isArea,
          styleValue: isArea ? out.width : (layer.paint || {})["line-width"],
          value: out.width,
          note: isArea
            ? "šírka obrysovej čiary v px"
            : "px = toľko obrysu na každej strane, % = násobok hrúbky čiary",
          onChange: (v) => patchSub(layer.id, "outline", { width: v ?? 1 })
        })
      );
    }
    return parts;
  }

  /**
   * AKÉ ATRIBÚTY A HODNOTY MÁ TÁ VRSTVA V MAPE PRÁVE TERAZ.
   *
   * Číta sa to Z DLAŽDÍC, nie zo zoznamu v zdrojáku, a je to rozhodnutie:
   * schéma OpenMapTiles vydáva `surface` len pre niektoré triedy ciest a
   * pri niektorých zoomoch, takže vymenovaný zoznam by ponúkal rozlíšenia,
   * ktoré nikdy nič netrafia – a to sa prejaví až tým, že v mape sa nič
   * nezmení. Takto sa ponúka to, čo naozaj je, aj s počtami, a hodnota,
   * ktorá v tomto výreze nie je, sa ani nedá naklikať.
   *
   * Počty sú z NAČÍTANÝCH dlaždíc, teda z toho, čo je práve na obrazovke –
   * a to je správna odpoveď na „ktoré hodnoty tu vlastne sú".
   */
  function scanAttrs(layer) {
    const m = getMap();
    const sourceLayer = layer["source-layer"];
    if (!m || !layer.source || !sourceLayer) return new Map();
    let features = [];
    try {
      features = m.querySourceFeatures(layer.source, { sourceLayer, filter: layer.filter });
    } catch {
      try {
        features = m.querySourceFeatures(layer.source, { sourceLayer });
      } catch {
        return new Map();
      }
    }
    const out = new Map();
    for (const f of features) {
      for (const [k, v] of Object.entries(f.properties || {})) {
        if (v == null || v === "") continue;
        // Meno, popis ani `ref` nie sú kategórie – rozlíšiť podľa nich by
        // znamenalo variant na každú cestu zvlášť.
        if (SKIP_ATTRS.has(k) || k.startsWith("name")) continue;
        if (!out.has(k)) out.set(k, new Map());
        const hodnoty = out.get(k);
        const s = String(v);
        if (s.length > 40) continue;
        hodnoty.set(s, (hodnoty.get(s) || 0) + 1);
      }
    }
    // Atribút s jedinou hodnotou nerozlíši nič – variant by z predlohy vzal
    // všetko a predloha by ostala prázdna.
    for (const [k, v] of out) if (v.size < 2) out.delete(k);
    return out;
  }

  /** Zoznam variantov jednej vrstvy – z toho priečinka, do ktorého sa zapisuje. */
  const variantsOf = (id) => (layerOverride(id) || {}).variants || [];

  function setVariants(id, list) {
    setLayerOverride(id, { variants: list.length ? list : undefined });
  }

  function patchVariant(id, i, patch) {
    const list = [...variantsOf(id)];
    if (!list[i]) return;
    const next = { ...list[i], ...patch };
    for (const k of Object.keys(next)) if (next[k] === undefined) delete next[k];
    list[i] = next;
    setVariants(id, list);
    apply({ immediate: true });
  }

  /** Jedna vlastnosť `paint` vo variante; `undefined` = späť na to, čo má predloha. */
  function patchVariantPaint(id, i, prop, value) {
    const cur = { ...(variantsOf(id)[i]?.paint || {}) };
    if (value === undefined) delete cur[prop];
    else cur[prop] = value;
    patchVariant(id, i, { paint: Object.keys(cur).length ? cur : undefined });
  }

  /** Pri ktorých rozlíšeniach je rozbalený výber ikony. */
  const variantIconOpen = new Set();

  /** Čo má rozlíšenie nastavené inak než predloha – do jedného riadku. */
  function variantSummary(v) {
    const kusy = [];
    if (v.icon !== undefined) kusy.push(`ikona ${v.icon || "žiadna"}`);
    for (const [prop, value] of Object.entries(v.paint || {})) {
      const meno = COLOR_LABELS[prop] || NUM_PROPS[prop]?.label || prop;
      kusy.push(
        isRelative(value)
          ? `${meno} ${pctOf(value)} %`
          : Array.isArray(value)
            ? `${meno} podľa zoomu`
            : `${meno} ${value}`
      );
    }
    for (const [prop, value] of Object.entries(v.layout || {})) {
      const meno = LAYOUT_PROPS[prop]?.label || prop;
      kusy.push(isRelative(value) ? `${meno} ${pctOf(value)} %` : `${meno} ${value}`);
    }
    if (v.dash) kusy.push(`čiara ${dashLabel(v.dash)}`);
    if (v.outline) kusy.push("vlastný okraj");
    return kusy.join(" · ");
  }

  /**
   * ROZLÍŠENIE PODĽA `kľúč = hodnota` Z OSM – „studnička má inú ikonu než
   * prameň", „nespevnená cesta bodkovane".
   *
   * Je to ten istý zoznam, aký panel vypisuje v „Prvkoch" pod kurzorom: kľúč
   * z dlaždice a hodnoty, ktoré v ňom naozaj sú. Vybrané hodnoty dostanú
   * vlastnú vrstvu (`variants` v úprave) a z predlohy sa odoberú, takže sa
   * prvok nakreslí práve raz.
   *
   * IKONA JE TU NAJDÔLEŽITEJŠIA. Formát úprav ju vo variante vedel od
   * začiatku (`cleanVariants` aj `variantLayers` s ňou počítajú), ale panel
   * ju nemal kde vybrať – dala sa nastaviť len celej vrstve naraz, takže
   * „vodný zdroj s `natural=spring` nech má prameň a zvyšok studňu" sa
   * naklikať nedalo vôbec.
   */
  function variantSection(layer, o) {
    if (!layer["source-layer"]) return [];
    const parts = [
      sectionTitle(
        "Podľa kľúč = hodnota",
        "vlastná ikona alebo štýl pre prvky s konkrétnym tagom z OSM"
      )
    ];
    const varianty = o.variants || [];
    const isLine = layer.type === "line";
    const isSymbol = layer.type === "symbol";
    const iconNow = (layer.layout || {})["icon-image"];
    const set = (getIconSets?.() || []).find(
      (s) => s.id === selectedIconSource(overrides)
    ) || (getIconSets?.() || [])[0];

    varianty.forEach((v, i) => {
      const suhrn = variantSummary(v);
      const riadky = [
        el("div", { class: "dev-row" }, [
          el("span", { class: "dev-name" }, [
            el("span", { text: `${v.attr} = ${v.values.join(", ")}` }),
            el("small", { text: suhrn || "zatiaľ bez vlastného štýlu" })
          ]),
          el("button", {
            type: "button",
            class: "dev-mini",
            title: "Zrušiť toto rozlíšenie – prvky sa vrátia do predlohy",
            text: "🗑",
            onclick: () => {
              setVariants(layer.id, varianty.filter((_, j) => j !== i));
              apply({ immediate: true });
            }
          })
        ])
      ];

      // ---- ikona ----
      // AJ TAM, KDE SI VRSTVA MENO IKONY SKLADÁ VÝRAZOM (POI podľa triedy).
      // Variant je vlastná vrstva a `variantLayers` jej `icon-image` prepíše
      // natvrdo, takže „prameň má prameň a zvyšok vodných zdrojov studňu"
      // funguje aj tam, kde sa ikona celej vrstvy vybrať nedá – a práve to
      // je otázka, kvôli ktorej sa rozlíšenie podľa `kľúč = hodnota` robí.
      if (isSymbol) {
        const kluc = `${layer.id}:${i}`;
        const zoStyle = typeof iconNow === "string" ? iconNow : "";
        const teraz = v.icon !== undefined ? v.icon : zoStyle;
        riadky.push(
          el("div", { class: `dev-sub${v.icon !== undefined ? " changed" : ""}` }, [
            el("span", { class: "dev-propname", text: "ikona" }),
            el("span", {
              class: "dev-note",
              text: teraz || (zoStyle ? "žiadna" : "podľa kategórie prvku")
            }),
            el("button", {
              type: "button",
              class: "dev-mini",
              text: variantIconOpen.has(kluc) ? "▾ vybrať" : "▸ vybrať",
              onclick: () => {
                if (variantIconOpen.has(kluc)) variantIconOpen.delete(kluc);
                else variantIconOpen.add(kluc);
                renderBody();
              }
            }),
            v.icon !== undefined
              ? el("button", {
                  type: "button",
                  class: "dev-mini",
                  title: "Späť na ikonu, akú má celá vrstva",
                  text: "⟲",
                  onclick: () => patchVariant(layer.id, i, { icon: undefined })
                })
              : null
          ])
        );
        if (variantIconOpen.has(kluc)) {
          riadky.push(
            iconGrid({
              kluc: `variant:${kluc}`,
              value: teraz,
              names: pickableIcons(set, zoStyle || undefined),
              noneLabel: "bez ikony",
              onPick: (n) => patchVariant(layer.id, i, { icon: n || "" })
            })
          );
        }
      }

      // ---- farba ----
      const farbaProp = primaryColorProp(layer);
      if (farbaProp) {
        riadky.push(
          el("div", { class: `dev-sub${v.paint?.[farbaProp] !== undefined ? " changed" : ""}` }, [
            el("span", { class: "dev-propname", text: COLOR_LABELS[farbaProp] || "farba" }),
            colorControl({
              value: v.paint?.[farbaProp] ?? layer.paint[farbaProp],
              changed: v.paint?.[farbaProp] !== undefined,
              onInput: (c) => patchVariantPaint(layer.id, i, farbaProp, c),
              onReset: v.paint?.[farbaProp] !== undefined
                ? () => patchVariantPaint(layer.id, i, farbaProp, undefined)
                : null
            })
          ])
        );
      }

      // ---- čiara: prerušovanie, hrúbka, okraj ----
      if (isLine) {
        riadky.push(
          el("div", { class: `dev-sub${v.dash ? " changed" : ""}` }, [
            dashField({
              label: "prerušovanie",
              value: v.dash || "",
              builtin: builtinDash(layer),
              onChange: (d) => patchVariant(layer.id, i, { dash: d || undefined })
            })
          ]),
          // Hrúbka variantu sa ladí tým istým editorom ako hrúbka vrstvy –
          // vrátane pásiem, takže „nespevnená cesta je od z16 tenšia" je
          // jedno naklikanie, nie prepísanie celej krivky.
          zoomValueEditor({
            key: `${layer.id}:var${i}:line-width`,
            label: "hrúbka",
            min: 0.1,
            max: 40,
            step: 0.5,
            unit: " px",
            styleValue: (layer.paint || {})["line-width"],
            value: v.paint?.["line-width"],
            onChange: (nv) => patchVariantPaint(layer.id, i, "line-width", nv)
          }),
          el("div", { class: `dev-sub${v.outline ? " changed" : ""}` }, [
            selectField({
              label: "okraj",
              value: v.outline ? "on" : "off",
              options: [["off", "žiadny"], ["on", "obrys pod čiarou"]],
              onChange: (val) => patchVariant(layer.id, i, {
                outline: val === "on"
                  ? v.outline || { color: darken(primaryColor(layer)), width: { scale: 1.5 } }
                  : undefined
              })
            }),
            v.outline
              ? colorControl({
                  value: v.outline.color,
                  changed: true,
                  onInput: (c) => patchVariant(layer.id, i, { outline: { ...v.outline, color: c } })
                })
              : null
          ])
        );
        if (v.outline) {
          riadky.push(
            zoomValueEditor({
              key: `${layer.id}:var${i}:outline`,
              label: "šírka okraja",
              min: 0.5,
              max: 40,
              step: 0.5,
              unit: " px",
              styleValue: (layer.paint || {})["line-width"],
              value: v.outline.width,
              note: "px = toľko obrysu na každej strane, % = násobok hrúbky čiary",
              onChange: (nv) =>
                patchVariant(layer.id, i, { outline: { ...v.outline, width: nv ?? 1 } })
            })
          );
        }
      }

      parts.push(el("div", { class: "dev-variant" }, riadky));
    });

    if (varianty.length >= MAX_VARIANTS) {
      parts.push(el("div", { class: "dev-sub" }, [
        el("span", { class: "dev-note",
          text: `Viac než ${MAX_VARIANTS} rozlíšení na jednu vrstvu sa už nedá prečítať v mape ani tu.` })
      ]));
      return parts;
    }

    // ---- pridanie ----
    const atributy = scanAttrs(layer);
    if (!atributy.size) {
      parts.push(el("div", { class: "dev-sub" }, [
        el("span", { class: "dev-note",
          text: "V načítaných dlaždiciach táto vrstva nemá atribút, ktorým by sa "
            + "dala rozlíšiť. Posuň sa tam, kde sa kreslí, alebo priblíž." })
      ]));
      return parts;
    }
    const brane = new Set(varianty.flatMap((v) => v.values.map((x) => `${v.attr}=${x}`)));
    const vybraneAttr = variantAttr.get(layer.id) || [...atributy.keys()][0];
    const vybraneHodnoty = variantValues.get(layer.id) || new Set();

    parts.push(el("div", { class: "dev-sub" }, [
      selectField({
        label: "atribút",
        value: vybraneAttr,
        options: [...atributy].map(([k, v]) => [k, `${k} (${v.size} hodnôt)`]),
        onChange: (k) => {
          variantAttr.set(layer.id, k);
          variantValues.set(layer.id, new Set());
          // Len stav panela – mapa sa nemení, tak sa ani neprekresľuje.
          render();
        }
      }),
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Pridať rozlíšenie",
        title: vybraneHodnoty.size
          ? `Vybrané hodnoty dostanú vlastnú vrstvu; zvyšok ostane v predlohe`
          : "Najprv vyber aspoň jednu hodnotu",
        onclick: () => {
          if (!vybraneHodnoty.size) return;
          setVariants(layer.id, [
            ...varianty,
            { attr: vybraneAttr, values: [...vybraneHodnoty], label: [...vybraneHodnoty].join(", ") }
          ]);
          variantValues.set(layer.id, new Set());
          apply({ immediate: true });
        }
      })
    ]));

    const hodnoty = [...(atributy.get(vybraneAttr) || new Map())]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    parts.push(el("div", { class: "dev-chips" }, hodnoty.map(([val, pocet]) => {
      const uz = brane.has(`${vybraneAttr}=${val}`);
      const on = vybraneHodnoty.has(val);
      return el("button", {
        type: "button",
        class: `dev-chip${on ? " on" : ""}${uz ? " off" : ""}`,
        text: `${val} · ${pocet}`,
        title: uz
          ? "Túto hodnotu už berie iné rozlíšenie – dve vrstvy nad tým istým "
            + "prvkom by sa kreslili cez seba"
          : `${pocet} prvkov v načítaných dlaždiciach`,
        onclick: () => {
          if (uz) return;
          if (on) vybraneHodnoty.delete(val);
          else vybraneHodnoty.add(val);
          variantValues.set(layer.id, vybraneHodnoty);
          render();
        }
      });
    })));
    return parts;
  }

  // ---------- tab: prvky ----------
  /**
   * PORADIE KRESLENIA jednej vrstvy.
   *
   * MapLibre kreslí vrstvy tak, ako idú v štýle za sebou – navrchu je tá
   * POSLEDNÁ. Dovtedy sa to dalo zmeniť len v zdrojáku, takže „násyp má byť
   * pod cestou" znamenalo commit a build. Tu je to presun a uloží sa do
   * `style-overrides.json` ako všetko ostatné.
   *
   * Susedov treba VYPÍSAŤ: zoznam vrstiev je zoradený po skupinách, nie
   * podľa kreslenia, takže z neho nie je vidieť, čo je nad čím – a po
   * ťuknutí na „vyššie" by sa nedalo povedať, či sa niečo stalo.
   */
  function orderSection(layer) {
    const head = orderHead(layer);
    const poradie = drawOrder();
    const i = poradie.findIndex((l) => l.id === head);
    const menoV = (l) => (l?.metadata || {})["frico:label"] || l?.id || "";
    const presun = (overrides.order || []).find((m) => m.id === head);

    if (i < 0) {
      return el("div", { class: "dev-sub" }, [
        el("span", {
          class: "dev-note",
          text: REGION_MASK_LAYERS.includes(layer.id)
            ? "Maska regiónu sa kreslí vždy úplne navrchu – vrstva za ňou by kreslila aj mimo stiahnutého regiónu."
            : "Túto vrstvu presúvať netreba – kreslí sa so svojou predlohou."
        })
      ]);
    }

    const pod = poradie[i - 1];
    const nad = poradie[i + 1];
    const parts = [
      sectionTitle(
        "Poradie kreslenia",
        `${i + 1}. z ${poradie.length} · navrchu je posledná · platí pre všetky typy máp`
      ),
      el("div", { class: "dev-sub" }, [
        el("span", {
          class: "dev-note",
          text:
            (nad ? `nad ňou: ${menoV(nad)}` : "je úplne navrchu") +
            " · " +
            (pod ? `pod ňou: ${menoV(pod)}` : "je úplne naspodku") +
            (head === layer.id ? "" : ` · presúva sa s vrstvou „${menoV(poradie[i])}"`)
        })
      ]),
      el("div", { class: `dev-fields${presun ? " changed" : ""}` }, [
        el("button", {
          type: "button",
          class: "dev-btn",
          text: "▲ vyššie",
          disabled: nad ? null : true,
          title: nad ? `Kresliť nad vrstvu „${menoV(nad)}"` : "Vyššie to už nejde",
          onclick: () => {
            setLayerOrder(head, poradie[i + 2] ? poradie[i + 2].id : null);
            apply({ immediate: true });
          }
        }),
        el("button", {
          type: "button",
          class: "dev-btn",
          text: "▼ nižšie",
          disabled: pod ? null : true,
          title: pod ? `Kresliť pod vrstvu „${menoV(pod)}"` : "Nižšie to už nejde",
          onclick: () => {
            setLayerOrder(head, pod.id);
            apply({ immediate: true });
          }
        }),
        el("button", {
          type: "button",
          class: "dev-btn",
          text: "navrch",
          title: "Kresliť nad všetko ostatné (maska regiónu ostáva navrchu vždy)",
          onclick: () => {
            setLayerOrder(head, null);
            apply({ immediate: true });
          }
        }),
        presun
          ? el("button", {
              type: "button",
              class: "dev-mini",
              text: "⟲",
              title: "Späť na poradie zo štýlu",
              onclick: () => {
                setLayerOrder(head, undefined);
                apply({ immediate: true });
              }
            })
          : null
      ]),
      // Skok cez celý zoznam. „O jednu vyššie" je pri dvoch stovkách vrstiev
      // na presun násypu pod cesty nepoužiteľné – toto je tá istá otázka
      // položená naraz.
      el("div", { class: `dev-sub${presun ? " changed" : ""}` }, [
        selectField({
          label: "kresliť tesne pod",
          value: presun ? presun.before ?? "" : "",
          options: [
            ["", presun ? "— úplne navrch —" : "— poradie zo štýlu —"],
            ...poradie
              .filter((l) => l.id !== head)
              .map((l) => [l.id, `${menoV(l)} (${l.id})`])
          ],
          onChange: (v) => {
            setLayerOrder(head, v || null);
            apply({ immediate: true });
          }
        })
      ])
    ];
    return el("div", {}, parts);
  }

  /** Hodnota atribútu do tabuľky – prázdne a dlhé sa musia dať rozoznať. */
  const attrText = (v) => {
    if (v === null || v === undefined) return "—";
    if (typeof v === "object") return JSON.stringify(v);
    const s = String(v);
    return s === "" ? '""' : s;
  };

  /** Odkaz na prvok v OpenStreetMape, ak vieme jeho id. */
  function osmLink(props) {
    if (props.rel != null) {
      return ["relácia", `https://www.openstreetmap.org/relation/${props.rel}`];
    }
    // OpenMapTiles dlaždice id prvkov nenesú; `osm_id` býva len tam, kde si
    // ho schéma výslovne vypýtala.
    if (props.osm_id != null) {
      const id = Number(props.osm_id);
      if (Number.isFinite(id) && id > 0) {
        return ["prvok", `https://www.openstreetmap.org/way/${id}`];
      }
    }
    return null;
  }

  function trailRow(p) {
    const colours = mergedPalette(getTheme(), overrides);
    const type = TRAIL_TYPES.find((t) => t.id === p.route);
    // Tá istá cesta k farbe ako v štýle: pomenovaná značka → paleta,
    // neznámy hex z OSM → priamo, žiadna farba → podľa druhu trasy.
    const colour =
      colours[TRAIL_MARK_KEYS[p.colour]] ||
      p.hex ||
      colours[type?.palette] ||
      "#888888";
    const title = [p.ref, p.name].filter(Boolean).join(" ") || "(bez názvu)";
    // Značka, ako ju do dlaždíc zapísal `workers/trails/tags.py` – v teréne
    // je to práve ona, takže patrí do inšpektora hneď vedľa farby.
    const markLabel = p.mark
      ? `značka ${MARK_SHAPES.find((sh) => sh.id === p.mark)?.label || p.mark} ` +
        `(${p.mark_fg} na ${p.mark_bg === "yellow" ? "žltom" : p.mark_bg})`
      : "";
    const detail = [type?.short || p.route, p.colour || p.hex, markLabel, p.network, p.tier]
      .filter(Boolean)
      .join(" · ");
    const link = osmLink(p);
    return el("div", { class: "dev-prow" }, [
      el("span", { class: "dev-swatch", style: `background:${colour}` }),
      el("span", { class: "dev-name" }, [
        el("span", { text: title }),
        el("small", { text: `${detail}${p.off != null ? ` · pruh ${p.off}` : ""}` })
      ]),
      link
        ? el("a", {
            class: "dev-mini",
            href: link[1],
            target: "_blank",
            rel: "noopener",
            title: "Otvoriť v OpenStreetMape",
            text: "↗"
          })
        : null
    ]);
  }

  function featureItem(f, index) {
    const meta = (getStyle()?.layers || []).find((l) => l.id === f.layer.id)?.metadata || {};
    const props = f.properties || {};
    const keys = Object.keys(props).sort();
    const open = pickOpen.has(index);
    const kind = meta["frico:kind"] || "";
    const link = osmLink(props);

    const head = el("div", { class: "dev-row" }, [
      el("span", {
        class: `dev-kind${kind ? ` k-${kind}` : ""}`,
        text: KIND_LABELS[kind] || f.layer.type
      }),
      el("span", {
        class: "dev-name",
        onclick: () => {
          if (open) pickOpen.delete(index);
          else pickOpen.add(index);
          renderBody();
        }
      }, [
        el("span", { text: `${open ? "▾ " : "▸ "}${meta["frico:label"] || f.layer.id}` }),
        el("small", {
          text: `${f.layer.id}${f.sourceLayer ? ` · ${f.sourceLayer}` : ""} · ${keys.length} atribútov`
        })
      ]),
      el("button", {
        type: "button",
        class: "dev-mini",
        title: "Kopírovať prvok ako JSON",
        text: "⧉",
        onclick: (ev) =>
          copyText(
            JSON.stringify(
              { layer: f.layer.id, source: f.source, sourceLayer: f.sourceLayer, properties: props },
              null,
              2
            ),
            ev.currentTarget
          )
      }),
      el("button", {
        type: "button",
        class: "dev-mini",
        title: "Nájsť vrstvu v zozname vrstiev",
        text: "✎",
        onclick: () => {
          tab = "layers";
          search = f.layer.id;
          expanded.add(f.layer.id);
          render();
        }
      })
    ]);

    if (!open) return el("div", { class: "dev-item" }, [head]);

    const rows = keys.length
      ? keys.map((k) =>
          el("div", { class: "dev-kv" }, [
            el("b", { text: k }),
            el("span", { text: attrText(props[k]) })
          ])
        )
      : [el("p", { class: "dev-hint", text: "Prvok nemá žiadne atribúty." })];
    if (link) {
      rows.push(
        el("div", { class: "dev-kv" }, [
          el("b", { text: "v OSM" }),
          el("a", { href: link[1], target: "_blank", rel: "noopener", text: link[1] })
        ])
      );
    }
    return el("div", { class: "dev-item" }, [head, el("div", { class: "dev-details" }, rows)]);
  }

  function renderPick() {
    const hint = el("p", {
      class: "dev-hint",
      html:
        "Klikni do mapy a tu bude <b>všetko, čo je pod kurzorom</b> – plochy, " +
        "čiary, body aj popisky zo všetkých vrstiev naraz, s celým obsahom " +
        "dlaždice. Vypisuje sa len to, čo je na danom zoome naozaj vykreslené; " +
        "vybraté prvky sú v mape zvýraznené oranžovo."
    });

    const radius = numberField({
      label: "polomer (px)",
      value: pickRadius,
      min: 1,
      max: 40,
      step: 1,
      onChange: (v) => {
        pickRadius = Math.min(40, Math.max(1, v ?? 6));
        renderBody();
      }
    });

    if (!picked) {
      return el("div", {}, [
        hint,
        el("div", { class: "dev-bulk on" }, [radius]),
        el("p", { class: "dev-hint", text: "Zatiaľ nič – klikni do mapy." })
      ]);
    }

    const { lng, lat } = picked.lngLat;
    const coords = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
    const osmUrl = `https://www.openstreetmap.org/#map=${Math.round(picked.zoom)}/${lat.toFixed(5)}/${lng.toFixed(5)}`;

    const head = el("div", { class: "dev-bulk on" }, [
      el("span", { class: "dev-bulklabel", text: coords }),
      el("button", {
        type: "button",
        class: "dev-mini",
        title: "Kopírovať súradnice",
        text: "⧉",
        onclick: (ev) => copyText(coords, ev.currentTarget)
      }),
      el("a", {
        class: "dev-btn",
        href: osmUrl,
        target: "_blank",
        rel: "noopener",
        text: "Toto miesto v OSM"
      }),
      radius,
      el("button", {
        type: "button",
        class: "dev-btn danger",
        text: "Vyčistiť",
        onclick: clearPick
      })
    ]);

    const parts = [hint, head];

    // Značené trasy sa vypisujú zvlášť: pásiky sú posunuté vedľa cesty, takže
    // klik do cesty ich netrafí – a práve „ktoré trasy tadiaľto vedú" je to,
    // čo človek pri chodníku hľadá.
    if (picked.trails.length) {
      parts.push(
        el("h4", { class: "dev-h4", text: `Značené trasy tadiaľto (${picked.trails.length})` }),
        el("div", { class: "dev-list" }, picked.trails.map(trailRow))
      );
    }

    parts.push(
      el("h4", {
        class: "dev-h4",
        text: `Prvky pod kurzorom (${picked.features.length})`
      })
    );
    parts.push(
      picked.features.length
        ? el("div", { class: "dev-list" }, picked.features.map(featureItem))
        : el("p", {
            class: "dev-hint",
            text: "Na tomto mieste nie je vykreslený žiadny prvok – skús väčší polomer alebo iný zoom."
          })
    );

    return el("div", {}, parts);
  }

  // ---------- tab: paleta ----------
  function renderPalette() {
    const theme = getTheme();
    const colors = mergedPalette(theme, overrides);
    const changed = overrides.palette[theme] || {};

    const bulkColor = el("input", { type: "color", class: "dev-color", value: "#ff0000" });
    const bulk = el("div", { class: `dev-bulk${selectedPaletteKeys.size ? " on" : ""}` }, [
      el("span", { class: "dev-bulklabel", text: `Vybraných: ${selectedPaletteKeys.size}` }),
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Zrušiť výber",
        onclick: () => {
          selectedPaletteKeys.clear();
          renderBody();
        }
      }),
      bulkColor,
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Zafarbiť výber",
        onclick: () => {
          for (const key of selectedPaletteKeys) setPaletteColor(key, bulkColor.value);
          apply();
        }
      }),
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Kopírovať výber",
        onclick: (ev) => {
          const out = {};
          for (const key of selectedPaletteKeys) out[key] = colors[key];
          copyText(JSON.stringify(out, null, 2), ev.currentTarget);
        }
      }),
      el("button", {
        type: "button",
        class: "dev-btn",
        text: "Vložiť farby",
        onclick: () => {
          const raw = prompt(
            "Vlož JSON s farbami palety, napr.\n{\"forest\": \"#a8cc8e\", \"grass\": \"#cbe0aa\"}"
          );
          if (!raw) return;
          try {
            for (const [k, v] of Object.entries(JSON.parse(raw))) {
              if (PALETTE_LABELS[k] && isHexColor(v)) setPaletteColor(k, normColor(v));
            }
            apply();
          } catch (err) {
            alert(`Nepodarilo sa prečítať JSON: ${err.message}`);
          }
        }
      }),
      el("button", {
        type: "button",
        class: "dev-btn danger",
        text: "Reset palety",
        onclick: () => {
          delete overrides.palette[theme];
          apply();
        }
      })
    ]);

    const groups = [];
    for (const group of PALETTE_GROUPS) {
      groups.push(el("div", { class: "dev-group" }, [
        el("span", { class: "dev-groupname", text: group.label }),
        el("button", {
          type: "button",
          class: "dev-mini",
          title: "Vybrať skupinu",
          text: "☑",
          onclick: () => {
            const keys = group.keys.map(([k]) => k);
            const all = keys.every((k) => selectedPaletteKeys.has(k));
            for (const k of keys) {
              if (all) selectedPaletteKeys.delete(k);
              else selectedPaletteKeys.add(k);
            }
            renderBody();
          }
        })
      ]));

      for (const [key, label] of group.keys) {
        const check = el("input", { type: "checkbox", class: "dev-check" });
        check.checked = selectedPaletteKeys.has(key);
        check.addEventListener("change", () => {
          if (check.checked) selectedPaletteKeys.add(key);
          else selectedPaletteKeys.delete(key);
          const el2 = body.querySelector(".dev-bulklabel");
          if (el2) el2.textContent = `Vybraných: ${selectedPaletteKeys.size}`;
        });

        groups.push(
          el("div", { class: `dev-prow${changed[key] ? " changed" : ""}` }, [
            check,
            el("span", { class: "dev-name", title: key }, [
              el("span", { text: label }),
              el("small", { text: key })
            ]),
            colorControl({
              value: colors[key],
              changed: !!changed[key],
              onInput: (v) => {
                setPaletteColor(key, v);
                apply({ rerender: false });
              },
              onReset: changed[key]
                ? () => {
                    setPaletteColor(key, undefined);
                    apply({ immediate: true });
                  }
                : null
            })
          ])
        );
      }
    }

    return el("div", {}, [
      el("p", {
        class: "dev-hint",
        text: `Farby témy „${THEMES[theme].label}". Zmena tu prefarbí naraz všetky vrstvy, ktoré farbu používajú.`
      }),
      bulk,
      el("div", { class: "dev-list" }, groups)
    ]);
  }

  // ---------- tab: trasy ----------
  // Značené trasy sa nedajú poriadne ladiť v záložke Vrstiev: jeden druh
  // trasy sú tam TRI vrstvy (pásik, ikona, názov), farba nie je v `paint`, ale
  // vo výraze podľa značky z OSM, a odstup od cesty je vlastnosť všetkých
  // naraz. Táto záložka je preto o druhu trasy, nie o vrstve.

  /**
   * ČO SA NA JEDNEJ TRASE DÁ LADIŤ PODĽA ZOOMU.
   *
   * Jeden druh trasy je v štýle NIEKOĽKO vrstiev a každá odpovedá na inú
   * otázku: pásik „ako hrubo", značka „ako veľká a ako často", názov „aké
   * veľké písmo". Zoom a pásma sa preto nastavujú na tej vrstve, ktorej sa
   * týkajú – je to tá istá úprava (`overrides.layers[<id>]`), akú robí
   * záložka Vrstvy, len tu je pokope to, čo patrí k jednej trase.
   *
   * `paint` a `layout` sú dve police MapLibre a nedajú sa zamieňať: hrúbka
   * čiary je `paint`, veľkosť ikony `layout` (rozpis pri `LAYOUT_PROPS`).
   */
  const TRAIL_LAYER_ROLES = [
    {
      suffix: "",
      label: "Pásik",
      note: "farebná čiara vedľa cesty",
      paint: ["line-width", "line-opacity"]
    },
    {
      suffix: "-mark",
      label: "Značka",
      note: "štvorec s pásom – veľkosť a ako často sa opakuje",
      layout: ["icon-size", "symbol-spacing", "icon-padding"]
    },
    {
      suffix: "-icon",
      label: "Ikona druhu",
      note: "kreslí sa len tam, kde trasa značku nemá",
      layout: ["icon-size", "symbol-spacing"],
      paint: ["icon-opacity"]
    },
    {
      suffix: "-label",
      label: "Názov trasy",
      note: "„0801 Cesta hrdinov SNP“ pozdĺž čiary",
      layout: ["text-size", "symbol-spacing"],
      paint: ["text-opacity"]
    }
  ];


  /** Jedna vrstva trasy – `layerBlock` nad jej id. */
  const trailLayerBlock = (role, typeId) =>
    layerBlock(`trail-${typeId}${role.suffix}`, role);

  /**
   * JEDNA VRSTVA S ČÍSLAMI, KTORÉ K NEJ PATRIA: rozsah zoomu a k tomu každé
   * číslo s krivkou alebo pásmami, teda „na týchto zoomoch takto, na týchto
   * inak".
   *
   * Je to tá istá úprava (`overrides.layers[<id>]`), akú robí záložka Vrstvy –
   * rozdiel je len v tom, že tu je pokope to, čo patrí k jednej veci: štyri
   * vrstvy jednej trasy, alebo štítok jednej triedy cesty. V zozname vrstiev
   * ležia na štyroch rôznych miestach a bez farby a značky vedľa nich sa nedá
   * povedať, ktorá je ktorá.
   */
  function layerBlock(id, role) {
    const layer = getStyle().layers.find((l) => l.id === id);
    // Vrstva nemusí existovať: ikona sa nekreslí, keď ju sada ikoniek nemá,
    // a značka vtedy, keď ju developer mode vypol. Mlčky sa preskočiť nesmie
    // – inak by panel vyzeral, že sa tá vec nedá nastaviť.
    if (!layer) {
      return el("div", { class: "dev-sub" }, [
        el("span", { class: "dev-note", text: `${role.label}: v mape teraz nie je (${role.note})` })
      ]);
    }
    const o = layerOverride(id) || {};
    const zmenene = o.minzoom != null || o.maxzoom != null || o.paint || o.layout;
    const rows = [];
    for (const prop of role.paint || []) {
      if ((layer.paint || {})[prop] === undefined) continue;
      rows.push(layerValueEditor(layer, prop, NUM_PROPS[prop] || { label: prop }));
    }
    // Rovnako ako v záložke Vrstiev: ponúka sa to, čo na vrstve niečo znamená,
    // nie to, čo štýl náhodou nastavil (rozpis pri `layoutPropsFor`). Bez toho
    // sa nedal zaviesť rozostup tam, kde ho štýl nechal na predvolenom –
    // a práve to je otázka „ako často má byť číslo cesty vidieť".
    const daSa = new Set(layoutPropsFor(layer));
    for (const prop of role.layout || []) {
      if (!daSa.has(prop)) continue;
      const m = LAYOUT_PROPS[prop];
      rows.push(
        layerValueEditor(layer, prop, {
          where: "layout", label: m.label, min: m.min, max: m.max, step: m.step
        })
      );
    }
    return el("div", { class: `dev-sub${zmenene ? " changed" : ""}` }, [
      el("div", { class: "dev-row" }, [
        el("span", { class: "dev-name" }, [
          el("span", { text: role.label }),
          el("small", { text: `${id} · ${role.note}` })
        ]),
        el("button", {
          type: "button",
          class: `dev-zrange${activeAt(layer, zoomView) ? "" : " off"}`,
          text: zoomRangeText(layer),
          title: `Na z${zoomCell()} ${activeAt(layer, zoomView) ? "sa kreslí – klikni, nech sa nekreslí" : "sa nekreslí – klikni, nech sa kreslí"}`,
          onclick: () => {
            setZoomAt(layer, zoomCell(), !activeAt(layer, zoomView));
            apply({ immediate: true });
          }
        })
      ]),
      el("div", { class: `dev-fields${o.minzoom != null || o.maxzoom != null ? " changed" : ""}` }, [
        numberField({
          label: "od z",
          value: layer.minzoom,
          min: 0, max: 24, step: 0.5, placeholder: "0", stepFrom: 0,
          onChange: (v) => {
            setLayerOverride(id, { minzoom: v });
            apply({ immediate: true });
          }
        }),
        numberField({
          label: "do z",
          value: layer.maxzoom,
          min: 0, max: 24, step: 0.5, placeholder: "24", stepFrom: MAX_DISPLAY_Z,
          onChange: (v) => {
            setLayerOverride(id, { maxzoom: v });
            apply({ immediate: true });
          }
        }),
        o.minzoom != null || o.maxzoom != null
          ? el("button", {
              type: "button", class: "dev-mini", text: "⟲",
              title: "Späť na pôvodný rozsah zoomu",
              onclick: () => {
                setLayerOverride(id, { minzoom: undefined, maxzoom: undefined });
                apply({ immediate: true });
              }
            })
          : null
      ]),
      ...rows
    ]);
  }

  /** Nastavenie jedného druhu trasy (`overrides.trails.types[id]`). */
  function setTrailType(id, patch) {
    const cur = { ...(overrides.trails.types[id] || {}), ...patch };
    for (const k of Object.keys(cur)) if (cur[k] === undefined) delete cur[k];
    if (Object.keys(cur).length) overrides.trails.types[id] = cur;
    else delete overrides.trails.types[id];
  }

  /** Rozostup a veľkosť značiek; `undefined` = späť na predvolené. */
  function setTrailMarks(key, value) {
    if (value === undefined || value === null || value === "" ||
        Number(value) === TRAIL_MARK_DEFAULTS[key]) {
      delete overrides.trails.marks[key];
    } else {
      overrides.trails.marks[key] = Number(value);
    }
  }

  /** Odstup pásikov od cesty; `undefined` = späť na predvolený. */
  function setTrailGap(key, value) {
    if (value === undefined || value === null || value === "" ||
        Number(value) === TRAIL_GAP_DEFAULTS[key]) {
      delete overrides.trails.gap[key];
    } else {
      overrides.trails.gap[key] = Number(value);
    }
  }

  /** Hľadanie v mriežke ikon – zvlášť pre každé miesto, kde sa vyberá. */
  const iconQuery = new Map();

  /** Sada, z ktorej sa práve berú ikony (a jej sprite na náhľady). */
  function currentSet() {
    const sets = getIconSets?.() || [];
    return sets.find((s2) => s2.id === selectedIconSource(overrides)) || sets[0] || null;
  }

  /**
   * Načíta PNG spritu, nech je z čoho kresliť náhľady. Beží raz na sadu;
   * po dokreslení sa panel prekreslí, aby sa mriežka naplnila.
   */
  function spriteImageFor(set) {
    if (!set) return null;
    if (spriteImages.has(set.id)) return spriteImages.get(set.id);
    if (!set.spriteUrl) return null;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => renderBody();
    img.src = `${set.spriteUrl}.png`;
    spriteImages.set(set.id, img);
    return img;
  }

  /**
   * Výber ikony s NÁHĽADMI – jedno miesto pre vrstvy aj pre druhy trás.
   *
   * @param {string} kluc     kde sa vyberá (drží si hľadaný text)
   * @param {string} value    práve vybraná ikona
   * @param {string[]} names  mená zo sady
   * @param {(n: string) => void} onPick
   * @param {string} [noneLabel] keď sa má dať vybrať aj „žiadna"
   */
  function iconGrid({ kluc, value, names, onPick, noneLabel }) {
    const set = currentSet();
    return iconPicker({
      set,
      image: spriteImageFor(set),
      value,
      names,
      custom: overrides.customIcons || [],
      color: mergedPalette(getTheme(), overrides).poiIcon || "#444444",
      noneLabel,
      query: iconQuery.get(kluc) || "",
      onQuery: (q) => {
        iconQuery.set(kluc, q);
        renderBody();
      },
      onPick
    });
  }

  /** Mená ikon z nasadenej sady (aj s tou, ktorú štýl práve používa). */
  function iconNames(extra) {
    const set = (getIconSets?.() || []).find(
      (s2) => s2.id === selectedIconSource(overrides)
    ) || (getIconSets?.() || [])[0];
    return pickableIcons(set, extra);
  }

  /** Ktorá ikona je pre daný druh trasy naozaj v mape (z hotového štýlu). */
  function trailIconNow(id) {
    const layer = getStyle().layers.find((l) => l.id === `trail-${id}-icon`);
    const name = (layer?.layout || {})["icon-image"];
    return typeof name === "string" ? name : "";
  }

  function renderTrails() {
    const theme = getTheme();
    const colors = mergedPalette(theme, overrides);
    const changedPalette = overrides.palette[theme] || {};
    const gaps = trailGapPx(overrides);

    // ---- odstup od cesty ----
    const gapFields = [
      ["road", "Pri ceste", "pásik ide tesne za okraj cesty aj s jej obrysom"],
      ["path", "Pri chodníku a lesnej ceste", "jemný odstup, nech je pod pásikom vidieť aj chodník"],
      ["pitch", "Rozostup dvoch trás",
        "predvolené = šírka pásika, čiže nalepené na seba; menej znamená, " +
        "že sa prekrývajú a spodná farba nie je vidieť"]
    ].map(([key, label, note]) =>
      el("div", { class: `dev-sub${overrides.trails.gap[key] != null ? " changed" : ""}` }, [
        numberField({
          label,
          value: gaps[key],
          min: 0,
          max: 60,
          step: 0.1,
          onChange: (v) => {
            setTrailGap(key, v);
            apply({ immediate: true });
          }
        }),
        el("span", { class: "dev-note", text: `${note} · predvolené ${TRAIL_GAP_DEFAULTS[key]} px` })
      ])
    );

    // ---- značky v teréne ----
    // Rozostup je to, čo z „v pravidelných intervaloch" naozaj rozhoduje:
    // menší = značka je vidieť častejšie, ale trasa sa zaplní štvorcami.
    const marks = trailMarkPx(overrides);
    const markFields = [
      ["spacing", "Rozostup po trase", ...TRAIL_MARK_RANGES.spacing, 5,
        "vzdialenosť dvoch značiek NA TRASE, v pixeloch obrazovky – teda ako " +
        "často sa značka po ceste opakuje"],
      ["size", "Veľkosť značky", ...TRAIL_MARK_RANGES.size, 0.05,
        "násobok predvolenej veľkosti štvorca"],
      ["step", "Odstup značiek nad sebou", ...TRAIL_MARK_RANGES.step, 1,
        "keď vedie po jednej ceste viac trás, stavajú sa ich značky nad seba – " +
        "toto je krok toho stĺpika. Predvolené je presne strana štvorca, čiže " +
        "značky sedia tesne na sebe bez medzery; 0 ich položí na seba"]
    ].map(([key, label, min, max, step, note]) =>
      el("div", { class: `dev-sub${overrides.trails.marks[key] != null ? " changed" : ""}` }, [
        numberField({
          label,
          value: marks[key],
          min,
          max,
          step,
          onChange: (v) => {
            setTrailMarks(key, v);
            apply({ immediate: true });
          }
        }),
        el("span", { class: "dev-note", text: `${note} · predvolené ${TRAIL_MARK_DEFAULTS[key]}` })
      ])
    );

    // ---- druhy trás ----
    const typeRows = TRAIL_TYPES.map((type) => {
      const def = trailTypeDef(type, overrides);
      const own = overrides.trails.types[type.id] || {};
      const icons = iconNames(trailIconNow(type.id));
      // Zoomy a pásma sú za rozkliknutím: sú to štyri vrstvy krát pár čísel,
      // takže rozbalené naraz pri šiestich druhoch trás by sa v paneli
      // nedalo nič nájsť. Zbalené ostáva to, čo sa mení najčastejšie.
      const otvorene = trailOpen.has(type.id);
      const layerZmeny = TRAIL_LAYER_ROLES.filter(
        (r) => layerOverride(`trail-${type.id}${r.suffix}`)
      ).length;
      return el("div", { class: `dev-item${Object.keys(own).length || layerZmeny ? " changed" : ""}` }, [
        el("div", { class: "dev-row" }, [
          el("span", { class: "dev-swatch", style: `background:${colors[type.palette]}` }),
          el("button", {
            type: "button",
            class: "dev-name",
            title: "Zoom a pásma tejto trasy – klikni pre detaily",
            onclick: () => {
              if (otvorene) trailOpen.delete(type.id);
              else trailOpen.add(type.id);
              renderBody();
            }
          }, [
            el("span", { text: `${otvorene ? "▾ " : "▸ "}${type.label}` }),
            el("small", {
              text: `${type.id} · ${type.side > 0 ? "vpravo od cesty" : "vľavo od cesty (opačná strana než pešie)"}`
                + (layerZmeny ? ` · ${layerZmeny} upravených vrstiev` : "")
            })
          ])
        ]),
        el("div", { class: "dev-sub" }, [
          el("span", { class: "dev-note", text: "Farba bez značky" }),
          colorControl({
            value: colors[type.palette],
            changed: !!changedPalette[type.palette],
            onInput: (v) => {
              setPaletteColor(type.palette, v);
              apply({ rerender: false });
            },
            onReset: changedPalette[type.palette]
              ? () => {
                  setPaletteColor(type.palette, undefined);
                  apply({ immediate: true });
                }
              : null
          })
        ]),
        el("div", { class: `dev-sub${own.dash ? " changed" : ""}` }, [
          dashField({
            label: "Čiara",
            value: def.dash,
            onChange: (v) => {
              setTrailType(type.id, { dash: v === type.dash ? undefined : v });
              apply({ immediate: true });
            }
          }),
          own.dash
            ? el("button", {
                type: "button",
                class: "dev-mini",
                title: "Späť na pôvodnú čiaru",
                text: "⟲",
                onclick: () => {
                  setTrailType(type.id, { dash: undefined });
                  apply({ immediate: true });
                }
              })
            : null
        ]),
        el("div", { class: `dev-sub${own.mark != null ? " changed" : ""}` }, [
          selectField({
            label: "Značka",
            // Tri odpovede, nie dve: prázdna položka je „taká, aká je v OSM"
            // (`osmc:symbol` – pásová, vrcholová, bicykel), „žiadna" značky
            // vypne a meno tvaru ich všetky prekreslí na jeden.
            value: own.mark != null ? own.mark || "ziadna" : "",
            options: [
              ["", "— podľa OSM —"],
              ["ziadna", "— žiadna —"],
              ...MARK_SHAPES.map((sh) => [sh.id, sh.label])
            ],
            onChange: (v) => {
              setTrailType(type.id, {
                mark: v === "" ? undefined : (v === "ziadna" ? "" : v)
              });
              apply({ immediate: true });
            }
          }),
          el("span", {
            class: "dev-note",
            text: "biely (pešia) alebo žltý (cyklo) štvorec s farebným pásom – " +
              "farbu aj podklad berie z OSM, tvar sa dá prekresliť"
          })
        ]),
        el("div", { class: `dev-sub${own.icon != null ? " changed" : ""}` }, [
          el("span", {
            class: "dev-note",
            // Ikonka sa kreslí len tam, kde trasa značku NEMÁ (neznáma farba
            // z OSM) – inak by na jednej čiare boli dva symboly naraz.
            text: `Ikona druhu: ${own.icon != null
              ? (own.icon || "žiadna")
              : (trailIconNow(type.id) || "žiadna")} · kreslí sa tam, kde trasa značku nemá`
          }),
          own.icon != null
            ? el("button", {
                type: "button",
                class: "dev-mini",
                title: "Späť na pôvodnú ikonu",
                text: "⟲",
                onclick: () => {
                  setTrailType(type.id, { icon: undefined });
                  apply({ immediate: true });
                }
              })
            : null
        ]),
        iconGrid({
          kluc: `trail:${type.id}`,
          value: own.icon != null ? own.icon : trailIconNow(type.id),
          names: icons,
          // Prázdna položka je „žiadna" – trasa hustá na ikonky sa inak
          // nedá zbaviť inak než skrytím celej vrstvy.
          noneLabel: "žiadna",
          onPick: (v) => {
            setTrailType(type.id, { icon: v });
            apply({ immediate: true });
          }
        }),
        // ---- zoom a pásma všetkých vrstiev tejto trasy ----
        otvorene
          ? el("div", { class: "dev-details" }, [
              el("div", { class: "dev-h5" }, [
                el("span", { text: "Od akého zoomu a ako" }),
                el("small", { text: "„% štýlu\" drží pomer na všetkých zoomoch, „pevná\" nastaví číslo" })
              ]),
              ...TRAIL_LAYER_ROLES.map((role) => trailLayerBlock(role, type.id)),
              el("div", { class: "dev-bulk on" }, [
                el("button", {
                  type: "button",
                  class: "dev-btn danger",
                  text: "Späť na pôvodné zoomy a hodnoty",
                  title: "Zahodí zoomy, hrúbky, veľkosti a rozostupy VŠETKÝCH vrstiev tejto trasy",
                  onclick: () => {
                    for (const r of TRAIL_LAYER_ROLES) resetLayer(`trail-${type.id}${r.suffix}`);
                    apply({ immediate: true });
                  }
                })
              ])
            ])
          : null
      ]);
    });

    // ---- farby značiek ----
    // Turistická značka farbu NESIE z OSM (červená, modrá…), takže farba
    // druhu trasy je pri nej len náhrada pre trasy bez značky. Skutočné
    // farby značiek sú tieto – a patria sem, nie do palety niekde inde.
    const markRows = TRAIL_MARK_COLOURS.map(([name, key]) =>
      el("div", { class: `dev-prow${changedPalette[key] ? " changed" : ""}` }, [
        el("span", { class: "dev-swatch", style: `background:${colors[key]}` }),
        el("span", { class: "dev-name", title: key }, [
          el("span", { text: PALETTE_LABELS[key] || name }),
          el("small", { text: `colour=${name}` })
        ]),
        colorControl({
          value: colors[key],
          changed: !!changedPalette[key],
          onInput: (v) => {
            setPaletteColor(key, v);
            apply({ rerender: false });
          },
          onReset: changedPalette[key]
            ? () => {
                setPaletteColor(key, undefined);
                apply({ immediate: true });
              }
            : null
        })
      ])
    );

    return el("div", {}, [
      el("p", {
        class: "dev-hint",
        text:
          "Značené trasy sa kreslia ako farebné pásiky vedľa cesty, nie na nej – " +
          "samotná cesta tak zostane vidieť. Pešie trasy idú na jednu stranu, " +
          "cyklo a MTB na druhú; druhá trasa na tej istej ceste sa nalepí na prvú."
      }),
      el("div", { class: "dev-h5" }, [
        el("span", { text: "Odstup od cesty" }),
        el("small", { text: `v pixeloch pri z${TRAIL_GAP_ZOOM}, ostatné zoomy sa škálujú s ním` })
      ]),
      ...gapFields,
      el("div", { class: "dev-bulk on" }, [
        el("button", {
          type: "button",
          class: "dev-btn danger",
          text: "Späť na predvolené odstupy a značky",
          onclick: () => {
            overrides.trails.gap = {};
            overrides.trails.marks = {};
            apply();
          }
        })
      ]),
      el("div", { class: "dev-h5" }, [
        el("span", { text: "Značky v teréne" }),
        el("small", { text: `v pixeloch pri z${TRAIL_MARK_ZOOM}, ostatné zoomy sa škálujú s ním` })
      ]),
      ...markFields,
      el("div", { class: "dev-h5" }, [
        el("span", { text: "Druhy trás" }),
        el("small", { text: "farba, čiara, značka a ikona podľa druhu (route)" })
      ]),
      el("div", { class: "dev-list" }, typeRows),
      el("div", { class: "dev-h5" }, [
        el("span", { text: "Farby značiek" }),
        el("small", { text: "turistická značka nesie farbu z OSM – toto sú tie farby" })
      ]),
      el("div", { class: "dev-list" }, markRows),
      el("div", { class: "dev-bulk on" }, [
        el("button", {
          type: "button",
          class: "dev-btn danger",
          text: "Späť na pôvodné trasy",
          onclick: () => {
            overrides.trails = { gap: {}, types: {}, marks: {} };
            for (const [, key] of TRAIL_MARK_COLOURS) setPaletteColor(key, undefined);
            for (const t of TRAIL_TYPES) setPaletteColor(t.palette, undefined);
            apply();
          }
        })
      ])
    ]);
  }

  // ---------- tab: štítky ciest ----------
  // Štítok s číslom cesty („D1", „I/18") sa nedá ladiť v záložke Vrstiev
  // rovnako ako trasa: farba ani tvar nie sú v `paint`, sú UPEČENÉ do obrázka
  // v sprite (`workers/assets/shields.mjs`). V prehliadači sa preto dá
  // prepnúť TVAR – všetky tvary sú v sprite naraz, takže je to zmena mena
  // obrázka; farba štítka sa mení v palete a prejaví sa až po builde.

  /**
   * ČO SA NA ŠTÍTKU S ČÍSLOM CESTY DÁ LADIŤ PODĽA ZOOMU.
   *
   * Tá istá otázka ako pri značke trasy („od akého zoomu, ako veľký, ako
   * často"), takže tá istá odpoveď: je to jedna vrstva (`road-shield-<trieda>`)
   * a nastavuje sa `layerBlock`-om, nie druhou pákou vedľa.
   *
   * VEĽKOSŤ ŠTÍTKA JE VEĽKOSŤ PÍSMA, a nie je to zjednodušenie: podklad je
   * obrázok s `icon-text-fit`, teda natiahnutý presne na číslo. Vlastnú
   * `icon-size` nemá – keby ju dostal, prestal by číslu sedieť.
   */
  const SHIELD_LAYER_ROLE = {
    label: "Štítok v mape",
    note: "od akého zoomu, aké veľké číslo a ako často po ceste",
    layout: ["text-size", "symbol-spacing"]
  };

  /** Tvar štítka jednej triedy cesty; `undefined` = späť na predvolený. */
  function setShieldShape(id, shape) {
    if (shape === undefined) delete overrides.shields[id];
    else overrides.shields[id] = { shape };
  }

  function renderShields() {
    const theme = getTheme();
    const colors = mergedPalette(theme, overrides);
    const changedPalette = overrides.palette[theme] || {};

    const rows = SHIELD_DEFS.map(([id, label, classes, colorKey, mz, shapeId, textKey]) => {
      const shape = shieldShapeFor(id, shapeId, overrides);
      const own = overrides.shields[id];
      return el("div", { class: `dev-item${own ? " changed" : ""}` }, [
        el("div", { class: "dev-row" }, [
          // Náhľad je obyčajný HTML štvorček vo farbách štítka – obrázok
          // v sprite je až v mape a tu ide o to, ktorý riadok je ktorý.
          el("span", {
            class: "dev-swatch",
            style: `background:${colors[colorKey]};color:${colors[textKey]};` +
              `border-radius:${shape === "shield-round" ? "50%" : "3px"}`
          }),
          el("span", { class: "dev-name" }, [
            el("span", { text: label }),
            el("small", { text: `${classes ? classes.join(", ") : "podľa siete"} · od z${mz}` })
          ])
        ]),
        el("div", { class: `dev-sub${own ? " changed" : ""}` }, [
          selectField({
            label: "Tvar štítka",
            value: shape,
            options: SHIELD_SHAPES.map((sh) => [sh.id, sh.label]),
            onChange: (v) => {
              setShieldShape(id, v === shapeId ? undefined : v);
              apply({ immediate: true });
            }
          }),
          own
            ? el("button", {
                type: "button",
                class: "dev-mini",
                title: "Späť na pôvodný tvar",
                text: "⟲",
                onclick: () => {
                  setShieldShape(id, undefined);
                  apply({ immediate: true });
                }
              })
            : null
        ]),
        el("div", { class: "dev-sub" }, [
          el("span", { class: "dev-note", text: "Farba štítka" }),
          colorControl({
            value: colors[colorKey],
            changed: !!changedPalette[colorKey],
            onInput: (v) => {
              setPaletteColor(colorKey, v);
              apply({ rerender: false });
            },
            onReset: changedPalette[colorKey]
              ? () => {
                  setPaletteColor(colorKey, undefined);
                  apply({ immediate: true });
                }
              : null
          })
        ]),
        // Zoom, veľkosť čísla a rozostup po ceste – to isté, čo sa pri
        // značkách trás ladí v záložke „Trasy". Dovtedy sa to dalo nastaviť
        // len v zozname vrstiev, kde sa `road-shield-primary` musel najprv
        // nájsť medzi dvoma stovkami iných.
        layerBlock(`road-shield-${id}`, SHIELD_LAYER_ROLE)
      ]);
    });

    return el("div", {}, [
      el("p", {
        class: "dev-hint",
        text:
          "Číslo cesty je značka, nie text – má podklad, stojí narovno a opakuje " +
          "sa po celej ceste. Podklad je obrázok upečený do spritu, takže sa tu " +
          "prepína jeho TVAR; farba sa v mape prejaví až po prebuildovaní spritu " +
          "(v prehliadači je vidieť len na náhľade vľavo). Zoom, veľkosť čísla " +
          "a rozostup po ceste sú pod každou triedou – tie platia hneď."
      }),
      el("div", { class: "dev-list" }, rows),
      el("div", { class: "dev-bulk on" }, [
        el("button", {
          type: "button",
          class: "dev-btn danger",
          text: "Späť na pôvodné štítky",
          onclick: () => {
            overrides.shields = {};
            for (const [id, , , colorKey, , , textKey, borderKey] of SHIELD_DEFS) {
              for (const key of [colorKey, textKey, borderKey]) setPaletteColor(key, undefined);
              // Aj zoom, veľkosť a rozostup – tie sedia v `layers`, nie
              // v `shields`, takže by ich vyprázdnenie `shields` nechalo tak
              // a tlačidlo by nesplnilo, čo sľubuje.
              resetLayer(`road-shield-${id}`);
            }
            apply();
          }
        })
      ])
    ]);
  }

  // ---------- tab: ikony ----------
  /**
   * Náhľad ikoniek: sprite je SDF, takže alfa nesie vzdialenostné pole a
   * hrana symbolu leží na 0,75. Prekreslíme ho na plnú farbu, nech je vidieť,
   * ako budú ikony na mape naozaj vyzerať.
   */
  function drawPreview(canvas, image, names, color) {
    if (!image || !image.complete || !image.naturalWidth) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
    let x = 0;
    for (const [, e] of names) {
      const w = e.width;
      const h = e.height;
      const tmp = document.createElement("canvas");
      tmp.width = w;
      tmp.height = h;
      const tctx = tmp.getContext("2d");
      tctx.drawImage(image, e.x, e.y, w, h, 0, 0, w, h);
      const data = tctx.getImageData(0, 0, w, h);
      for (let i = 0; i < data.data.length; i += 4) {
        const a = data.data[i + 3];
        // 191 = hrana SDF; úzky prechod okolo nej dá vyhladený okraj.
        const alpha = a >= 200 ? 255 : a >= 175 ? ((a - 175) * 255) / 25 : 0;
        data.data[i] = r;
        data.data[i + 1] = g;
        data.data[i + 2] = b;
        data.data[i + 3] = alpha;
      }
      tctx.putImageData(data, 0, 0);
      const scale = Math.min(1, (canvas.height - 2) / h);
      ctx.drawImage(tmp, x, (canvas.height - h * scale) / 2, w * scale, h * scale);
      x += w * scale + 4;
      if (x > canvas.width) break;
    }
  }

  const PREVIEW_CLASSES = [
    "restaurant", "cafe", "fuel", "hospital", "bank", "lodging", "museum",
    "picnic_site", "campsite", "information", "shop", "bus", "railway",
    "park", "pharmacy", "post", "swimming", "mountain"
  ];

  function renderIcons() {
    const sets = getIconSets ? getIconSets() : [];
    const current = selectedIconSource(overrides);
    const color = mergedPalette(getTheme(), overrides).poiIcon || "#444444";

    if (!sets.length) {
      return el("p", {
        class: "dev-hint",
        text: "Nenašla sa žiadna nasadená sada ikoniek."
      });
    }

    const cards = sets.map((set) => {
      const radio = el("input", { type: "radio", name: "dev-iconset", class: "dev-check" });
      radio.checked = set.id === current;
      radio.addEventListener("change", () => {
        overrides.icons = set.id;
        apply({ immediate: true });
      });

      const canvas = el("canvas", { class: "dev-preview", width: "360", height: "26" });
      // Ukážeme len ikony, ktoré sada naozaj má.
      const index = set.index || null;
      const names = PREVIEW_CLASSES.map((c) => `${c}${set.suffix || ""}`)
        .filter((n) => set.icons.includes(n))
        .slice(0, 14);
      // Sprite načítava `spriteImageFor` – jedno miesto pre náhľad sady aj
      // pre mriežku s výberom ikoniek. Kým sa obrázok stiahne, je plátno
      // prázdne a po dokreslení sa panel prekreslí sám.
      if (names.length) {
        drawPreview(
          canvas,
          spriteImageFor(set),
          names.map((n) => [n, (index || {})[n]]).filter(([, e]) => e),
          color
        );
      }

      return el("label", { class: `dev-iconset${set.id === current ? " on" : ""}` }, [
        el("div", { class: "dev-row" }, [
          radio,
          el("span", { class: "dev-name" }, [
            el("span", { text: set.label }),
            el("small", { text: `${set.count} obrázkov · ${set.license || "?"}` })
          ]),
          set.sdf
            ? el("span", { class: "dev-kind k-point", text: "farbiteľné" })
            : el("span", { class: "dev-kind", text: "bez farby" })
        ]),
        names.length ? canvas : null,
        set.note ? el("p", { class: "dev-hint", text: set.note }) : null,
        set.source
          ? el("a", { class: "dev-note", href: set.source, target: "_blank", rel: "noreferrer", text: set.source })
          : null
      ]);
    });

    return el("div", {}, [
      el("p", {
        class: "dev-hint",
        text:
          "Sada ikoniek pre POI, vrcholy a letiská. Pipeline z každého zdroja " +
          "vyrobí SDF sprite bez podkladov, takže sa dajú prepínať naživo a " +
          "vybraná sada sa zapečie do štýlu pre web aj iOS."
      }),
      ...cards,
      customSetSection(),
      customIconSection()
    ]);
  }

  // ---------- vlastná sada ikoniek ----------
  // Sprite je verejná dvojica súborov, takže nie je dôvod, aby bol zoznam
  // sád uzavretý v zdrojáku. Sem sa zadá adresa BEZ prípony (pipeline si
  // doplní `.json` aj `.png`) a prípona mien ikon, ak ju sada má (`_11`).
  function customSetSection() {
    const rows = (overrides.iconSets || []).map((set) =>
      el("div", { class: "dev-prow changed" }, [
        el("span", { class: "dev-name", title: set.sprite }, [
          el("span", { text: set.label }),
          el("small", { text: `${set.id}${set.suffix ? ` · prípona ${set.suffix}` : ""}` })
        ]),
        el("button", {
          type: "button",
          class: "dev-mini",
          title: "Zmazať túto sadu",
          text: "×",
          onclick: () => {
            overrides.iconSets = (overrides.iconSets || []).filter((x) => x.id !== set.id);
            // Zmazaná sada nesmie ostať vybraná – mapa by sa pýtala na sprite,
            // ktorý nikto nesťahuje, a ostala by bez ikon.
            if (overrides.icons === set.id) overrides.icons = DEFAULT_ICON_SOURCE;
            apply({ immediate: true });
          }
        })
      ])
    );

    const meno = el("input", { type: "text", class: "dev-text", placeholder: "Moja sada" });
    const adresa = el("input", {
      type: "url",
      class: "dev-text",
      placeholder: "https://…/sprites/moja  (bez .json a .png)"
    });
    const pripona = el("input", { type: "text", class: "dev-num", placeholder: "_11", size: "4" });

    return el("div", {}, [
      el("div", { class: "dev-h5" }, [
        el("span", { text: "Vlastná sada ikoniek" }),
        el("small", { text: "adresa spritu bez prípony – build si ho stiahne a prerobí na SDF" })
      ]),
      ...rows,
      el("div", { class: "dev-sub" }, [meno, adresa, pripona,
        el("button", {
          type: "button",
          class: "dev-btn",
          text: "+ Pridať sadu",
          onclick: () => {
            const url = adresa.value.trim().replace(/\.(json|png)$/i, "");
            if (!url) return poznamka("Zadaj adresu spritu (bez .json a .png).");
            const id = `${CUSTOM_SET_PREFIX}${(meno.value.trim() || "sada")
              .toLowerCase()
              .normalize("NFD")
              .replace(/[\u0300-\u036f]/g, "")
              .replace(/[^a-z0-9-]+/g, "-")
              .replace(/^-+|-+$/g, "")
              .slice(0, 32) || "sada"}`;
            const next = [...(overrides.iconSets || []), {
              id,
              label: meno.value.trim() || id,
              sprite: url,
              suffix: pripona.value.trim()
            }];
            const { overrides: clean, problems } = normalizeOverrides({ ...overrides, iconSets: next });
            if (problems.length) return poznamka(problems[0]);
            overrides = clean;
            meno.value = "";
            adresa.value = "";
            apply({ immediate: true });
          }
        })
      ]),
      el("p", {
        class: "dev-hint",
        text:
          "Kým beh mapy sadu nespracuje, načíta sa v prehliadači priamo z jej " +
          "adresy – ikony vtedy majú svoje pôvodné farby a nedajú sa prefarbiť. " +
          "Po builde je z nej SDF sprite ako z ostatných."
      })
    ]);
  }

  // ---------- vlastné ikony ----------
  // Jedna konkrétna vec inak: značka, POI, čokoľvek symbolové. Obrázok sa
  // prevedie na PNG a leží PRIAMO v úpravách, takže ho má aj mapa v mobile
  // (rozpis v hlavičke `poc/web/dev-icons.js`).
  /**
   * NAHRATIE VLASTNÉHO OBRÁZKA AKO VZORU.
   *
   * Obrázok sa uloží ako VLASTNÁ IKONA úprav (`own:…`) – to nie je obchádzka,
   * ale celá pointa: taký obrázok sa nesie priamo v úpravách (funguje offline
   * aj v balíku pre mobil), prehliadač ho dokreslí hneď a do každého spritu
   * ho dopečie `workers/assets/custom-icons.mjs`. Druhá cesta pre „obrázky,
   * ktoré sú vzory" by bola druhé miesto, ktoré sa raz rozíde s prvým.
   *
   * VEĽKOSŤ DLAŽDICE SA VYBERÁ TU, pri nahratí, a obrázok sa na ňu rovno
   * prevzorkuje. `fill-pattern` sa v MapLibre neškáluje – dlaždicuje sa tak,
   * ako je obrázok veľký –, takže „veľkosť až pri kreslení" by musel rovnako
   * spraviť aj sprite. Čo je uložené, je to, čo mapa kreslí.
   */
  function patternUpload(layer) {
    const velkost = el("select", { class: "dev-select", title: "Strana dlaždice" },
      IMAGE_PATTERN_SIZES.map((px) =>
        el("option", {
          value: String(px),
          text: `${px} px`,
          ...(px === IMAGE_PATTERN_SIZE ? { selected: true } : {})
        })
      )
    );

    const subor = el("input", {
      type: "file",
      class: "dev-file",
      accept: "image/png,image/jpeg,image/svg+xml"
    });
    subor.addEventListener("change", async () => {
      const file = subor.files && subor.files[0];
      if (!file) return;
      try {
        const px = Number(velkost.value) || IMAGE_PATTERN_SIZE;
        const { png, pixelRatio } = await fileToIconPng(file, px);
        const name = iconNameFromFile(file.name, CUSTOM_ICON_PREFIX);
        const next = [
          ...(overrides.customIcons || []).filter((x) => x.name !== name),
          { name, png, pixelRatio }
        ];
        // Obrázok aj jeho použitie ako vzoru naraz: keby sa uložil len
        // obrázok, musel by ho človek ešte nájsť v mriežke – a keby sa uložil
        // len vzor, ukazoval by na obrázok, ktorý v úpravách nie je.
        const skuska = {
          ...overrides,
          customIcons: next,
          layers: {
            ...overrides.layers,
            [layer.id]: { ...(overrides.layers[layer.id] || {}), pattern: { image: name, opacity: 1 } }
          }
        };
        const { overrides: clean, problems } = normalizeOverrides(skuska);
        if (problems.length) {
          poznamka(problems[0]);
          return;
        }
        overrides = clean;
        poznamka(`Vzor „${name}" (${px} px) nahratý a nasadený na ${layer.id}.`);
        apply({ immediate: true });
      } catch (err) {
        poznamka(`Obrázok sa nepodarilo načítať: ${err.message}`);
      } finally {
        subor.value = "";
      }
    });

    return el("div", { class: "dev-sub" }, [
      el("span", { class: "dev-note", text: "Vlastný obrázok ako vzor" }),
      velkost,
      subor,
      el("p", {
        class: "dev-hint",
        text:
          "PNG, JPG alebo SVG. Obrázok sa prevzorkuje na zvolenú stranu dlaždice " +
          "a uloží sa priamo do úprav – mapa ho má hneď a build ho dopečie do " +
          "spritu (aj pre mobil). Dlaždicuje sa v tej veľkosti, v akej je " +
          "uložený; inú veľkosť dostaneš nahratím znova. Nahraté obrázky sú " +
          "vo výbere vzoru pri každej ploche aj čiare."
      })
    ]);
  }

  function customIconSection() {
    const zoznam = overrides.customIcons || [];
    const rows = zoznam.map((ikona) => {
      const nahlad = el("canvas", { class: "dev-icon", width: "22", height: "22" });
      const img = new Image();
      img.onload = () => {
        const ctx = nahlad.getContext("2d");
        const scale = Math.min(1, 20 / img.width, 20 / img.height);
        ctx.drawImage(img, (22 - img.width * scale) / 2, (22 - img.height * scale) / 2,
                      img.width * scale, img.height * scale);
      };
      img.src = ikona.png;
      return el("div", { class: "dev-prow changed" }, [
        nahlad,
        el("span", { class: "dev-name" }, [
          el("span", { text: ikona.name }),
          el("small", { text: `${Math.round(ikona.png.length / 1024)} kB · @${ikona.pixelRatio || 1}x` })
        ]),
        el("button", {
          type: "button",
          class: "dev-mini",
          title: "Zmazať túto ikonu (vrstvy, ktoré ju používajú, ostanú bez ikony)",
          text: "×",
          onclick: () => {
            overrides.customIcons = zoznam.filter((x) => x.name !== ikona.name);
            apply({ immediate: true });
          }
        })
      ]);
    });

    const subor = el("input", { type: "file", class: "dev-file", accept: "image/png,image/jpeg,image/svg+xml" });
    subor.addEventListener("change", async () => {
      const file = subor.files && subor.files[0];
      if (!file) return;
      try {
        const { png, pixelRatio } = await fileToIconPng(file, CUSTOM_ICON_MAX_PX);
        const name = iconNameFromFile(file.name, CUSTOM_ICON_PREFIX);
        const next = [
          ...(overrides.customIcons || []).filter((x) => x.name !== name),
          { name, png, pixelRatio }
        ];
        const { overrides: clean, problems } = normalizeOverrides({ ...overrides, customIcons: next });
        if (problems.length) {
          poznamka(problems[0]);
          return;
        }
        overrides = clean;
        poznamka(`Ikona "${name}" pridaná – nájdeš ju vo výbere ikon.`);
        apply({ immediate: true });
      } catch (err) {
        poznamka(`Ikonu sa nepodarilo načítať: ${err.message}`);
      } finally {
        subor.value = "";
      }
    });

    return el("div", {}, [
      el("div", { class: "dev-h5" }, [
        el("span", { text: "Vlastné ikony" }),
        el("small", {
          text: `PNG, JPG alebo SVG · najviac ${CUSTOM_ICON_MAX_COUNT} po `
            + `${Math.round(CUSTOM_ICON_MAX_BYTES / 1024)} kB`
        })
      ]),
      ...rows,
      el("div", { class: "dev-sub" }, [subor]),
      el("p", {
        class: "dev-hint",
        text:
          `Obrázok sa zmenší na ${CUSTOM_ICON_MAX_PX} px a uloží sa priamo do ` +
          "úprav, takže mapa má ikonu hneď – a build ju dopečie do každého " +
          "spritu, aby bola aj v mape pre mobil. Vybrať sa dá všade, kde sa " +
          "vyberá ikona (vrstva aj druh trasy)."
      })
    ]);
  }

  // ---------- tab: POI ----------
  function scanPoiClasses() {
    const map2 = getMap();
    if (!map2) return [];
    const counts = new Map();
    // Aj vlastné body (prameň, jaskyňa, rozhľadňa): sú to tie isté kategórie
    // s tou istou otázkou („akou značkou sa kreslia") a ich vrstva berie
    // ikonu aj skryté triedy z toho istého zoznamu – keby tu neboli, dali by
    // sa nastaviť len naslepo.
    for (const [source, sourceLayer] of [["omt", "poi"], ["points", "feature_point"]]) {
      let features = [];
      try {
        features = map2.querySourceFeatures(source, { sourceLayer });
      } catch {
        features = [];
      }
      for (const f of features) {
        const key = f.properties?.subclass || f.properties?.class;
        if (key) counts.set(key, (counts.get(key) || 0) + 1);
      }
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }

  /** Skryté POI triedy: spoločné aj tie pre práve zobrazený typ mapy. */
  const poiHiddenAll = () =>
    new Set([...overrides.poi.hidden, ...(mapBucket()?.poi?.hidden || [])]);

  /**
   * IKONA KATEGÓRIE. `undefined` = späť na ikonu podľa sady, `""` = žiadna –
   * sú to tri odpovede a nedajú sa stlačiť do dvoch (tá istá úvaha ako pri
   * značke druhu trasy).
   *
   * Je to spoločné pre všetky typy máp, na rozdiel od skrývania: akou značkou
   * sa kreslí studnička, je vlastnosť kategórie, nie mapy.
   */
  function setPoiIcon(cls, name) {
    overrides.poi.icons = { ...(overrides.poi.icons || {}) };
    if (name === undefined) delete overrides.poi.icons[cls];
    else overrides.poi.icons[cls] = name;
  }

  /** Ktorá ikona je pre kategóriu naozaj v mape (to isté, čo počíta štýl). */
  function poiIconNow(cls) {
    const set = currentSet();
    return poiIconName(cls, {
      classes: iconClassesOf(set?.icons || [], set?.suffix || ""),
      suffix: set?.suffix || "",
      overrides
    });
  }

  function setPoiHidden(cls, hide) {
    const bucket = editScope === "all" ? overrides.poi : mapBucket(true).poi;
    const next = new Set(bucket.hidden);
    if (hide) next.add(cls);
    else next.delete(cls);
    bucket.hidden = [...next].sort();
    pruneMaps();
  }

  function renderPoi() {
    const hidden = poiHiddenAll();
    const inBase = new Set(overrides.poi.hidden);
    const known = new Map(poiClasses);
    for (const h of hidden) if (!known.has(h)) known.set(h, 0);
    const list = [...known.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

    const set = currentSet();
    const image = spriteImageFor(set);
    const farba = mergedPalette(getTheme(), overrides).poiIcon || "#444444";
    const vlastne = overrides.poi.icons || {};

    const rows = list.flatMap(([cls, count]) => {
      const check = el("input", { type: "checkbox", class: "dev-check" });
      check.checked = !hidden.has(cls);
      check.addEventListener("change", () => {
        setPoiHidden(cls, !check.checked);
        apply({ rerender: false });
      });
      // Trieda skrytá spoločne sa v rozsahu „len táto mapa" vrátiť nedá –
      // nech je jasné, prečo odškrtnutie nič neurobí.
      const stuck = editScope === "map" && inBase.has(cls);
      const ikona = poiIconNow(cls);
      const zmenena = vlastne[cls] !== undefined;
      const otvorene = poiOpen.has(cls);
      const riadok = el("div", { class: `dev-prow${hidden.has(cls) ? " off" : ""}${zmenena ? " changed" : ""}` }, [
        check,
        // NÁHĽAD JE PRIAMO V RIADKU, nie až po rozkliknutí: otázka „akú má
        // táto kategória ikonu" je práve tá, kvôli ktorej sem človek ide,
        // a meno (`restaurant_11`) na ňu neodpovedá.
        iconPreview({ name: ikona, set, image, custom: overrides.customIcons || [], color: farba }),
        el("button", {
          type: "button",
          class: "dev-name",
          title: `${cls} – klikni pre výber ikony`,
          onclick: () => {
            if (otvorene) poiOpen.delete(cls);
            else poiOpen.add(cls);
            renderBody();
          }
        }, [
          el("span", { text: `${otvorene ? "▾ " : "▸ "}${cls}` }),
          el("small", {
            text:
              (stuck
                ? "skryté pre všetky mapy – prepni rozsah"
                : count
                ? `${count} v zobrazenom výreze`
                : "skryté") +
              ` · ${ikona || "bez ikony"}${zmenena ? " (vlastná)" : ""}`
          })
        ]),
        zmenena
          ? el("button", {
              type: "button",
              class: "dev-mini",
              text: "⟲",
              title: "Späť na ikonu podľa sady",
              onclick: () => {
                setPoiIcon(cls, undefined);
                apply({ immediate: true });
              }
            })
          : null
      ]);
      if (!otvorene) return [riadok];
      return [
        riadok,
        el("div", { class: "dev-details" }, [
          iconGrid({
            kluc: `poi:${cls}`,
            value: ikona,
            names: iconNames(ikona),
            noneLabel: "žiadna",
            onPick: (name) => {
              setPoiIcon(cls, name);
              apply({ immediate: true });
            }
          })
        ])
      ];
    });

    return el("div", {}, [
      el("p", {
        class: "dev-hint",
        text:
          "Ktoré body sa zobrazujú a akou ikonou. Zoznam sa načíta z dlaždíc " +
          "v aktuálnom výreze – prejdi mapu tam, kde tie body sú, a načítaj znova. " +
          "Klikni na kategóriu a vyber jej ikonu; voľba „žiadna“ nechá len popisok. " +
          "Ikona platí pre všetky typy máp, skrývanie sa riadi rozsahom nižšie."
      }),
      scopeBar(),
      el("div", { class: "dev-bulk on" }, [
        el("button", {
          type: "button",
          class: "dev-btn",
          text: "Načítať triedy z mapy",
          onclick: () => {
            poiClasses = scanPoiClasses();
            renderBody();
          }
        }),
        el("button", {
          type: "button",
          class: "dev-btn danger",
          text: editScope === "all" ? "Zobraziť všetky (všade)" : "Zobraziť všetky (táto mapa)",
          onclick: () => {
            if (editScope === "all") overrides.poi.hidden = [];
            else if (mapBucket()) mapBucket().poi.hidden = [];
            pruneMaps();
            apply();
          }
        }),
        Object.keys(overrides.poi.icons || {}).length
          ? el("button", {
              type: "button",
              class: "dev-btn danger",
              text: "Späť na pôvodné ikony",
              title: "Zahodí vybrané ikony všetkých kategórií (skrývanie ostane)",
              onclick: () => {
                overrides.poi.icons = {};
                apply();
              }
            })
          : null
      ]),
      rows.length
        ? el("div", { class: "dev-list" }, rows)
        : el("p", { class: "dev-hint", text: "Zatiaľ nič – klikni na tlačidlo Načítať triedy z mapy." })
    ]);
  }

  // ---------- tab: súbor ----------
  function renderFile() {
    const json = serializeOverrides(overrides);
    const area = el("textarea", { class: "dev-json", spellcheck: "false" });
    area.value = json;

    const fileInput = el("input", { type: "file", accept: ".json,application/json", class: "dev-file" });
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      try {
        const parsed = JSON.parse(await file.text());
        const { overrides: clean, problems } = normalizeOverrides(parsed);
        overrides = clean;
        apply({ immediate: true });
        if (problems.length) alert(`Načítané s výhradami:\n\n${problems.join("\n")}`);
      } catch (err) {
        alert(`Súbor sa nepodarilo načítať: ${err.message}`);
      }
    });

    return el("div", {}, [
      el("p", {
        class: "dev-hint",
        html:
          "Úpravy sú priebežne uložené v prehliadači. Stiahni ich ako " +
          "<code>style-overrides.json</code> a nahraj cez workflow " +
          "<b>Mapa · úpravy štýlu</b> (Actions → Run workflow → " +
          "vlož obsah súboru). Pipeline ich zapečie do mapy pre web aj iOS.<br>" +
          "V súbore je <code>layers</code> a <code>poi</code> spoločné pre " +
          "všetky typy máp, <code>maps</code> drží to, čo platí len pre jednu."
      }),
      el("div", { class: "dev-bulk on" }, [
        el("button", {
          type: "button",
          class: "dev-btn",
          text: "⬇ Stiahnuť style-overrides.json",
          onclick: () => {
            const blob = new Blob([serializeOverrides(overrides)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = el("a", { href: url, download: "style-overrides.json" });
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          }
        }),
        el("button", {
          type: "button",
          class: "dev-btn",
          text: "⧉ Kopírovať JSON",
          onclick: (ev) => copyText(serializeOverrides(overrides), ev.currentTarget)
        }),
        el("button", {
          type: "button",
          class: "dev-btn",
          text: "Použiť z textu",
          onclick: () => {
            try {
              const { overrides: clean, problems } = normalizeOverrides(JSON.parse(area.value));
              overrides = clean;
              apply({ immediate: true });
              if (problems.length) alert(`Použité s výhradami:\n\n${problems.join("\n")}`);
            } catch (err) {
              alert(`Neplatný JSON: ${err.message}`);
            }
          }
        }),
        el("button", {
          type: "button",
          class: "dev-btn danger",
          text: "Vymazať všetky zmeny",
          onclick: () => {
            if (!confirm("Naozaj zahodiť všetky úpravy štýlu?")) return;
            overrides = emptyOverrides();
            selectedLayers.clear();
            selectedPaletteKeys.clear();
            apply({ immediate: true });
          }
        })
      ]),
      el("label", { class: "dev-hint", text: "Nahrať súbor:" }),
      fileInput,
      area
    ]);
  }

  // ---------- render ----------
  function renderBody() {
    const view =
      tab === "layers"
        ? renderLayers()
        : tab === "stack"
        ? renderStack()
        : tab === "pick"
        ? renderPick()
        : tab === "palette"
        ? renderPalette()
        : tab === "trails"
        ? renderTrails()
        : tab === "shields"
        ? renderShields()
        : tab === "icons"
        ? renderIcons()
        : tab === "poi"
        ? renderPoi()
        : renderFile();
    const scroll = body.scrollTop;
    body.replaceChildren(view);
    body.scrollTop = scroll;
  }

  function render() {
    renderThemeToggle();
    renderTabs();
    renderBody();
    renderStatus();
  }

  render();

  return {
    getOverrides: () => overrides,
    refresh: render,
    /** Beží inšpektor? Viewer vtedy nevyskakuje s vlastným popupom. */
    isPicking: () => tab === "pick",
    setOverrides(next) {
      overrides = normalizeOverrides(next).overrides;
      apply({ immediate: true });
    }
  };
}
