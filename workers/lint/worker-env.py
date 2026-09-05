#!/usr/bin/env python3
"""Kontrola: skript vo `workers/` dostáva env, ktoré naozaj číta.

Keď sa veľký `run:` blok stiahne do skriptu, stane sa jedno z dvoch:
`${{ výraz }}` sa zmení na `$PREMENNÚ` a tá sa zabudne dopísať do `env:`
(skript beží s prázdnym reťazcom a nespadne), alebo sa premenuje `id` kroku,
na ktorý sa odkazujú výstupy jobu (job ticho vráti prázdno).

Čo si skript nastaví sám a `${VAR:-default}` sa neráta. Sourcovaný
`workers/*.sh` sa prečíta tiež.
"""
import glob, os, re, sys, yaml

# Dáva ich GitHub alebo shell sám; `GH_TOKEN` a spol. číta nástroj
# pod skriptom, takže sa v jeho texte nemusia objaviť.
BUILTIN = {
    "GITHUB_OUTPUT", "GITHUB_ENV", "GITHUB_PATH", "GITHUB_STEP_SUMMARY",
    "GITHUB_WORKSPACE", "GITHUB_REPOSITORY", "GITHUB_REF", "GITHUB_SHA",
    "GITHUB_RUN_ID", "GITHUB_RUN_NUMBER", "GITHUB_SERVER_URL",
    "GITHUB_ACTOR", "GITHUB_EVENT_NAME", "GITHUB_TOKEN", "RUNNER_OS",
    "RUNNER_TEMP", "AGENT_TOOLSDIRECTORY", "HOME", "PATH", "PWD",
    "TMPDIR", "USER", "SHELL", "IFS", "RANDOM", "LINENO", "OSTYPE",
    "GH_TOKEN", "GDAL_CACHEMAX", "PROJ_NETWORK", "PYTHONUNBUFFERED",
    "GDRIVE_CREDENTIALS", "DRIVE_CLIENT", "DRIVE_SECRET", "DRIVE_REFRESH",
}

def bez_komentarov(s):
    return "\n".join(l for l in s.split("\n") if not re.match(r"^\s*#", l))

def bez_apostrofov(s):
    """`'…'` preč – bash v nich nič nerozvíja, takže `$r` z jq programu
    (`jq --arg r … '.[$r].name'`) nie je premenná prostredia."""
    out, i, in_d = [], 0, False
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(s[i:i + 2]); i += 2; continue
        if c == '"':
            in_d = not in_d
        if c == "'" and not in_d:
            j = s.find("'", i + 1)
            if j < 0:
                break
            i = j + 1; continue
        out.append(c); i += 1
    return "".join(out)

def nastavene(s):
    """Čo si skript nastaví sám (vrátane `local a b c` a `mapfile`)."""
    s = bez_komentarov(s)
    out = set(re.findall(
        r"(?:^|[;&|(]|\bexport\s+|\blocal\s+|\bdeclare\s+-\w+\s+)"
        r"\s*([A-Za-z_][A-Za-z0-9_]*)=", s, re.M))
    out |= set(re.findall(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b", s))
    out |= set(re.findall(
        r"\b(?:mapfile|readarray)\s+(?:-\w+\s+)*([A-Za-z_][A-Za-z0-9_]*)", s))
    for m in re.findall(r"\bread\b([^\n]*)$", s, re.M):
        out |= set(re.findall(r"(?<!-)\b([A-Za-z_][A-Za-z0-9_]*)\b(?!=)", m))
    for m in re.findall(r"^\s*(?:local|declare|typeset)\s+(.+)$", s, re.M):
        for tok in m.split():
            out.add(re.split(r"=", tok)[0])
    # `source workers/x.sh` – ten súbor vieme prečítať, tak sa doňho pozrieme.
    # Bez toho by kontrola hlásila premennú, ktorú nastavuje sourcovaný skript
    # (`PM_Z` z `pmtiles-budget.sh`), ako chýbajúcu z prostredia.
    for cesta in re.findall(r"^\s*(?:source|\.)\s+(workers/[\w./-]+\.sh)",
                            s, re.M):
        if os.path.exists(cesta):
            out |= nastavene(open(cesta).read())
    # Čokoľvek iné sourcované sa staticky zistiť nedá.
    if re.search(r"^\s*(?:source|\.)\s+(?!workers/[\w./-]+\.sh\s*$)\S",
                 s, re.M):
        out.add("__SOURCED__")
    return {v for v in out if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v)}

def citane(s):
    """Čo skript číta a musí mu to niekto dať. `${VAR:-x}` sa neráta –
    na ten prípad má predvolenú hodnotu."""
    s = bez_apostrofov(bez_komentarov(s))
    volitelne = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?[-=+])", s))
    out = set(re.findall(r"\$\{#?([A-Za-z_][A-Za-z0-9_]*)", s))
    out |= set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", s))
    # vnorený node/python si prostredie číta po svojom
    out |= set(re.findall(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)", s))
    out |= set(re.findall(r"environ(?:\.get\(|\[)[\"']([A-Za-z_][A-Za-z0-9_]*)", s))
    return out - volitelne

# Otvárací token výrazu workflowu. Kým táto kontrola bývala heredocom
# v `lint-workflows.yml`, musel sa SKLADAŤ – doslova napísaný by z toho YAMLu
# spravil presne tú chybu, ktorú hľadá, a actionlint by sa naň zhodil. Odkedy
# je to samostatný `.py`, tá pasca neplatí (kontrola `Zátvorky výrazov` čítá
# len `run:` bloky), ale skladanie tu ostáva: hľadá sa v `workers/*.sh` a tam
# je to ten istý druh chyby.
OPEN = "$" + "{" * 2

bad = 0
for path in sorted(glob.glob(".github/workflows/*.yml")):
    wf = yaml.safe_load(open(path)) or {}
    for job_name, job in (wf.get("jobs") or {}).items():
        for st in job.get("steps") or []:
            run = (st.get("run") or "").strip()
            m = re.fullmatch(r"(?:bash\s+|sh\s+)?(workers/[\w./-]+\.sh)", run)
            if not m:
                continue
            skript = m.group(1)
            if not os.path.exists(skript):
                print(f"::error file={path}::{job_name} / "
                      f"{st.get('name')}: {skript} neexistuje")
                bad += 1
                continue
            text = open(skript).read()
            if OPEN in text:
                print(f"::error file={skript}::ostal v ňom výraz "
                      f"workflowu ({OPEN} …) – v shelli sa "
                      f"nevyhodnotí, skončí ako holý text")
                bad += 1
            dane = (set(wf.get("env") or {}) | set(job.get("env") or {})
                    | set(st.get("env") or {}) | nastavene(text) | BUILTIN)
            chyba = sorted(v for v in citane(text)
                           if v not in dane and not v.isdigit()
                           and not ("__SOURCED__" in dane and v.islower()))
            if chyba:
                print(f"::error file={path}::{job_name} / "
                      f"{st.get('name')} → {skript}: skript číta "
                      f"{chyba} z prostredia, ale krok mu to nedáva. "
                      f"Doplň to do `env:` kroku – inak beží "
                      f"s prázdnym reťazcom a nespadne.")
                bad += 1

    # `steps.<id>.outputs` musí mať svoj krok
    for job_name, job in (wf.get("jobs") or {}).items():
        ids = {s["id"] for s in (job.get("steps") or []) if s.get("id")}
        blob = yaml.dump(job, allow_unicode=True)
        for ref in sorted(set(re.findall(
                r"steps\.([A-Za-z0-9_-]+)\.outputs", blob))):
            if ref not in ids:
                print(f"::error file={path}::job '{job_name}' sa "
                      f"odkazuje na steps.{ref}.outputs, ale taký krok "
                      f"v ňom nie je (má: {sorted(ids)}). Premenovaný "
                      f"krok = ticho prázdny výstup jobu.")
                bad += 1
print(f"skripty vo workers a ich env: {bad} chýb")
sys.exit(1 if bad else 0)
