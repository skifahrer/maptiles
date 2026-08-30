/**
 * Zdroje ikoniek pre POI, vrcholy a letiská.
 *
 * Každý zdroj je hotový MapLibre sprite (PNG + JSON index) z otvoreného
 * štýlu. Pipeline z každého vyrobí vlastný **SDF sprite** bez podkladov
 * (workers/assets/sprite.mjs) a nasadí ich všetky, takže sa dajú
 * v developer móde prepínať naživo a vybraná sada sa zapečie do štýlu
 * pre web aj iOS.
 *
 * Prečo práve tieto: schéma OpenMapTiles pomenúva POI cez `class`/`subclass`
 * (`restaurant`, `cafe`, `fuel`, …) a štýl z toho skladá meno ikony. Zdroj je
 * teda použiteľný len vtedy, keď jeho ikony nesú rovnaké mená. Preverené boli
 * aj sprity ostatných štýlov OpenMapTiles (positron, dark-matter, klokantech,
 * maptiler-basic, fiord) – tie majú v sprite 1–4 obrázky, teda žiadne POI
 * ikony – a sprite Protomaps v4, ktorý má vlastné pomenovanie a z bežných
 * tried OSM pokryje asi tretinu, navyše s rámčekom okolo symbolu.
 */

import { DEFAULT_ARROW_IMAGE } from "./arrows.js";

export const ICON_SOURCES = [
  {
    id: "osm-liberty",
    label: "OSM Liberty (maki)",
    sprite:
      "https://raw.githubusercontent.com/maputnik/osm-liberty/gh-pages/sprites/osm-liberty",
    source: "https://github.com/maputnik/osm-liberty",
    license: "BSD-3-Clause, ikony maki (CC0)",
    suffix: "_11",
    note:
      "Klasická sada maki – najširšie pokrytie tried OSM. V origináli je " +
      "každý symbol v bielom koliesku, ktoré pipeline odstráni."
  },
  {
    id: "osm-liberty-topo",
    label: "OSM Liberty Topo (turistická)",
    sprite:
      "https://raw.githubusercontent.com/nst-guide/osm-liberty-topo/gh-pages/sprites/osm-liberty-topo",
    source: "https://github.com/nst-guide/osm-liberty-topo",
    license: "BSD-3-Clause",
    suffix: "_11",
    note:
      "Turistická odvodenina osm-liberty s doplnenými outdoorovými symbolmi."
  },
  {
    id: "osm-bright",
    label: "OSM Bright (OpenMapTiles)",
    sprite:
      "https://raw.githubusercontent.com/openmaptiles/osm-bright-gl-style/gh-pages/sprite",
    source: "https://github.com/openmaptiles/osm-bright-gl-style",
    license: "BSD-3-Clause",
    suffix: "_11",
    note:
      "Striedmejšia sada bez koliesok – symboly majú len svetlé halo, ktoré " +
      "pipeline odlúpne. Menej tried, zato čistejšia kresba."
  }
];

/**
 * VLASTNÁ SADA IKONIEK. Zdroje vyššie sú tie, ktoré má repozitár overené –
 * ale nie je dôvod, aby to bol uzavretý zoznam: sprite je verejný súbor
 * (`<niečo>.json` + `<niečo>.png`) a kto má vlastný, má ho vedieť skúsiť bez
 * zásahu do zdrojáku. Vlastné sady sú preto v úpravách z developer módu
 * (`overrides.iconSets`) a pipeline ich sťahuje a prerába na SDF presne tak
 * ako tie tri hore.
 *
 * `id` má PREDPONU `own-`, a to nie je kozmetika: podľa nej sa dá odlíšiť,
 * čo je z repozitára a čo dopísal človek – a zároveň sa tým nedá prepísať
 * overená sada tichou zhodou mien.
 */
export const CUSTOM_SET_PREFIX = "own-";

/** Vlastné sady z úprav (už prečistené `normalizeOverrides`). */
export function customIconSources(overrides) {
  return Array.isArray(overrides?.iconSets) ? overrides.iconSets : [];
}

/** Všetky sady: overené z repozitára + vlastné z úprav. */
export function allIconSources(overrides) {
  return [...ICON_SOURCES, ...customIconSources(overrides)];
}

/** Sada podľa id (aj vlastná); pri neznámom id vráti predvolenú. */
export function iconSourceIn(id, overrides) {
  return allIconSources(overrides).find((s) => s.id === id) || ICON_SOURCES[0];
}

export const DEFAULT_ICON_SOURCE = "osm-liberty";

export const ICON_SOURCE_IDS = ICON_SOURCES.map((s) => s.id);

/** Zdroj podľa id; pri neznámom id vráti predvolený. */
export function iconSource(id) {
  return ICON_SOURCES.find((s) => s.id === id) || ICON_SOURCES[0];
}

/**
 * Mená ikon, na ktoré sa štýl odkazuje priamo (nie cez `class`/`subclass`).
 * Odvodzujú sa z prípony zdroja; ak ich sprite nemá, štýl ich vynechá.
 */
export function specialIcons(id, overrides) {
  const { suffix } = overrides ? iconSourceIn(id, overrides) : iconSource(id);
  return {
    peak: `mountain${suffix}`,
    volcano: `volcano${suffix}`,
    airport: `airport${suffix}`,
    // ŠÍPKA JEDNOSMERKY NIE JE ZO SADY. Kým to bola cudzia `arrow`, mala ju
    // jediná z troch overených sád – pri ostatných sa vrstva `road-oneway`
    // do štýlu vôbec nedostala, takže sa nedalo nastaviť ani ako často sú
    // šípky, ani akej sú farby (rozpis v `poc/web/arrows.js`). Kreslíme si ju
    // preto sami a pečieme do každého spritu, ako štítky ciest a značky trás.
    arrow: DEFAULT_ARROW_IMAGE
  };
}
