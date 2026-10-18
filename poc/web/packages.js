/** Maps of one package each; who owns a layer follows the app's `MapOverlay.claimant`. */

export const BASE_PACKAGE = "base";

/** `needs`: the manifest key the region must have; none = the base tiles carry it. */
export const PACKAGES = [
  {
    id: BASE_PACKAGE,
    label: "Základná mapa",
    note: "Celá kartografia; čo z nej ukáže, určuje typ mapy."
  },
  {
    id: "roads",
    label: "Cesty",
    note: "Cesty, kam vojde auto, s obmedzeniami na ceste a značkami."
  },
  {
    id: "paths",
    label: "Chodníky",
    note: "Chodníky, cyklotrasy, schody a pešie zóny, so značenými trasami."
  },
  {
    id: "railways",
    label: "Železnice a lanovky",
    note: "Železnice, električky, lanovky a vleky – aj plánované a zrušené – so stanicami."
  },
  {
    id: "history",
    label: "Armáda a história",
    note: "Vojenské objekty, pamiatky, bane, násypy a všetko opustené.",
    needs: "history"
  },
  {
    id: "boundaries",
    label: "Hranice",
    note: "Štát, kraj, okres a obec, s názvami."
  },
  {
    id: "water",
    label: "Vodstvo",
    note: "Rieky, jazerá, nádrže a more, s názvami."
  },
  {
    id: "settlements",
    label: "Sídla",
    note: "Budovy s výmerou a menom a sídla, ktoré tvoria.",
    needs: "buildings"
  },
  {
    id: "points",
    label: "Body záujmu",
    note: "Pramene, jaskyne, rozhľadne a ďalšie body v krajine.",
    needs: "points"
  }
];

export const PACKAGE_IDS = PACKAGES.map((p) => p.id);

/** Packages the region can draw, base first. */
export function packagesOf(region) {
  return PACKAGES.filter((p) => !p.needs || region?.[p.needs]);
}

export function packageDef(id) {
  return PACKAGES.find((p) => p.id === id) || PACKAGES[0];
}

/** The id if the region has it, else the base map. */
export function normalizePackage(id, region) {
  return packagesOf(region).some((p) => p.id === id) ? id : BASE_PACKAGE;
}

const BASE_RAIL = new Set(["rail-bg", "rail-hatch", "aerialway"]);
const FEATURE_LIFTS = new Set([
  "feature-aerialway-construction", "feature-aerialway-proposed", "feature-aerialway-disused"
]);
const BASE_PATHS = new Set([
  "road-path", "road-footway", "road-cycleway", "road-steps", "pedestrian-area", "road-sign-paths"
]);
const BASE_CLAIMS = {
  transportation: "roads", transportation_name: "roads", traffic_sign: "roads",
  water: "water", water_name: "water", waterway: "water",
  boundary: "boundaries"
};
const SOURCE_OWNERS = {
  transport: ["roads"], paths: ["paths"], points: ["points"], boundaries: ["boundaries"],
  water: ["water"], buildings: ["settlements"], rail: ["railways"], history: ["history"],
  trails: [BASE_PACKAGE, "paths"]
};

/** Packages drawing the layer; empty for the background, terrain and shading. */
export function layerOwners(layer) {
  const id = layer.metadata?.["frico:derived"] || layer.id;
  const source = layer.source;
  if (!source) return [];
  if (source === "omt") {
    if (BASE_RAIL.has(id)) return ["railways"];
    if (BASE_PATHS.has(id) || id.startsWith("road-pedestrian")) return ["paths"];
    return [BASE_CLAIMS[layer["source-layer"]] || BASE_PACKAGE];
  }
  if (source === "features") return [FEATURE_LIFTS.has(id) ? "railways" : BASE_PACKAGE];
  return SOURCE_OWNERS[source] || (source === "dem" ? [] : [BASE_PACKAGE]);
}

const INK = {
  railCasing: ["#5C5650", "#B8B2AA"],
  railGround: ["#FFFFFF", "#1C1C1E"],
  railSiding: ["#948E87", "#7D7871"],
  railInactive: ["#A89F95", "#6F6A64"],
  railProposed: ["#7CB9E8", "#4A7FA8"],
  railPlatform: ["#D9CFC5", "#3A3733"],
  railBroad: ["#2B2723", "#F0EFEB"],
  railNarrow: ["#8F8981", "#8F8981"],
  tram: ["#C2185B", "#E57399"],
  subway: ["#1565C0", "#6FA8E8"],
  lightRail: ["#6A1B9A", "#B388D9"],
  otherUrban: ["#6F6A64", "#A89F95"],
  railLabel: ["#4A443E", "#D9CFC5"],
  halo: ["#FFFFFF", "#000000"],
  markInk: ["#2B2723", "#F0EFEB"],
  liftInk: ["#4A443E", "#C9C3BD"],
  liftGoods: ["#8D5A3B", "#C99A74"],
  army: ["#6B7A3A", "#A3B46A"],
  mining: ["#7A5536", "#C0956C"],
  embankment: ["#968770", "#A89C84"],
  heritage: ["#9C3D2A", "#D9826C"],
  gone: ["#7B7B86", "#A7A7B2"]
};

const MAIN = ["rail", "narrow_gauge", "preserved"];
const URBAN = ["tram", "subway", "light_rail", "monorail", "funicular", "miniature"];
const OUT_OF_USE = ["abandoned", "disused", "razed", "dismantled", "construction"];
const GAUGE_MM = ["to-number", ["coalesce", ["get", "gauge_mm"], ["get", "gauge"]], 0];
const BROAD = [">", GAUGE_MM, 1435];
const NARROW = ["any", ["==", ["get", "class"], "narrow_gauge"],
  ["all", [">", GAUGE_MM, 0], ["<", GAUGE_MM, 1435]]];
const GAUGE_SCALE = ["case", BROAD, 1.35, NARROW, 0.65, 1];
const SERVICE = ["has", "service"];
const INDUSTRIAL_LIFT = ["any", ["==", ["get", "class"], "goods"], ["==", ["get", "usage"], "industrial"]];

const zoomed = (stops, scale) => [
  "interpolate", ["linear"], ["zoom"],
  ...stops.map((v, i) => (i % 2 && scale ? ["*", v, scale] : v))
];

function railLine(id, classes, paint, { extra, minzoom, dash, scale, layer = "railway" } = {}) {
  const byClass = ["match", ["get", "class"], classes, true, false];
  const made = {
    id: `pkg-rail-${id}`,
    type: "line",
    source: "rail",
    "source-layer": layer,
    filter: extra ? ["all", byClass, extra] : byClass,
    layout: { "line-cap": dash ? "butt" : "round", "line-join": "round" },
    paint: { "line-color": paint.color, "line-width": zoomed(paint.width, scale) }
  };
  if (dash) made.paint["line-dasharray"] = dash;
  if (minzoom != null) made.minzoom = minzoom;
  return made;
}

function liftLine(id, states, color, { extra, dash, width = [10, 0.8, 16, 1.8] } = {}) {
  const byState = ["match", ["get", "state"], states, true, false];
  const made = {
    id: `pkg-rail-${id}`,
    type: "line",
    source: "rail",
    "source-layer": "aerialway",
    filter: extra ? ["all", byState, extra] : byState,
    layout: { "line-cap": dash ? "butt" : "round", "line-join": "round" },
    paint: { "line-color": color, "line-width": zoomed(width) }
  };
  if (dash) made.paint["line-dasharray"] = dash;
  return made;
}

function label(id, source, sourceLayer, ink, halo, font, extra) {
  return {
    id,
    type: "symbol",
    source,
    "source-layer": sourceLayer,
    ...extra.top,
    layout: { "text-field": ["get", "name"], "text-font": [font], ...extra.layout },
    paint: { "text-color": ink, "text-halo-color": halo, "text-halo-width": 1.2 }
  };
}

/** Lines and areas, then marks and names – the app's standard Railways look. */
export function railLayers(dark, { bold = "Noto Sans Bold" } = {}) {
  const k = (name) => INK[name][dark ? 1 : 0];
  const urban = ["match", ["get", "class"],
    "tram", k("tram"), "subway", k("subway"), "light_rail", k("lightRail"), k("otherUrban")];
  const urbanInk = ["case", ["has", "colour"], ["to-color", ["get", "colour"], urban], urban];
  const casing = ["case", BROAD, k("railBroad"), NARROW, k("railNarrow"), k("railCasing")];
  const ground = [
    railLine("inactive-casing", OUT_OF_USE, { color: k("railInactive"), width: [8, 1, 16, 4.5] }),
    railLine("inactive", OUT_OF_USE, { color: k("railGround"), width: [10, 0.4, 16, 2.6] },
      { dash: [3, 3], minzoom: 10 }),
    railLine("proposed-casing", ["proposed"], { color: k("railProposed"), width: [6, 1.2, 16, 4.5] }),
    railLine("proposed", ["proposed"], { color: k("railGround"), width: [8, 0.4, 16, 2.6] },
      { dash: [3, 3], minzoom: 8 }),
    {
      id: "pkg-rail-platform-area",
      type: "fill",
      source: "rail",
      "source-layer": "railway_area",
      minzoom: 14,
      filter: ["match", ["get", "class"], ["platform", "station"], true, false],
      paint: { "fill-color": k("railPlatform"), "fill-opacity": 0.8 }
    },
    railLine("siding", MAIN, { color: k("railSiding"), width: [6, 1.2, 16, 4.5] },
      { extra: SERVICE, scale: GAUGE_SCALE }),
    railLine("siding-hatch", MAIN, { color: k("railGround"), width: [8, 0.4, 16, 2.6] },
      { extra: SERVICE, scale: GAUGE_SCALE, dash: [3, 3], minzoom: 8 }),
    railLine("main-casing", MAIN, { color: casing, width: [6, 1.2, 16, 4.5] },
      { extra: ["!", SERVICE], scale: GAUGE_SCALE }),
    railLine("main", MAIN, { color: k("railGround"), width: [8, 0.4, 16, 2.6] },
      { extra: ["!", SERVICE], scale: GAUGE_SCALE, dash: [3, 3], minzoom: 8 }),
    railLine("urban", URBAN, { color: urbanInk, width: [10, 0.8, 16, 2.6] }),
    liftLine("lift", ["active"], k("liftInk"), { extra: ["!", INDUSTRIAL_LIFT] }),
    liftLine("lift-goods", ["active"], k("liftGoods"), { extra: INDUSTRIAL_LIFT }),
    liftLine("lift-construction", ["construction"], k("liftInk"), { dash: [3, 2] }),
    liftLine("lift-proposed", ["proposed"], k("railProposed"), { dash: [1, 2] }),
    liftLine("lift-inactive", ["disused", "abandoned"], k("railInactive"),
      { dash: [2, 3], width: [10, 0.6, 16, 1.4] })
  ];
  const ink = k("markInk");
  const halo = k("halo");
  const marks = [
    label("pkg-rail-line-label", "rail", "railway", k("railLabel"), halo, bold, {
      top: { minzoom: 13, filter: ["all", ["has", "name"], ["!", SERVICE]] },
      layout: { "symbol-placement": "line", "text-size": 11, "text-offset": [0, -0.9] }
    }),
    label("pkg-rail-lift-label", "rail", "aerialway", k("railLabel"), halo, bold, {
      top: { minzoom: 13, filter: ["has", "name"] },
      layout: { "symbol-placement": "line", "text-size": 10, "text-offset": [0, -0.8] }
    }),
    {
      id: "pkg-rail-station",
      type: "circle",
      source: "rail",
      "source-layer": "station",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"],
          9, ["match", ["get", "class"], "station", 3, 2],
          16, ["match", ["get", "class"], "station", 7, 5]],
        "circle-color": halo,
        "circle-stroke-color": ink,
        "circle-stroke-width": ["match", ["get", "class"], "station", 2.5, 1.5]
      }
    },
    label("pkg-rail-station-label", "rail", "station", ink, halo, bold, {
      top: { filter: ["has", "name"] },
      layout: {
        "text-size": ["interpolate", ["linear"], ["zoom"], 9, 10, 16, 13],
        "text-anchor": "top", "text-offset": [0, 0.8], "text-max-width": 8, "text-optional": true
      }
    }),
    {
      id: "pkg-rail-lift-station",
      type: "circle",
      source: "rail",
      "source-layer": "aerialway_station",
      minzoom: 12,
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 2, 16, 4.5],
        "circle-color": halo,
        "circle-stroke-color": ink,
        "circle-stroke-width": 1.5
      }
    },
    label("pkg-rail-lift-station-label", "rail", "aerialway_station", ink, halo, bold, {
      top: { minzoom: 13, filter: ["has", "name"] },
      layout: {
        "text-size": 11, "text-anchor": "top", "text-offset": [0, 0.7],
        "text-max-width": 8, "text-optional": true
      }
    })
  ];
  return { ground, marks };
}

const HISTORY_THEMES = [
  ["gone", "gone"], ["embankment", "embankment"], ["mining", "mining"],
  ["history", "heritage"], ["army", "army"]
];

/** Areas and lines by theme, then a dot and a name – the app's Army & history. */
export function historyLayers(dark, { regular = "Noto Sans Regular" } = {}) {
  const halo = INK.halo[dark ? 1 : 0];
  const ground = [];
  const marks = [];
  for (const [layer, inkName] of HISTORY_THEMES) {
    const ink = INK[inkName][dark ? 1 : 0];
    const base = { source: "history", "source-layer": layer };
    ground.push(
      {
        id: `pkg-history-${layer}-fill`, type: "fill", ...base,
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "fill-color": ink,
          "fill-opacity": ["interpolate", ["linear"], ["zoom"], 8, 0.12, 14, 0.25]
        }
      },
      {
        id: `pkg-history-${layer}-outline`, type: "line", ...base,
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "line-color": ink,
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.6, 16, 1.6],
          "line-dasharray": [3, 2]
        }
      },
      {
        id: `pkg-history-${layer}-line`, type: "line", ...base,
        filter: ["==", ["geometry-type"], "LineString"],
        paint: {
          "line-color": ink,
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.8, 16, 2.4]
        }
      }
    );
    marks.push(
      {
        id: `pkg-history-${layer}-point`, type: "circle", ...base,
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-color": ink,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 2.5, 17, 5],
          "circle-stroke-color": halo,
          "circle-stroke-width": 1
        }
      },
      label(`pkg-history-${layer}-name`, "history", layer, ink, halo, regular, {
        top: { minzoom: 14, filter: ["has", "name"] },
        layout: {
          "text-size": ["interpolate", ["linear"], ["zoom"], 14, 10, 18, 13],
          "text-offset": [0, 0.9], "text-anchor": "top", "text-max-width": 8
        }
      })
    );
  }
  return { ground, marks };
}

/** Keeps what the package draws over the paper; railways and history add their archive. */
export function packageStyle(style, id, own = {}) {
  if (id === BASE_PACKAGE) return style;
  const { dark = false, fonts = {}, railUrl, railMaxzoom = 15, historyUrl, historyMaxzoom = 14 } = own;
  const added = { ground: [], marks: [] };
  const sources = {};
  if (id === "railways" && railUrl) {
    sources.rail = { type: "vector", url: railUrl, maxzoom: railMaxzoom };
    Object.assign(added, railLayers(dark, fonts));
  }
  if (id === "history" && historyUrl) {
    sources.history = { type: "vector", url: historyUrl, maxzoom: historyMaxzoom };
    Object.assign(added, historyLayers(dark, fonts));
  }
  // the rail archive draws lines and lifts itself, the base map's would double them
  const ownArchive = Object.keys(sources).length > 0;
  const kept = style.layers.filter((layer) => {
    const owners = layerOwners(layer);
    if (!owners.length) return layer.type === "background" || layer.source === "dem";
    return owners.includes(id) && !ownArchive;
  });
  const firstLabel = kept.findIndex((l) => l.type === "symbol");
  const at = firstLabel < 0 ? kept.length : firstLabel;
  const layers = [...kept.slice(0, at), ...added.ground, ...kept.slice(at), ...added.marks];

  const used = new Set(layers.map((l) => l.source).filter(Boolean));
  const allSources = { ...style.sources, ...sources };
  const keptSources = Object.fromEntries(
    Object.entries(allSources).filter(([key]) => used.has(key) || key === "dem")
  );
  return {
    ...style,
    metadata: { ...(style.metadata || {}), "frico:package": id },
    sources: keptSources,
    layers
  };
}
