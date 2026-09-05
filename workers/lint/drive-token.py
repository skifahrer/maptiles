#!/usr/bin/env python3
"""Kontrola: token vlastníka Drive sa dostane všade, kde sa z Drive číta.

Z Drive sa číta na štyroch miestach a leží na ňom aj cache buildu. Keď token
na jedno miesto nepríde, nič nespadne – len sa číta verejným odkazom s denným
limitom alebo sa cache nenájde a build počíta hodiny odznova.

Kontroluje sa z oboch strán: či volajúci podáva `secrets: inherit` a či to
volaný deklaruje (`workflow_call` nededí nič sám). `DRIVE_CLIENT` medzi
secrets nie je – `client_id` nie je tajný údaj, je to repository variable.
"""
import glob, re, sys, yaml

# prihlásenie sa dá podať v jednom secrete alebo po kusoch; nekompletná
# skupina sa nesmie brať ako „veď tam niečo je" – drive-auth.py na polovici
# údajov spadne až v tom trojhodinovom behu
BLOB = "GDRIVE_CREDENTIALS"
GROUPS = (("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET",
           "GDRIVE_REFRESH_TOKEN"),
          ("DRIVE_SECRET", "DRIVE_REFRESH"))

def authed(names):
    """Dá sa z týchto premenných prihlásiť?"""
    return (BLOB in names
            or any(all(k in names for k in g) for g in GROUPS))

def why_not(names):
    for g in GROUPS:
        have = [k for k in g if k in names]
        if have:
            return (f"z {'/'.join(g)} tam je len "
                    f"{', '.join(have)} – prihlásenie s polovicou "
                    f"údajov `drive-auth.py` odmieta")
    return f"chýba {BLOB} alebo {'/'.join(GROUPS[1])}"

# volanie sa hľadá na začiatku riadku v `run:`: tie isté mená spomínajú ako
# dáta aj iné kontroly. Interpret je nepovinný (`run: workers/dem/check.sh`),
# pred cestou smú stáť len shellové kľúčové slová a operátory.
CMD = re.compile(r"^\s*(?:(?:if|elif|then|else|do|!|&&|\|\|)\s+)*"
                 r"(?:\w+=\$\()?(?:(?:python3?|bash|sh)\s+)?"
                 r"(?:\./)?[\w./-]*"
                 r"(?:dmr5-drive|slope-chunks|contours-build"
                 r"|terrain-build|check-dem|fetch-dem"
                 r"|drive-folder|drive-cache|drive-store"
                 r"|publish-map|publish-results)"
                 r"\.(?:py|sh)\b", re.M)
# cache leží na Drive, takže každý krok s ňou sa musí vedieť prihlásiť
CACHE = "./.github/actions/cache-"
# workflowy, ktoré samy z Drive čítajú – volajúci im prihlásenie musí podať
CALLED = ("./.github/workflows/dmr5-drive" + ".yml",
          "./.github/workflows/update-dem" + ".yml",
          "./.github/workflows/shading-rocks" + ".yml")
bad = 0

for path in sorted(glob.glob(".github/workflows/*.yml")):
    d = yaml.safe_load(open(path)) or {}
    top = d.get("env") or {}
    for name, job in (d.get("jobs") or {}).items():
        job = job or {}
        # volaný si secret vyzdvihne sám, ale volajúci mu ho musí podať
        if job.get("uses") in CALLED:
            called = job["uses"].rsplit("/", 1)[1]
            sec = job.get("secrets")
            if not (sec == "inherit"
                    or (isinstance(sec, dict) and authed(sec))):
                print(f"::error file={path}::job '{name}' volá "
                      f"{called} bez `secrets: inherit`, takže "
                      f"doplnenie by z Drive čítalo verejným odkazom "
                      f"s denným limitom.")
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
            print(f"::error file={path}::krok "
                  f"'{step.get('name', '?')}' v jobe '{name}' "
                  + ("pracuje s cache na Drive" if cache else
                     "číta z Drive")
                  + f", ale prihlásiť sa z toho nedá: "
                  f"{why_not(names)}. "
                  + ("Cache by sa nenašla ani neuložila a build by "
                     "počítal všetko odznova"
                     if cache else
                     "Bežal by na verejnom dennom limite")
                  + " – doplň to do `env:` toho kroku, jobu alebo "
                    "celého workflowu.")
            bad += 1

# a druhá strana: volaný workflow to musí prijať
for called in CALLED:
    d = yaml.safe_load(open(called[2:]))
    on = d[[k for k in d if k is True or k == "on"][0]]
    decl = (on.get("workflow_call") or {}).get("secrets") or {}
    if not authed(decl):
        print(f"::error file={called[2:]}::`workflow_call` "
              f"nedeklaruje prihlásenie na Drive ({why_not(decl)}), "
              f"takže mu ho volajúci nemá ako podať.")
        bad += 1
print(f"prihlásenie na Drive: {bad} chýb")
sys.exit(1 if bad else 0)
