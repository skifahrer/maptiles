/**
 * Skladanie DOM prvkov – jediná vec, ktorú developer mode potrebuje
 * z „frameworku".
 *
 * Vlastný súbor preto, že to isté potrebuje aj `dev-icons.js`; dve kópie by sa
 * raz rozišli (`el("div", { text })` a `{ html }` sú dva rôzne spôsoby).
 */
export const el = (tag, props = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of [].concat(children)) if (c) node.appendChild(c);
  return node;
};
