#!/usr/bin/env python3
"""Prihlásenie na Google Drive ako vlastník dát – „kto som a aký mám token".

Verejný odkaz má denný limit sťahovania na súbor a zdieľa ho každý, kto naň
siahne; keď sa vyčerpá, Drive prestane dávať dáta (raz to bol job visiaci
2 h 16 min). Prihlásený vlastník má na svoje súbory oveľa vyšší strop. Ktorý
režim beh použil, sa vždy vypíše – tichý návrat do verejného limitu je omyl,
na ktorý sa potom pol dňa čaká.

Čo treba raz nastaviť: v Google Cloud Console povoliť Drive API, OAuth consent
screen dať na **In production** (v „Testing" platí refresh token 7 dní), vyrobiť
OAuth client ID typu Desktop app a spustiť `--login` na počítači s prehliadačom.
Výsledný JSON ide do secretu `GDRIVE_CREDENTIALS`. Bez počítača to vie
`.github/workflows/drive-login.yml` – prehliadač je telefón, shell je runner
a token sa nikde nevypíše.

Rozsah práv: odkedy je na Drive aj cache buildu, sa tam aj zapisuje a
`drive.readonly` nestačí. Rozsah je v tokene zapečený od prihlásenia, dopísať
sa nedá – starý readonly token ostane platný na čítanie a cache pod ním len
nebude vedieť ukladať.

    python3 workers/drive/auth.py --login --client-id=… --client-secret=…
    python3 workers/drive/auth.py --check [--file=<id>]
"""
import argparse
import importlib.util
import json
import os
import sys
import threading
import time
import urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne.

    Cez `sys.modules`, aby sa modul nevykonal dvakrát.
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# spojenie na Google (proxy, vlastný CA) vie `serve.py` – je to ten súbor,
# ktorý po HTTP hovorí
drive = load("drive_serve", "serve.py")

# volanie API je vedľa, v `api.py`: jedna požiadavka s opakovaním, preklad
# odmietnutí a otázka na rozsahy tokenu. Tento súbor sa pýta, kto sme.
# (Rozdelené, lebo spolu to malo 894 riadkov.) Mená sa vystavujú ďalej, takže
# ostatné workery ich vidia na tom istom mieste ako doteraz.
api = load("drive_api", "api.py")
AuthError = api.AuthError
request_json, api_call = api.request_json, api.api_call
api_get, api_delete = api.api_get, api.api_delete
granted_scopes, can_write = api.granted_scopes, api.can_write
api_hint, api_reason, scope_hint = api.api_hint, api.api_reason, api.scope_hint
project_of = api.project_of

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_HOST = "oauth2.googleapis.com"
TOKEN_PATH = "/token"
API_HOST = "www.googleapis.com"

# dva rozsahy, a rozhoduje, či sa na Drive aj zapisuje. Menší zapisovací
# `drive.file` nestačí: vidí len súbory, ktoré appka sama vytvorila – ani
# DMR 5.0, ani priečinok cache vzniknutý v prehliadači.
SCOPE_READ = "https://www.googleapis.com/auth/drive.readonly"
SCOPE_WRITE = "https://www.googleapis.com/auth/drive"
# predvolene ten širší: token bez zápisu vyzerá rovnako a rozdiel sa ukáže až
# tým, že sa cache prestane ukladať
SCOPE = SCOPE_WRITE

# tokeninfo povie, aké rozsahy token naozaj dostal – lacná otázka, ktorá sa
# inak zodpovie až odmietnutým zápisom
TOKENINFO_PATH = "/tokeninfo?access_token="

# access token platí hodinu, čítanie blokov trvá aj dve
RENEW_BEFORE_S = 300

KEYS = ("client_id", "client_secret", "refresh_token")

# tá istá trojica, dve pomenovania: druhé už leží v secrets tohto repozitára
# a `client_secret` Google druhýkrát neukáže
TRIOS = (
    ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN"),
    ("DRIVE_CLIENT", "DRIVE_SECRET", "DRIVE_REFRESH"),
)


# prihlasovacie údaje

class Credentials:
    """Refresh token vlastníka + access token, ktorý sa sám obnovuje.

    Obnova je tu, nie u volajúceho: čítanie beží v desiatkach vlákien a trvá
    hodiny, takže by sa token obnovoval desaťkrát alebo by beh spadol na 401.
    """

    def __init__(self, client_id, client_secret, refresh_token, source="?"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.source = source
        self.email = None            # doplní `whoami()`
        self._token = None
        self._until = 0.0
        self._lock = threading.Lock()

    # aby sa dal objekt bezpečne vypísať do logu
    def __repr__(self):
        return f"<Credentials {self.email or 'neznámy účet'} z {self.source}>"

    def token(self):
        """Platný access token; obnoví ho, keď dochádza."""
        with self._lock:
            if not self._token or time.time() > self._until - RENEW_BEFORE_S:
                self._fetch()
            return self._token

    def renew(self, stale):
        """Vymeň token, ktorý dostal 401 – ale raz, nie raz za vlákno.

        `stale` je token, s ktorým to zlyhalo.
        """
        with self._lock:
            if stale is None or self._token == stale:
                self._fetch()
            return self._token

    def _fetch(self):
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        status, data = request_json("POST", TOKEN_HOST, TOKEN_PATH, body)
        if status != 200 or not data.get("access_token"):
            raise AuthError(token_error(status, data, self.source))
        self._token = data["access_token"]
        self._until = time.time() + float(data.get("expires_in") or 3600)


def token_error(status, data, source):
    """Hláška k neúspešnej obnove tokenu – aj s tým, čo s ňou."""
    reason = str(data.get("error") or f"HTTP {status}")
    detail = data.get("error_description") or ""
    if reason == "invalid_grant":
        return (f"Drive odmietol refresh token z {source} ({detail}). "
                "Najčastejšie je to publishing status „Testing“ na OAuth "
                "consent screene – v ňom token platí len 7 dní. Prepni ho na "
                "„In production“, vygeneruj nový token cez "
                "`python3 workers/drive/auth.py --login` a prepíš secret "
                "GDRIVE_CREDENTIALS. Rovnako to vyzerá po zmene hesla účtu "
                "alebo po odvolaní prístupu.")
    if reason == "invalid_client":
        return (f"Drive nepozná OAuth klienta z {source} ({detail}). "
                "`client_id` a `client_secret` musia byť z TOHO ISTÉHO "
                "klienta, ktorým bol refresh token vyrobený – token platí len "
                "pre pár, ktorý ho vydal. Keď vznikol v OAuth Playgrounde, "
                "patria sem údaje toho web klienta, nie desktopového.")
    if reason == "invalid_scope":
        return (f"Rozsah práv {SCOPE} nie je pre tento OAuth projekt povolený "
                "– skontroluj, či je v projekte zapnuté Google Drive API a či "
                "je ten rozsah na OAuth consent screene medzi „Scopes“.")
    return (f"Obnova access tokenu z {source} zlyhala: {reason} {detail} "
            "(HTTP {status}). Nový token: "
            "`python3 workers/drive/auth.py --login`.").replace("{status}", str(status))


def _flatten(data, source):
    """JSON z Google Console má údaje pod `installed`/`web` – rozbaľ ich."""
    if not isinstance(data, dict):
        raise AuthError(f"{source} nie je JSON objekt s {', '.join(KEYS)}.")
    out = dict(data)
    for key in ("installed", "web"):
        if isinstance(data.get(key), dict):
            out = {**data[key], **{k: v for k, v in data.items() if k != key}}
    return out


def parse_creds(raw, source):
    """Text secretu → dict. Berie JSON aj riadky `kľúč=hodnota`.

    Riadky preto, že secret sa dá vyplniť aj z telefónu, kde token nevzniká
    cez `--login`, ale sa prepisuje z OAuth Playgroundu – a skladať pritom na
    mobilnej klávesnici JSON je robota, v ktorej sa spraví preklep.

    Oddeľovač smie byť `=` alebo `:`, prázdne riadky a `#` sa preskočia.
    """
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            return _flatten(json.loads(raw), source)
        except ValueError as exc:
            raise AuthError(
                f"{source} vyzerá ako JSON, ale nie je platný ({exc}). Skús "
                "namiesto neho tri riadky `client_id=…`, `client_secret=…`, "
                "`refresh_token=…` – to sa píše bez zátvoriek.") from None
    out = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # delí sa na prvom oddeľovači: v tokene sa `=` aj `:` môžu vyskytovať
        cut = min((line.find(c) for c in "=:" if c in line), default=-1)
        if cut <= 0:
            raise AuthError(
                f"{source}: riadok {line[:24]!r}… nemá tvar `kľúč=hodnota`. "
                f"Čakám {', '.join(KEYS)} – každé na vlastnom riadku.")
        key = line[:cut].strip().lower().replace("-", "_")
        out[key] = line[cut + 1:].strip().strip('"').strip("'").rstrip(",")
    return out


def from_env(env=None):
    """Prihlasovacie údaje z prostredia, alebo None, keď v ňom nie sú.

    Čiastočné údaje sú chyba, nie „tak teda verejne": kto nastavil polovicu,
    čaká prihlásený beh.
    """
    env = os.environ if env is None else env
    raw = (env.get("GDRIVE_CREDENTIALS") or "").strip()
    path = (env.get("GDRIVE_CREDENTIALS_FILE") or "").strip()
    data, source = None, None
    # čo chýba, sa pomenuje tak, ako to treba doplniť v Settings → Secrets
    as_named = None
    if raw:
        source = "secret GDRIVE_CREDENTIALS"
        data = parse_creds(raw, source)
    elif path:
        source = f"súbor {path} (GDRIVE_CREDENTIALS_FILE)"
        if not os.path.exists(path):
            raise AuthError(f"{source} neexistuje.")
        with open(path) as f:
            data = _flatten(json.load(f), source)
    else:
        # hľadá sa úplná trojica; nekompletná sa zapamätá len na to, aby sa
        # dalo povedať, čo v nej chýba
        partial = None
        for names in TRIOS:
            vals = {k: (env.get(n) or "").strip() for k, n in zip(KEYS, names)}
            named = dict(zip(KEYS, names))
            label = "secrets " + " / ".join(names)
            if all(vals.values()):
                source, data, as_named = label, vals, named
                break
            if any(vals.values()) and partial is None:
                partial = (label, vals, named)
        else:
            if partial:
                source, data, as_named = partial
    if data is None:
        return None
    missing = [(as_named or {}).get(k, k) for k in KEYS if not data.get(k)]
    if missing:
        extra = ""
        if missing == ["DRIVE_REFRESH"] or missing == ["refresh_token"]:
            # najčastejší stav: `client_id`/`client_secret` sú identita
            # aplikácie, nie povolenie k dátam – refresh token vzniká jedine
            # prihlásením vlastníka v prehliadači
            extra = (" Refresh token je to, čo z klienta robí prihlásenie: "
                     "client_id a client_secret sú len identita aplikácie. "
                     "Vyrobí sa `python3 workers/drive/auth.py --login`, "
                     "alebo z telefónu cez Google OAuth Playground (postup "
                     "v hlavičke workers/drive/auth.py).")
        raise AuthError(
            f"{source} nemá {', '.join(missing)}. Prihlásenie s polovicou "
            "údajov nefunguje a verejný odkaz použiť nemôžem – to by bol tichý "
            f"návrat k dennému limitu.{extra}")
    return Credentials(data["client_id"], data["client_secret"],
                       data["refresh_token"], source)


# kto som a čo vidím

def client_from_env(env=None):
    """Len `client_id` a `client_secret` – to, čo je známe pred tokenom.

    `from_env()` sa použiť nedá: ten žiada úplnú trojicu, kým tu sa refresh
    token práve vyrába.
    """
    env = os.environ if env is None else env
    raw = (env.get("GDRIVE_CREDENTIALS") or "").strip()
    pair, source = ("", ""), "prostredie"
    if raw:
        data = parse_creds(raw, "secret GDRIVE_CREDENTIALS")
        pair = (data.get("client_id", ""), data.get("client_secret", ""))
        source = "secret GDRIVE_CREDENTIALS"
    else:
        for names in TRIOS:
            got = ((env.get(names[0]) or "").strip(),
                   (env.get(names[1]) or "").strip())
            if any(got):
                pair, source = got, f"secrets {names[0]} / {names[1]}"
            if all(got):
                break
    if not all(pair):
        raise AuthError(
            f"Chýba client_id alebo client_secret ({source}). Vlož client_id "
            f"do repository variable {TRIOS[1][0]} (nie secret – nie je to "
            f"tajné) a client_secret do secretu {TRIOS[1][1]} – vyrobia sa "
            "v Google Cloud Console → Credentials → OAuth client ID.")
    return pair[0], pair[1], source


def code_from(text):
    """Kód z toho, čo sa dá skopírovať z prehliadača.

    Berie aj celú adresu, na ktorej prehliadač skončil – v telefóne z nej
    ostane len adresný riadok. Prilepený `#` a medzery sa odstrihnú.
    """
    text = (text or "").strip().strip("<>\"'")
    if "code=" in text:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(text).query
                                  or text.split("?", 1)[-1])
        got = (q.get("code") or [""])[0]
        if got:
            return got
        raise AuthError(f"V tom, čo si vložil, je `code=`, ale prázdne. "
                        f"Skopíruj celú adresu, na ktorej prehliadač skončil.")
    if text.startswith("http"):
        raise AuthError(
            "V tej adrese nie je `code=`. Keď je v nej `error=access_denied`, "
            "prihlásenie si zamietol; keď `error=admin_policy_enforced`, účet "
            "nie je v tej istej organizácii ako OAuth appka.")
    if not text or " " in text:
        raise AuthError("Nedostal som kód. Vlož celú adresu, na ktorej "
                        "prehliadač po potvrdení skončil (je v nej `?code=…`).")
    return text


def exchange_to_file(code, redirect_uri, out, env=None):
    """Kód → refresh token do súboru, nie na výstup.

    Do súboru zámerne: v public repozitári vidí log behu ktokoľvek.

    Token sa uloží skôr, než sa čokoľvek overuje – kód od Googlu je
    jednorazový a kým sa ukladal až po `whoami`, stačilo nezapnuté Drive API
    a hotový platný token sa zahodil aj s kódom.
    """
    client_id, client_secret, source = client_from_env(env)
    data = exchange(client_id, client_secret, code_from(code), redirect_uri)
    with open(out, "w") as f:
        f.write(data["refresh_token"])
    os.chmod(out, 0o600)
    creds = Credentials(client_id, client_secret, data["refresh_token"], source)
    try:
        return creds, whoami(creds)
    except AuthError as exc:
        # token je uložený a platný, nefunguje len otázka „kto som" – nech to
        # volajúci dokončí a padne až na overení
        print(f"::warning::Token je vyrobený a uložený, ale overenie účtu "
              f"neprešlo: {exc}")
        return creds, {}


def whoami(creds):
    """Účet, ktorým sme prihlásení. Vyplní aj `creds.email`."""
    data = api_get(creds, "/drive/v3/about?fields=user(displayName,emailAddress),"
                          "storageQuota(limit,usage)")
    user = data.get("user") or {}
    creds.email = user.get("emailAddress")
    return user


FILE_FIELDS = ("id,name,size,mimeType,ownedByMe,owners(emailAddress),"
               "capabilities(canDownload)")


def file_info(creds, file_id):
    """Metadáta jedného súboru – hlavne či ho prihlásený účet vlastní.

    Na cudzí zdieľaný súbor sa vzťahuje ten istý denný limit ako na verejný
    prístup, takže prihlásenie by nič neriešilo.
    """
    return api_get(creds, f"/drive/v3/files/{file_id}"
                          f"?fields={FILE_FIELDS}&supportsAllDrives=true")


def describe(creds):
    """Krátky popis režimu do logu – jedna veta, ktorá platí aj bez tokenu."""
    if creds is None:
        return ("verejný odkaz (neprihlásený) – platí denný limit sťahovania "
                "na súbor, zdieľaný so všetkými klientmi")
    return f"prihlásený ako {creds.email or 'vlastník (účet nezistený)'}"


# jednorazové prihlásenie

def scope_of(name):
    """Meno rozsahu z formulára → adresa rozsahu. Jedna odpoveď na jednom mieste."""
    if name in ("citanie", "read", SCOPE_READ):
        return SCOPE_READ
    if name in ("", "zapis", "write", SCOPE_WRITE):
        return SCOPE_WRITE
    raise AuthError(f"Neznámy rozsah „{name}“ – čakám `zapis` (číta aj "
                    f"ukladá cache) alebo `citanie` (len číta).")


def auth_url(client_id, redirect_uri, scope=SCOPE):
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        # `offline` + `consent` vyrobia refresh token; bez `consent` ho Google
        # pri druhom prihlásení toho istého účtu už nepošle
        "access_type": "offline",
        "prompt": "consent",
    })


def exchange(client_id, client_secret, code, redirect_uri):
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    status, data = request_json("POST", TOKEN_HOST, TOKEN_PATH, body)
    if status != 200 or not data.get("refresh_token"):
        if status == 200:
            raise AuthError(
                "Google poslal access token, ale nie refresh token. Odvolaj "
                "prístup appky v https://myaccount.google.com/permissions "
                "a spusti `--login` znova.")
        raise AuthError(token_error(status, data, "prihlásenie"))
    return data


def wait_for_code(port):
    """Loopback server, ktorý zachytí `?code=…` z presmerovania.

    Google zrušil „out of band" tok, takže presmerovanie musí prísť na
    `http://127.0.0.1:<port>` – na runneri to nemá čo robiť.
    """
    import http.server

    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            body = ("<h2>Hotovo</h2><p>Prihlásenie prebehlo. Vráť sa do "
                    "terminálu – JSON s tokenom je tam.</p>"
                    if got.get("code") else
                    f"<h2>Nepodarilo sa</h2><p>{got.get('error', 'chýba code')}"
                    "</p>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with http.server.HTTPServer(("127.0.0.1", port), Handler) as httpd:
        httpd.timeout = 300
        while not got:
            httpd.handle_request()
    if not got.get("code"):
        raise AuthError(f"Prihlásenie neprešlo: {got.get('error', 'bez kódu')}")
    return got["code"]


def do_login(args):
    client_id = args.client_id or os.environ.get("GDRIVE_CLIENT_ID", "")
    client_secret = args.client_secret or os.environ.get("GDRIVE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise AuthError(
            "Chýba --client-id / --client-secret. Vyrobia sa v Google Cloud "
            "Console → Credentials → OAuth client ID, typ „Desktop app“ "
            "(rozpis je v hlavičke tohto súboru).")

    port = args.port or 8731
    redirect_uri = f"http://127.0.0.1:{port}"
    scope = scope_of(args.scope)
    url = auth_url(client_id, redirect_uri, scope)
    print(f"Rozsah práv: {scope}"
          + ("  (číta DMR 5.0 aj ukladá cache)" if scope == SCOPE_WRITE
             else "  (LEN ČÍTANIE – cache na Drive sa pod ním neuloží)"))
    print("Otvor v prehliadači (prihlás sa účtom, ktorý DMR 5.0 vlastní):\n")
    print("  " + url + "\n")
    print("Neoverenú appku preklikáš cez „Advanced → Go to … (unsafe)“.\n")
    if args.manual:
        print("Po potvrdení skončíš na adrese, ktorá sa nedá otvoriť "
              f"({redirect_uri}/?code=…).\nSkopíruj z nej celú adresu alebo "
              "len kód a vlož sem:")
        raw = input("code: ").strip()
        code = raw
        if "code=" in raw:
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(raw).query)
            code = (q.get("code") or [""])[0]
        if not code:
            raise AuthError("Nedostal som kód.")
    else:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:                           # noqa: BLE001
            pass
        print(f"Čakám na presmerovanie na {redirect_uri} … (Ctrl-C zruší; "
              "bez prehliadača na tomto stroji použi --manual)")
        code = wait_for_code(port)

    data = exchange(client_id, client_secret, code, redirect_uri)
    creds = Credentials(client_id, client_secret, data["refresh_token"],
                        "prihlásenie")
    user = whoami(creds)
    print(f"\nPrihlásený ako {user.get('emailAddress')} "
          f"({user.get('displayName')}).")
    print("\nVlož TOTO ako secret GDRIVE_CREDENTIALS "
          "(Settings → Secrets and variables → Actions):\n")
    print(json.dumps({"client_id": client_id, "client_secret": client_secret,
                      "refresh_token": data["refresh_token"]}, indent=1))
    print("\nPotom to over behom `Dáta · DMR 5.0` v režime „len sonda“ – "
          "krok „Prihlásenie na Drive“ vypíše, ktorým účtom beh číta.")
    return 0


# CLI

def do_check(args):
    creds = from_env()
    if creds is None:
        print("::warning::Bez prihlásenia – DMR 5.0 sa číta verejným odkazom, "
              "na ktorý platí denný limit sťahovania zdieľaný so všetkými "
              "klientmi. Nastav secret GDRIVE_CREDENTIALS (rozpis: "
              "workers/drive/auth.py --login).")
        print(f"Režim čítania z Drive: {describe(None)}")
        return 0
    user = whoami(creds)
    print(f"Režim čítania z Drive: {describe(creds)}")
    print(f"  účet   {user.get('emailAddress')} ({user.get('displayName')})")
    print(f"  údaje  z {creds.source}")
    # rozsah patrí do každého „kto som": readonly token vyzerá rovnako ako
    # plný, kým sa niečo nemá uložiť
    write = can_write(creds)
    print("  rozsah " + {True: "číta aj zapisuje (cache na Drive funguje)",
                         False: "LEN ČÍTANIE – cache na Drive sa neuloží",
                         None: "nedá sa zistiť (tokeninfo neodpovedalo)"}[write])
    if write is False:
        print(f"::warning::{scope_hint()}")
    bad = 0
    for file_id in args.file or []:
        try:
            info = file_info(creds, file_id)
        except AuthError as exc:
            print(f"::error::Súbor {file_id}: {exc}")
            bad += 1
            continue
        size = int(info.get("size") or 0)
        owned = bool(info.get("ownedByMe"))
        owner = ", ".join(o.get("emailAddress", "?")
                          for o in info.get("owners") or []) or "neznámy"
        print(f"  {info.get('name', file_id)}: {size / 2**30:.2f} GiB, "
              f"vlastník {owner}"
              + (" – tento účet ✓" if owned else " – NIE tento účet"))
        if not info.get("capabilities", {}).get("canDownload", True):
            print(f"::error::Na {info.get('name', file_id)} tento účet nemá "
                  "právo sťahovať.")
            bad += 1
        elif not owned:
            # zdieľaný cudzí súbor má ten istý denný limit ako verejný odkaz
            print("::warning::Ten súbor tento účet nevlastní, len naň vidí. "
                  "Denný limit sťahovania sa tým neposunie – prihlás sa účtom "
                  "vlastníka, alebo si nahraj vlastnú kópiu do priečinka "
                  "z `FOLDER_ID` vo workers/drive/dmr5.py.")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", action="store_true",
                    help="jednorazové prihlásenie; vypíše JSON do secretu")
    ap.add_argument("--manual", action="store_true",
                    help="pri --login: kód vložíš ručne (stroj bez prehliadača)")
    ap.add_argument("--client-id", default="")
    ap.add_argument("--client-secret", default="")
    ap.add_argument("--scope", default="zapis", choices=("zapis", "citanie"),
                    help="`zapis` (predvolené) číta DMR 5.0 aj ukladá cache "
                         "na Drive; `citanie` je starý readonly rozsah")
    ap.add_argument("--port", type=int, default=0,
                    help="port loopbacku pri --login (predvolene 8731)")
    ap.add_argument("--auth-url", action="store_true",
                    help="vypíš odkaz na prihlásenie (client_id z prostredia)")
    ap.add_argument("--exchange", action="store_true",
                    help="kód z prehliadača → refresh token do --out")
    ap.add_argument("--code", default="",
                    help="pri --exchange: kód, alebo celá adresa s `?code=…`")
    ap.add_argument("--redirect-uri", default="",
                    help="musí byť rovnaké ako pri --auth-url "
                         "(predvolene http://127.0.0.1:8731)")
    ap.add_argument("--out", default="",
                    help="pri --exchange: súbor pre refresh token")
    ap.add_argument("--check", action="store_true",
                    help="povedz, ktorým účtom sa číta (a či naň vidí)")
    ap.add_argument("--file", action="append", metavar="ID",
                    help="Drive file id na overenie; dá sa opakovať")
    ap.add_argument("--print-token", action="store_true",
                    help="vypíš access token (len lokálne, do curlu)")
    args = ap.parse_args()

    redirect_uri = args.redirect_uri or f"http://127.0.0.1:{args.port or 8731}"
    try:
        if args.auth_url:
            client_id, _secret, source = client_from_env()
            print(f"client_id z {source}", file=sys.stderr)
            print(auth_url(client_id, redirect_uri, scope_of(args.scope)))
            return 0
        if args.exchange:
            if not args.out:
                print("::error::--exchange potrebuje --out: token sa nevypisuje "
                      "na výstup, aby neskončil v logu behu.")
                return 2
            creds, user = exchange_to_file(args.code, redirect_uri, args.out)
            print(f"Prihlásené ako {user.get('emailAddress')} "
                  f"({user.get('displayName')}).")
            print(f"Refresh token je v {args.out} – nikde inde a nevypisuje sa.")
            return 0
        if args.login:
            return do_login(args)
        if args.print_token:
            # v Actions by token skončil v logu, ktorý vidí každý
            if os.environ.get("GITHUB_ACTIONS") == "true":
                print("::error::--print-token je len na lokálne ladenie; "
                      "v Actions by token ostal v logu.")
                return 2
            creds = from_env()
            if creds is None:
                print("::error::V prostredí nie sú prihlasovacie údaje.")
                return 2
            print(creds.token())
            return 0
        return do_check(args)
    except AuthError as exc:
        print(f"::error::{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
