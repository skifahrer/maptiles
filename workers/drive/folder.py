#!/usr/bin/env python3
"""
Priečinok na Google Drive – čo v ňom je, stiahnuť z neho, nahrať doň.
Všetko prihlásené, cez Drive API.

PREČO TO EXISTUJE. Sonnyho dlaždice sa sťahovali `gdown --folder --no-cookies`,
čiže NEPRIHLÁSENE. Verejný odkaz má denný strop sťahovania na súbor a ten
zdieľajú všetci, kto naň siahnu – nielen naše behy. Keď sa vyčerpá, Drive
nevráti chybu, ale HTTP 200 a HTML stránku „Too many users have viewed or
downloaded this file recently" (presne to zhodilo doplnenie modelu; ten istý
tvar odmietnutia rozoberá `quota_hint` v `drive-serve.py`). Prihlásená cesta je
v tomto slušná: pošle 403 a JSON s dôvodom, takže beh spadne v sekundách
a s vysvetlením, nie po hodinách ticha.

ČO PRIHLÁSENIE RIEŠI A ČO NIE – a toto sa NESMIE zamlčať. Strop je viazaný na
VLASTNÍKA súboru, nie na toho, kto sťahuje. Na súbory, ktoré prihlásený účet
naozaj vlastní (DMR 5.0), je strop rádovo vyšší a nedelí sa oň s cudzími
klientmi. Na cudzí priečinok zdieľaný odkazom (Sonny) platí ten istý denný
strop ako predtým – prihlásenie z neho spraví požiadavku s menom účtu namiesto
anonymnej, čo pomáha, ale zázrak to nie je. Preto sa pri každom súbore vypíše,
či ho tento účet vlastní, a v súhrne to stojí čiernym po bielom. Skutočná
poistka proti Sonnyho stropu je to, čo pipeline robí aj tak: stiahnuť raz sem
a uložiť do releasu, z ktorého si už build berie dlaždice bez Drive.

PREČO NIE `gdown`. Nevie sa prihlásiť tokenom, obsah priečinka zisťuje
parsovaním HTML stránky (mení sa) a stiahnuté súbory nevie dopočítať – zrušený
beh po sebe nenechá nič. Tu je jednotkou práce SÚBOR: hotový sa preskočí,
rozrobený sa dopočíta z `.part` cez `Range`, takže zrušený beh nezahodí prácu
(to isté pravidlo ako sklad sklonu v `slope-chunks.py`).

Odpoveď na „prihlásený, alebo nie" je JEDNA a je tu: `--mode`. Workflow sa
pýta jej, neprepočítava si to z toho, či je nastavený secret – dve miesta,
ktoré si tú istú vec počítajú samy, sa raz rozídu.

OPAČNÝM SMEROM to vie tiež (`ensure_path`, `upload` na konci súboru): cache
buildu (`drive-cache.py`) aj hotová mapa (`publish-map.py`) sa na Drive
NAHRÁVAJÚ, a je to tá istá otázka z druhej strany. Nahráva sa „resumable"
uploadom po blokoch, nech výpadok siete nezahodí gigabajt práce – to isté
pravidlo ako `.part` súbory pri sťahovaní.

Použitie:
    python3 workers/drive/folder.py --mode
    python3 workers/drive/folder.py --folder=<URL alebo id> --list
    python3 workers/drive/folder.py --folder=<URL alebo id> --out=dl
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.parse

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


# Prihlásenie aj spojenia sú hotové inde a berú sa odtiaľ: `drive-auth.py` vie
# „kto som a aký mám token", `drive-serve.py` má `Pool` – čítanie cez Range,
# obnovu vypršaného tokenu, presmerovania a preklad odmietnutí do hlášky, ktorá
# povie, čo s tým. Napísať to tu druhýkrát by znamenalo druhú pravdu o tom
# istom.
drive = load("drive_serve", "serve.py")
auth = load("drive_auth", "auth.py")

FOLDER_MIME = "application/vnd.google-apps.folder"

# SKRATKA (shortcut) je položka, ktorá len UKAZUJE na súbor inde na Drive.
# Nemá `size` ani obsah – `alt=media` na ňu vráti prázdno a verejné
# `uc?export=download` odpovie „the owner hasn't given you permission to
# download this file", hoci cieľ zdieľaný je. Sonnyho priečinok s 1″ modelom
# je celý z nich (15 dlaždíc = 15 skratiek, zmerané 2026-08-11), takže bez
# ich rozuzlenia by `listing` vrátila dva obrázky a ani jednu dlaždicu –
# a hláška by pritom vinila zdieľanie priečinka, ktoré je v poriadku.
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

# Bloky po 16 MiB: dosť veľké na to, aby réžia okolo požiadavky nebola vidieť,
# a dosť malé na to, aby sa zrušený beh vrátil najviac o 16 MiB dozadu.
CHUNK = 16 * 1024 * 1024

# Východiskový odhad rýchlosti, kým nie je meranie práve z tejto cesty.
# Skript na konci vypíše NAMERANÉ MB/s oproti tomuto číslu – po prvom behu ho
# sem prepíš tým nameraným, nech odhad na začiatku niečo znamená.
EST_MB_S = 20.0

# Vnorenie priečinkov. Sonnyho priečinok je plochý, ale cudzí priečinok sa
# môže zmeniť a nekonečná rekurzia v cudzích dátach je zlý nápad.
MAX_DEPTH = 5


def folder_id(text):
    """Id priečinka z URL aj z holého id.

    Berie `…/drive/folders/<id>`, `…/open?id=<id>` aj samotné `<id>` – vo
    formulári býva raz jedno, raz druhé a hádať sa o tvar nemá zmysel.
    """
    text = (text or "").strip()
    if not text:
        raise SystemExit("::error::Chýba --folder (URL priečinka alebo jeho id).")
    m = re.search(r"/folders/([-\w]{10,})", text)
    if m:
        return m.group(1)
    parts = urllib.parse.urlsplit(text)
    if parts.query:
        got = urllib.parse.parse_qs(parts.query).get("id")
        if got:
            return got[0]
    if re.fullmatch(r"[-\w]{10,}", text):
        return text
    raise SystemExit(f"::error::Z „{text}“ sa nedá vyčítať id priečinka na "
                     f"Drive. Čakám odkaz tvaru "
                     f"https://drive.google.com/drive/folders/<id> alebo id.")


def rozuzli(creds, f, rel):
    """Skratka → súbor, na ktorý ukazuje. Vracia `(položka, dôvod preskočenia)`.

    Meno ostáva to zo SKRATKY – to je, čo priečinok ukazuje, a pri dlaždiciach
    je meno sľub o rozsahu (`N49E020` hovorí „tento celý stupeň"). Keď sa cieľ
    volá inak, je to buď premenovaná skratka, alebo skratka na cudziu dlaždicu;
    ani jedno sa nesmie prehltnúť ticho, lebo z toho vyjde dlaždica s dátami
    z iného miesta.

    Cieľ sa dopytuje po jednom, nie dávkovo: priečinkov s tisíckami skratiek
    tu nie je (Sonny ich má 15) a jednoduchosť je tu viac než ušetrené volania.
    """
    det = f.get("shortcutDetails") or {}
    tid = det.get("targetId")
    if not tid:
        return f, (f"{rel} (skratka bez cieľa – cieľ zmazaný alebo "
                   f"neprístupný tomuto účtu)")
    if det.get("targetMimeType") == FOLDER_MIME:
        return dict(f, id=tid, mimeType=FOLDER_MIME), ""
    try:
        ciel = auth.file_info(creds, tid)
    except Exception as exc:                        # noqa: BLE001
        return f, f"{rel} (na cieľ skratky {tid} sa nedá dopýtať: {exc})"
    if ciel.get("name") and ciel["name"] != f.get("name"):
        print(f"::warning::Skratka „{rel}“ ukazuje na súbor s iným menom "
              f"„{ciel['name']}“. Meno dlaždice je sľub o tom, ktoré územie "
              f"v nej je – over, či je to naozaj tá dlaždica, alebo priečinok "
              f"vynechaj.", flush=True)
    # `size`, `ownedByMe` aj id sa berú z CIEĽA: strop sťahovania visí na
    # vlastníkovi cieľa a sťahuje sa tiež cieľ. Skratka nemá ani jedno.
    return dict(f, id=tid, size=ciel.get("size"),
                ownedByMe=ciel.get("ownedByMe"),
                mimeType=ciel.get("mimeType", ""), shortcutDetails=det), ""


def listing(creds, fid, depth=0, prefix="", extra=""):
    """Súbory v priečinku (aj v podpriečinkoch), zoradené podľa mena.

    Vracia zoznam dictov `{id, name, path, size, owned, raw}`. Google-natívne
    dokumenty (tabuľky, prezentácie) sa preskakujú: `alt=media` ich nestiahne
    a v priečinku s dlaždicami nemajú čo hľadať.

    `extra` sú polia navyše (napr. `createdTime`) – v `raw` ich potom nájde
    volajúci. Je to tu preto, aby „vypíš priečinok na Drive" ostalo jedno
    miesto: pýta sa ho aj cache (`drive-cache.py`, chce časy) aj DMR 5.0
    (`dmr5-drive.py`, chce id súborov podľa mena).

    SKRATKY sa rozuzľujú TU, nie u volajúceho. Volajúci sa pýta „čo je
    v priečinku a odkiaľ to stiahnem" a odpoveď na to má byť jedna – keby si
    každý (cache, DMR 5.0, doplnenie modelu) riešil skratky sám, raz by sa
    rozišli, a tri zo štyroch by to nerobili vôbec.
    """
    out, skipped, token = [], [], ""
    while True:
        q = urllib.parse.quote(f"'{fid}' in parents and trashed = false")
        path = (f"/drive/v3/files?q={q}&pageSize=1000&orderBy=folder,name"
                f"&supportsAllDrives=true&includeItemsFromAllDrives=true"
                f"&fields=nextPageToken,files(id,name,size,mimeType,ownedByMe,"
                f"shortcutDetails(targetId,targetMimeType)"
                + (f",{extra}" if extra else "") + ")")
        if token:
            path += "&pageToken=" + urllib.parse.quote(token)
        data = auth.api_get(creds, path)
        for f in data.get("files") or []:
            name = f.get("name") or f["id"]
            rel = f"{prefix}{name}"
            if f.get("mimeType") == SHORTCUT_MIME:
                f, problem = rozuzli(creds, f, rel)
                if problem:
                    skipped.append(problem)
                    continue
            if f.get("mimeType") == FOLDER_MIME:
                if depth >= MAX_DEPTH:
                    skipped.append(f"{rel}/ (vnorené hlbšie než {MAX_DEPTH})")
                    continue
                sub, sub_skipped = listing(creds, f["id"], depth + 1, rel + "/",
                                           extra)
                out += sub
                skipped += sub_skipped
                continue
            if f.get("size") is None:
                skipped.append(f"{rel} ({f.get('mimeType', '?')})")
                continue
            out.append({"id": f["id"], "name": name, "path": rel,
                        "size": int(f["size"]), "owned": bool(f.get("ownedByMe")),
                        "raw": f})
        token = data.get("nextPageToken") or ""
        if not token:
            return out, skipped


def human(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


class Progress:
    """Tep sťahovania: čo sa práve deje a koľko ešte.

    Hodina ticha v logu sa nedá odlíšiť od zaseknutého behu, a `\\r`-ové
    percentá sa v logu GitHub Actions neobjavia, kým krok neskončí – preto
    celé riadky a preto raz za `every` sekúnd.
    """

    def __init__(self, total, every=30):
        self.total = total
        self.every = every
        self.done = 0
        self.t0 = time.time()
        self.last = self.t0

    def add(self, n, label):
        self.done += n
        now = time.time()
        if now - self.last < self.every:
            return
        self.last = now
        rate = self.done / max(now - self.t0, 1e-6)
        line = (f"    [{(now - self.t0) / 60:5.1f} min] {label}: "
                f"{human(self.done)} z {human(self.total)} "
                f"({rate / 1e6:.1f} MB/s)")
        # Odhad zvyšku má zmysel len vtedy, keď sa naozaj sťahuje – pri
        # rýchlosti okolo nuly by vyšli tisíce minút a to je horšie než nič.
        if rate > 1e5 and self.done < self.total:
            line += f", zostáva ~{(self.total - self.done) / rate / 60:.0f} min"
        print(line, flush=True)


def fetch(pool, item, dest, progress):
    """Jeden súbor do `dest`; hotový preskočí, rozrobený dopočíta.

    Cez `.part` a premenovanie, nie priamo do cieľa: inak by po zrušenom behu
    ostal skrátený súbor s finálnym menom a ďalší beh by ho pokladal za hotový
    (to isté pravidlo, na ktorom stojí sklad častí sklonu).
    """
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) == item["size"]:
        progress.done += item["size"]
        print(f"    hotové z predošlého behu ({human(item['size'])})", flush=True)
        return 0
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if have > item["size"]:                 # cudzí zvyšok alebo zmenený súbor
        have = 0
    if have:
        print(f"    pokračujem od {human(have)}", flush=True)
        progress.done += have
    got = 0
    with open(part, "r+b" if have else "wb") as f:
        f.seek(have)
        f.truncate(have)
        while have < item["size"]:
            end = min(have + CHUNK, item["size"]) - 1
            want = end - have + 1
            _, _, body = pool.get(item["id"], f"bytes={have}-{end}", want=want)
            f.write(body)
            have += len(body)
            got += len(body)
            progress.add(len(body), item["name"])
    os.replace(part, dest)
    return got


# ---------- opačný smer: priečinky a nahrávanie ----------
#
# Ten istý súbor preto, že je to tá istá otázka z druhej strany: „čo je
# v priečinku" a „daj to do priečinka". Cache buildu (`drive-cache.py`) aj
# publikovanie hotovej mapy (`publish-map.py`) potrebujú oboje a druhá kópia
# nahrávania by bola druhá pravda o tom, ako sa s Drive hovorí.

# Nahrávanie po blokoch. Google žiada násobok 256 KiB; 32 MiB je kompromis
# medzi réžiou požiadavky a tým, o koľko sa vráti prerušené nahrávanie.
# Vlastné meno, nie `CHUNK`: to je o 150 riadkov vyššie a patrí SŤAHOVANIU –
# dve konštanty s jedným menom v jednom súbore znamenajú, že tá druhá ticho
# prepíše prvú.
UPLOAD_CHUNK = 32 * 1024 * 1024

UPLOAD_PATH = ("/upload/drive/v3/files?uploadType=resumable"
               "&supportsAllDrives=true&fields=id,name,size")


def find_folder(creds, parent, name):
    """Id podpriečinka `name` v `parent`, alebo None."""
    q = urllib.parse.quote(
        f"'{parent}' in parents and trashed = false and "
        f"mimeType = '{FOLDER_MIME}' and name = '{name}'")
    data = auth.api_get(creds, f"/drive/v3/files?q={q}&pageSize=10"
                               f"&supportsAllDrives=true"
                               f"&includeItemsFromAllDrives=true"
                               f"&fields=files(id,name)")
    files = data.get("files") or []
    return files[0]["id"] if files else None


def files_named(creds, parent, name):
    """Súbory s menom `name` v priečinku – Drive dovolí duplikáty.

    Preto ich je zoznam a nie jeden: dva behy môžu nahrať to isté meno vedľa
    seba a „ten starý" potom nie je jeden.
    """
    q = urllib.parse.quote(
        f"'{parent}' in parents and trashed = false and name = '{name}'")
    data = auth.api_get(creds, f"/drive/v3/files?q={q}&pageSize=100"
                               f"&supportsAllDrives=true"
                               f"&includeItemsFromAllDrives=true"
                               f"&fields=files(id,name,size,mimeType)")
    return [f for f in (data.get("files") or [])
            if f.get("mimeType") != FOLDER_MIME]


def ids_in(creds, parent):
    """`{id: meno}` súborov, ktoré v priečinku TERAZ sú (bez podpriečinkov).

    Na otázku „existuje ešte súbor, na ktorý ukazuje odkaz v katalógu" –
    a preto id, nie mená. KAŽDÉ nahratie vyrobí NOVÉ id (`upload_clobber`
    nahrá a starý súbor zmaže), takže odkaz v `maps.json` prestane platiť
    v okamihu, keď ten istý balík nahrá ďalší beh. Kým sa to nedalo overiť,
    nikto o tom nevedel: odkaz vyzerá rovnako, či za ním súbor je, alebo nie.

    Plytko zámerne: balíky mapy ležia priamo v priečinku mapy a podpriečinky
    sú výseky (`vysoke_tatry`), teda cudzie položky katalógu. `listing()` sa
    vnára a na túto otázku by odpovedal o priečinok širšie.
    """
    out, token = {}, ""
    while True:
        q = urllib.parse.quote(f"'{parent}' in parents and trashed = false")
        path = (f"/drive/v3/files?q={q}&pageSize=1000"
                f"&supportsAllDrives=true&includeItemsFromAllDrives=true"
                f"&fields=nextPageToken,files(id,name,mimeType)")
        if token:
            path += "&pageToken=" + urllib.parse.quote(token)
        data = auth.api_get(creds, path)
        for f in data.get("files") or []:
            if f.get("mimeType") == FOLDER_MIME:
                continue
            out[f["id"]] = f.get("name") or f["id"]
        token = data.get("nextPageToken") or ""
        if not token:
            return out


def id_z_odkazu(url):
    """Id súboru z odkazu, aký píše `file_link` / `download_link`, inak "".

    Katalóg nesie odkazy, nie id – kto chce vedieť, či za odkazom ešte niečo
    je, musí id vylúpnuť. Obe podoby sú tu vedľa seba zámerne: sú to dva
    tvary tej istej veci a keby si ich čítal každý sám, raz sa rozídu.
    """
    text = (url or "").strip()
    if "/file/d/" in text:
        return text.split("/file/d/", 1)[1].split("/", 1)[0].split("?", 1)[0]
    if "id=" in text:
        return text.split("id=", 1)[1].split("&", 1)[0]
    return ""


def upload_clobber(creds, path, name, parent, description=""):
    """Nahraj a AŽ POTOM zmaž staré súbory toho istého mena.

    To poradie je celé, o čom to je (viď `workers/drive/store.py`): Drive
    dovolí dva súbory s tým istým menom vedľa seba, takže „najprv zmaž" by po
    spadnutom nahrávaní nenechalo ani nové, ani staré – a v priečinku by nebolo
    nič namiesto toho, čo tam pred minútou bolo.

    Vracia `(id nahratého súboru, koľko starých verzií sa zmazalo)`.
    """
    stare = [f["id"] for f in files_named(creds, parent, name)]
    fid = upload(creds, path, name, parent, description)
    for old in stare:
        auth.api_delete(creds, old)
    if stare:
        print(f"    starú verziu ({len(stare)}×) som zmazal", flush=True)
    return fid, len(stare)


def file_link(fid):
    """Odkaz na súbor – ten, čo sa dá poslať človeku (vidí ho, kto má prístup)."""
    return f"https://drive.google.com/file/d/{fid}/view"


def download_link(fid):
    """Odkaz, ktorý súbor rovno stiahne (pri veľkých pýta Drive potvrdenie)."""
    return f"https://drive.google.com/uc?export=download&id={fid}"


def delete_named(creds, parent, name):
    """Zmaž súbory daného mena – „toto v tomto builde nie je".

    Bez toho by v priečinku vedľa novej mapy ostal starý balík vrstvy, ktorú
    tento build nevyrobil, a nikto by na ňom nepoznal, že je z iného behu.
    """
    stare = files_named(creds, parent, name)
    for f in stare:
        auth.api_delete(creds, f["id"])
    return len(stare)


def ensure_folder(creds, parent, name):
    """Podpriečinok `name` v `parent` – nájdi, alebo vyrob. Vracia id.

    Drive dovolí dva priečinky s tým istým menom vedľa seba, takže sa najprv
    HĽADÁ. Dva behy naraz môžu ten istý priečinok vyrobiť dvakrát; berie sa
    potom ten prvý, čo Drive vráti, a druhý ostane prázdny – neškodné, ale
    stojí za to o tom vedieť.
    """
    hit = find_folder(creds, parent, name)
    if hit:
        return hit
    data = auth.api_call(creds, "POST",
                         "/drive/v3/files?supportsAllDrives=true&fields=id,name",
                         {"name": name, "mimeType": FOLDER_MIME,
                          "parents": [parent]})
    print(f"    priečinok „{name}“ vyrobený", flush=True)
    return data["id"]


def ensure_path(creds, root, parts):
    """Cesta priečinkov pod `root` (vyrobí, čo chýba). Vracia id posledného."""
    fid = root
    for part in parts:
        fid = ensure_folder(creds, fid, part)
    return fid


def folder_link(fid):
    return f"https://drive.google.com/drive/folders/{fid}"


def upload(creds, path, name, parent, description="", tries=4):
    """Súbor na Drive cez „resumable upload". Vracia id.

    PREČO RESUMABLE A NIE JEDNODUCHÝ POST. Nahráva sa cache buildu aj hotová
    mapa – stovky MB až jednotky GB. Jednoduché nahranie je jedna požiadavka,
    ktorá sa pri prvom výpadku siete celá zahodí; resumable sa Drive spýta
    „koľko si toho dostal" a pokračuje odtiaľ. Tá istá logika ako `.part`
    súbory inde v pipeline: hodina práce nesmie zmiznúť kvôli jednému
    stratenému spojeniu.
    """
    size = os.path.getsize(path)
    meta = json.dumps({"name": name, "parents": [parent],
                       # Dlhý text nejde do `appProperties`: tie majú strop
                       # 124 B na hodnotu a kľúče cache sú dlhšie.
                       "description": description,
                       "appProperties": {
                           "repo": os.environ.get("GITHUB_REPOSITORY", ""),
                           "run": os.environ.get("GITHUB_RUN_ID", "")}})

    headers = _post_session(creds, meta, size)
    loc = headers.get("Location")
    if not loc:
        raise RuntimeError("Drive nevrátil adresu nahrávania (Location)")
    parts = urllib.parse.urlsplit(loc)
    host = parts.netloc
    upath = parts.path + (("?" + parts.query) if parts.query else "")

    progress = Progress(size)
    sent = 0
    attempt = 0
    with open(path, "rb") as f:
        while sent < size:
            f.seek(sent)
            body = f.read(min(UPLOAD_CHUNK, size - sent))
            end = sent + len(body) - 1
            try:
                status, headers, _ = _put_chunk(host, upath, body, sent, end,
                                                size, creds)
            except Exception as exc:                # noqa: BLE001
                attempt += 1
                if attempt >= tries:
                    raise RuntimeError(
                        f"Nahrávanie na Drive zlyhalo ani na {tries}. pokus "
                        f"({exc}). Uložené je {human(sent)} z {human(size)}.")
                time.sleep(min(2 ** attempt, 20))
                # Koľko toho Drive naozaj má, vie len Drive – spýtaj sa ho,
                # nedopočítavaj to. Keď neodpovie ani na to, skús ten istý
                # blok znova: opakovaný blok Drive zahodí, chýbajúci nie.
                try:
                    sent = _uploaded(host, upath, size, creds)
                except Exception as exc2:           # noqa: BLE001
                    print(f"  (Drive nepovedal, koľko má: {exc2})", flush=True)
                continue
            if status in (200, 201):
                progress.add(len(body), name)
                return json.loads(headers["_telo"] or b"{}").get("id", "")
            if status == 308:
                sent = _resume_from(headers, sent + len(body))
                progress.add(len(body), name)
                attempt = 0
                continue
            if status in (401, 403) and attempt < tries:
                # Vypršaný token vymeň a skús ten istý blok znova.
                attempt += 1
                creds.renew(None)
                continue
            raise RuntimeError(_upload_error(status, headers, parent))
    raise RuntimeError("Drive nahrávanie neukončil – posledný blok nedostal "
                       "odpoveď 200/201.")


def _upload_error(status, headers, parent):
    body = headers.get("_telo") or b""
    reason = drive.api_error(body) or f"HTTP {status}"
    if status == 403 and "insufficient" in str(reason).lower():
        return auth.scope_hint(str(reason))
    if status == 403:
        return (f"Drive odmietol zápis ({reason}). Najčastejšie je to plný "
                f"disk účtu alebo právo len na čítanie priečinka {parent}.")
    return f"Drive vrátil HTTP {status} pri nahrávaní ({reason})"


def _request(host, method, path, body, headers, timeout=300):
    """Jedna požiadavka; telo odpovede vracia v hlavičkách pod `_telo`.

    Vlastná a nie `urllib` z toho istého dôvodu ako inde: runner nemá nič
    doinštalované a proxy s vlastným CA rieši `drive.connect`.
    """
    conn = drive.connect(host, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        head = dict(resp.headers)
        head["_telo"] = raw
        return resp.status, head, raw
    finally:
        try:
            conn.close()
        except Exception:                           # noqa: BLE001
            pass


def _post_session(creds, meta, size):
    """Otvor nahrávaciu reláciu. Vracia hlavičky odpovede (v nich `Location`).

    Na 401 sa token raz vymení a skúsi znova – vypršať mohol práve teraz a
    zahodiť kvôli tomu celé nahrávanie by bolo drahé.
    """
    for pokus in range(2):
        status, head, _ = _request(
            auth.API_HOST, "POST", UPLOAD_PATH, meta.encode("utf-8"),
            {"Authorization": "Bearer " + creds.token(),
             "Content-Type": "application/json; charset=UTF-8",
             "X-Upload-Content-Type": "application/octet-stream",
             "X-Upload-Content-Length": str(size),
             "User-Agent": drive.UA})
        if status in (200, 201):
            return head
        if status == 401 and pokus == 0:
            creds.renew(None)
            continue
        raise RuntimeError(_upload_error(status, head, "?"))
    raise RuntimeError("Drive nezačal nahrávanie")


def _put_chunk(host, path, body, start, end, size, creds):
    return _request(host, "PUT", path, body,
                    {"Authorization": "Bearer " + creds.token(),
                     "Content-Range": f"bytes {start}-{end}/{size}",
                     "Content-Length": str(len(body)),
                     "User-Agent": drive.UA})


def _uploaded(host, path, size, creds):
    """Koľko bajtov už Drive z tohto nahrávania má."""
    status, head, _ = _request(host, "PUT", path, b"",
                               {"Authorization": "Bearer " + creds.token(),
                                "Content-Range": f"bytes */{size}",
                                "Content-Length": "0",
                                "User-Agent": drive.UA})
    if status in (200, 201):
        return size
    return _resume_from(head, 0)


def _resume_from(headers, default):
    """`Range: bytes=0-<n>` z odpovede 308 → odkiaľ pokračovať."""
    rng = headers.get("Range") or ""
    if "-" in rng:
        try:
            return int(rng.rsplit("-", 1)[1]) + 1
        except ValueError:
            pass
    return default


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", default="",
                    help="URL priečinka na Drive alebo jeho id")
    ap.add_argument("--out", default="dl", help="kam sťahovať")
    ap.add_argument("--mode", action="store_true",
                    help="vypíš `auth` alebo `public` a skonči – jediná "
                         "odpoveď na „vieme sa prihlásiť?“")
    ap.add_argument("--list", action="store_true",
                    help="vypíš, čo v priečinku je, a nesťahuj nič")
    args = ap.parse_args()

    # Neúplný pár secretov je CHYBA a `from_env` na ňom padne – zámerne:
    # kto nastavil polovicu, čaká prihlásený beh, a ticho prepadnúť na verejný
    # denný limit je presne ten omyl, čo sa nájde až o pol dňa.
    creds = auth.from_env()

    if args.mode:
        print("auth" if creds is not None else "public")
        return 0

    if creds is None:
        print("::error::Priečinok z Drive sa dá vypísať len prihlásene "
              "(Drive API neobsluhuje anonymné požiadavky), ale v prostredí "
              "nie je token vlastníka. Doplň premennú DRIVE_CLIENT a secrety "
              "DRIVE_SECRET / DRIVE_REFRESH – vyrobí ich workflow "
              "„Údržba · prihlásenie Drive“ (.github/workflows/"
              "drive-login.yml), z počítača `python3 workers/drive/auth.py "
              "--login`.")
        return 3

    fid = folder_id(args.folder)
    who = auth.whoami(creds)
    print(f"Režim čítania z Drive: {auth.describe(creds)}")
    print(f"  účet     {who.get('emailAddress', '?')} "
          f"({who.get('displayName', '?')})")
    print(f"  údaje    z {creds.source}")
    print(f"  priečinok {fid}")

    files, skipped = listing(creds, fid)
    if not files:
        # Čo sa preskočilo, patrí do TEJ ISTEJ hlášky. Kým tu bolo len
        # „vidí naň účet?", posielala hláška hľadať chybu do zdieľania
        # priečinka aj vtedy, keď bolo zdieľanie v poriadku a preskočili sa
        # napríklad nerozuzlené skratky.
        for f in skipped:
            print(f"  preskočené: {f}")
        print(f"::error::V priečinku {fid} nie je ani jeden stiahnuteľný súbor "
              f"({len(skipped)} položiek preskočených, viď vyššie). Vidí naň "
              f"účet {who.get('emailAddress', '?')}? Priečinok musí byť "
              f"zdieľaný aspoň „ktokoľvek s odkazom – čitateľ“.")
        return 1
    total = sum(f["size"] for f in files)
    foreign = [f for f in files if not f["owned"]]

    # PLÁN PRED DRAHOU ČASŤOU. Krok, ktorý len mlčí a po hodine spadne na
    # timeout, minie celý rozpočet a nevyrobí nič.
    print(f"\nPlán: {len(files)} súborov, {human(total)}, "
          f"odhad ~{total / (EST_MB_S * 1e6) / 60:.0f} min "
          f"pri {EST_MB_S:.0f} MB/s")
    for f in skipped:
        print(f"  preskakujem {f}")
    if foreign:
        # Nesmie to vyzerať ako vyriešený problém, keď vyriešený nie je.
        print(f"  POZOR: {len(foreign)} z {len(files)} súborov tento účet "
              f"NEVLASTNÍ. Na cudzí zdieľaný súbor platí ten istý denný strop "
              f"sťahovania ako na verejný odkaz – prihlásenie ho nedvíha. "
              f"Preto sa sťahujú raz sem a ukladajú do releasu; build mapy už "
              f"na Drive nesiaha.")
    if args.list:
        for f in files:
            print(f"  {'vlastné' if f['owned'] else 'cudzie '}  "
                  f"{human(f['size']):>9}  {f['path']}"
                  + ("  (skratka)" if f["raw"].get("shortcutDetails") else ""))
        return 0

    pool = drive.Pool(creds=creds)
    progress = Progress(total)
    t0 = time.time()
    fresh = 0
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f['path']} – {human(f['size'])}", flush=True)
        fresh += fetch(pool, f, os.path.join(args.out, f["path"]), progress)

    # NAMERANÉ ČÍSLA OPROTI ODHADU. Bez nich sa odhad hore nikdy neopraví.
    el = time.time() - t0
    rate = fresh / max(el, 1e-6) / 1e6
    print(f"\nHotovo: {len(files)} súborov, {human(total)} "
          f"(z toho {human(fresh)} stiahnutých v tomto behu) "
          f"za {el / 60:.1f} min, {rate:.1f} MB/s "
          f"(odhad počítal s {EST_MB_S:.0f} MB/s)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except auth.AuthError as exc:
        # Text tých hlášok už nesie, čo s nimi – netreba k nemu nič pridávať.
        print(f"::error::{exc}")
        sys.exit(1)
    except RuntimeError as exc:
        print(f"::error::{exc}")
        sys.exit(1)
