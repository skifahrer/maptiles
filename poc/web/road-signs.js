/** Road sign images from a region's sheet (`{region}-roadsigns@2x.json/.png`). */

/** Names the sheets give a sign: `sk.ts.253-50`. */
export const ROAD_SIGN_IMAGE = /^[a-z]{2}\.ts\./;

const sheets = new Map();

/** The sheet's JSON among the manifest's files, the sharper one first. */
export function sheetJson(files) {
  const list = files || [];
  return list.find((f) => f.endsWith("@2x.json")) || list.find((f) => f.endsWith(".json")) || null;
}

/** The sheet of a region, loaded once; null when it has none or it can't be read. */
export function loadSheet(baseUrl, region) {
  const json = sheetJson(region?.road_sign_sprite);
  if (!json) return Promise.resolve(null);
  if (!sheets.has(json)) {
    sheets.set(json, (async () => {
      try {
        const index = await (await fetch(`${baseUrl}/${json}`)).json();
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.src = `${baseUrl}/${json.replace(/\.json$/, ".png")}`;
        await img.decode();
        const canvas = document.createElement("canvas");
        canvas.width = img.width;
        canvas.height = img.height;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0);
        return { index, ctx };
      } catch {
        return null;
      }
    })());
  }
  return sheets.get(json);
}

/** Adds the image `name` from `sheet` to the map; false when the sheet lacks it. */
export function addSign(map, sheet, name) {
  const e = sheet?.index?.[name];
  if (!e) return false;
  if (!map.hasImage(name)) {
    map.addImage(name, sheet.ctx.getImageData(e.x, e.y, e.width, e.height),
      { pixelRatio: e.pixelRatio || 1 });
  }
  return true;
}
