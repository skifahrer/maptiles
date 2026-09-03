#!/usr/bin/env node
/**
 * Kontrola: TMAVÝ VARIANT SA NEPOČÍTA STLMENÍM SVETLEJ FARBY.
 *
 * Štvrtá z vecí, ktoré stráži `workers/lint/overrides.mjs`; vo vlastnom
 * súbore preto, že ten prerástol 800 riadkov a nad tým ho „Kontrola · lint
 * workflowov" neprepustí (pravidlo 5 v CLAUDE.md). Rez vedie tam, kde sa mení
 * otázka: tam „prejde úprava normalizáciou celá", tu „nie je tmavá podoba
 * o rád nápadnejšia než svetlá".
 *
 * `paintDark` je farba pre TMAVÚ tému a jediné, s čím sa dá porovnať, je
 * TMAVÝ podklad. Kým sa robil tak, že sa svetlá hodnota trochu stlmila,
 * vychádzalo z bielej ulice `#ffffff` (proti svetlému podkladu kontrast
 * 1,15 : 1) skoro biele `#d0c8c8` – proti tmavému podkladu 10,5 : 1. Na
 * jednej čiare to nie je vidieť; v dedine a v meste sú tie čiary siete
 * a mesto z nich SVIETI. Presne to hlásil používateľ ako „plochy miest sú
 * príliš svetlé".
 *
 * Kontrola preto neporovnáva farby, ale VÁHU: koľkokrát viac vrstva
 * vyčnieva zo svojho podkladu v tmavej téme než vo svetlej. Prah je voľný
 * (šesťnásobný kontrast a štvornásobná váha), lebo v tmavej téme majú prvky
 * prirodzene vyššie číslo – zachytiť má tú triedu chyby, keď je tmavý
 * variant o RÁD nápadnejší, nie každý rozdiel.
 */
import { THEMES } from "../../poc/web/themes.js";

/**
 * Prejde uložené úpravy a nahlási dvojice, kde je tmavý variant o rád
 * nápadnejší než svetlý. Vracia, koľko dvojíc sa porovnalo – to číslo ide
 * do súhrnu kontroly, aby bolo vidieť, že sa naozaj niečo merilo.
 *
 * @param {object} ulozene obsah `poc/web/style-overrides.json`
 * @param {(subor: string, text: string) => void} chyba hlásenie chyby
 * @returns {number} počet porovnaných dvojíc
 */
export function vahyUprav(ulozene, chyba) {
  const CR_MAX = 6;      // pod týmto kontrastom nič nehlásime
  const VAHA_MAX = 4;    // koľkonásobok svetlej váhy sa ešte znesie
  const _lin = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const _lum = (h) => {
    const m = /^#([0-9a-f]{6})$/i.exec(String(h).trim());
    if (!m) return null;
    const [r, g, b] = [0, 2, 4].map((i) => _lin(parseInt(m[1].slice(i, i + 2), 16) / 255));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const _kontrast = (a, b) => {
    const x = _lum(a), y = _lum(b);
    if (x === null || y === null) return null;
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  };
  const SVETLE_POZADIE = THEMES.svetla.background;
  const TMAVE_POZADIE = THEMES.tmava.background;
  let dvojic = 0;

  const vahaDvojice = (kde, id, prop, svetla, tmava) => {
    const cl = _kontrast(svetla, SVETLE_POZADIE);
    const cd = _kontrast(tmava, TMAVE_POZADIE);
    if (cl === null || cd === null) return;
    dvojic += 1;
    if (cd <= CR_MAX || cd <= VAHA_MAX * cl) return;
    chyba(
      "poc/web/style-overrides.json",
      `${kde}vrstva "${id}", ${prop}: tmavý variant ${tmava} vyčnieva z tmavého ` +
      `podkladu ${cd.toFixed(1)}:1, kým svetlý ${svetla} zo svetlého len ` +
      `${cl.toFixed(2)}:1 – to je ${(cd / cl).toFixed(0)}× väčšia váha. ` +
      `Tmavý variant sa nepočíta stlmením svetlej farby, ale od tmavého ` +
      `podkladu; inak z hustej siete takých čiar svieti celá dedina aj mesto.`
    );
  };

  const vahyVrstiev = (vrstvy, kde) => {
    for (const [id, def] of Object.entries(vrstvy || {})) {
      for (const [prop, svetla] of Object.entries(def?.paint || {})) {
        const tmava = def?.paintDark?.[prop];
        if (prop.endsWith("-color") && tmava) vahaDvojice(kde, id, prop, svetla, tmava);
      }
      // Obrys nesie svoju dvojicu zvlášť (`color` / `colorDark`) – a je to tá
      // istá otázka, takže ju kladieme tým istým meradlom.
      if (def?.outline?.color && def?.outline?.colorDark) {
        vahaDvojice(kde, id, "obrys", def.outline.color, def.outline.colorDark);
      }
    }
  };

  vahyVrstiev(ulozene.layers, "");
  for (const [mapa, def] of Object.entries(ulozene.maps || {})) {
    vahyVrstiev(def?.layers, `mapa „${mapa}": `);
  }
  return dvojic;
}
