#!/usr/bin/env python3
"""The Drive owner's token reaches every place that reads from Drive.

When the token misses one place nothing fails – it just reads through a public
link with a daily quota, or the cache isn't found and the build recomputes for
hours. Checked from both sides: the caller passes `secrets: inherit` and the
callee declares it. `DRIVE_CLIENT` is a repository variable, not a secret.
"""
import glob, re, sys, yaml

# sign-in comes as one secret or in parts; a partial group fails only hours into a run
BLOB = "GDRIVE_CREDENTIALS"
GROUPS = (("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET",
           "GDRIVE_REFRESH_TOKEN"),
          ("DRIVE_SECRET", "DRIVE_REFRESH"))

def authed(names):
    """Can these variables sign in?"""
    return (BLOB in names
            or any(all(k in names for k in g) for g in GROUPS))

def why_not(names):
    for g in GROUPS:
        have = [k for k in g if k in names]
        if have:
            return (f"of {'/'.join(g)} only {', '.join(have)} is there – "
                    f"`drive-auth.py` refuses half a sign-in")
    return f"{BLOB} or {'/'.join(GROUPS[1])} is missing"

# a call at a `run:` line start (other lints name the same files as data)
CMD = re.compile(r"^\s*(?:(?:if|elif|then|else|do|!|&&|\|\|)\s+)*"
                 r"(?:\w+=\$\()?(?:(?:python3?|bash|sh)\s+)?"
                 r"(?:\./)?[\w./-]*"
                 r"(?:dmr5-drive|slope-chunks|contours-build"
                 r"|terrain-build|check-dem|fetch-dem"
                 r"|drive-folder|drive-cache|drive-store"
                 r"|publish-map|publish-results)"
                 r"\.(?:py|sh)\b", re.M)
# the cache lives on Drive, so every step using it must sign in
CACHE = "./.github/actions/cache-"
# workflows that read Drive themselves – callers must pass them the sign-in
CALLED = ("./.github/workflows/dmr5-drive" + ".yml",
          "./.github/workflows/update-dem" + ".yml",
          "./.github/workflows/shading-rocks" + ".yml")
bad = 0

for path in sorted(glob.glob(".github/workflows/*.yml")):
    d = yaml.safe_load(open(path)) or {}
    top = d.get("env") or {}
    for name, job in (d.get("jobs") or {}).items():
        job = job or {}
        # the callee picks the secret up, but the caller must pass it
        if job.get("uses") in CALLED:
            called = job["uses"].rsplit("/", 1)[1]
            sec = job.get("secrets")
            if not (sec == "inherit"
                    or (isinstance(sec, dict) and authed(sec))):
                print(f"::error file={path}::job '{name}' calls "
                      f"{called} without `secrets: inherit`, so the "
                      f"refill would read Drive through a public link "
                      f"with a daily quota.")
                bad += 1
            continue
        jenv = job.get("env") or {}
        for step in job.get("steps") or []:
            step = step or {}
            cache = str(step.get("uses") or "").startswith(CACHE)
            if not cache and not CMD.search(str(step.get("run") or "")):
                continue
            names = set(top) | set(jenv) | set(step.get("env") or {})
            if authed(names):
                continue
            print(f"::error file={path}::step "
                  f"'{step.get('name', '?')}' in job '{name}' "
                  + ("uses the Drive cache" if cache else
                     "reads from Drive")
                  + f", but can't sign in: "
                  f"{why_not(names)}. "
                  + ("The cache would be neither found nor saved and the "
                     "build would recompute everything"
                     if cache else
                     "It would run on the public daily quota")
                  + " – add it to the `env:` of that step, job or the "
                    "whole workflow.")
            bad += 1

# and the other side: the called workflow must accept it
for called in CALLED:
    d = yaml.safe_load(open(called[2:]))
    on = d[[k for k in d if k is True or k == "on"][0]]
    decl = (on.get("workflow_call") or {}).get("secrets") or {}
    if not authed(decl):
        print(f"::error file={called[2:]}::`workflow_call` "
              f"declares no Drive sign-in ({why_not(decl)}), "
              f"so callers have no way to pass it.")
        bad += 1
print(f"Drive sign-in: {bad} errors")
sys.exit(1 if bad else 0)
