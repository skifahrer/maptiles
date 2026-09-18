# Štítky čísel ciest podľa siete

Číslo cesty na mape je značka z terénu, nie text. Dovtedy sme kreslili podklad
podľa **triedy** cesty z OSM – diaľnica červená, I. trieda modrá, II./III. biela,
E‑cesta zelená. To je pre Slovensko blízko pravde a pre okolie nie: maďarská
`M1` na hranici dostala slovenskú červenú a chorvátska `A1` obdĺžnik namiesto
zeleného šesťuholníka.

Tvar a farbu vie povedať **sieť** (`network` na trasovej relácii, v dlaždiciach
`route_N_network`). Tabuľka sieť → štítok je v `poc/web/route-shields.js`.

## Odkiaľ je tabuľka

Z [OSM Americana](https://github.com/osm-americana/openstreetmap-americana),
súbor `src/js/shield_defs.js`, licencia CC0. Je to jediný projekt, ktorý má
štítky čísel ciest popísané pre celý svet ako dáta, nie ako obrázky – a to je
presne to, čo sa dá prebrať do inej pipeline.

Prebrali sme európsku časť: tvar (zaoblený obdĺžnik, šesťuholník s hrotom hore
aj dole, osemuholník), farbu poľa, obrysu a čísla, a šírku, kde ju Americana
určuje napevno. Aj paletu – sú to Pantone čísla dopravných značiek.

Neprebrali sme:

- **shieldlib** ako knižnicu. Kreslí štítky v prehliadači cez `styleimagemissing`
  a `canvas`; MapLibre Native v aplikácii ani jedno nemá, takže obrázok musí
  vzniknúť pri builde. Pipeline si navyše nedrží `node_modules`.
- **Štítky z hotových SVG** (`spriteBlank`, napr. holandské mestské okruhy).
  Sú to obrázky konkrétnych tabuliek, nie recept.
- **Francúzske departementné cesty.** Sto sietí s tým istým žltým obdĺžnikom;
  ako záloha im stačí klasický štítok.

Doplnili sme dve siete, ktoré Americana nemá a bez ktorých by na slovenskej
mape mali vlastný štítok len diaľnice: `sk:primary` (I. trieda, modrá tabuľka)
a `sk:regional` (II./III. trieda, biela).

## Ako to drží pokope

`workers/assets/route-shields.mjs` dopečie obrázky do spritu po
`workers/assets/shields.mjs`. Rovnaký recept = jeden obrázok, takže zo 73 sietí
je 14 obrázkov.

Štýl nevyrába nové vrstvy. `road-shield-*` dostanú `icon-image` a `text-color`
ako `match` cez sieť a **na konci `match`‑u je klasický štítok podľa triedy** –
záloha je v tom istom výraze, nie vedľa neho. Rovnako aj vrstva európskych
ciest, hoci sieť má jednu: aplikácia sa vie prepnúť späť tým, že z každého
`match`‑u vezme poslednú vetvu, a na to musia byť všetky štyri rovnaké. Cesta v sieti, ktorú tabuľka
nepozná, vyzerá presne ako predtým. To isté, keď sa obrázky nedopečú alebo keď
sa v developer móde prepne *Podklad štítka* na *Klasický podľa triedy*
(`overrides.routeShields: false`).

Stráži to `workers/lint/route-shields.mjs`: obrázok pre každú sieť, rozťahovacie
pásma, žiadne `sdf` a záloha na konci `match`‑u.

## Prečo sa šesťuholník nerozťahuje

Zaoblený obdĺžnik má rovnú časť hrany, takže sa naťahuje deväťdielne a ostane
obdĺžnikom aj pri „III/3059". Šesť‑ a osemuholník majú v strede hrot – natiahnuté
pásmo by z neho spravilo rovnú strechu. Tie sa preto škálujú celé: tvar ostane,
len sa roztiahne, čo je aj to, ako vyzerá naozajstná širšia značka.
