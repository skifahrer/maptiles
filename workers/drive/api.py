#!/usr/bin/env python3
"""Drive API: one call, one translation of a refusal.

Everything that talks to the Google API: requests with retries, errors turned
into a sentence with advice, `files.delete` and the token-scope question. It
knows nothing of `Credentials` (`creds` is a parameter), so no circular import.
Used as a module: `api = load("drive_api", "api.py")`.
"""
import json
import os
import time
import urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    """workers/*.py can't be imported normally because of the dash in the name."""
    import importlib.util
    import sys
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# the connection to Google (proxy, own CA) lives in `serve.py`, one place for it
drive = load("drive_serve", "serve.py")

TOKEN_HOST = "oauth2.googleapis.com"
API_HOST = "www.googleapis.com"

# the build cache writes and deletes on Drive, so `drive`; `drive.file` sees only
# files the app made itself – neither DMR 5.0 nor a cache folder made in a browser
SCOPE_READ = "https://www.googleapis.com/auth/drive.readonly"
SCOPE_WRITE = "https://www.googleapis.com/auth/drive"

# tokeninfo tells the scopes the token REALLY got, before Drive refuses a write
TOKENINFO_PATH = "/tokeninfo?access_token="

# the same trio under two names (see `auth.py`); refusal messages say where to fill it
TRIOS = (
    ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN"),
    ("DRIVE_CLIENT", "DRIVE_SECRET", "DRIVE_REFRESH"),
)


class AuthError(RuntimeError):
    """A sign-in error whose text says what to do – print it as `::error::`."""


def request_json(method, host, path, body=None, headers=None, tries=4):
    """One JSON request to Google. Returns (status, dict)."""
    last = None
    for attempt in range(tries):
        conn = drive.connect(host, timeout=60)
        try:
            hdr = {"User-Agent": drive.UA, "Accept-Encoding": "identity",
                   **(headers or {})}
            if body is not None:
                # `setdefault`: a JSON caller chose its type, a form type gets a 400
                hdr.setdefault("Content-Type",
                               "application/x-www-form-urlencoded")
            conn.request(method, path, body=body, headers=hdr)
            resp = conn.getresponse()
            raw = resp.read()
            try:
                data = json.loads(raw or b"{}")
            except ValueError:
                data = {"_body": raw[:400].decode("utf-8", "replace")}
            if not isinstance(data, dict):
                data = {"_body": str(data)[:400]}
            return resp.status, data
        except Exception as exc:                    # noqa: BLE001
            last = exc
            time.sleep(min(1.5 ** attempt, 10))
        finally:
            try:
                conn.close()
            except Exception:                       # noqa: BLE001
                pass
    raise AuthError(f"{host}{path.split('?')[0]} didn't answer in {tries} "
                    f"tries ({last}). Check the network or proxy.")


def project_of(client_id):
    """The project number from a client_id (`<project>-<hash>.apps.googleusercontent.com`)."""
    head = (client_id or "").split("-", 1)[0]
    return head if head.isdigit() else ""


def api_hint(status, data, creds, path):
    """A message for a Drive API error – with what to do about it."""
    reason = api_reason(data) or f"HTTP {status}"
    err = data.get("error") if isinstance(data, dict) else None
    detail = str(err.get("message") or "") if isinstance(err, dict) else ""
    if reason == "accessNotConfigured":
        # NOT a token error: the project hasn't enabled the Drive API (run 31332232209)
        proj = project_of(creds.client_id)
        where = ("https://console.cloud.google.com/apis/library/"
                 "drive.googleapis.com" + (f"?project={proj}" if proj else ""))
        return (f"The Google Cloud project{f' (number {proj})' if proj else ''} "
                f"hasn't enabled the **Google Drive API**, so the token is valid "
                f"but the API won't serve it. Enable it here: {where} – then run "
                f"again." + (f" Google says: {detail}" if detail else ""))
    if reason in ("insufficientPermissions", "forbidden") and "scope" in detail.lower():
        return scope_hint(detail)
    return (f"The Drive API returned HTTP {status} for {path.split('?')[0]}: {reason}"
            + (f" – {detail}" if detail else ""))


def scope_hint(detail=""):
    """A message for "the token has no right to that"; a scope can't be added later."""
    return (f"The token lacks the {SCOPE_WRITE} scope"
            + (f" ({detail})" if detail else "")
            + ". A readonly token reads DMR 5.0 but can't save or thin the "
              "Drive cache. Make a new one: the workflow \"Maintenance · Drive "
              "sign-in\", or `python3 workers/drive/auth.py --login` (asks "
              "for writing by default) – and overwrite the same secret.")


def api_call(creds, method, path, body=None, ctype="application/json"):
    """One Drive API call with the token (reads and writes alike); errors become messages."""
    raw = body if body is None else (
        body if isinstance(body, bytes) else
        (body if isinstance(body, str) else json.dumps(body)).encode("utf-8"))
    head = {"Authorization": "Bearer " + creds.token()}
    if raw is not None:
        head["Content-Type"] = ctype
    status, data = request_json(method, API_HOST, path, raw, head)
    if status == 401:
        # the token may have expired just now – renew it once
        head["Authorization"] = "Bearer " + creds.renew(None)
        status, data = request_json(method, API_HOST, path, raw, head)
    if status not in (200, 204):
        raise AuthError(api_hint(status, data, creds, path))
    return data


def api_get(creds, path):
    """A GET on the Drive API with the token. Returns a dict; errors become messages."""
    return api_call(creds, "GET", path)


def api_delete(creds, file_id):
    """Delete a file on Drive; used to thin the cache."""
    return api_call(creds, "DELETE",
                    f"/drive/v3/files/{urllib.parse.quote(file_id)}"
                    "?supportsAllDrives=true")


def granted_scopes(creds):
    """The scopes the token REALLY got – before an hour of work ends in a 403."""
    status, data = request_json(
        "GET", TOKEN_HOST, TOKENINFO_PATH + urllib.parse.quote(creds.token()))
    if status != 200:
        raise AuthError(f"tokeninfo returned HTTP {status} "
                        f"({data.get('error_description') or data.get('error') or ''})")
    return (data.get("scope") or "").split()


def can_write(creds):
    """Can this token write to Drive? (None = can't be told.)"""
    try:
        return SCOPE_WRITE in granted_scopes(creds)
    except AuthError:
        return None


def api_reason(data):
    """The first `reason` of a Drive API error answer, or None."""
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        for e in err.get("errors") or []:
            if e.get("reason"):
                return e["reason"]
        return err.get("status") or err.get("message")
    if isinstance(err, str):                        # OAuth errors are `{"error": "…"}`
        return err
    return None
