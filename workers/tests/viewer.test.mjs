import { test } from "node:test";
import assert from "node:assert/strict";
import { labelLanguages, osmCodes, localName } from "../../poc/web/languages.js";
import { iconNameFromFile } from "../../poc/web/dev-icons.js";
import { drawPattern } from "../../poc/web/dev-patterns.js";

test("osmCodes: browser tags to tile name suffixes", () => {
  assert.deepEqual(osmCodes("sk-SK"), ["sk"]);
  assert.deepEqual(osmCodes("zh-TW"), ["zh-Hant", "zh"]);
  assert.deepEqual(osmCodes("zh_Hant_HK"), ["zh-Hant", "zh"]);
  assert.deepEqual(osmCodes("zh-CN"), ["zh-Hans", "zh"]);
  assert.deepEqual(osmCodes("sr-Latn-RS"), ["sr-Latn"]);
  assert.deepEqual(osmCodes("sr"), ["sr"]);
  assert.deepEqual(osmCodes("nn"), ["nn", "no"]);
  assert.deepEqual(osmCodes("no"), ["no", "nb"]);
  assert.deepEqual(osmCodes(""), []);
});

test("labelLanguages: first `limit` tags, no duplicates", () => {
  assert.deepEqual(labelLanguages(["sk-SK", "sk", "cs", "en", "de"]), ["sk", "cs"]);
  assert.deepEqual(labelLanguages(["nb", "no"], 2), ["nb", "no"]);
  assert.deepEqual(labelLanguages(), []);
});

test("localName: first reader language, else the local name", () => {
  const props = { name: "Bratislava", "name:de": "Pressburg", "name:hu": "Pozsony" };
  assert.equal(localName(props, ["fr", "hu", "de"]), "Pozsony");
  assert.equal(localName(props, ["fr"]), "Bratislava");
});

test("iconNameFromFile: a valid sprite name", () => {
  assert.equal(iconNameFromFile("Chata pod Rysmi.PNG", "own:"), "own:chata-pod-rysmi");
  assert.equal(iconNameFromFile("Ľadová_jaskyňa.svg", "own:"), "own:ladova_jaskyna");
  assert.equal(iconNameFromFile("???.png", "own:"), "own:ikona");
  assert.equal(iconNameFromFile("", "own:"), "own:ikona");
  assert.equal(iconNameFromFile("x".repeat(60), "").length, 40);
});

test("drawPattern without a pattern only fills the background", () => {
  const calls = [];
  const ctx = new Proxy({}, {
    get: (_, k) => (k === "fillStyle" ? undefined : (...a) => calls.push([k, ...a])),
    set: (_, k, v) => calls.push([`=${k}`, v])
  });
  drawPattern({ width: 10, height: 5, getContext: () => ctx }, null, "#336633");
  assert.deepEqual(calls, [["clearRect", 0, 0, 10, 5], ["=fillStyle", "#336633"], ["fillRect", 0, 0, 10, 5]]);
  calls.length = 0;
  drawPattern({ width: 10, height: 5, getContext: () => ctx }, null, "none");
  assert.deepEqual(calls, [["clearRect", 0, 0, 10, 5]]);
});
