#!/usr/bin/env node
/**
 * Kontroly hotového štýlu. Volá ich `Kontrola · lint workflowov`.
 *
 * ŠTYRI VECI, VŠETKY TICHÉ:
 *   1. `fill` vrstva nad zmiešanou geometriou musí mať stráž (rozpis nižšie),
 *   2. odvodená vrstva (vzor, okraj) musí byť vidieť práve vtedy, keď je
 *      vidieť jej predloha,
 *   3. vzor plochy, ktorý má byť ROZSYP, nesmie mať prázdny šev dlaždice –
 *      z opakovania by bola mriežka prázdnych uličiek (v mape „raster"),
 *   4. dôležitejšia cesta musí byť NAD menej dôležitou – inak sa na každej
 *      križovatke kreslí účelová cesta cez diaľnicu. K tomu dve veci, ktoré
 *      z toho istého poradia žijú: obrysy jedného priechodu patria CELÉ pod
 *      jeho výplne (nie po dvojiciach – striedavo preložené prejdú a casing
 *      diaľnice pritom prereže účelovú cestu), a priechody idú tunel →
 *      povrch → most, čo je úroveň, nie trieda.
 *
 * ČO STRÁŽI A PREČO. MapLibre `fill` vrstve NEPRESKOČÍ čiary. Prvok pustí do
 * výplne bez ohľadu na typ geometrie a otvorenú lomenú čiaru pošle earcutu,
 * ako keby to bol uzavretý prstenec – vypadne z toho sebaprekrývajúci sa
 * mnohouholník, ktorý s tou čiarou nemá nič spoločné.
 *
 * Presne to bola tá chyba, po ktorej táto kontrola vznikla: `pedestrian-area`
 * bola `fill` nad vrstvou `transportation` s `class in [pedestrian, path]`
 * a `minzoom: 13`, chodníky sú v tej vrstve ČIARY a Planetiler ich pri
 * `--transportation_z13_paths=true` púšťa do dlaždíc práve od z13. Na
 * obyčajnej mape (bez skál a vrstevníc) z toho boli od zoomu 13 „prerezané"
 * útvary, vo vnútri s farbou `pedestrian`, ktorá je od `background` na
 * nerozoznanie – čiže to vyzeralo, že tam je diera do podkladu.
 *
 * PREČO TO NEVIDEL NIKTO SKÔR: mapa sa načíta, štýl je platný, MapLibre
 * nepovie ani slovo. Je to tichý omyl v čistej podobe (pravidlo 8 v CLAUDE.md)
 * a jediné, čo ho spoľahlivo chytí, je toto: pozrieť sa na hotový štýl a
 * spýtať sa, či každá výplň nad zmiešanou vrstvou vie, že chce len plochy.
 *
 * Kontroluje sa VŠETKÝCH typ mapy × téma, nie jeden vygenerovaný súbor: profil
 * typu mapy vrstvy pridáva aj vypína, takže chyba môže byť len v jednom z nich.
 *
 * Použitie:
 *   node workers/lint/style.mjs
 */
import { THEMES, buildStyle, ROAD_DEFS, ROAD_PASSES } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS, MAP_TYPES, applyMapType } from "../../poc/web/map-types.js";
import { PATTERNS, renderPattern } from "../../poc/web/patterns.js";

/**
 * Vrstvy dlaždíc, v ktorých NIE JE len jeden typ geometrie – a čím to je.
 * Kým tu niečo je, každá `fill` nad tým musí mať v filtri `geometry-type`.
 */
const MIXED = {
  transportation:
    "cesty a chodníky sú čiary, ale pešia zóna, mólo a teleso mosta polygóny",
  aeroway: "dráhy a rolovacie dráhy sú čiary, odbavovacie plochy polygóny",
  park: "obrys je polygón, k nemu ide bod pre popisok (pointOnSurface)",
  piste: "workers/features/features.yml púšťa zjazdovku ako plochu AJ ako os (čiaru)",
  mountain_peak: "vrcholy sú body, ale `cliff`, `ridge` a `arete` čiary"
};

/** Výplňové typy vrstiev – tie, ktoré earcut naozaj triangulujú. */
const FILL = new Set(["fill", "fill-extrusion"]);

/**
 * Náhrada za `_site/region.geojson` – tvar je jedno, ide o to, že vrstvy
 * masky v štýle vzniknú. Vyrába ho `workers/deploy/region-mask.py`.
 */
const OUTLINE = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", properties: { kind: "mimo" },
      geometry: { type: "MultiPolygon", coordinates: [] } },
    { type: "Feature", properties: { kind: "hranica" },
      geometry: { type: "MultiPolygon", coordinates: [] } }
  ]
};

function styles() {
  const out = [];
  for (const theme of Object.keys(THEMES)) {
    for (const mapType of MAP_TYPE_IDS) {
      out.push({
        kde: `${mapType} / ${theme}`,
        style: buildStyle({
          theme,
          mapType,
          tilesUrl: "https://x/tiles.pmtiles",
          spriteUrl: "https://x/sprite",
          glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
          // Vrstvy z vlastných .pmtiles pridá štýl len vtedy, keď tie
          // archívy existujú – bez URL by sa `piste` nikdy neskontrolovala.
          contoursUrl: "https://x/contours.pmtiles",
          rocksUrl: "https://x/rocks.pmtiles",
          trailsUrl: "https://x/trails.pmtiles",
          featuresUrl: "https://x/features.pmtiles",
          pointsUrl: "https://x/points.pmtiles",
          roadsUrl: "https://x/roads.pmtiles",
          // Hranica stiahnutého regiónu – bez nej by sa kontrola 4 nemala
          // na čom chytiť (vrstvy masky by v štýle vôbec neboli).
          regionOutline: OUTLINE
        })
      });
    }
  }
  return out;
}

let bad = 0;
let checked = 0;
let derived = 0;
const videne = new Set();

// ---------- 2. odvodená vrstva drží s predlohou ----------
// Vzor nad plochou je VLASTNÁ vrstva (`rock-area__pattern`) – MapLibre nevie
// kresliť výplň a vzor v jednej. Pravidlá typu mapy sa ale trafia podľa `id`,
// takže kým sa odvodená vrstva nepýtala za svoju predlohu, ostal vzor visieť
// nad vypnutou plochou: štýl platný, MapLibre ticho, v mape kresba bez toho,
// čo mala textúrovať.
//
// SKÚŠA SA TO NA VYROBENEJ DVOJICI, nie na tom, čo v štýle práve je. Dnešné
// pravidlo na skaly (`/^rock-/`) totiž odvodenú vrstvu chytí aj bez opravy –
// je to predpona. Kontrola postavená na dnešnom stave vrstiev by teda bola
// zelená aj nad pokazeným kódom a strážila by len samu seba. Preto sa berie
// prvé pravidlo, ktoré vypína vrstvy VYMENOVANÍM ID (tam predpona nepomôže),
// a overí sa, že vypne aj vrstvu od nich odvodenú.
for (const type of MAP_TYPES) {
  const rule = (type.rules || []).find(
    (r) => r.visible === false && Array.isArray(r.match?.id) && r.match.id.length
  );
  if (!rule) continue;
  const parentId = rule.match.id[0];
  const probe = {
    layers: [
      { id: parentId, type: "line", layout: {}, metadata: {} },
      {
        id: `${parentId}__pattern`,
        type: "fill",
        layout: {},
        metadata: { "frico:derived": parentId }
      }
    ]
  };
  applyMapType(probe, type.id);
  const hidden = (l) => (l.layout || {}).visibility === "none";
  derived += 1;
  if (hidden(probe.layers[0]) && !hidden(probe.layers[1])) {
    console.log(
      `::error file=poc/web/map-types.js::typ mapy \`${type.id}\` vypína ` +
      `\`${parentId}\`, ale vrstvu \`${parentId}__pattern\` odvodenú od nej ` +
      `nechal zapnutú. Vzor bez svojej plochy visí nad prázdnym podkladom ` +
      `a nikto to nepovie – \`matchesLayer\` sa musí na odvodenú vrstvu pýtať ` +
      `id jej predlohy (\`frico:derived\`).`
    );
    bad += 1;
  }
}

// A k tomu to isté nad hotovými štýlmi: odvodená vrstva musí mať predlohu
// a byť vidieť práve vtedy, keď je vidieť ona.
for (const { kde, style } of styles()) {
  const podla = new Map(style.layers.map((l) => [l.id, l]));
  for (const layer of style.layers) {
    const parentId = (layer.metadata || {})["frico:derived"];
    if (!parentId) continue;
    derived += 1;
    const parent = podla.get(parentId);
    const vis = (l) => ((l.layout || {}).visibility === "none" ? "vypnutá" : "zapnutá");
    if (!parent) {
      console.log(
        `::error file=poc/web/themes.js::odvodená vrstva \`${layer.id}\` ` +
        `(${kde}) sa odkazuje na predlohu \`${parentId}\`, ktorá v štýle nie je.`
      );
      bad += 1;
    } else if (vis(parent) !== vis(layer)) {
      console.log(
        `::error file=poc/web/map-types.js::odvodená vrstva \`${layer.id}\` ` +
        `je ${vis(layer)}, ale jej predloha \`${parentId}\` je ${vis(parent)} ` +
        `(${kde}).`
      );
      bad += 1;
    }
  }
}

// ---------- 1. výplň nad zmiešanou geometriou ----------
for (const { kde, style } of styles()) {
  for (const layer of style.layers) {
    const src = layer["source-layer"];
    if (!FILL.has(layer.type) || !MIXED[src]) continue;
    checked += 1;
    if (JSON.stringify(layer.filter ?? null).includes("geometry-type")) continue;
    // Tá istá vrstva vyjde v každej téme rovnako – hlás ju raz.
    if (videne.has(layer.id)) continue;
    videne.add(layer.id);
    console.log(
      `::error file=poc/web/themes.js::vrstva \`${layer.id}\` (${layer.type} ` +
      `nad \`${src}\`, ${kde}) nemá v filtri \`geometry-type\`. Vo vrstve ` +
      `\`${src}\` ${MIXED[src]}, a MapLibre pustí do výplne aj čiaru – ` +
      `earcutom z nej vyrobí nezmyselný mnohouholník, ktorý v mape vyzerá ` +
      `ako plocha prerezaná cez krajinu. Obaľ filter do \`polygonOnly(…)\`.`
    );
    bad += 1;
  }
}

// ---------- 3. vzor sa nesmie prezradiť švom ----------
// TRETIA TICHÁ VEC. Vzor plochy sa dlaždicuje. Keď v ňom všetky tvary ležia
// vnútri dlaždice, má dlaždica po obvode prázdny okraj – a z opakovania je
// MRIEŽKA PRÁZDNYCH ULIČIEK každých `size` pixelov. Jedna dlaždica pritom
// vyzerá úplne v poriadku, štýl je platný a MapLibre nepovie nič; vidieť je to
// až na hotovej ploche v mape, a to ako „nejaký raster", nie ako chyba vzoru.
//
// Kontroluje sa preto to, čo tú príčinu vystihuje: koľko inku je na samom šve
// proti priemeru celej dlaždice. Prázdny šev (0 %) je chyba; presahujúce tvary
// ju nemajú ako spôsobiť, lebo rasterizér počíta aj 3×3 susedné kópie.
//
// Čiarové vzory (`line: true`) sú z toho vynechané: tie sa opakujú POZDĹŽ
// čiary a ich zvislé okraje sú prázdne zámerne (priečka, šípka).
const SEAM_MIN = 0.25;   // aspoň štvrtina priemerného krytia
let vzorov = 0;
for (const pat of PATTERNS) {
  // Len vzory, ktoré o sebe hlásia, že sú ROZSYP (`scatter`). Pravidelný
  // motív v bunke (bodky, krúžky, krížiky na cintoríne, stromčeky v lese) má
  // prázdny okraj zámerne a mriežka je pri ňom to, čo od neho chceme.
  if (pat.line || !pat.scatter) continue;
  vzorov += 1;
  const size = 24;
  const { data } = renderPattern(
    { id: pat.id, color: "#000000", size, weight: 1 }, 1
  );
  const a = (x, y) => data[(y * size + x) * 4 + 3] / 255;
  let all = 0;
  const rows = [], cols = [];
  for (let i = 0; i < size; i++) {
    let r = 0, cc = 0;
    for (let j = 0; j < size; j++) { r += a(j, i); cc += a(i, j); }
    rows.push(r / size); cols.push(cc / size); all += r;
  }
  const ink = all / (size * size);
  const seam = (rows[0] + rows[size - 1] + cols[0] + cols[size - 1]) / 4;
  if (ink > 0 && seam < ink * SEAM_MIN) {
    console.log(
      `::error file=poc/web/patterns.js::vzor \`${pat.id}\` má na šve dlaždice ` +
      `${(seam * 100).toFixed(1)} % inku proti ${(ink * 100).toFixed(1)} % ` +
      `v celej dlaždici. Z opakovania bude mriežka prázdnych uličiek každých ` +
      `\`size\` pixelov – v ploche to vyzerá ako raster. Posuň časť tvarov tak, ` +
      `aby PREČNIEVALI za hranu (súradnice mimo 0–1); rasterizér dokreslí ` +
      `druhú polovicu na opačnej strane sám.`
    );
    bad += 1;
  }
}

// ---------- 5. dôležitejšia cesta je NAD menej dôležitou ----------
// PIATA TICHÁ VEC. MapLibre kreslí vrstvy v poradí, v akom sú v štýle: navrchu
// je tá POSLEDNÁ. Kým sa cesty pridávali od diaľnice nadol (teda v poradí
// dôležitosti), skončila účelová cesta NAD diaľnicou a na každej križovatke
// bol cez diaľničný pás prúžok v jej farbe – vyzeralo to ako prerušená
// diaľnica, hoci dáta aj štýl boli v poriadku. Nič nespadne, nič sa nevypíše.
//
// Poradie dôležitosti je `ROAD_DEFS` v `themes.js` – jedna odpoveď na jednom
// mieste. Kontrola len trvá na tom, že v hotovom štýle idú vrstvy PRESNE
// naopak, a to v každom z troch priechodov (tunel, povrch, most) zvlášť,
// pre výplne aj pre obrysy.
let cestnychDvojic = 0;
for (const { kde, style } of styles()) {
  const poradie = new Map(style.layers.map((l, i) => [l.id, i]));
  for (const suffix of ROAD_PASSES) {
    for (const casing of ["", "-casing"]) {
      // Od najmenej dôležitej po najdôležitejšiu – index v štýle musí rásť.
      const rad = [...ROAD_DEFS]
        .reverse()
        .map(([id]) => [`road-${id}${casing}${suffix}`, id])
        .filter(([layerId]) => poradie.has(layerId));
      for (let i = 0; i + 1 < rad.length; i += 1) {
        const [nizsiId, nizsi] = rad[i];
        const [vyssiId, vyssi] = rad[i + 1];
        cestnychDvojic += 1;
        if (poradie.get(nizsiId) < poradie.get(vyssiId)) continue;
        console.log(
          `::error file=poc/web/themes.js::v štýle (${kde}) je \`${nizsiId}\` ` +
          `NAD \`${vyssiId}\`. \`${nizsi}\` je menej dôležitá cesta než ` +
          `\`${vyssi}\` (poradie hovorí ROAD_DEFS), takže sa v mape kreslí ` +
          `cez ňu a na križovatkách ju prerušuje. Vrstvy ciest sa pridávajú ` +
          `OD KONCA ROAD_DEFS – viď \`roadPass\`.`
        );
        bad += 1;
      }
    }
  }
  // Obrysy celého priechodu patria POD jeho výplne – CELÉ, nie po dvojiciach.
  // Porovnávať `road-X-casing` len s `road-X` nestačí: obrysy a výplne sa dajú
  // preložiť striedavo (obrys+výplň na každú cestu, teda jedna slučka namiesto
  // dvoch v `roadPass`) a každá jedna dvojica pritom sedí. Casing diaľnice by
  // tak sadol NAD výplň účelovej cesty a na križovatke by ju prerezal tmavým
  // pásom – presne ten artefakt, pred ktorým je `roadPass` napísaný v dvoch
  // slučkách. Preto sa porovnáva NAJNIŽŠIA výplň proti NAJVYŠŠIEMU obrysu.
  for (const suffix of ROAD_PASSES) {
    const idx = (pre) => ROAD_DEFS
      .map(([id]) => poradie.get(`road-${id}${pre}${suffix}`))
      .filter((i) => i !== undefined);
    const obrysy = idx("-casing");
    const vyplne = idx("");
    if (!obrysy.length || !vyplne.length) continue;
    cestnychDvojic += 1;
    const najvyssiObrys = Math.max(...obrysy);
    const najnizsiaVypln = Math.min(...vyplne);
    if (najvyssiObrys < najnizsiaVypln) continue;
    const vinnik = ROAD_DEFS
      .map(([id]) => id)
      .find((id) => poradie.get(`road-${id}-casing${suffix}`) === najvyssiObrys);
    console.log(
      `::error file=poc/web/themes.js::v štýle (${kde}) sa obrysy a výplne ` +
      `ciest priechodu \`${suffix || "(povrch)"}\` prekladajú – obrys ` +
      `\`road-${vinnik}-casing${suffix}\` je nad niektorou výplňou toho istého ` +
      `priechodu. Obrysy patria CELÉ pod výplne (v \`roadPass\` sú preto dve ` +
      `slučky, nie jedna), inak ich prekryjú križovatky.`
    );
    bad += 1;
  }

  // Priechody idú TUNEL → POVRCH → MOST, a to je iná otázka než dôležitosť
  // triedy. Vnútri priechodu rozhoduje trieda (diaľnica nad účelovou), MEDZI
  // priechodmi rozhoduje úroveň: účelová cesta na moste patrí nad diaľnicu na
  // povrchu, lebo most naozaj je nad ňou, a tunelová diaľnica pod všetko.
  // Kontrola vyššie beží v každom priechode zvlášť, takže by prehodené
  // `roadPass(...)` volania prešli bez slova – mosty by sa kreslili pod tunelmi
  // a v mape by to vyzeralo, akoby cesta pod mostom viedla po ňom.
  const urovne = ROAD_PASSES
    .map((suffix) => {
      const idx = ROAD_DEFS
        .flatMap(([id]) => [`road-${id}-casing${suffix}`, `road-${id}${suffix}`])
        .map((l) => poradie.get(l))
        .filter((i) => i !== undefined);
      return idx.length ? { suffix, od: Math.min(...idx), po: Math.max(...idx) } : null;
    })
    .filter(Boolean);
  for (let i = 0; i + 1 < urovne.length; i += 1) {
    const nizsi = urovne[i];
    const vyssi = urovne[i + 1];
    cestnychDvojic += 1;
    if (nizsi.po < vyssi.od) continue;
    const meno = (s) => s === "-tunnel" ? "tunely" : s === "-bridge" ? "mosty" : "povrch";
    console.log(
      `::error file=poc/web/themes.js::v štýle (${kde}) nie sú priechody ciest ` +
      `v poradí tunel → povrch → most: \`${meno(nizsi.suffix)}\` ` +
      `(${nizsi.od}–${nizsi.po}) zasahuje nad \`${meno(vyssi.suffix)}\` ` +
      `(od ${vyssi.od}). Poradie hovorí ROAD_PASSES a je to úroveň, nie trieda ` +
      `– cesta na moste patrí nad každú cestu na povrchu.`
    );
    bad += 1;
  }
}

// ---------- 4. maska regiónu ostáva úplne navrchu ----------
// ŠTVRTÁ TICHÁ VEC. Mapa sa stavia z PBF kraja, ale dlaždice vznikajú po
// celých dlaždiciach a vodstvo s Natural Earth kreslí Planetiler na celom
// obdĺžniku bboxu – teda ďaleko za regiónom, ktorý si používateľ stiahol.
// Prekrýva to vrstva `region-outside`, a jej jediná podmienka je, že je
// POSLEDNÁ: čokoľvek pridané za ňu sa mimo regiónu opäť nakreslí. Nikto to
// nepovie – štýl je platný, mapa sa načíta a len zase presahuje. A platí to
// pre KAŽDÝ typ mapy, lebo profil typu mapy vrstvy pridáva aj vypína.
let masiek = 0;
for (const { kde, style } of styles()) {
  const ids = style.layers.map((l) => l.id);
  masiek += 1;
  if (!ids.includes("region-outside")) {
    console.log(
      `::error file=poc/web/themes.js::v štýle (${kde}) nie je vrstva ` +
      `\`region-outside\`, hoci hranica regiónu prišla. Mapa by v aplikácii ` +
      `siahala za stiahnutý región.`
    );
    bad += 1;
    continue;
  }
  const posledne = ids.slice(-2);
  if (!posledne.includes("region-outside") || !posledne.includes("region-border")) {
    console.log(
      `::error file=poc/web/themes.js::maska regiónu nie je navrchu (${kde}): ` +
      `posledné vrstvy sú [${ids.slice(-3)}]. Vrstva za \`region-outside\` ` +
      `sa kreslí aj mimo stiahnutého regiónu – pridávaj ju PRED masku.`
    );
    bad += 1;
  }
}

console.log(
  `štýl: ${bad} chýb (${checked} výplní nad zmiešanou geometriou, ` +
  `${derived} skúšok odvodených vrstiev, ${vzorov} vzorov plôch na šev, ` +
  `${cestnychDvojic} dvojíc ciest na poradie, ` +
  `${masiek} štýlov s maskou regiónu, ` +
  `${Object.keys(THEMES).length} tém × ${MAP_TYPE_IDS.length} typov mapy)`
);
process.exit(bad ? 1 : 0);
