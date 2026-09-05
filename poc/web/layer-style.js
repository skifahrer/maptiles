/**
 * Čítanie a prenášanie štýlu jednej vrstvy – bez DOM, aby sa to dalo spustiť
 * aj z kontroly (`workers/lint/overrides.mjs`).
 *
 * Dve otázky, ktoré developer mode potreboval a nemal:
 *
 *   1. „Čo tá vlastnosť práve teraz robí?" Hrúbka čiary je spravidla
 *      `interpolate` podľa zoomu, takže políčko ukazuje „auto"; `valueAtZoom`
 *      z krivky vytiahne hodnotu na aktuálnom zoome.
 *   2. „Sprav túto vrstvu takú, ako je tamtá." `snapshotStyle` odfotí účinný
 *      vzhľad (nie len úpravu nad ním) a `pasteStyle` ho preloží inam.
 *
 * Účinný vzhľad preto, že kopírovanie z vrstvy, ktorú nikto neladil, by inak
 * vrátilo prázdno – a práve to je najčastejšie zadanie.
 *
 * Preklad medzi druhmi vrstiev je podľa prípony, nie podľa mena: `fill-color`
 * na čiaru je `line-color`. Vlastnosť, ktorú cieľ nepozná, sa nevloží a povie
 * sa to – tichý polovičný vklad by vyzeral ako pokazené kopírovanie.
 */
import {
  MAX_PAINT_STOPS,
  NO_FILL,
  sortStops,
  sortBands,
  isBandList,
  isScalarValue,
  stepToBands,
  valueAtZoom
} from "./themes.js";
import { dashIdOf } from "./patterns.js";

export { dashIdOf };

// `valueAtZoom` býval tu; presunul sa do `themes.js`, lebo tú istú odpoveď
// potrebuje aj skladanie štýlu (percento v pásme). Vyváža sa ďalej odtiaľto,
// aby volajúci nemuseli vedieť, kde presne leží.
export { valueAtZoom };

/** Vlastnosti, ktoré formát úprav vôbec pozná (`cleanPaintScalar`). */
const SUFFIXES = ["-color", "-opacity", "-width", "-exaggeration"];

/**
 * Čo smie mať ktorý druh vrstvy. Zámerne je to VÝPOČET, nie „skús a uvidíš":
 * MapLibre neznámu `paint` vlastnosť odmietne aj s celým štýlom.
 */
const ALLOWED = {
  fill: ["fill-color", "fill-opacity", "fill-outline-color"],
  line: ["line-color", "line-opacity", "line-width"],
  "fill-extrusion": ["fill-extrusion-color", "fill-extrusion-opacity"],
  symbol: [
    "text-color", "text-opacity", "text-halo-color", "text-halo-width",
    "icon-color", "icon-opacity", "icon-halo-color", "icon-halo-width"
  ],
  circle: [
    "circle-color", "circle-opacity", "circle-stroke-color",
    "circle-stroke-width", "circle-stroke-opacity"
  ],
  background: ["background-color", "background-opacity"],
  // Tieňovanie reliéfu. `hillshade-exaggeration` je jeho sila – jediné
  // číslo, ktoré nie je krytie ani hrúbka a úpravy ho aj tak poznajú
  // (viď `cleanPaintScalar`).
  hillshade: [
    "hillshade-exaggeration",
    "hillshade-shadow-color",
    "hillshade-highlight-color",
    "hillshade-accent-color"
  ]
};

/** Predpona, pod ktorou má daný druh vrstvy svoju hlavnú vlastnosť. */
const PREFIX = {
  fill: "fill",
  line: "line",
  "fill-extrusion": "fill-extrusion",
  symbol: "text",
  circle: "circle",
  background: "background",
  hillshade: "hillshade"
};

/** Podporuje vrstva vzor a okraj? (plochy a čiary áno, popisky nie) */
export const canDecorate = (layer) =>
  layer?.type === "fill" || layer?.type === "line" || layer?.type === "fill-extrusion";

/**
 * Hodnota z hotového štýlu → hodnota, akú unesie súbor úprav.
 * Krivka sa zapíše ako zoomové zlomy, `step` ako zoomové pásma. Keď ich je
 * viac než `MAX_PAINT_STOPS`, nechajú sa krajné a rovnomerne rozložené
 * vnútorné – inak by `normalizeOverrides` celú vlastnosť zahodil.
 */
function snapValue(value) {
  if (isScalarValue(value)) return value;
  if (!Array.isArray(value)) return null;
  if (isBandList(value)) return thinBands(sortBands(value));
  if (Array.isArray(value[0])) {
    const stops = sortStops(value.filter((s) => Array.isArray(s) && s.length === 2));
    return stops.length ? thin(stops) : null;
  }
  // Schodisko podľa zoomu sa odfotí ako PÁSMA – teda ako to, čo ho vyrobilo.
  // Preložiť ho na krivku by z konštantných pásiem spravilo plynulý prechod
  // a vložená vrstva by vyzerala inak než tá, z ktorej sa kopírovalo.
  if (value[0] === "step") {
    const bands = stepToBands(value);
    return bands ? thinBands(bands) : null;
  }
  if (value[0] !== "interpolate") return null;
  const [, , input, ...rest] = value;
  if (!Array.isArray(input) || input[0] !== "zoom") return null;
  const stops = [];
  for (let i = 0; i + 1 < rest.length; i += 2) {
    if (typeof rest[i] !== "number" || !isScalarValue(rest[i + 1])) return null;
    stops.push([rest[i], rest[i + 1]]);
  }
  return stops.length ? thin(stops) : null;
}

/**
 * Preriedi PÁSMA na strop. Vypustené pásmo pohltí to pred ním (predĺži sa
 * jeho `do`), takže rad ostane SÚVISLÝ – medzeru by `cleanPaintBands`
 * odmietol a s ňou celú vlastnosť.
 */
function thinBands(bands) {
  if (!bands.length) return null;
  const vybrane =
    bands.length <= MAX_PAINT_STOPS
      ? bands
      : (() => {
          const out = [bands[0]];
          const krok = (bands.length - 1) / (MAX_PAINT_STOPS - 1);
          for (let i = 1; i < MAX_PAINT_STOPS - 1; i += 1) out.push(bands[Math.round(i * krok)]);
          out.push(bands[bands.length - 1]);
          const seen = new Set();
          return out.filter(([od]) => (seen.has(od) ? false : seen.add(od)));
        })();
  return vybrane.map(([od, doZ, v], i) => [
    od,
    i + 1 < vybrane.length ? vybrane[i + 1][0] - 1 : doZ,
    v
  ]);
}

/** Preriedi zlomy na strop – krajné ostávajú, vnútorné sa vyberú rovnomerne. */
function thin(stops) {
  if (stops.length <= MAX_PAINT_STOPS) return stops.map(([z, v]) => [z, v]);
  const out = [stops[0]];
  const step = (stops.length - 1) / (MAX_PAINT_STOPS - 1);
  for (let i = 1; i < MAX_PAINT_STOPS - 1; i += 1) out.push(stops[Math.round(i * step)]);
  out.push(stops[stops.length - 1]);
  // Preriedenie môže tú istú stopu vybrať dvakrát – dva zlomy na jednom zoome
  // by `normalizeOverrides` odmietol a s ním celú vlastnosť.
  const seen = new Set();
  return out.filter(([z]) => (seen.has(z) ? false : seen.add(z)));
}

/**
 * Odfotí vzhľad vrstvy tak, ako je NAOZAJ v mape.
 *
 * @param {object} layer  vrstva z hotového štýlu (už s úpravami)
 * @param {object} [o]    úprava tej vrstvy – nesie to, čo sa zo `paint`
 *                        prečítať nedá: „bez výplne", vzor a okraj
 * @returns {{from: string, label: string, type: string, paint: object,
 *            dash?: string, pattern?: object|null, outline?: object,
 *            icon?: string, dropped: string[]}}
 */
export function snapshotStyle(layer, o = {}) {
  const paint = {};
  const dropped = [];
  for (const [prop, value] of Object.entries(layer.paint || {})) {
    if (!SUFFIXES.some((s) => prop.endsWith(s))) continue;
    // „Bez výplne" je v štýle priehľadná farba – v úpravách má vlastné slovo.
    const own = (o.paint || {})[prop];
    const snap = own === NO_FILL ? NO_FILL : snapValue(value);
    if (snap === null) dropped.push(prop);
    else paint[prop] = snap;
  }

  const out = {
    from: layer.id,
    label: (layer.metadata || {})["frico:label"] || layer.id,
    type: layer.type,
    paint,
    dropped
  };

  const dasharray = (layer.paint || {})["line-dasharray"];
  // Plná čiara sa odfotí AKO „solid", nie ako prázdno – „sprav túto vrstvu
  // takú, ako je tamtá" musí vedieť aj zrušiť prerušovanie, ktoré má cieľová
  // vrstva zo štýlu (železnica, brod). Len pri čiare: na ploche by „solid"
  // nebola odpoveď na nič.
  const dash = o.dash || dashIdOf(dasharray)
    || (layer.type === "line" && !Array.isArray(dasharray) ? "solid" : null);
  if (dash) out.dash = dash;
  // Prerušovanie, ktoré nie je ani jedna z predvolieb (štýl si ho môže napísať
  // vlastné), sa do úprav zapísať nedá – a mlčať o tom by znamenalo, že vložená
  // vrstva vyzerá inak než tá, z ktorej sa kopírovalo.
  else if (Array.isArray(dasharray)) dropped.push("line-dasharray");

  // Vzor môže byť zabudovaný v štýle (`frico:pattern`) alebo z úpravy –
  // odfotiť treba ten ÚČINNÝ, inak by sa kopírovanie zo skalnej plochy tvárilo,
  // že žiadny vzor nemá.
  const builtin = (layer.metadata || {})["frico:pattern"] || null;
  const pattern = o && "pattern" in o ? o.pattern : builtin;
  if (pattern) out.pattern = { ...pattern };

  if (o.outline) out.outline = { ...o.outline };

  const icon = (layer.layout || {})["icon-image"];
  if (layer.type === "symbol" && typeof icon === "string") out.icon = icon;

  return out;
}

/** Hlavná vlastnosť danej prípony – tá, ktorá nie je halo ani obrys. */
function primaryOf(paint, suffix) {
  const props = Object.keys(paint).filter((p) => p.endsWith(suffix));
  return props.find((p) => !p.includes("halo") && !p.includes("outline")) || props[0] || null;
}

/**
 * Preloží odfotený vzhľad na inú vrstvu.
 *
 * Rovnaký druh dostane všetko, čo pozná. Iný druh dostane hlavnú vlastnosť
 * každej prípony preloženú na svoju predponu (`fill-color` → `line-color`).
 *
 * @returns {{patch: object, skipped: string[]}} `patch` ide do `setLayerOverride`
 */
export function pasteStyle(snap, target) {
  const allowed = new Set(ALLOWED[target.type] || []);
  const paint = {};
  const skipped = [];

  if (snap.type === target.type) {
    for (const [prop, value] of Object.entries(snap.paint)) {
      if (allowed.has(prop)) paint[prop] = value;
      else skipped.push(prop);
    }
  } else {
    const prefix = PREFIX[target.type];
    const used = new Set();
    for (const suffix of SUFFIXES) {
      const from = primaryOf(snap.paint, suffix);
      if (!from) continue;
      used.add(from);
      const to = prefix ? `${prefix}${suffix}` : null;
      if (to && allowed.has(to)) paint[to] = snap.paint[from];
      else skipped.push(from);
    }
    // Všetko ostatné (halo, obrys výplne) je vlastnosť TOHO druhu vrstvy –
    // na inom druhu nemá kam sadnúť a mlčky zmiznúť nesmie.
    for (const prop of Object.keys(snap.paint)) if (!used.has(prop)) skipped.push(prop);
  }

  // „Bez výplne" má zmysel len tam, kde je čo nevyplniť; na čiare by ju
  // `normalizeOverrides` odmietol a vypísal chybu.
  for (const [prop, value] of Object.entries(paint)) {
    if (value !== NO_FILL) continue;
    if (prop === "fill-color" || prop === "fill-extrusion-color") continue;
    delete paint[prop];
    skipped.push(prop);
  }

  const patch = {};
  if (Object.keys(paint).length) patch.paint = paint;

  if (snap.dash) {
    if (target.type === "line") patch.dash = snap.dash;
    // „Plná" na inú než čiarovú vrstvu nie je strata – tá o prerušovaní
    // nevie a v zozname „neprenieslo sa" by len mýlila.
    else if (snap.dash !== "solid") skipped.push("prerušovanie čiary");
  }
  if (snap.pattern) {
    if (canDecorate(target)) patch.pattern = { ...snap.pattern };
    else skipped.push("vzor");
  }
  if (snap.outline) {
    if (canDecorate(target)) patch.outline = { ...snap.outline };
    else skipped.push("okraj");
  }
  if (snap.icon) {
    if (target.type === "symbol" && typeof (target.layout || {})["icon-image"] === "string") {
      patch.icon = snap.icon;
    } else {
      skipped.push("ikona");
    }
  }

  return { patch, skipped: [...new Set(skipped)] };
}
