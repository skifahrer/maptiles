#!/usr/bin/env python3
"""Sign in to Google Drive as the data owner – "who am I and what token do I have".

A public link has a daily per-file download limit shared by everyone; the
signed-in owner has a much higher cap. Which mode a run used is always printed.

Set up once: enable the Drive API in the Google Cloud Console, put the OAuth
consent screen **In production** ("Testing" refresh tokens last 7 days), make a
Desktop app OAuth client ID and run `--login` on a computer with a browser. The
JSON goes into the `GDRIVE_CREDENTIALS` secret. Without a computer,
`.github/workflows/drive-login.yml` does it – the phone is the browser.

The build cache writes to Drive, so `drive.readonly` isn't enough; a scope is
baked into a token at sign-in and can't be added later.

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
    """workers/*.py can't be imported normally; `sys.modules` keeps it to one run."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# the connection to Google (proxy, own CA) lives in `serve.py`
drive = load("drive_serve", "serve.py")

# API calls are in `api.py`; the names are re-exported so other workers see them here
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

# `drive.file` sees only files the app made – neither DMR 5.0 nor a browser-made cache folder
SCOPE_READ = "https://www.googleapis.com/auth/drive.readonly"
SCOPE_WRITE = "https://www.googleapis.com/auth/drive"
# the wider one by default: a token without writing looks the same until the cache stops saving
SCOPE = SCOPE_WRITE

# tokeninfo tells the scopes the token really got
TOKENINFO_PATH = "/tokeninfo?access_token="

# an access token lasts an hour, reading blocks takes two
RENEW_BEFORE_S = 300

KEYS = ("client_id", "client_secret", "refresh_token")

# the same trio under two names; `client_secret` isn't shown by Google twice
TRIOS = (
    ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN"),
    ("DRIVE_CLIENT", "DRIVE_SECRET", "DRIVE_REFRESH"),
)


class Credentials:
    """The owner's refresh token + an access token renewing itself."""
    # renewal is here: reading runs in tens of threads for hours

    def __init__(self, client_id, client_secret, refresh_token, source="?"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.source = source
        self.email = None            # filled by `whoami()`
        self._token = None
        self._until = 0.0
        self._lock = threading.Lock()

    # safe to print to a log
    def __repr__(self):
        return f"<Credentials {self.email or 'unknown account'} from {self.source}>"

    def token(self):
        """A valid access token; renewed when running out."""
        with self._lock:
            if not self._token or time.time() > self._until - RENEW_BEFORE_S:
                self._fetch()
            return self._token

    def renew(self, stale):
        """Replace a token that got 401 – once, not once per thread."""
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
    """A message for a failed token renewal – with what to do about it."""
    reason = str(data.get("error") or f"HTTP {status}")
    detail = data.get("error_description") or ""
    if reason == "invalid_grant":
        return (f"Drive refused the refresh token from {source} ({detail}). "
                "Most often the OAuth consent screen's publishing status is "
                "\"Testing\", where a token lasts only 7 days. Switch it to "
                "\"In production\", make a new token with "
                "`python3 workers/drive/auth.py --login` and overwrite the "
                "GDRIVE_CREDENTIALS secret. It looks the same after a password "
                "change or revoked access.")
    if reason == "invalid_client":
        return (f"Drive doesn't know the OAuth client from {source} ({detail}). "
                "`client_id` and `client_secret` must be from THE SAME client "
                "the refresh token was made with – a token is valid only for "
                "the pair that issued it. Made in the OAuth Playground, it "
                "needs that web client's details, not the desktop one's.")
    if reason == "invalid_scope":
        return (f"The {SCOPE} scope isn't allowed for this OAuth project – "
                "check that the Google Drive API is enabled in the project and "
                "the scope is among \"Scopes\" on the OAuth consent screen.")
    return (f"Renewing the access token from {source} failed: {reason} {detail} "
            "(HTTP {status}). A new token: "
            "`python3 workers/drive/auth.py --login`.").replace("{status}", str(status))


def _flatten(data, source):
    """Google Console JSON keeps details under `installed`/`web` – unpack them."""
    if not isinstance(data, dict):
        raise AuthError(f"{source} isn't a JSON object with {', '.join(KEYS)}.")
    out = dict(data)
    for key in ("installed", "web"):
        if isinstance(data.get(key), dict):
            out = {**data[key], **{k: v for k, v in data.items() if k != key}}
    return out


def parse_creds(raw, source):
    """Secret text → dict; JSON or `key=value` lines (easier on a phone keyboard)."""
    # the separator may be `=` or `:`, blank lines and `#` are skipped
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            return _flatten(json.loads(raw), source)
        except ValueError as exc:
            raise AuthError(
                f"{source} looks like JSON but isn't valid ({exc}). Try three "
                "lines `client_id=…`, `client_secret=…`, `refresh_token=…` "
                "instead – no brackets needed.") from None
    out = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # split on the first separator: a token may contain `=` and `:`
        cut = min((line.find(c) for c in "=:" if c in line), default=-1)
        if cut <= 0:
            raise AuthError(
                f"{source}: line {line[:24]!r}… isn't `key=value`. "
                f"Expecting {', '.join(KEYS)} – each on its own line.")
        key = line[:cut].strip().lower().replace("-", "_")
        out[key] = line[cut + 1:].strip().strip('"').strip("'").rstrip(",")
    return out


def from_env(env=None):
    """Sign-in details from the environment, or None when there are none."""
    # partial details are an error: who set half expects a signed-in run
    env = os.environ if env is None else env
    raw = (env.get("GDRIVE_CREDENTIALS") or "").strip()
    path = (env.get("GDRIVE_CREDENTIALS_FILE") or "").strip()
    data, source = None, None
    # what is missing is named as it must be filled in Settings → Secrets
    as_named = None
    if raw:
        source = "secret GDRIVE_CREDENTIALS"
        data = parse_creds(raw, source)
    elif path:
        source = f"file {path} (GDRIVE_CREDENTIALS_FILE)"
        if not os.path.exists(path):
            raise AuthError(f"{source} doesn't exist.")
        with open(path) as f:
            data = _flatten(json.load(f), source)
    else:
        # a whole trio is sought; a partial one is kept only to say what is missing
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
            # the commonest: client_id/secret identify the app; only the owner's sign-in makes a token
            extra = (" The refresh token is what makes a client a sign-in: "
                     "client_id and client_secret only identify the app. It "
                     "is made by `python3 workers/drive/auth.py --login`, or "
                     "from a phone with the Google OAuth Playground (steps "
                     "in the header of workers/drive/auth.py).")
        raise AuthError(
            f"{source} lacks {', '.join(missing)}. Signing in with half the "
            "details doesn't work and I can't use the public link – that "
            f"would be a silent return to the daily limit.{extra}")
    return Credentials(data["client_id"], data["client_secret"],
                       data["refresh_token"], source)


def client_from_env(env=None):
    """Only `client_id` and `client_secret` – what is known before a token exists."""
    env = os.environ if env is None else env
    raw = (env.get("GDRIVE_CREDENTIALS") or "").strip()
    pair, source = ("", ""), "environment"
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
            f"client_id or client_secret is missing ({source}). Put client_id "
            f"into the repository variable {TRIOS[1][0]} (not a secret – it "
            f"isn't secret) and client_secret into the secret {TRIOS[1][1]} – "
            "made in Google Cloud Console → Credentials → OAuth client ID.")
    return pair[0], pair[1], source


def code_from(text):
    """The code from what can be copied from a browser, a whole address too."""
    text = (text or "").strip().strip("<>\"'")
    if "code=" in text:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(text).query
                                  or text.split("?", 1)[-1])
        got = (q.get("code") or [""])[0]
        if got:
            return got
        raise AuthError("What you pasted has `code=`, but empty. Copy the whole "
                        "address the browser ended on.")
    if text.startswith("http"):
        raise AuthError(
            "That address has no `code=`. With `error=access_denied` you "
            "declined the sign-in; with `error=admin_policy_enforced` the "
            "account isn't in the same organisation as the OAuth app.")
    if not text or " " in text:
        raise AuthError("I got no code. Paste the whole address the browser "
                        "ended on after confirming (it has `?code=…`).")
    return text


def exchange_to_file(code, redirect_uri, out, env=None):
    """Code → refresh token into a file, not the output (a public repo's log is public)."""
    # saved before any check: Google's code is one-off and a failed check would lose it
    client_id, client_secret, source = client_from_env(env)
    data = exchange(client_id, client_secret, code_from(code), redirect_uri)
    with open(out, "w") as f:
        f.write(data["refresh_token"])
    os.chmod(out, 0o600)
    creds = Credentials(client_id, client_secret, data["refresh_token"], source)
    try:
        return creds, whoami(creds)
    except AuthError as exc:
        # the token is saved and valid, only "who am I" fails – let the check fail later
        print(f"::warning::The token is made and saved, but the account check "
              f"didn't pass: {exc}")
        return creds, {}


def whoami(creds):
    """The account we are signed in with. Fills `creds.email` too."""
    data = api_get(creds, "/drive/v3/about?fields=user(displayName,emailAddress),"
                          "storageQuota(limit,usage)")
    user = data.get("user") or {}
    creds.email = user.get("emailAddress")
    return user


FILE_FIELDS = ("id,name,size,mimeType,ownedByMe,owners(emailAddress),"
               "capabilities(canDownload)")


def file_info(creds, file_id):
    """One file's metadata – mainly whether the signed-in account owns it."""
    # someone else's shared file has the public daily limit, signing in wouldn't help
    return api_get(creds, f"/drive/v3/files/{file_id}"
                          f"?fields={FILE_FIELDS}&supportsAllDrives=true")


def describe(creds):
    """A short description of the mode for the log – one sentence, token or not."""
    if creds is None:
        return ("public link (not signed in) – a daily per-file download "
                "limit applies, shared with all clients")
    return f"signed in as {creds.email or 'the owner (account unknown)'}"


def scope_of(name):
    """A form scope name → the scope address. One answer in one place."""
    if name in ("read", "citanie", SCOPE_READ):
        return SCOPE_READ
    if name in ("", "write", "zapis", SCOPE_WRITE):
        return SCOPE_WRITE
    raise AuthError(f"Unknown scope \"{name}\" – expecting `write` (reads and "
                    f"saves the cache) or `read` (reads only).")


def auth_url(client_id, redirect_uri, scope=SCOPE):
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        # `offline` + `consent` make a refresh token; without `consent` a second sign-in gets none
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
                "Google sent an access token but no refresh token. Revoke the "
                "app's access at https://myaccount.google.com/permissions "
                "and run `--login` again.")
        raise AuthError(token_error(status, data, "sign-in"))
    return data


def wait_for_code(port):
    """A loopback server catching `?code=…` from the redirect (no out-of-band flow)."""
    import http.server

    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            body = ("<h2>Done</h2><p>Signed in. Go back to the terminal – the "
                    "JSON with the token is there.</p>"
                    if got.get("code") else
                    f"<h2>It didn't work</h2><p>{got.get('error', 'no code')}"
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
        raise AuthError(f"Sign-in didn't pass: {got.get('error', 'no code')}")
    return got["code"]


def do_login(args):
    client_id = args.client_id or os.environ.get("GDRIVE_CLIENT_ID", "")
    client_secret = args.client_secret or os.environ.get("GDRIVE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise AuthError(
            "--client-id / --client-secret is missing. They are made in Google "
            "Cloud Console → Credentials → OAuth client ID, type \"Desktop app\" "
            "(steps in this file's header).")

    port = args.port or 8731
    redirect_uri = f"http://127.0.0.1:{port}"
    scope = scope_of(args.scope)
    url = auth_url(client_id, redirect_uri, scope)
    print(f"Scope: {scope}"
          + ("  (reads DMR 5.0 and saves the cache)" if scope == SCOPE_WRITE
             else "  (READ ONLY – the Drive cache won't save under it)"))
    print("Open in a browser (sign in with the account owning DMR 5.0):\n")
    print("  " + url + "\n")
    print("Click through an unverified app with \"Advanced → Go to … (unsafe)\".\n")
    if args.manual:
        print("After confirming you end on an address that won't open "
              f"({redirect_uri}/?code=…).\nCopy the whole address or just the "
              "code and paste it here:")
        raw = input("code: ").strip()
        code = raw
        if "code=" in raw:
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(raw).query)
            code = (q.get("code") or [""])[0]
        if not code:
            raise AuthError("I got no code.")
    else:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:                           # noqa: BLE001
            pass
        print(f"Waiting for the redirect to {redirect_uri} … (Ctrl-C cancels; "
              "without a browser on this machine use --manual)")
        code = wait_for_code(port)

    data = exchange(client_id, client_secret, code, redirect_uri)
    creds = Credentials(client_id, client_secret, data["refresh_token"],
                        "sign-in")
    user = whoami(creds)
    print(f"\nSigned in as {user.get('emailAddress')} "
          f"({user.get('displayName')}).")
    print("\nPut THIS into the secret GDRIVE_CREDENTIALS "
          "(Settings → Secrets and variables → Actions):\n")
    print(json.dumps({"client_id": client_id, "client_secret": client_secret,
                      "refresh_token": data["refresh_token"]}, indent=1))
    print("\nThen check it with a `Data · DMR 5.0` run in \"probe only\" mode – "
          "the step \"Drive sign-in\" prints which account the run reads with.")
    return 0


def do_check(args):
    creds = from_env()
    if creds is None:
        print("::warning::Not signed in – DMR 5.0 is read through the public "
              "link, with a daily download limit shared by all clients. Set "
              "the GDRIVE_CREDENTIALS secret (steps: "
              "workers/drive/auth.py --login).")
        print(f"Drive read mode: {describe(None)}")
        return 0
    user = whoami(creds)
    print(f"Drive read mode: {describe(creds)}")
    print(f"  account {user.get('emailAddress')} ({user.get('displayName')})")
    print(f"  details from {creds.source}")
    # the scope belongs to every "who am I": readonly looks the same until something saves
    write = can_write(creds)
    print("  scope   " + {True: "reads and writes (the Drive cache works)",
                          False: "READ ONLY – the Drive cache won't save",
                          None: "can't be told (tokeninfo didn't answer)"}[write])
    if write is False:
        print(f"::warning::{scope_hint()}")
    bad = 0
    for file_id in args.file or []:
        try:
            info = file_info(creds, file_id)
        except AuthError as exc:
            print(f"::error::File {file_id}: {exc}")
            bad += 1
            continue
        size = int(info.get("size") or 0)
        owned = bool(info.get("ownedByMe"))
        owner = ", ".join(o.get("emailAddress", "?")
                          for o in info.get("owners") or []) or "unknown"
        print(f"  {info.get('name', file_id)}: {size / 2**30:.2f} GiB, "
              f"owner {owner}"
              + (" – this account ✓" if owned else " – NOT this account"))
        if not info.get("capabilities", {}).get("canDownload", True):
            print(f"::error::This account may not download "
                  f"{info.get('name', file_id)}.")
            bad += 1
        elif not owned:
            # someone else's shared file has the public link's daily limit
            print("::warning::This account doesn't own the file, only sees it. "
                  "The daily download limit doesn't move – sign in as the "
                  "owner, or upload your own copy into the folder of "
                  "`FOLDER_ID` in workers/drive/dmr5.py.")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", action="store_true",
                    help="a one-off sign-in; prints the JSON for the secret")
    ap.add_argument("--manual", action="store_true",
                    help="with --login: paste the code by hand (a machine without a browser)")
    ap.add_argument("--client-id", default="")
    ap.add_argument("--client-secret", default="")
    ap.add_argument("--scope", default="write",
                    choices=("write", "read", "zapis", "citanie"),
                    help="`write` (default) reads DMR 5.0 and saves the Drive "
                         "cache; `read` is the old readonly scope")
    ap.add_argument("--port", type=int, default=0,
                    help="the loopback port with --login (default 8731)")
    ap.add_argument("--auth-url", action="store_true",
                    help="print the sign-in link (client_id from the environment)")
    ap.add_argument("--exchange", action="store_true",
                    help="a code from the browser → refresh token into --out")
    ap.add_argument("--code", default="",
                    help="with --exchange: the code, or the whole address with `?code=…`")
    ap.add_argument("--redirect-uri", default="",
                    help="must equal the one with --auth-url "
                         "(default http://127.0.0.1:8731)")
    ap.add_argument("--out", default="",
                    help="with --exchange: the file for the refresh token")
    ap.add_argument("--check", action="store_true",
                    help="say which account reads (and whether it sees the files)")
    ap.add_argument("--file", action="append", metavar="ID",
                    help="a Drive file id to check; repeatable")
    ap.add_argument("--print-token", action="store_true",
                    help="print the access token (local only, for curl)")
    args = ap.parse_args()

    redirect_uri = args.redirect_uri or f"http://127.0.0.1:{args.port or 8731}"
    try:
        if args.auth_url:
            client_id, _secret, source = client_from_env()
            print(f"client_id from {source}", file=sys.stderr)
            print(auth_url(client_id, redirect_uri, scope_of(args.scope)))
            return 0
        if args.exchange:
            if not args.out:
                print("::error::--exchange needs --out: the token isn't printed, "
                      "so it doesn't end in the run's log.")
                return 2
            creds, user = exchange_to_file(args.code, redirect_uri, args.out)
            print(f"Signed in as {user.get('emailAddress')} "
                  f"({user.get('displayName')}).")
            print(f"The refresh token is in {args.out} – nowhere else, never printed.")
            return 0
        if args.login:
            return do_login(args)
        if args.print_token:
            # in Actions the token would end in a log anyone sees
            if os.environ.get("GITHUB_ACTIONS") == "true":
                print("::error::--print-token is for local debugging only; "
                      "in Actions the token would stay in the log.")
                return 2
            creds = from_env()
            if creds is None:
                print("::error::No sign-in details in the environment.")
                return 2
            print(creds.token())
            return 0
        return do_check(args)
    except AuthError as exc:
        print(f"::error::{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
