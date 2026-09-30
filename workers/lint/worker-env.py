#!/usr/bin/env python3
"""A script in `workers/` gets the env it really reads.

When a big `run:` block moves into a script, either a `${{ expression }}` turns
into `$VARIABLE` that's never added to `env:` (the script runs with an empty
string and doesn't fail), or a step `id` the job outputs point at is renamed
(the job quietly returns nothing). What the script sets itself and
`${VAR:-default}` don't count; a sourced `workers/*.sh` is read too.
"""
import glob, os, re, sys, yaml

# given by GitHub or the shell; `GH_TOKEN` and co. are read by tools under the script
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

def no_comments(s):
    return "\n".join(l for l in s.split("\n") if not re.match(r"^\s*#", l))

def no_single_quotes(s):
    """Drop `'…'` – bash expands nothing there, so a jq `$r` isn't an env variable."""
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

def assigned(s):
    """What a script sets itself (`local a b c` and `mapfile` included)."""
    s = no_comments(s)
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
    # `source workers/x.sh` is readable, so its assignments count too
    for path in re.findall(r"^\s*(?:source|\.)\s+(workers/[\w./-]+\.sh)",
                            s, re.M):
        if os.path.exists(path):
            out |= assigned(open(path).read())
    # anything else sourced can't be known statically
    if re.search(r"^\s*(?:source|\.)\s+(?!workers/[\w./-]+\.sh\s*$)\S",
                 s, re.M):
        out.add("__SOURCED__")
    return {v for v in out if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v)}

def read_vars(s):
    """What a script reads and someone must give it; `${VAR:-x}` has a default."""
    s = no_single_quotes(no_comments(s))
    optional = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?[-=+])", s))
    out = set(re.findall(r"\$\{#?([A-Za-z_][A-Za-z0-9_]*)", s))
    out |= set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", s))
    # embedded node/python read the environment their own way
    out |= set(re.findall(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)", s))
    out |= set(re.findall(r"environ(?:\.get\(|\[)[\"']([A-Za-z_][A-Za-z0-9_]*)", s))
    return out - optional

# a workflow expression's opening token, assembled so this file never contains it
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
            script = m.group(1)
            if not os.path.exists(script):
                print(f"::error file={path}::{job_name} / "
                      f"{st.get('name')}: {script} doesn't exist")
                bad += 1
                continue
            text = open(script).read()
            if OPEN in text:
                print(f"::error file={script}::a workflow expression "
                      f"({OPEN} …) is left in it – the shell doesn't "
                      f"evaluate it, it ends up as plain text")
                bad += 1
            given = (set(wf.get("env") or {}) | set(job.get("env") or {})
                    | set(st.get("env") or {}) | assigned(text) | BUILTIN)
            missing = sorted(v for v in read_vars(text)
                           if v not in given and not v.isdigit()
                           and not ("__SOURCED__" in given and v.islower()))
            if missing:
                print(f"::error file={path}::{job_name} / "
                      f"{st.get('name')} → {script}: the script reads "
                      f"{missing} from the environment, but the step doesn't "
                      f"give it. Add it to the step's `env:` – otherwise it "
                      f"runs with an empty string and doesn't fail.")
                bad += 1

    # `steps.<id>.outputs` must have its step
    for job_name, job in (wf.get("jobs") or {}).items():
        ids = {s["id"] for s in (job.get("steps") or []) if s.get("id")}
        blob = yaml.dump(job, allow_unicode=True)
        for ref in sorted(set(re.findall(
                r"steps\.([A-Za-z0-9_-]+)\.outputs", blob))):
            if ref not in ids:
                print(f"::error file={path}::job '{job_name}' "
                      f"refers to steps.{ref}.outputs, but has no such "
                      f"step (it has: {sorted(ids)}). A renamed step = a "
                      f"quietly empty job output.")
                bad += 1
print(f"workers scripts and their env: {bad} errors")
sys.exit(1 if bad else 0)
