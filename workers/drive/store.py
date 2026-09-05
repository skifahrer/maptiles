#!/usr/bin/env python3
"""Sklad hotových dát na Google Drive – náhrada za GitHub releasy.

Publikuje sa len na Drive: release má na asset strop 2 GB, ktorý pipeline
zvonku tvaroval, a hotové dáta v releasoch verejného repozitára vyzerajú ako
vydanie softvéru, ktorým nie sú. Drive už drží DMR 5.0, cache aj hotové mapy.

    gh release view          → --names / --index / --latest
    gh release download      → --get
    gh release upload        → --put
    gh release delete-asset  → --rm

Mená súborov ostávajú tie isté, aké mali assety – meno je sľub o rozsahu.
Dve podoby DMR 5.0 ostávajú tiež: tie nedržal strop assetu, ale runner
(1°×1° dlaždica má v metri ~48 GB a voľných je ~60 GB).

Rozloženie je plochá dvojúrovňová vec, nech sa dá prezerať očami:
`<koreň>/<sklad>/<meno assetu>`. Koreň `fricomaps-sklad` vzniká sám pri prvom
zápise; inde ho posadí `DRIVE_STORE_FOLDER`.

„Clobber" je najprv nahrať nové, až potom zmazať staré – opačne by po spadnutom
uploade nebolo ani jedno. Pri čítaní vyhráva najnovší súbor daného mena.

Bez prihlásenia to nefunguje a nesmie to byť tiché: „v sklade nič nie je"
a „nemám token" by boli na nerozoznanie.

    python3 workers/drive/store.py --check | --list --store=dem-dmr5
    python3 workers/drive/store.py --get --store=dem-dmr5 --dir=dem/tiles \
        --name=N49E019.tif --missing-ok
    python3 workers/drive/store.py --put --store=dem-terrain --file=/tmp/x.tar.zst
"""
import argparse
import calendar
import importlib.util
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# S Drive hovoria tri hotové súbory a tento si ich požičiava celé – rovnako ako
# `drive-cache.py`. Napísať sťahovanie po blokoch, priečinky či resumable
# upload sem druhýkrát by znamenalo druhú pravdu o tom istom.
drive = load("drive_serve", "serve.py")     # Pool: Range, presmerovania
auth = load("drive_auth", "auth.py")        # kto som, token, mazanie
folder = load("drive_folder", "folder.py")  # výpis, priečinky, upload

# Priečinok skladu. Prázdne = `STORE_NAME` v koreni My Drive vlastníka tokenu
# (nájde sa podľa mena, a keď nie je, vyrobí sa). Prebiť sa dá premennou
# DRIVE_STORE_FOLDER – id aj celý odkaz.
FOLDER_ID = ""
STORE_NAME = "fricomaps-sklad"

# Sklady, ktoré pipeline pozná. Zoznam je tu na jednu jedinú vec: keď sa niekto
# preklepne v mene skladu, `--get` by mu inak povedal „nič tam nie je" a build
# by ticho počítal odznova. Nový sklad sem treba dopísať.
#
# A KEĎ SA TO ZABUDNE, PADÁ TO AŽ PO PRÁCI. `dem-sonny1` tu chýbal od chvíle,
# čo pribudol zdroj `sonny1`: doplnenie stiahlo z Drive 12 dlaždíc, rozuzlilo
# skratky, prevedlo ich – a až posledný krok, nahratie do skladu, spadol na
# tomto zozname. Hotová práca sa zahodila a s ňou aj vrstevnice, skaly
# a tieňovanie, ktoré na ten sklad čakali (beh 31533988137, štyri padnuté joby).
# Že zoznam sedí s tým, čo si pipeline pýta, stráži `workers/lint/stores.py`.
KNOWN = {
    "dem-sonny": "Výškový model – Sonny's LiDAR DTM (1°×1° dlaždice)",
    "dem-sonny1": "Výškový model – Sonny's LiDAR DTM 1″ (.hgt, krok výšky 1 m)",
    "dem-dmr35": "Výškový model – ÚGKK DMR 3.5 (otvorené dáta, 10 m)",
    # `-v2` NIE JE KOZMETIKA. Dlaždice v `dem-dmr5` vznikli čítaním z 4 m
    # pyramídy priemerom na 5 m (pomer 1,25) a majú v sebe zapečenú mriežku –
    # bolo ju vidieť ako svetlo-tmavé políčka v tieňovaní a ako zubatosť
    # vrstevníc s tým istým rastrom. Oprava je vo `workers/drive/dmr5-cut.py`,
    # lenže meno súboru je `N49E020.tif` a to sa zmeniť nesmie (je to sľub
    # o rozsahu, pravidlo 2). Podobu teda nesie MENO SKLADU – presne tak, ako
    # ju pri tieňovaní nesie `-v4` v mene assetu. Bez toho by `check-dem`
    # našiel staré dlaždice, povedal „model máme" a mapa by ostala zrnitá
    # pri zelenom builde (pravidlo 8).
    #
    # Starý `dem-dmr5` na Drive OSTÁVA – nič ho nemaže. Keď sa `-v2` osvedčí,
    # dá sa zmazať ručne (`store.py --prune`), je to zrkadlo a vyrobí sa znova.
    "dem-dmr5": "Výškový model – ÚGKK DMR 5.0, dlaždicová podoba (5 m), pred opravou resamplingu",
    "dem-dmr5-v2": "Výškový model – ÚGKK DMR 5.0, dlaždicová podoba (5 m)",
    "dem-ugkk": "Výškový model – ÚGKK DMR 5.0, výrez v plnom 1 m rozlíšení",
    "dem-terrain": "Výškové (terrarium) dlaždice pre tieňovanie a 3D terén",
    "dem-rocks": "Skalné plochy počítané zo sklonu výškového modelu",
    "dem-rocks-img": "Skalné plochy z tmavých miest v tieňovaných dlaždiciach",
    "dem-slope": "Raster sklonu po častiach (medzivýsledok skál)",
    "vysledky": "Medzivýsledky buildu na pozretie (vrstevnice, skaly, trasy)",
}

_ROOT = {}      # id koreňa skladu – zisťuje sa raz za beh
_STORES = {}    # meno skladu → id priečinka


def log(msg):
    print(msg, flush=True)


def human(n):
    return folder.human(n)


# ---------- prihlásenie a priečinky ----------

def creds_or_die(what):
    """Prihlásenie, alebo pád s návodom.

    Bez tokenu sa nedá ani vypísať priečinok – Drive API anonymné požiadavky
    neobsluhuje. Tichý „v sklade to nie je" by tu bol ten najdrahší druh
    omylu: každý beh by počítal všetko odznova a nikde by nebolo vidieť prečo.
    """
    creds = auth.from_env()
    if creds is None:
        raise SystemExit(
            f"::error::Sklad na Drive potrebuje prihlásenie ({what}), ale "
            "v prostredí nie je token vlastníka. Doplň secret "
            "GDRIVE_CREDENTIALS (alebo premennú DRIVE_CLIENT a secrety "
            "DRIVE_SECRET / DRIVE_REFRESH) a podaj ho jobu cez `env:` – "
            "vyrobí ich workflow "
            "„Údržba · prihlásenie Drive“.")
    return creds


def root_id(creds, create=False):
    """Id koreňového priečinka skladu; `create=True` ho vyrobí, keď nie je.

    `root` je alias na My Drive, ale do dopytu `'<id>' in parents` sa dáva
    skutočné id – to je jedna lacná otázka a nemusí sa hádať, čo Drive
    z aliasu urobí.

    ČÍTANIE NIKDY NEVYRÁBA PRIEČINOK. Nie z čistoty, ale preto, že
    `ensure_folder` pri výrobe niečo vypíše na stdout – a `--names`, `--index`
    aj `--latest` sa čítajú do premennej v shelli (`ASSET=$(… --latest)`),
    takže by sa tá hláška stala súčasťou mena súboru.
    """
    if "id" in _ROOT:
        return _ROOT["id"]
    want = (os.environ.get("DRIVE_STORE_FOLDER") or FOLDER_ID or "").strip()
    if want:
        _ROOT["id"] = folder.folder_id(want)
        return _ROOT["id"]
    mine = auth.api_get(creds, "/drive/v3/files/root?fields=id")["id"]
    fid = (folder.ensure_folder(creds, mine, STORE_NAME) if create
           else folder.find_folder(creds, mine, STORE_NAME))
    if fid:
        _ROOT["id"] = fid
    return fid


def store_id(creds, store, create=False):
    """Id priečinka skladu, alebo None, keď ešte neexistuje."""
    if store in _STORES:
        return _STORES[store]
    root = root_id(creds, create=create)
    if not root:
        return None
    fid = (folder.ensure_folder(creds, root, store) if create
           else folder.find_folder(creds, root, store))
    if fid:
        _STORES[store] = fid
    return fid


def known_or_die(store):
    """Preklep v mene skladu je chyba, nie prázdny sklad."""
    if store in KNOWN:
        return store
    raise SystemExit(
        f"::error::Sklad „{store}“ pipeline nepozná. Sú to: "
        f"{', '.join(sorted(KNOWN))}. Keď má pribudnúť nový, dopíš ho do "
        f"KNOWN vo workers/drive/store.py – inak by sa preklep v mene "
        f"neodlíšil od prázdneho skladu a build by ticho počítal odznova.")


# ---------- čo je v sklade ----------

def index(creds, store):
    """{meno: {id, size, created}} – pri duplikátoch mena vyhráva NAJNOVŠÍ.

    Duplikát vzniká pri „clobberi": nové sa nahrá skôr, než sa staré zmaže
    (viď rozpis v hlavičke). Keby vyhrával starší, jeden neúspešný beh by
    vracal staré dáta pod novým menom – presne ten tichý omyl, ktorý sa
    v mape nájde až o týždeň.
    """
    fid = store_id(creds, store)
    if not fid:
        return {}
    files, _skipped = folder.listing(creds, fid, extra="createdTime")
    out = {}
    for f in files:
        raw = f.get("raw") or {}
        item = {"id": f["id"], "size": f["size"],
                "created": raw.get("createdTime") or ""}
        old = out.get(f["name"])
        if old is None or item["created"] > old["created"]:
            if old is not None:
                item["dupes"] = old.get("dupes", []) + [old["id"]]
            out[f["name"]] = item
        else:
            old.setdefault("dupes", []).append(f["id"])
    return out


def latest(items, prefix="", suffix=""):
    """Najnovšie meno, ktoré sedí na predponu a príponu.

    Zoradiť sa MUSÍ podľa času nahratia, nie podľa mena: v menách assetov sú
    prahy a mriežky, takže abecedne by vyhral ten s najväčším číslom, nie ten
    posledný. (Tak to robilo aj `gh --jq 'sort_by(.createdAt) | last'`.)
    """
    hit = [(v["created"], k) for k, v in items.items()
           if k.startswith(prefix) and k.endswith(suffix)]
    return max(hit)[1] if hit else ""


# ---------- prenosy ----------

def download(creds, item, dest):
    """Súbor zo skladu na disk. Sťahovanie po blokoch má hotové `drive-folder`,
    vrátane `.part` a premenovania – zrušený beh tak nenechá polovičný súbor,
    ktorý by nabudúce prešiel ako hotový."""
    pool = drive.Pool(creds=creds)
    progress = folder.Progress(item["size"])
    t0 = time.time()
    folder.fetch(pool, {"id": item["id"], "name": item["name"],
                        "size": item["size"]}, dest, progress)
    el = max(time.time() - t0, 1e-6)
    log(f"  stiahnuté {item['name']} ({human(item['size'])}) za {el:.0f} s "
        f"({item['size'] / el / 1e6:.1f} MB/s)")


def upload(creds, store, path, name, note="", clobber=True):
    """Súbor do skladu; rovnaké meno sa prepíše (až po úspešnom nahratí).

    `clobber=False` preskočí hľadanie starej verzie – a s ním jedno vypísanie
    priečinka. Je to pre `slope-chunks.py`: ten nahráva rádovo stovku častí,
    ktoré v sklade podľa svojho zoznamu nie sú, takže by sa priečinok vypisoval
    stokrát pre nič. Cena je, že po neúspešnom sťahovaní môže časť pribudnúť
    druhýkrát; obsah je ten istý a `index()` berie novšiu, takže je to
    neškodné.
    """
    fid = store_id(creds, store, create=True)
    size = os.path.getsize(path)
    bolo = index(creds, store).get(name) if clobber else None
    stare = ([bolo["id"]] + bolo.get("dupes", [])) if bolo else []
    t0 = time.time()
    folder.upload(creds, path, name, fid, note or f"{store}/{name}")
    el = max(time.time() - t0, 1e-6)
    log(f"  nahraté {name} ({human(size)}) za {el:.0f} s "
        f"({size / el / 1e6:.1f} MB/s)")
    for old in stare:
        auth.api_delete(creds, old)
    if stare:
        log(f"  starú verziu ({len(stare)}×) som zmazal")


# ---------- príkazy ----------

def do_check(args):
    """Vie tento beh zo skladu čítať a doň zapisovať? Lacná otázka.

    Vlastný príkaz preto, že odpoveď na ňu sa inak dozvieme až po hodine
    výpočtu, keď sa má výsledok uložiť – a vtedy je neskoro.
    """
    creds = creds_or_die("kontroluje sa prístup")
    who = auth.whoami(creds)
    root = root_id(creds)
    if root:
        log(f"Sklad na Google Drive, priečinok {root}")
        log(f"  {folder.folder_link(root)}")
    else:
        log(f"Sklad na Google Drive: priečinok „{STORE_NAME}“ v My Drive ešte "
            f"nie je – vyrobí sa pri prvom uložení.")
    log(f"  účet    {who.get('emailAddress', '?')} (údaje z {creds.source})")
    write = auth.can_write(creds)
    log("  rozsah  " + {True: "číta aj zapisuje ✓",
                        False: "LEN ČÍTANIE – nič sa neuloží",
                        None: "nedá sa zistiť"}[write])
    celkom = 0
    for store in sorted(KNOWN):
        items = index(creds, store)
        vel = sum(v["size"] for v in items.values())
        celkom += vel
        log(f"  {store:<14} {len(items):>5} súborov  {human(vel):>10}"
            + ("" if store_id(creds, store) else "   (ešte nie je)"))
    log(f"  {'spolu':<14} {'':>5}           {human(celkom):>10}")
    if write is False:
        log(f"::error::{auth.scope_hint()}")
        return 1
    return 0


def do_list(args):
    creds = creds_or_die("vypisuje sa sklad")
    items = index(creds, args.store)
    vel = sum(v["size"] for v in items.values())
    log(f"Sklad {args.store}: {len(items)} súborov, {human(vel)} "
        f"– {KNOWN[args.store]}")
    for name in sorted(items):
        v = items[name]
        log(f"  {v['created'][:19]}  {human(v['size']):>10}  {name}")
    return 0


def do_names(args):
    """Mená, jedno na riadok – to, čo robilo `gh release view --json assets`."""
    creds = creds_or_die("vypisujú sa mená v sklade")
    for name in sorted(index(creds, args.store)):
        print(name)
    return 0


def do_index(args):
    """`meno:veľkosť` na riadok. Z toho si `check-dem.sh` počíta otlačok
    obsahu skladu do kľúča cache – meno samo by nestačilo, keby sa ten istý
    asset doplnil nanovo a bol iný."""
    creds = creds_or_die("vypisuje sa obsah skladu")
    items = index(creds, args.store)
    for name in sorted(items):
        print(f"{name}:{items[name]['size']}")
    return 0


def do_latest(args):
    creds = creds_or_die("hľadá sa najnovší súbor v sklade")
    name = latest(index(creds, args.store), args.prefix, args.suffix)
    if not name:
        return 3
    print(name)
    return 0


def do_get(args):
    """Vypýtané mená na disk. Vracia 3, keď sa nezískalo ANI JEDNO.

    `--missing-ok` je pre dlaždice: bbox je obdĺžnik, ale model pokrýva
    krajinu, takže rohové dlaždice v ňom nikdy nebudú a „chýba jedna, tak
    spadni" by zhodilo každý build pri hranici.
    """
    creds = creds_or_die("sťahuje sa zo skladu")
    os.makedirs(args.dir, exist_ok=True)
    items = index(creds, args.store)
    if not items:
        log(f"::warning::V sklade {args.store} nie je nič "
            + ("(priečinok ešte neexistuje)." if not store_id(creds, args.store)
               else "."))
    mam, chyba = [], []
    for name in args.name:
        dest = os.path.join(args.dir, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 0 and args.skip_local:
            log(f"  {name} už na disku je – nesťahujem")
            mam.append(name)
            continue
        if name not in items:
            chyba.append(name)
            continue
        item = dict(items[name], name=name)
        try:
            download(creds, item, dest)
        except (RuntimeError, OSError) as exc:
            log(f"::warning::{name} sa zo skladu {args.store} nedal stiahnuť "
                f"({exc}).")
            chyba.append(name)
            continue
        mam.append(name)
    if chyba:
        log(f"  v sklade {args.store} nie je: {' '.join(chyba)}")
    log(f"Zo skladu {args.store}: {len(mam)} z {len(args.name)} súborov")
    if not mam:
        return 3
    return 0 if (not chyba or args.missing_ok) else 3


def do_put(args):
    creds = creds_or_die("ukladá sa do skladu")
    # ROZSAH SA PÝTA PRED NAHRÁVANÍM. Readonly token `files.create` nepustí,
    # takže by sa gigabajt najprv zbytočne poslal a padlo by to až potom.
    if auth.can_write(creds) is False:
        raise SystemExit(f"::error::Do skladu {args.store} sa nič neuložilo: "
                         f"{auth.scope_hint()}")
    log(f"Sklad {args.store}: ukladám {len(args.file)} súborov")
    for i, path in enumerate(args.file):
        if not os.path.exists(path):
            raise SystemExit(f"::error::{path} neexistuje – nie je čo uložiť.")
        name = args.name[i] if i < len(args.name) else os.path.basename(path)
        upload(creds, args.store, path, name, args.note)
    return 0


def do_rm(args):
    """Zmaž súbor podľa mena (aj jeho duplikáty).

    Volá to build pri „pregenerovaní": kým starý súbor existuje, ďalší beh by
    zobral jeho, a beh, ktorý mal počítať nanovo, by o svoju prácu prišiel.
    """
    creds = creds_or_die("maže sa zo skladu")
    items = index(creds, args.store)
    n = 0
    for name in args.name:
        v = items.get(name)
        if v is None:
            log(f"  v sklade {args.store} nebolo: {name}")
            continue
        for fid in [v["id"]] + v.get("dupes", []):
            if args.dry_run:
                log(f"  zmazal by som: {name} ({human(v['size'])})")
            else:
                auth.api_delete(creds, fid)
                log(f"  zmazané: {name} ({human(v['size'])})")
            n += 1
    return 0


def do_prune(args):
    """Preriedenie jedného skladu podľa veku.

    NIE VŠETKO SA PRERIEĎUJE. Dlaždice výškového modelu sú drahé zrkadlá
    (jeden stupeň DMR 5.0 je rádovo pol hodiny čítania z Drive) a majú tam
    ležať, kým ich niekto ručne nezmaže – preto sa sklad zadáva a nemá
    predvolenú hodnotu. Zmysel to má pri `vysledky`, kde každý beh pridá
    nový súbor a starý už nikto nechce.
    """
    creds = creds_or_die("prerieďuje sa sklad")
    items = index(creds, args.store)
    vel = sum(v["size"] for v in items.values())
    log(f"Sklad {args.store}: {len(items)} súborov, {human(vel)}")
    hranica = time.time() - args.keep_days * 86400
    smeti = [(n, v) for n, v in sorted(items.items())
             if args.keep_days > 0 and v["created"]
             and _epoch(v["created"]) < hranica]
    usetrene = sum(v["size"] for _, v in smeti)
    log(f"Na zmazanie: {len(smeti)} súborov starších než {args.keep_days:g} "
        f"dní, {human(usetrene)}")
    for name, v in smeti:
        log(f"  {v['created'][:19]}  {human(v['size']):>10}  {name}")
    if args.dry_run:
        log("Len výpis, nič sa nemazalo.")
    else:
        for _name, v in smeti:
            for fid in [v["id"]] + v.get("dupes", []):
                auth.api_delete(creds, fid)
        log(f"Zmazaných {len(smeti)} súborov, uvoľnené {human(usetrene)}")
    if args.summary:
        with open(args.summary, "a") as f:
            f.write(f"### Sklad `{args.store}` na Drive\n\n")
            f.write("| vec | hodnota |\n|---|--:|\n")
            f.write(f"| súborov pred | {len(items)} |\n")
            f.write(f"| veľkosť pred | {human(vel)} |\n")
            f.write(f"| {'na zmazanie' if args.dry_run else 'zmazaných'} "
                    f"| {len(smeti)} |\n")
            f.write(f"| {'uvoľnilo by sa' if args.dry_run else 'uvoľnené'} "
                    f"| {human(usetrene)} |\n")
            f.write(f"| ostáva | {human(vel - usetrene)} |\n\n")
    return 0


def _epoch(stamp):
    """RFC 3339 z Drive → sekundy. `timegm`, nie `mktime`: časy z Drive sú
    v UTC a `mktime` by ich čítal ako miestne – na runneri v UTC by to nebolo
    vidieť a inde by prerieďovanie mazalo o hodiny vedľa."""
    try:
        return calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return time.time()


def lines(values):
    """`--name` a `--file` sa dajú zadať viackrát AJ ako viac riadkov (alebo
    medzerami oddelený zoznam) v jednej hodnote – shellové slučky to tak
    podávajú prirodzenejšie než opakovaným prepínačom."""
    out = []
    for v in values or []:
        for line in v.splitlines():
            out += line.split()
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--names", action="store_true")
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--get", action="store_true")
    ap.add_argument("--put", action="store_true")
    ap.add_argument("--rm", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--store", default="", help="ktorý sklad (viď KNOWN)")
    ap.add_argument("--name", action="append", default=[],
                    help="meno súboru v sklade; dá sa opakovať")
    ap.add_argument("--file", action="append", default=[],
                    help="čo nahrať; dá sa opakovať")
    ap.add_argument("--dir", default=".", help="kam sťahovať")
    ap.add_argument("--prefix", default="", help="pri --latest")
    ap.add_argument("--suffix", default="", help="pri --latest")
    ap.add_argument("--note", default="", help="popis súboru na Drive")
    ap.add_argument("--missing-ok", action="store_true",
                    help="pri --get: chýbajúce meno je varovanie, nie chyba")
    ap.add_argument("--skip-local", action="store_true",
                    help="pri --get: čo už je na disku, nesťahuj znova")
    ap.add_argument("--keep-days", type=float, default=90,
                    help="pri --prune: čo je staršie, ide preč (0 = nemazať)")
    ap.add_argument("--dry-run", action="store_true",
                    help="len vypíš, čo by sa stalo")
    ap.add_argument("--summary", default="",
                    help="pri --prune: kam dopísať súhrn (GITHUB_STEP_SUMMARY)")
    args = ap.parse_args()
    args.name = lines(args.name)
    args.file = lines(args.file)

    prikazy = [k for k in ("check", "list", "names", "index", "latest",
                           "get", "put", "rm", "prune") if getattr(args, k)]
    if len(prikazy) != 1:
        ap.error("povedz presne jednu vec: --check / --list / --names / "
                 "--index / --latest / --get / --put / --rm / --prune")
    if prikazy[0] != "check":
        if not args.store:
            ap.error("--store je povinný")
        known_or_die(args.store)
    if args.get and not args.name:
        ap.error("--get potrebuje aspoň jedno --name")
    if args.put and not args.file:
        ap.error("--put potrebuje aspoň jedno --file")
    if args.rm and not args.name:
        ap.error("--rm potrebuje aspoň jedno --name")

    try:
        return {"check": do_check, "list": do_list, "names": do_names,
                "index": do_index, "latest": do_latest, "get": do_get,
                "put": do_put, "rm": do_rm, "prune": do_prune}[prikazy[0]](args)
    except auth.AuthError as exc:
        # Text tých hlášok už nesie, čo s nimi.
        print(f"::error::{exc}")
        return 1
    except RuntimeError as exc:
        print(f"::error::{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
