# Štítky čísel ciest podľa siete

Číslo cesty na mape je značka z terénu, nie text. Dovtedy sme kreslili podklad
podľa **triedy** cesty z OSM – diaľnica červená, I. trieda modrá, II./III. biela,
E‑cesta zelená. To je pre Slovensko blízko pravde a pre okolie nie: maďarská
`M1` na hranici dostala slovenskú červenú a chorvátska `A1` obdĺžnik namiesto
zeleného šesťuholníka.

Tvar a farbu vie povedať **sieť** (`network` na trasovej relácii, v dlaždiciach
`route_N_network`). Tabuľka je svetová: **1 449 sietí, 74 obrázkov**.

## Odkiaľ je tabuľka

Z [OSM Americana](https://github.com/osm-americana/openstreetmap-americana),
súbor `src/js/shield_defs.js`, licencia CC0. Je to jediný projekt, ktorý má
štítky čísel ciest popísané pre celý svet ako dáta, nie ako obrázky – a to je
presne to, čo sa dá prebrať do inej pipeline.

`workers/tools/americana-shields.mjs` prepíše `poc/web/route-shield-americana.js`
z checkoutu Americany. Helpery knižnice nahrádza rovnakými funkciami, takže
netreba `node_modules` ani `shieldlib`:

    git clone --depth 1 https://github.com/osm-americana/openstreetmap-americana /tmp/am
    node workers/tools/americana-shields.mjs --americana=/tmp/am

Vezme siete kreslené tvarom (`shapeBlank`) – zaoblený obdĺžnik, kapsulu, elipsu,
štít, rybiu hlavu, trojuholník, lichobežník, kosoštvorec, päť‑, šesť‑ a
osemuholník. Dvanásť kresliacich funkcií Americany je prepísaných v
`poc/web/route-shield-shapes.js` krok po kroku, len namiesto canvasu skladajú
lomenú čiaru, ktorú si `route-shields.js` vyplní sám.

Vynecháva **453 sietí kreslených hotovým obrázkom** (`spriteBlank`) – americké
štátne štítky, holandské mestské okruhy. Sú to obrázky konkrétnych tabuliek, nie
recept, a ostáva im záloha podľa triedy cesty.

Vlastné siete idú do `EXTRA_SHIELDS` v `poc/web/route-shield-defs.js`, aby ich
ďalší import nezmazal. Sú tam dve: `sk:primary` (I. trieda, modrá tabuľka) a
`sk:regional` (II./III. trieda, biela). Americana ich nemá a bez nich by na
slovenskej mape mali vlastný štítok len diaľnice.

## Ako to drží pokope

`workers/assets/route-shields.mjs` dopečie obrázky do spritu po
`workers/assets/shields.mjs`. Rovnaký recept = jeden obrázok, takže z 1 449
sietí je 74 obrázkov: **13 kB v sprite, 33 kB v `@2x`**.

Štýl nevyrába nové vrstvy. `road-shield-*` dostanú `icon-image` a `text-color`
ako `match` cez sieť a **na konci `match`‑u je klasický štítok podľa triedy** –
záloha je v tom istom výraze, nie vedľa neho. Rovnako aj vrstva európskych
ciest, hoci sieť má jednu: aplikácia sa vie prepnúť späť tým, že z každého
`match`‑u vezme poslednú vetvu, a na to musia byť všetky štyri rovnaké. Sieť,
ktorej by vyšlo to isté čo zálohe, sa nemenuje; keď vyjde to isté všetkým,
ostane namiesto `match`‑u rovno tá hodnota.

Cena je veľkosť štýlu: **77 kB → 216 kB** (26 kB po gzipe). Pipeline píše 20
štýlov na región, čo je v ZIPe balíka pod pol megabajtu – oproti 130–220 MB
balíka je to nič, ale je dobré vedieť, odkiaľ to je.

Prepnúť späť sa dá v developer móde (Štítky → *Podklad štítka*,
`overrides.routeShields`) aj v aplikácii (Settings → Map → Road numbers).

Stráži to `workers/lint/route-shields.mjs`: každý recept sa dá nakresliť a
zmestí sa do obrázka, každá sieť ukazuje na existujúci recept, obrázky sa
dopečú, rozťahovacie pásma prežijú preskladanie spritu, žiadny nie je `sdf`
a záloha je na konci každého `match`‑u.

## Prečo sa hrot nerozťahuje

Zaoblený obdĺžnik a kapsula majú rovnú časť hrany, takže sa naťahujú deväťdielne
a ostanú sebou aj pri „III/3059". Ostatné tvary majú v strede hrot – natiahnuté
pásmo by z neho spravilo rovnú strechu. Tie sa preto škálujú celé: tvar ostane,
len sa roztiahne, čo je aj to, ako vyzerá naozajstná širšia značka.

Americana si šírku počíta z dĺžky čísla, lebo kreslí za behu v prehliadači. Tu
obrázok vzniká pri builde, keď číslo ešte nie je známe, tak sa berie šírka
napevno z definície a inak 24 px (plus to, čo si tvar pýta navyše) – a zvyšok
dorobí `icon-text-fit`.
