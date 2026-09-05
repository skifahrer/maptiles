/**
 * Zdroje ikoniek pre POI, vrcholy a letiská.
 *
 * Každý zdroj je hotový MapLibre sprite z otvoreného štýlu; pipeline z každého
 * vyrobí SDF sprite bez podkladov a nasadí ich všetky, takže sa dajú prepínať
 * naživo a vybraná sada sa zapečie do štýlu pre web aj iOS.
 *
 * Prečo práve tieto: štýl skladá meno ikony z `class`/`subclass` OpenMapTiles,
 * takže zdroj je použiteľný, len keď jeho ikony nesú rovnaké mená. Sprity
 * ostatných štýlov OpenMapTiles majú 1–4 obrázky, Protomaps v4 má vlastné
 * pomenovanie a pokryje asi tretinu tried.
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
 * Vlastná sada ikoniek. Sprite je verejný súbor (`<x>.json` + `<x>.png`), tak
 * nie je dôvod, aby bol zoznam uzavretý – vlastné sady sú v úpravách
 * z developer módu a pipeline ich prerába na SDF ako tie tri hore.
 *
 * `id` má predponu `own-`: podľa nej sa dá odlíšiť, čo je z repozitára,
 * a nedá sa tichou zhodou mien prepísať overená sada.
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
