/**
 * Tabuľka sieť → štítok: celý svet z OSM Americana a k tomu, čo Americana
 * nemá a slovenská mapa potrebuje.
 *
 * Americánska časť je generovaná (`route-shield-americana.js`), táto nie.
 */
import { AMERICANA_SHAPES, AMERICANA_NETWORKS } from "./route-shield-americana.js";

/**
 * Siete, ktoré Americana nepozná. Bez nich by na slovenskej mape mali vlastný
 * štítok len diaľnice: `sk:national` sú D a R, čísla I. a II./III. triedy sú
 * inde a majú vlastnú tabuľku – modrú a bielu.
 */
export const EXTRA_SHIELDS = {
  "sk:primary": {
    shape: "roundedRectangle", fill: "#003f87", stroke: "#ffffff",
    text: "#ffffff", width: 34, radius: 2
  },
  "sk:regional": {
    shape: "roundedRectangle", fill: "#ffffff", stroke: "#000000",
    text: "#000000", width: 34, radius: 2
  }
};

const shapes = [...AMERICANA_SHAPES];
const byNetwork = { ...AMERICANA_NETWORKS };
const kluce = new Map(shapes.map((s, i) => [JSON.stringify(s), i]));

// vlastná definícia prebíja americkú: rovnaký recept nesmie byť dva obrázky
for (const [network, def] of Object.entries(EXTRA_SHIELDS)) {
  const kluc = JSON.stringify(def);
  if (!kluce.has(kluc)) {
    kluce.set(kluc, shapes.length);
    shapes.push(def);
  }
  byNetwork[network] = kluce.get(kluc);
}

export const ROUTE_SHIELD_SHAPES = shapes;
export const ROUTE_SHIELD_BY_NETWORK = byNetwork;
