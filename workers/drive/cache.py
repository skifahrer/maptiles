#!/usr/bin/env python3
"""Cache buildu na Google Drive – náhrada za `actions/cache`.

GitHubová cache má na repozitár 10 GB a keď sa naplní, ticho zahodí najstaršie
záznamy. Táto pipeline do nej ukladá desiatky GB na jeden výrez, takže sa
vyhadzovala navzájom a hodinové výpočty sa rátali znova. Na Drive miesto máme.

Sémantika ostáva tá istá, nech sa `if:` podmienky vo workflowoch neprepisujú:
`cache-hit` len pri presnej zhode kľúča, `restore-keys` sú predpony a berie sa
najnovší záznam, existujúci kľúč sa neprepisuje.

Jeden záznam = jeden `.tar.zst` v priečinku `FOLDER_ID`, pomenovaný kľúčom.
Celý kľúč je aj v `description`: v mene sa znaky mimo `[A-Za-z0-9._-]`
nahrádzajú podčiarkovníkom, takže dva kľúče by sa mohli zliať do jedného mena.

Zapisovať sa musí dať: pod `drive.readonly` sa cache uloží nikdy a `--save` na
tom padne s návodom. Nič sa nemaže samo – na to je `--prune`, ktorý raz za
týždeň spúšťa upratovanie. Prerieďuje dvoma rýchlosťami: hotové vrstvy z DEM sú
hodiny výpočtu na kraj, ostatné sa dá zohnať znova.

    python3 workers/drive/cache.py --check | --list
    python3 workers/drive/cache.py --restore --key=abc --path=dem
    python3 workers/drive/cache.py --save --key=abc --path=dem
    python3 workers/drive/cache.py --prune --keep-days=30 --keep-gb=100
"""
import argparse
import calendar
import importlib.util
import os
import shutil
import subprocess
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


# S Drive hovoria tri hotové súbory a tento si ich požičiava celé: `drive-auth`
# vie „kto som a aký mám token" (aj zápis a mazanie cez API), `drive-serve` má
# `Pool` (Range, presmerovania, proxy, preklad odmietnutí) a `drive-folder` vie
# vypísať priečinok a stiahnuť z neho súbor tak, že zrušený beh nezahodí prácu.
# Napísať to sem druhýkrát by znamenalo druhú pravdu o tom istom.
drive = load("drive_serve", "serve.py")
auth = load("drive_auth", "auth.py")
folder = load("drive_folder", "folder.py")

# Priečinok s cache na Drive. Ako pri DMR 5.0 platí, že tajomstvo to nie je –
# id chodí v zdieľanom odkaze; tajomstvom je token vlastníka v secrete.
FOLDER_ID = "15-Z37buVADUk9_-RMWAQp6arqqjPdRaV"

# HOTOVÉ VRSTVY Z VÝŠKOVÉHO MODELU – vrstevnice, skaly a tieňovanie. Sú to
# HODINY výpočtu na jeden kraj a jediné záznamy, na ktoré sa build vie spýtať
# aj o mesiace neskôr („toto som už raz spočítal, nepočítaj to znova" –
# predpony kľúčov vo `workers/plan/cache-keys.sh`). Preto majú v prerieďovaní
# vlastný, dlhší vek a pri strope priečinka odchádzajú POSLEDNÉ: stiahnuté DEM
# dlaždice sa dajú stiahnuť znova a časti sklonu sú aj v sklade `dem-slope`,
# kým prepočítané vrstevnice celého kraja nevráti nič.
VRSTVY = ("contours-", "rocks-", "terrain-")


def vrstva(key):
    """Je to hotová vrstva (a teda to drahé, čo sa oplatí držať dlhšie)?"""
    return key.startswith(VRSTVY)


# Prípony, pod ktorými záznam leží. Dve preto, že `zstd` na runneri je, ale
# nemusí byť všade – rozbaľuje sa podľa toho, čo v mene naozaj je.
ZSTD = ".tar.zst"
GZIP = ".tar.gz"
SUFFIXES = (ZSTD, GZIP)

def human(n):
    return folder.human(n)


def log(msg):
    print(msg, flush=True)


# ---------- meno záznamu ----------

def safe(key):
    """Kľúč → meno súboru. Znak za znak, aby predpona ostala predponou."""
    return "".join(c if (c.isalnum() and c.isascii()) or c in "._-" else "_"
                   for c in key)


def entry_key(name):
    """Meno súboru → kľúč (bez prípony), alebo None, keď to nie je záznam."""
    for suf in SUFFIXES:
        if name.endswith(suf):
            return name[:-len(suf)]
    return None


# ---------- čo je v priečinku ----------

def creds_or_die(what):
    """Prihlásenie, alebo pád s návodom.

    Bez tokenu sa nedá ani vypísať priečinok – Drive API anonymné požiadavky
    neobsluhuje. Tichý „cache miss" by tu bol ten najdrahší druh omylu: build
    by počítal všetko odznova pri každom behu a nikde by nebolo vidieť prečo.
    """
    creds = auth.from_env()
    if creds is None:
        raise SystemExit(
            f"::error::Cache na Drive potrebuje prihlásenie ({what}), ale "
            "v prostredí nie je token vlastníka. Doplň secret "
            "GDRIVE_CREDENTIALS (alebo premennú DRIVE_CLIENT a secrety "
            "DRIVE_SECRET / DRIVE_REFRESH) a podaj ho jobu cez `env:` – "
            "vyrobí ich workflow „Údržba · prihlásenie Drive“.")
    return creds


def entries(creds):
    """Záznamy cache v priečinku, od najnovšieho.

    Vracia zoznam dictov `{id, name, key, plny_kluc, size, created}`. Čo nemá
    príponu záznamu, sa preskočí a NEMAŽE: v priečinku môže ležať čokoľvek,
    čo tam dal človek, a cache nemá právo mu to upratať.
    """
    files, _skipped = folder.listing(creds, FOLDER_ID,
                                     extra="createdTime,description")
    out = []
    for f in files:
        key = entry_key(f["name"])
        if key is None:
            continue
        raw = f.get("raw") or {}
        out.append({"id": f["id"], "name": f["name"], "key": key,
                    "plny_kluc": raw.get("description") or key,
                    "size": f["size"], "created": raw.get("createdTime") or ""})
    out.sort(key=lambda e: e["created"], reverse=True)
    return out


def find(items, key, restore_keys):
    """(záznam, presná zhoda?) podľa pravidiel `actions/cache`.

    Najprv PRESNÝ kľúč, potom predpony v poradí, v akom boli zadané – a v rámci
    predpony ten najnovší. To posledné je celý zmysel skladu častí sklonu:
    ukladá sa pod „predpona + číslo behu", takže sa dá dopĺňať, a hľadá sa
    najnovší, čo na predponu sedí.

    Porovnáva sa PLNÝ kľúč z `description`, nie meno súboru: v mene sú znaky
    mimo `[A-Za-z0-9._-]` nahradené podčiarkovníkom, takže by dva rôzne kľúče
    mohli vyzerať rovnako – a vrátiť skaly jedného pohoria ako skaly druhého je
    presne ten tichý omyl, ktorý sa v mape nájde až o týždeň.
    """
    exact = [e for e in items if e["plny_kluc"] == key]
    if exact:
        return exact[0], True
    for prefix in restore_keys:
        hit = [e for e in items if e["plny_kluc"].startswith(prefix)]
        if hit:
            return hit[0], False
    return None, False


# ---------- balenie ----------

def have(cmd):
    return shutil.which(cmd) is not None


def pack(paths, dest):
    """Zabalí cesty do jedného archívu. Vracia zoznam toho, čo v ňom je.

    Cesty sú relatívne k pracovnému priečinku – rovnako ako pri
    `actions/cache`, takže sa archív rozbalí tam, odkiaľ vznikol. Čo
    neexistuje, sa preskočí a napíše sa to: prázdny archív je horší než chyba.
    """
    su = [p for p in paths if os.path.exists(p)]
    for p in paths:
        if p not in su:
            log(f"  (v pracovnom priečinku nie je {p} – vynechávam)")
    if not su:
        raise SystemExit("::error::Ani jedna z ciest neexistuje – nie je čo "
                         "uložiť. (Volajúci krok to má strážiť `hashFiles`.)")
    cmd = ["tar", "--zstd" if dest.endswith(ZSTD) else "-z", "-cf", dest, *su]
    t0 = time.time()
    subprocess.run(cmd, check=True)
    log(f"  zabalené {', '.join(su)} → {human(os.path.getsize(dest))} "
        f"za {time.time() - t0:.0f} s")
    return su


def unpack(src):
    """Rozbalí archív do pracovného priečinka."""
    t0 = time.time()
    subprocess.run(["tar", "--zstd" if src.endswith(ZSTD) else "-z", "-xf", src],
                   check=True)
    log(f"  rozbalené za {time.time() - t0:.0f} s")


# ---------- sťahovanie ----------

def download(creds, item, dest):
    """Záznam z Drive na disk. Sťahovanie po blokoch má hotové `drive-folder`."""
    pool = drive.Pool(creds=creds)
    progress = folder.Progress(item["size"])
    t0 = time.time()
    folder.fetch(pool, {"id": item["id"], "name": item["name"],
                        "size": item["size"]}, dest, progress)
    el = max(time.time() - t0, 1e-6)
    log(f"  stiahnuté {human(item['size'])} za {el / 60:.1f} min "
        f"({item['size'] / el / 1e6:.1f} MB/s)")


# ---------- príkazy ----------

def out(name, value):
    """Výstup kroku – tie isté mená, aké má `actions/cache`."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{name}={value}\n")
    log(f"  {name}={value}")


def do_restore(args):
    creds = creds_or_die("hľadá sa záznam cache")
    items = entries(creds)
    hit, exact = find(items, args.key, args.restore_keys)
    out("cache-primary-key", args.key)
    if hit is None:
        log(f"Cache na Drive: nič pre `{args.key}`"
            + (f" ani pre predpony {args.restore_keys}" if args.restore_keys
               else "")
            + f" ({len(items)} záznamov v priečinku)")
        out("cache-hit", "false")
        out("cache-matched-key", "")
        return 0
    # Zhoda po PREDPONE znamená, že sa berie niečo, čo nevzniklo s dnešným
    # kľúčom – pri vrstvách z výškového modelu je to hotová vrstva
    # z predošlého behu. Preto nie do logu, ale `::notice::`: v behu má byť
    # vidieť, že sa niečo nepočítalo, aj bez rozklikávania kroku.
    if exact:
        log(f"Cache na Drive: presná zhoda – {hit['name']} "
            f"({human(hit['size'])}, {hit['created'][:19]})")
    else:
        log(f"::notice::Cache na Drive: zhoda po predpone – berie sa "
            f"`{hit['plny_kluc']}` ({human(hit['size'])}, "
            f"{hit['created'][:19]}) namiesto `{args.key}`.")
    tmp = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"),
                       "drive-cache-" + os.path.basename(hit["name"]))
    # NEPOUŽITEĽNÝ ZÁZNAM NESMIE ZABLOKOVAŤ BUILD. Keď sa nedá stiahnuť alebo
    # rozbaliť, je to drahé (počíta sa odznova), ale nie neriešiteľné – kým by
    # z toho bola tvrdá chyba, jeden pokazený archív by zastavil každý ďalší
    # beh, kým ho niekto ručne nezmaže. Preto sa hlási varovaním a ide sa
    # ďalej; pokazený archív sa navyše zmaže, nech sa nabudúce vyrobí nanovo.
    try:
        download(creds, hit, tmp)
    except (RuntimeError, OSError) as exc:
        print(f"::warning::Záznam `{hit['name']}` sa nepodarilo stiahnuť "
              f"({exc}) – počíta sa odznova.")
        _uprac(tmp)
        out("cache-hit", "false")
        out("cache-matched-key", "")
        return 0
    try:
        unpack(tmp)
    except subprocess.CalledProcessError as exc:
        print(f"::warning::Záznam `{hit['name']}` sa nedá rozbaliť ({exc}) – "
              f"mažem ho a počíta sa odznova.")
        auth.api_delete(creds, hit["id"])
        _uprac(tmp)
        out("cache-hit", "false")
        out("cache-matched-key", "")
        return 0
    _uprac(tmp)
    out("cache-hit", "true" if exact else "false")
    out("cache-matched-key", hit["plny_kluc"])
    return 0


def _uprac(tmp):
    """Stiahnutý archív po sebe – aj rozrobený `.part`."""
    for p in (tmp, tmp + ".part"):
        if os.path.exists(p):
            os.remove(p)


def do_save(args):
    creds = creds_or_die("ukladá sa cache")
    # ROZSAH SA PÝTA PRED BALENÍM, nie až pri nahrávaní. Readonly token
    # `files.create` nepustí, takže by sa najprv zbytočne zabalilo pol giga
    # (`planetiler-sources-v1` je 515 MB) a padlo by to až potom – v každom
    # jednom kroku každého jobu. Jedna lacná otázka to skráti na sekundu
    # a hláška je tá istá.
    if auth.can_write(creds) is False:
        raise SystemExit(f"::error::Uloženie cache `{args.key}` na Drive sa "
                         f"ani neskúšalo: {auth.scope_hint()}")
    items = entries(creds)
    hit, exact = find(items, args.key, [])
    if exact:
        # Tá istá sémantika ako v GitHube: existujúci kľúč sa neprepisuje.
        # Preto majú kľúče, ktoré sa majú dať dopĺňať, v sebe číslo behu.
        log(f"Cache na Drive: `{args.key}` už tam je "
            f"({human(hit['size'])}, {hit['created'][:19]}) – neukladám.")
        return 0
    name = safe(args.key) + (ZSTD if have("zstd") else GZIP)
    tmp = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), name)
    log(f"Cache na Drive: ukladám `{args.key}`")
    try:
        pack(args.path, tmp)
        size = os.path.getsize(tmp)
        t0 = time.time()
        folder.upload(creds, tmp, name, FOLDER_ID, args.key)
        el = max(time.time() - t0, 1e-6)
        log(f"  nahraté {human(size)} za {el / 60:.1f} min "
            f"({size / el / 1e6:.1f} MB/s)")
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        # Hlasno, nie ticho: cache, ktorá sa neuloží, stojí ďalší beh hodiny
        # a nikde inde to vidieť nie je. Volajúci krok má `continue-on-error`,
        # takže beh na tom nepadne, len to bude v logu červené.
        raise SystemExit(f"::error::Uloženie cache `{args.key}` na Drive "
                         f"zlyhalo: {exc}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return 0


def do_delete(args):
    """Zmaž záznam podľa presného kľúča (aj jeho duplikáty).

    Volá to build pri „pregenerovaní": kým starý záznam existuje, nový sa pod
    ten istý kľúč neuloží – a beh, ktorý mal počítať nanovo, by o svoju prácu
    prišiel.
    """
    creds = creds_or_die("maže sa záznam cache")
    smeti = [e for e in entries(creds) if e["plny_kluc"] == args.key]
    if not smeti:
        log(f"nebolo v cache: {args.key}")
        return 0
    for e in smeti:
        if args.dry_run:
            log(f"zmazal by som: {e['name']} ({human(e['size'])})")
            continue
        auth.api_delete(creds, e["id"])
        log(f"zmazané: {e['name']} ({human(e['size'])})")
    return 0


def do_list(args):
    creds = creds_or_die("vypisuje sa cache")
    items = entries(creds)
    total = sum(e["size"] for e in items)
    log(f"Cache na Drive ({FOLDER_ID}): {len(items)} záznamov, {human(total)}")
    for e in items:
        log(f"  {e['created'][:19]}  {human(e['size']):>9}  {e['plny_kluc']}")
    return 0


def do_prune(args):
    """Preriedenie: staré, duplicitné a to, čo nevojde do stropu.

    GitHub si cache vyhadzoval sám (7 dní bez použitia, 10 GB na repozitár),
    Drive nie – bez tohto by priečinok rástol donekonečna a raz by zaplnil účet,
    ktorý drží aj DMR 5.0. Poradie je zámerné: najprv duplikáty (tie sú vždy
    zbytočné), potom vek, a strop až nakoniec, nech sa maže od najstaršieho.
    """
    creds = creds_or_die("prerieďuje sa cache")
    items = entries(creds)
    total = sum(e["size"] for e in items)
    log(f"Cache na Drive ({FOLDER_ID}): {len(items)} záznamov, {human(total)}")

    smeti, dovod = [], {}

    def mark(e, why):
        if e["id"] not in dovod:
            smeti.append(e)
            dovod[e["id"]] = why

    videne = set()
    for e in items:                      # od najnovšieho
        if e["key"] in videne:
            mark(e, "duplikát (novší záznam s tým istým kľúčom už je)")
        videne.add(e["key"])

    # VEK: hotové vrstvy majú vlastnú, dlhšiu hranicu. Tridsať dní bolo
    # zdedené po GitHube (ten mazal po 7 dňoch bez použitia) a znamenalo, že
    # dávka nad krajinou spustená o mesiac počítala celé Slovensko odznova –
    # hoci výsledok v priečinku ležal a nič sa na ňom nezmenilo.
    for e in items:
        dni = args.keep_days_layers if vrstva(e["plny_kluc"]) else args.keep_days
        if dni <= 0 or not e["created"]:
            continue
        if _epoch(e["created"]) < time.time() - dni * 86400:
            mark(e, f"starší než {dni:g} dní"
                    + (" (hotová vrstva)" if vrstva(e["plny_kluc"]) else ""))

    if args.keep_gb > 0:
        strop = args.keep_gb * 1e9
        drzim = 0
        # Poradie držania, nie poradie mazania: najprv hotové vrstvy (od
        # najnovšej), potom zvyšok. Čo sa do stropu nezmestí, ide preč – takže
        # priečinok si udrží to drahé a obetuje to, čo sa dá stiahnuť znova.
        podla_ceny = ([e for e in items if vrstva(e["plny_kluc"])]
                      + [e for e in items if not vrstva(e["plny_kluc"])])
        for e in podla_ceny:
            if e["id"] in dovod:
                continue
            drzim += e["size"]
            if drzim > strop:
                mark(e, f"nad stropom {args.keep_gb:g} GB")

    usetrene = sum(e["size"] for e in smeti)
    log(f"Na zmazanie: {len(smeti)} záznamov, {human(usetrene)}")
    for e in smeti:
        log(f"  {e['created'][:19]}  {human(e['size']):>9}  {e['plny_kluc']} "
            f"– {dovod[e['id']]}")
    if args.dry_run:
        log("Len výpis, nič sa nemazalo.")
    else:
        for e in smeti:
            auth.api_delete(creds, e["id"])
        log(f"Zmazaných {len(smeti)} záznamov, uvoľnené {human(usetrene)}")

    if args.summary:
        with open(args.summary, "a") as f:
            f.write("### Cache na Drive\n\n")
            f.write(f"Hotové vrstvy (vrstevnice, skaly, tieňovanie) sa držia "
                    f"{args.keep_days_layers:g} dní, zvyšok "
                    f"{args.keep_days:g}.\n\n")
            f.write("| vec | hodnota |\n|---|--:|\n")
            f.write(f"| záznamov pred | {len(items)} |\n")
            f.write(f"| veľkosť pred | {human(total)} |\n")
            f.write(f"| {'na zmazanie' if args.dry_run else 'zmazaných'} "
                    f"| {len(smeti)} |\n")
            f.write(f"| {'uvoľnilo by sa' if args.dry_run else 'uvoľnené'} "
                    f"| {human(usetrene)} |\n")
            f.write(f"| ostáva | {human(total - usetrene)} |\n\n")
    return 0


def _epoch(stamp):
    """RFC 3339 z Drive → sekundy. Neznámy tvar = „nechaj to tak".

    `timegm`, nie `mktime`: časy z Drive sú v UTC a `mktime` by ich čítal ako
    miestne. Na runneri v UTC by to nebolo vidieť a inde by prerieďovanie
    mazalo o hodiny vedľa.
    """
    try:
        return calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return time.time()


def do_check(args):
    """Vie tento beh z cache čítať a do nej zapisovať? Lacná otázka.

    Vlastný príkaz preto, že odpoveď na ňu sa inak dozvieme až po hodine
    výpočtu, keď sa má výsledok uložiť – a vtedy je neskoro.
    """
    creds = creds_or_die("kontroluje sa prístup")
    who = auth.whoami(creds)
    print(f"Cache na Google Drive, priečinok {FOLDER_ID}")
    print(f"  účet    {who.get('emailAddress', '?')} (údaje z {creds.source})")
    write = auth.can_write(creds)
    print("  rozsah  " + {True: "číta aj zapisuje ✓",
                          False: "LEN ČÍTANIE – nič sa neuloží",
                          None: "nedá sa zistiť"}[write])
    info = auth.api_get(creds, f"/drive/v3/files/{FOLDER_ID}"
                               "?fields=id,name,ownedByMe,capabilities("
                               "canAddChildren,canListChildren)"
                               "&supportsAllDrives=true")
    caps = info.get("capabilities") or {}
    print(f"  priečinok „{info.get('name', '?')}“ – "
          f"{'vlastný' if info.get('ownedByMe') else 'cudzí'}, "
          f"pridávať {'áno' if caps.get('canAddChildren') else 'NIE'}")
    items = entries(creds)
    print(f"  obsah   {len(items)} záznamov, "
          f"{human(sum(e['size'] for e in items))}")
    quota = auth.api_get(creds, "/drive/v3/about?fields=storageQuota(limit,usage)")
    q = quota.get("storageQuota") or {}
    if q.get("limit"):
        print(f"  na účte {human(int(q.get('usage', 0)))} z "
              f"{human(int(q['limit']))}")
    if write is False or not caps.get("canAddChildren"):
        print(f"::error::{auth.scope_hint()}")
        return 1
    return 0


def lines(values):
    """`--path` sa dá zadať viackrát AJ ako viac riadkov v jednej hodnote.

    To druhé preto, že `actions/cache` má `path: |` s viacerými riadkami
    a composite akcia to podáva ďalej tak, ako to dostala.
    """
    out_ = []
    for v in values or []:
        out_ += [line.strip() for line in v.splitlines() if line.strip()]
    return out_


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--key", default="", help="kľúč záznamu")
    ap.add_argument("--path", action="append", default=[],
                    help="čo sa balí; dá sa opakovať aj zadať po riadkoch")
    ap.add_argument("--restore-keys", action="append", default=[],
                    help="predpony, po ktorých sa hľadá, keď kľúč nesedí")
    ap.add_argument("--keep-days", type=float, default=30,
                    help="pri --prune: čo je staršie, ide preč (0 = nemazať)")
    ap.add_argument("--keep-days-layers", type=float, default=180,
                    help="pri --prune: to isté pre hotové vrstvy (vrstevnice, "
                         "skaly, tieňovanie) – sú to hodiny výpočtu a build "
                         "sa na ne vie spýtať aj o mesiace")
    ap.add_argument("--keep-gb", type=float, default=100,
                    help="pri --prune: strop na celý priečinok (0 = bez stropu)")
    ap.add_argument("--dry-run", action="store_true",
                    help="len vypíš, čo by sa stalo")
    ap.add_argument("--summary", default="",
                    help="pri --prune: kam dopísať súhrn (GITHUB_STEP_SUMMARY)")
    args = ap.parse_args()
    args.path = lines(args.path)
    args.restore_keys = lines(args.restore_keys)

    if (args.restore or args.save or args.delete) and not args.key:
        ap.error("--key je povinný")
    if args.save and not args.path:
        ap.error("--save potrebuje aspoň jednu --path")

    try:
        if args.check:
            return do_check(args)
        if args.list:
            return do_list(args)
        if args.prune:
            return do_prune(args)
        if args.restore:
            return do_restore(args)
        if args.save:
            return do_save(args)
        if args.delete:
            return do_delete(args)
    except auth.AuthError as exc:
        # Text tých hlášok už nesie, čo s nimi.
        print(f"::error::{exc}")
        return 1
    except RuntimeError as exc:
        print(f"::error::{exc}")
        return 1
    ap.error("povedz, čo robiť: --restore / --save / --delete / --list / "
             "--prune / --check")


if __name__ == "__main__":
    sys.exit(main())
