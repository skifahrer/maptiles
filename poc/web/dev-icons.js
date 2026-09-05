/**
 * Výber ikonky v developer móde – a vlastné obrázky.
 *
 * Dovtedy tu bol `select` s tromi stovkami mien, z ktorých sa nedalo prečítať,
 * ako ikona vyzerá. Preto mriežka s náhľadmi, kreslená z toho istého spritu,
 * aký má mapa.
 *
 * SDF sa musí prekresliť: sprity z pipeline nesú vzdialenostné pole v alfe
 * (hrana na 0,75), takže vykreslené tak, ako sú, vyzerajú ako rozmazané
 * škvrny. Náhľad alfu prahuje a vyfarbí – ako MapLibre s `icon-color`.
 *
 * Vlastná ikona sa prevedie tu, v prehliadači, na PNG v `data:` adrese:
 * v úpravách je potom samotný obrázok (mapa funguje offline aj v balíku),
 * pipeline ho vie dopiecť bez rasterizácie SVG a v mape je presne to, čo sa
 * uložilo.
 */
import { el } from "./dom.js";

/** Najväčšia strana vlastnej ikony v pixeloch (pri `pixelRatio` 1). */
export const CUSTOM_ICON_MAX_PX = 64;

/**
 * Vykreslí jeden obrázok zo spritu do plátna.
 *
 * @param {HTMLCanvasElement} canvas kam
 * @param {HTMLImageElement} image   PNG spritu
 * @param {object} entry             položka indexu (`x`, `y`, `width`, `height`)
 * @param {string|null} color        farba pre SDF; `null` = kresli, ako je
 */
export function drawSpriteIcon(canvas, image, entry, color) {
  if (!image || !image.complete || !image.naturalWidth || !entry) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const { x, y, width: w, height: h } = entry;
  if (!w || !h) return;

  const tmp = document.createElement("canvas");
  tmp.width = w;
  tmp.height = h;
  const tctx = tmp.getContext("2d");
  tctx.drawImage(image, x, y, w, h, 0, 0, w, h);
  if (color) {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
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
  }
  const scale = Math.min(1, (canvas.width - 2) / w, (canvas.height - 2) / h);
  ctx.drawImage(
    tmp,
    (canvas.width - w * scale) / 2,
    (canvas.height - h * scale) / 2,
    w * scale,
    h * scale
  );
}

/** Plátno s jednou ikonou zo spritu alebo z `data:` adresy. */
function iconCanvas({ name, entry, image, color, png, size = 22 }) {
  const canvas = el("canvas", { class: "dev-icon", width: String(size), height: String(size), title: name });
  if (png) {
    const img = new Image();
    img.onload = () => {
      const ctx = canvas.getContext("2d");
      const scale = Math.min(1, (size - 2) / img.width, (size - 2) / img.height);
      ctx.clearRect(0, 0, size, size);
      ctx.drawImage(
        img,
        (size - img.width * scale) / 2,
        (size - img.height * scale) / 2,
        img.width * scale,
        img.height * scale
      );
    };
    img.src = png;
  } else {
    drawSpriteIcon(canvas, image, entry, color);
  }
  return canvas;
}

/**
 * Náhľad jednej ikony – to, čo je pri kategórii naozaj v mape.
 *
 * Bez neho sa výber urobiť nedá: „`restaurant_11`" je meno, nie obrázok.
 * Prázdne meno je platná odpoveď („táto kategória nemá ikonu") a kreslí sa
 * ako ∅ – prázdne miesto vyzerá ako nenačítaný obrázok.
 *
 * @param {object} opts
 * @param {string} opts.name    meno ikony (`""` = žiadna)
 * @param {object} opts.set     nasadená sada (`index`)
 * @param {HTMLImageElement} opts.image PNG spritu
 * @param {object[]} [opts.custom] vlastné ikony (`{name, png}`)
 * @param {string} opts.color   farba SDF náhľadu
 * @param {number} [opts.size]
 */
export function iconPreview({ name, set, image, custom = [], color, size = 22 }) {
  if (!name) {
    return el("span", { class: "dev-iconnone", title: "bez ikony", text: "∅" });
  }
  const vlastna = custom.find((c) => c.name === name);
  return iconCanvas({
    name,
    png: vlastna?.png,
    entry: (set?.index || {})[name],
    image,
    color,
    size
  });
}

/**
 * MRIEŽKA IKON NA VÝBER.
 *
 * @param {object} opts
 * @param {object} opts.set        nasadená sada (`index`, `icons`)
 * @param {HTMLImageElement} opts.image PNG spritu (môže byť ešte nenačítané)
 * @param {string} opts.value      meno práve vybranej ikony
 * @param {string[]} opts.names    mená na výber (už prefiltrované)
 * @param {object[]} opts.custom   vlastné ikony (`{name, png}`)
 * @param {string} opts.color      farba SDF náhľadu
 * @param {(name: string) => void} opts.onPick
 * @param {string} [opts.noneLabel] text položky „žiadna"; bez neho tam nie je
 * @param {string} opts.query      hľadaný text
 * @param {(q: string) => void} opts.onQuery
 */
export function iconPicker(opts) {
  const {
    set, image, value, names, custom = [], color, onPick,
    noneLabel, query = "", onQuery
  } = opts;
  const index = set?.index || {};
  const q = query.trim().toLowerCase();
  const vsetky = [
    ...custom.map((c) => ({ name: c.name, png: c.png, vlastna: true })),
    ...names.map((n) => ({ name: n, entry: index[n] }))
  ];
  const najdene = q ? vsetky.filter((i) => i.name.toLowerCase().includes(q)) : vsetky;
  // Vybraná ikona je v mriežke VŽDY, aj keď ju hľadanie odfiltrovalo – inak
  // by panel vyzeral, že nie je vybraná žiadna.
  if (value && !najdene.some((i) => i.name === value)) {
    const vybrana = vsetky.find((i) => i.name === value) || { name: value, entry: index[value] };
    najdene.unshift(vybrana);
  }

  const hladanie = el("input", {
    type: "search",
    class: "dev-search dev-iconsearch",
    value: query,
    placeholder: `hľadať v ${vsetky.length} ikonách…`
  });
  hladanie.addEventListener("input", () => onQuery(hladanie.value));

  const dlazdica = (item) =>
    el("button", {
      type: "button",
      class: `dev-icontile${item.name === value ? " on" : ""}`,
      title: item.name,
      onclick: () => onPick(item.name)
    }, [
      iconCanvas({ ...item, image, color }),
      el("small", { text: item.name.replace(/_\d+$/, "").replace(/^own:/, "") })
    ]);

  const STROP = 240;
  return el("div", { class: "dev-icons" }, [
    hladanie,
    el("div", { class: "dev-icongrid" }, [
      noneLabel
        ? el("button", {
            type: "button",
            class: `dev-icontile${value === "" ? " on" : ""}`,
            title: noneLabel,
            onclick: () => onPick("")
          }, [el("span", { class: "dev-iconnone", text: "∅" }), el("small", { text: noneLabel })])
        : null,
      ...najdene.slice(0, STROP).map(dlazdica)
    ]),
    najdene.length > STROP
      ? el("p", {
          class: "dev-hint",
          text: `Zobrazených prvých ${STROP} z ${najdene.length} – zúž hľadanie.`
        })
      : null
  ]);
}

/** Z názvu súboru spraví platné meno vlastnej ikony (`own:chata`). */
export function iconNameFromFile(fileName, prefix) {
  const zaklad = String(fileName || "ikona")
    .replace(/\.[a-z0-9]+$/i, "")
    .toLowerCase()
    // Diakritika sa v mene ikony nedá použiť (meno chodí aj do sprite indexu
    // a do štýlu), tak sa odstráni – nie zahodí celé slovo.
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return `${prefix}${zaklad || "ikona"}`;
}

/**
 * Prevedie nahraný súbor (PNG, JPG, SVG) na PNG v `data:` adrese.
 *
 * Kreslí sa na dvojnásobnú mriežku – tá istá konvencia ako pri `@2x` sprite.
 * Väčší obrázok sa zmenší na `CUSTOM_ICON_MAX_PX`, menší sa nezväčšuje.
 */
export function fileToIconPng(file, maxPx = CUSTOM_ICON_MAX_PX) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("súbor sa nedá prečítať"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("súbor nie je obrázok, ktorý by prehliadač otvoril"));
      img.onload = () => {
        // SVG bez rozmerov nemá `naturalWidth` – vtedy sa kreslí na štvorec.
        const w = img.naturalWidth || maxPx;
        const h = img.naturalHeight || maxPx;
        const scale = Math.min(1, maxPx / Math.max(w, h)) * 2;
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(w * scale));
        canvas.height = Math.max(1, Math.round(h * scale));
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve({
          png: canvas.toDataURL("image/png"),
          pixelRatio: 2,
          width: canvas.width,
          height: canvas.height
        });
      };
      img.src = String(reader.result);
    };
    reader.readAsDataURL(file);
  });
}
