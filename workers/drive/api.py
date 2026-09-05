#!/usr/bin/env python3
"""Drive API: jedno volanie, jeden preklad odmietnutia.

Všetko, čo hovorí s Google API: požiadavka s opakovaním, prevod chýb na vetu
s návodom, `files.delete` a otázka na rozsahy tokenu. Kto sme rieši
`workers/drive/auth.py`, ktorý si tento modul berie a jeho mená vystavuje
ďalej – `auth.api_get(...)` funguje v ostatných workeroch ako predtým.

Rez je nadol, nie nabok: tento modul o `Credentials` nevie nič (`creds` mu
chodí ako parameter), takže niet kruhovej závislosti.

Preklad odmietnutí je tu celý schválne: Google vracia na tri rôzne chyby ten
istý HTTP 403 a rozdiel je len v tele odpovede.

Spúšťa sa ako modul: `api = load("drive_api", "api.py")`.
"""
import json
import os
import time
import urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    import importlib.util
    import sys
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Spojenie na Google (aj cez firemné proxy a s vlastným CA) vie `drive-serve.py`
# – je to ten súbor, ktorý po HTTP hovorí. Opisovať ho sem by znamenalo dve
# miesta, ktoré si tú istú vec (proxy, CA) počítajú samy.
drive = load("drive_serve", "serve.py")

TOKEN_HOST = "oauth2.googleapis.com"
API_HOST = "www.googleapis.com"

# Dva rozsahy, a rozhoduje o nich to, či sa na Drive aj ZAPISUJE.
#
# `drive.readonly` stačilo, kým pipeline z Drive len čítala. Cache buildu tam
# ale súbory ukladá aj maže (`workers/drive/cache.py`), a na to treba `drive`.
# Menší zapisovací rozsah použiť nejde: `drive.file` vidí len súbory, ktoré
# appka sama vytvorila – ani DMR 5.0 (ležalo tam dávno pred ňou), ani priečinok
# cache, ktorý vznikol v prehliadači, by pod ním nebolo vidieť (`files.create`
# by na neznámy `parents` vrátilo 404).
SCOPE_READ = "https://www.googleapis.com/auth/drive.readonly"
SCOPE_WRITE = "https://www.googleapis.com/auth/drive"

# Tokeninfo povie, aké rozsahy token NAOZAJ dostal. Lacná otázka (jedna
# požiadavka), ktorá sa inak zodpovie až tým, že Drive odmietne zápis.
TOKENINFO_PATH = "/tokeninfo?access_token="

# Tá istá trojica mien, dve pomenovania – rozpis je vo `drive-auth.py`, kde sa
# z prostredia naozaj čítajú. Tu sú preto, že hlášky o odmietnutí radia, kam
# ten údaj doplniť.
TRIOS = (
    ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN"),
    ("DRIVE_CLIENT", "DRIVE_SECRET", "DRIVE_REFRESH"),
)


class AuthError(RuntimeError):
    """Chyba prihlásenia. Text už nesie, čo s tým – vypíš ho ako `::error::`."""


# ---------- HTTP ----------

def request_json(method, host, path, body=None, headers=None, tries=4):
    """Jedna JSON požiadavka na Google. Vracia (stav, dict).

    Vlastná, a nie `urllib`, z toho istého dôvodu ako v `drive-serve.py`:
    runner nemá nič doinštalované a proxy s vlastným CA treba obslúžiť tak
    ako tam.
    """
    last = None
    for attempt in range(tries):
        conn = drive.connect(host, timeout=60)
        try:
            hdr = {"User-Agent": drive.UA, "Accept-Encoding": "identity",
                   **(headers or {})}
            if body is not None:
                # `setdefault`, nie priradenie: volajúci, ktorý posiela JSON,
                # si typ určil sám a prepísať mu ho na formulárový by znamenalo
                # 400 od Google s hláškou o „invalid value".
                hdr.setdefault("Content-Type",
                               "application/x-www-form-urlencoded")
            conn.request(method, path, body=body, headers=hdr)
            resp = conn.getresponse()
            raw = resp.read()
            try:
                data = json.loads(raw or b"{}")
            except ValueError:
                data = {"_telo": raw[:400].decode("utf-8", "replace")}
            if not isinstance(data, dict):
                data = {"_telo": str(data)[:400]}
            return resp.status, data
        except Exception as exc:                    # noqa: BLE001
            last = exc
            time.sleep(min(1.5 ** attempt, 10))
        finally:
            try:
                conn.close()
            except Exception:                       # noqa: BLE001
                pass
    raise AuthError(f"{host}{path.split('?')[0]} neodpovedal ani na {tries}. "
                    f"pokus ({last}). Skontroluj sieť alebo proxy.")


def project_of(client_id):
    """Číslo projektu z client_id (`<projekt>-<hash>.apps.googleusercontent.com`)."""
    head = (client_id or "").split("-", 1)[0]
    return head if head.isdigit() else ""


def api_hint(status, data, creds, path):
    """Hláška k chybe z Drive API – aj s tým, čo s ňou."""
    reason = api_reason(data) or f"HTTP {status}"
    err = data.get("error") if isinstance(data, dict) else None
    detail = str(err.get("message") or "") if isinstance(err, dict) else ""
    if reason == "accessNotConfigured":
        # Toto NIE JE chyba tokenu: token je platný, len projekt nemá zapnuté
        # Drive API, tak ho API neobslúži. Bez odkazu s číslom projektu sa to
        # hľadá po Console zbytočne dlho (beh 31332232209).
        proj = project_of(creds.client_id)
        where = ("https://console.cloud.google.com/apis/library/"
                 "drive.googleapis.com" + (f"?project={proj}" if proj else ""))
        return (f"V projekte na Google Cloud{f' (číslo {proj})' if proj else ''} "
                f"nie je zapnuté **Google Drive API**, takže token síce platí, "
                f"ale API ho neobslúži. Zapni ho tu: {where} – a potom to spusti "
                f"znova." + (f" Google k tomu píše: {detail}" if detail else ""))
    if reason in ("insufficientPermissions", "forbidden") and "scope" in detail.lower():
        return scope_hint(detail)
    return (f"Drive API vrátilo HTTP {status} na {path.split('?')[0]}: {reason}"
            + (f" – {detail}" if detail else ""))


def scope_hint(detail=""):
    """Hláška k „token na to nemá právo" – aj s tým, čo s ňou.

    Rozsah sa do hotového tokenu dopísať nedá, je v ňom od prihlásenia. Preto
    je odpoveď vždy tá istá: prihlásiť sa znova, tentoraz so zápisom.
    """
    return (f"Token nemá rozsah {SCOPE_WRITE}"
            + (f" ({detail})" if detail else "")
            + ". Readonly token vie DMR 5.0 čítať, ale cache na Drive "
              "neuloží ani nepreriedi. Vyrob nový: workflow „Prihlásenie na "
              "Drive (jednorazové)“, alebo `python3 workers/drive/auth.py "
              "--login` (predvolene už pýta zápis) – a prepíš ten istý secret.")


def api_call(creds, method, path, body=None, ctype="application/json"):
    """Jedno volanie Drive API s tokenom. Vracia dict; chybu prekladá do hlášky.

    Aj zápis a mazanie, nielen GET: keď má cache na Drive ukladať a prerieďovať,
    musí to ísť tou istou cestou ako čítanie – s tou istou obnovou tokenu, tým
    istým prekladom chýb a cez tie isté proxy. Dve miesta, ktoré s Drive
    hovoria po svojom, sú dve rôzne hlášky na tú istú chybu.
    """
    raw = body if body is None else (
        body if isinstance(body, bytes) else
        (body if isinstance(body, str) else json.dumps(body)).encode("utf-8"))
    head = {"Authorization": "Bearer " + creds.token()}
    if raw is not None:
        head["Content-Type"] = ctype
    status, data = request_json(method, API_HOST, path, raw, head)
    if status == 401:
        # Token mohol vypršať práve teraz – skús ho raz vymeniť.
        head["Authorization"] = "Bearer " + creds.renew(None)
        status, data = request_json(method, API_HOST, path, raw, head)
    if status not in (200, 204):
        raise AuthError(api_hint(status, data, creds, path))
    return data


def api_get(creds, path):
    """GET na Drive API s tokenom. Vracia dict; chybu prekladá do hlášky."""
    return api_call(creds, "GET", path)


def api_delete(creds, file_id):
    """Zmaž súbor na Drive. Použije to prerieďovanie cache."""
    return api_call(creds, "DELETE",
                    f"/drive/v3/files/{urllib.parse.quote(file_id)}"
                    "?supportsAllDrives=true")


def granted_scopes(creds):
    """Rozsahy, ktoré token NAOZAJ dostal.

    Jedna lacná požiadavka, ktorá odpovedá na otázku „vie tento token
    zapisovať?" – inak sa odpoveď dozvieme až po hodine výpočtu, keď sa má
    uložiť cache a Drive vráti 403.
    """
    status, data = request_json(
        "GET", TOKEN_HOST, TOKENINFO_PATH + urllib.parse.quote(creds.token()))
    if status != 200:
        raise AuthError(f"tokeninfo vrátilo HTTP {status} "
                        f"({data.get('error_description') or data.get('error') or ''})")
    return (data.get("scope") or "").split()


def can_write(creds):
    """Vie tento token na Drive zapisovať? (None = nedá sa zistiť.)"""
    try:
        return SCOPE_WRITE in granted_scopes(creds)
    except AuthError:
        return None


def api_reason(data):
    """Prvý `reason` z chybovej odpovede Drive API, alebo None."""
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        for e in err.get("errors") or []:
            if e.get("reason"):
                return e["reason"]
        return err.get("status") or err.get("message")
    if isinstance(err, str):                        # OAuth chyby sú `{"error": "…"}`
        return err
    return None
