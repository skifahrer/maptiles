#!/usr/bin/env python3
"""
Upratovanie GitHubu: behy, ktoré nie sú záznamom o ničom – a všetky releasy
aj artefakty, lebo do GitHubu sa už nepublikuje nič.

PREČO TO NEJDE INAK: behy a vetvy nie sú súbory v repozitári, takže sa
nedajú zmazať pull requestom ani z lokálu – token mimo Actions na to nemá
právo (`Resource not accessible by integration`, HTTP 403). Vnútri behu ho
ale `GITHUB_TOKEN` má, keď mu workflow dá `actions: write` (behy) a
`contents: write` (vetvy). Preto je to workflow, ktorý sa spustí ručne.

ČO SA POVAŽUJE ZA SMETI:

1. **Behy zrušených workflowov.** Keď sa súbor workflowu zmaže, jeho behy
   ostanú a s nimi aj položka v ľavom zozname Actions – navždy. Zmizne až
   vtedy, keď má nula behov. Sem patria sondy `zz-*`, ktorými sa hľadalo,
   prečo GitHub odmietal `build-map-region.yml`, aj staršie zrušené workflowy.

2. **Behy odmietnutých súborov.** Keď je súbor workflowu neplatný (napr. nad
   stropom 128 KiB), GitHub to neohlási ako chybu – pri pushi vyrobí beh
   BEZ JOBOV, pomenovaný cestou k súboru. Vyzerá to, že sa workflow spustil
   sám po mergi, hoci má len `workflow_dispatch`. Spoznať sa dajú presne
   podľa toho mena: `.github/workflows/nieco.yml` namiesto `name:` z obsahu.

3. (voliteľne) **Vetvy `claude/*`, ktoré sú celé v hlavnej vetve.** Teda tie,
   ktorých práca je zmergovaná a nemajú oproti nej ani jeden vlastný commit.

4. **VŠETKY RELEASY, ICH TAGY A VŠETKY ARTEFAKTY.** Pipeline si do releasov
   odkladala výškové modely, skaly a tieňovanie a do artefaktov medzivýsledky
   na pozretie; oboje sa presťahovalo na Google Drive
   (`workers/drive/store.py`). Tie staré tam teda ostávajú ako niekoľko
   gigabajtov, ktoré nikto nečíta, a ako pozvánka pomýliť si ich s vydaním
   softvéru. Nič sa tým nestratí: čo je potrebné, je v sklade na Drive.

   Mazať to musí workflow. Release ani artefakt nie je súbor v repozitári,
   takže sa nedá zmazať pull requestom, a token mimo Actions na to nemá právo.
   Vnútri behu áno – `contents: write` na releasy a tagy, `actions: write` na
   artefakty.

Beží ako `workers/tools/cleanup-actions.py`; čo robiť, hovorí prostredie:
    MODE=behy | behy_a_vetvy | releasy_a_artefakty | vsetko   (default: behy)
    DRY_RUN=true | false                                      (default: false)
Očakáva `gh` a GITHUB_REPOSITORY / GITHUB_RUN_ID od runnera.
"""
import json
import os
import subprocess
import sys

REPO = os.environ["GITHUB_REPOSITORY"]
MODE = os.environ.get("MODE", "behy")
DRY = os.environ.get("DRY_RUN", "false").lower() == "true"
SELF_RUN = os.environ.get("GITHUB_RUN_ID", "")
SUMMARY = os.environ.get("GITHUB_STEP_SUMMARY", "")


def gh(path, method=None):
    """Jedno volanie API. Vráti rozparsovaný JSON, alebo None pri chybe."""
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json"]
    if method:
        cmd += ["-X", method]
    cmd.append(path)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        # Chyba jedného volania nemá zhodiť celé upratovanie – vypíše sa
        # a ide sa ďalej. Pri mazaní je 404 dokonca v poriadku (už je preč).
        print(f"::warning::{method or 'GET'} {path}: {p.stderr.strip()[:160]}")
        return None
    return json.loads(p.stdout) if p.stdout.strip() else {}


def pages(path, key, cap=20):
    """Postránkovo stiahne zoznam; `cap` je poistka proti nekonečnu."""
    out, page = [], 1
    sep = "&" if "?" in path else "?"
    while page <= cap:
        d = gh(f"{path}{sep}per_page=100&page={page}")
        if not d:
            break
        items = d[key] if isinstance(d, dict) else d
        out += items
        if len(items) < 100:
            break
        page += 1
    return out


def uprac_releasy():
    """Všetky releasy, ich assety aj tagy. Vracia (koľko, koľko bajtov).

    Assety sa nemažú zvlášť: zmazanie releasu ich vezme s sebou. Tag ÁNO –
    ten release po sebe nechá, a osamotený tag `dem-sonny` na verejnom
    repozitári vyzerá presne ako vydanie, ktorým nikdy nebol.
    """
    rels = pages(f"/repos/{REPO}/releases", None)
    bajty = sum(a.get("size", 0) for r in rels for a in (r.get("assets") or []))
    print(f"\nReleasov: {len(rels)}, v nich {human(bajty)} assetov")
    for r in rels:
        n = len(r.get("assets") or [])
        vel = human(sum(a.get("size", 0) for a in (r.get("assets") or [])))
        print(f"  {r['tag_name']:<16} {n:>4} assetov  {vel:>10}  {r['name']}")
    if DRY:
        return len(rels), bajty
    zmazane = 0
    for r in rels:
        if gh(f"/repos/{REPO}/releases/{r['id']}", method="DELETE") is None:
            print(f"::warning::release {r['tag_name']} sa nepodarilo zmazať")
            continue
        zmazane += 1
        # 404 je tu v poriadku: tag nemusel existovať (draft release ho nemá).
        gh(f"/repos/{REPO}/git/refs/tags/{r['tag_name']}", method="DELETE")
        print(f"  zmazané: release aj tag {r['tag_name']}")
    print(f"Zmazaných releasov: {zmazane} z {len(rels)}")
    return zmazane, bajty


def uprac_artefakty():
    """Všetky artefakty všetkých behov. Vracia (koľko, koľko bajtov).

    Aj tie, ktorým ešte nevypršala retencia. Krátkodobé artefakty (`site-*`,
    `steps-*`) sú prepravky jedného behu – po ňom už nie sú na nič, a keď je
    beh dávno hotový, je to len miesto.
    """
    arts = pages(f"/repos/{REPO}/actions/artifacts", "artifacts")
    # Ten svoj beh si nepodrežeme: `site-*` si joby podávajú práve teraz.
    mine = [a for a in arts
            if str((a.get("workflow_run") or {}).get("id", "")) == SELF_RUN]
    arts = [a for a in arts if a not in mine]
    bajty = sum(a.get("size_in_bytes", 0) for a in arts)
    print(f"\nArtefaktov: {len(arts)}, {human(bajty)}"
          + (f" (+{len(mine)} z tohto behu nechávam)" if mine else ""))
    podla_mena = {}
    for a in arts:
        m = podla_mena.setdefault(a["name"], [0, 0])
        m[0] += 1
        m[1] += a.get("size_in_bytes", 0)
    for name, (n, vel) in sorted(podla_mena.items()):
        print(f"  {name:<52} {n:>4}×  {human(vel):>10}")
    if DRY:
        return len(arts), bajty
    zmazane = 0
    for a in arts:
        if gh(f"/repos/{REPO}/actions/artifacts/{a['id']}",
              method="DELETE") is not None:
            zmazane += 1
    print(f"Zmazaných artefaktov: {zmazane} z {len(arts)}")
    return zmazane, bajty


def human(n):
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# Čo sa v ktorom režime robí. Rozpísané, a nie „obsahuje reťazec", nech sa
# preklep v `MODE` neprejaví ako beh, ktorý nič neupratal a zazelenal.
ROBIT = {
    "behy": ("behy",),
    "behy_a_vetvy": ("behy", "vetvy"),
    "releasy_a_artefakty": ("releasy", "artefakty"),
    "vsetko": ("behy", "vetvy", "releasy", "artefakty"),
}


def main():
    if MODE not in ROBIT:
        print(f"::error::Režim „{MODE}“ nepoznám. Sú to: "
              f"{', '.join(ROBIT)}.")
        return 1
    robim = ROBIT[MODE]
    print(f"Repozitár: {REPO}   režim: {MODE} ({', '.join(robim)})   "
          f"{'LEN VÝPIS (nič sa nemaže)' if DRY else 'ostro'}")

    zrusene, smeti, zmazane, vetvy = {}, [], 0, []
    rel_n = rel_b = art_n = art_b = 0

    if "releasy" in robim:
        rel_n, rel_b = uprac_releasy()
    if "artefakty" in robim:
        art_n, art_b = uprac_artefakty()
    if "behy" not in robim:
        return _suhrn(zrusene, smeti, zmazane, vetvy, rel_n, rel_b, art_n, art_b)

    # ---------- ktoré workflowy ešte majú svoj súbor ----------
    workflows = pages(f"/repos/{REPO}/actions/workflows", "workflows")
    zive, zrusene = {}, {}
    for w in workflows:
        # `dynamic/pages/...` je GitHubov vlastný workflow pre Pages, ten
        # súbor v repe nemá a mazať ho nesmieme.
        if not w["path"].startswith(".github/workflows/"):
            continue
        (zive if os.path.exists(w["path"]) else zrusene)[w["id"]] = w["path"]
    print(f"\nWorkflowy: {len(zive)} so súborom, {len(zrusene)} zrušených")
    for path in sorted(zrusene.values()):
        print(f"  zrušený: {path}")

    # ---------- čo zmazať ----------
    smeti = []   # (id, dôvod, popis)
    for wid, path in zrusene.items():
        for r in pages(f"/repos/{REPO}/actions/workflows/{wid}/runs", "workflow_runs"):
            smeti.append((r["id"], "zrušený workflow", f"{path} #{r['run_number']}"))

    for wid, path in zive.items():
        for r in pages(f"/repos/{REPO}/actions/workflows/{wid}/runs", "workflow_runs"):
            # Meno = cesta k súboru → GitHub ten súbor neprečítal, čiže beh
            # bez jobov. Behy so skutočným menom sú normálna história.
            if r["name"].startswith(".github/workflows/"):
                smeti.append((r["id"], "odmietnutý súbor", f"{path} #{r['run_number']}"))

    # Rozbehnutý beh sa mazať nedá a ten svoj by sme si podrezali sami.
    smeti = [s for s in smeti if str(s[0]) != SELF_RUN]

    print(f"\nBehov na zmazanie: {len(smeti)}")
    for _, dovod, popis in sorted(smeti, key=lambda s: s[2]):
        print(f"  [{dovod}] {popis}")

    zmazane = 0
    if not DRY:
        for rid, _, popis in smeti:
            if gh(f"/repos/{REPO}/actions/runs/{rid}", method="DELETE") is not None:
                zmazane += 1
            else:
                print(f"::warning::beh {popis} sa nepodarilo zmazať")
        print(f"\nZmazaných behov: {zmazane} z {len(smeti)}")

    # ---------- vetvy ----------
    if "vetvy" in robim:
        base = (gh(f"/repos/{REPO}") or {}).get("default_branch", "master")
        for b in pages(f"/repos/{REPO}/branches", None):
            name = b["name"]
            if name == base or not name.startswith("claude/"):
                continue
            cmp_ = gh(f"/repos/{REPO}/compare/{base}...{name}")
            if not cmp_:
                continue
            # `behind` = vetva nemá oproti hlavnej ani jeden vlastný commit,
            # `identical` = je to presne tá istá špička. Oboje je zmergované
            # alebo prázdne; `ahead` a `diverged` sa nechávajú na pokoji.
            if cmp_.get("status") in ("behind", "identical"):
                vetvy.append((name, cmp_["status"]))
            else:
                print(f"  nechávam vetvu {name} ({cmp_.get('status')}, "
                      f"vlastných commitov: {cmp_.get('ahead_by')})")

        print(f"\nVetiev na zmazanie: {len(vetvy)}")
        for name, st in vetvy:
            print(f"  {name} ({st})")
        if not DRY:
            for name, _ in vetvy:
                gh(f"/repos/{REPO}/git/refs/heads/{name}", method="DELETE")

    return _suhrn(zrusene, smeti, zmazane, vetvy, rel_n, rel_b, art_n, art_b)


def _suhrn(zrusene, smeti, zmazane, vetvy, rel_n, rel_b, art_n, art_b):
    """Súhrn do `GITHUB_STEP_SUMMARY`. Vlastná funkcia, lebo režim
    `releasy_a_artefakty` končí skôr a súhrn má vypísať aj tak."""
    if not SUMMARY:
        return 0
    with open(SUMMARY, "a") as f:
        f.write("## Upratovanie GitHubu\n\n")
        f.write("Len výpis, nič sa nemazalo.\n\n" if DRY else "")
        f.write("| čo | koľko |\n|---|--:|\n")
        if "behy" in ROBIT[MODE]:
            f.write(f"| zrušené workflowy (ostali po nich behy) | {len(zrusene)} |\n")
            f.write(f"| behy na zmazanie | {len(smeti)} |\n")
            if not DRY:
                f.write(f"| **skutočne zmazaných behov** | **{zmazane}** |\n")
        if "vetvy" in ROBIT[MODE]:
            f.write(f"| zlúčené vetvy `claude/*` | {len(vetvy)} |\n")
        if "releasy" in ROBIT[MODE]:
            f.write(f"| {'releasy na zmazanie' if DRY else 'zmazané releasy'} "
                    f"(aj s tagmi) | {rel_n} |\n")
            f.write(f"| assety v nich | {human(rel_b)} |\n")
        if "artefakty" in ROBIT[MODE]:
            f.write(f"| {'artefakty na zmazanie' if DRY else 'zmazané artefakty'} "
                    f"| {art_n} |\n")
            f.write(f"| ich veľkosť | {human(art_b)} |\n")
        if smeti:
            f.write("\n<details><summary>Zoznam behov</summary>\n\n")
            for _, dovod, popis in sorted(smeti, key=lambda s: s[2]):
                f.write(f"- `{popis}` – {dovod}\n")
            f.write("\n</details>\n")
        if "behy" in ROBIT[MODE]:
            f.write("\nPoložka workflowu zmizne z ľavého zoznamu Actions až "
                    "vtedy, keď nemá ani jeden beh – preto sa mažú všetky.\n")
        if "releasy" in ROBIT[MODE]:
            f.write("\nDo releasov ani artefaktov sa už nepublikuje nič – "
                    "všetko ide do skladu na Google Drive "
                    "(`workers/drive/store.py`). Nič sa teda nestratilo.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
