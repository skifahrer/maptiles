// jazyky čitateľa → prípony `name:xx`, ktoré nesú dlaždice
export function labelLanguages(tags = [], limit = 3) {
  const out = [];
  for (const tag of tags.slice(0, limit)) {
    for (const code of osmCodes(tag)) if (!out.includes(code)) out.push(code);
  }
  return out;
}

export function osmCodes(tag) {
  const parts = String(tag).replace(/_/g, "-").split("-");
  const lang = parts[0].toLowerCase();
  if (!lang) return [];
  const script = parts.slice(1).find((p) => p.length === 4)?.toLowerCase();
  const region = parts.slice(1).find((p) => p.length === 2)?.toUpperCase();
  switch (lang) {
    case "zh": {
      const hant = script === "hant" || (!script && ["TW", "HK", "MO"].includes(region));
      return [hant ? "zh-Hant" : "zh-Hans", "zh"];
    }
    case "sr": return script === "latn" ? ["sr-Latn"] : ["sr"];
    case "cnr": return ["cnr", "sr-Latn"];
    case "nb": case "nn": return [lang, "no"];
    case "no": return ["no", "nb"];
    default: return [lang];
  }
}

// prvé meno v jazyku čitateľa, inak miestne
export function localName(props, languages) {
  for (const l of languages) if (props[`name:${l}`]) return props[`name:${l}`];
  return props.name;
}
