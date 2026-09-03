#!/usr/bin/env python3
"""
Kto púšťa Planetiler, musí mať v jobe `actions/setup-java` – a tú istú verziu.

PREČO TO EXISTUJE. Planetiler je JAR preložený pre Javu 21 (class file 65)
a `ubuntu-latest` má predvolene 17 (61). Bez kroku `actions/setup-java` sa
`java -jar planetiler.jar` nespustí vôbec:

    UnsupportedClassVersionError: com/onthegomap/planetiler/Main has been
    compiled by a more recent version of the Java Runtime (class file version
    65.0), this version of the Java Runtime only recognizes class file
    versions up to 61.0

Ten krok je ale v YAMLe pri KAŽDOM jobe zvlášť (`setup-java` je akcia, tá sa
do bashu vo `workers/` stiahnuť nedá), takže je to päť kópií jednej vety – a
šiesty volajúci na ňu zabudol. Beh 31948543768: mapa sveta stiahla 100 MB
podkladov a padla až za nimi. V jobe `contours` by to bolo až za DEM, teda po
desiatkach minút. To je pravidlo 1 z CLAUDE.md v tej podobe, v akej sa proti
nemu nedá brániť inak než kontrolou: jedna odpoveď, ale zapísať sa musí na
šiestich miestach.

ČO SA KONTROLUJE:

  1. každý job, ktorý (aj cez `workers/*.sh`, ktoré si volá) púšťa Planetiler,
     má krok `actions/setup-java`,
  2. jeho `java-version` sa rovná `JAVA_MIN` vo `workers/lib/planetiler.sh` –
     tam je to číslo raz a odtiaľ ho číta aj kontrola v samotnom skripte,
  3. žiadny `setup-java` v repozitári si nedrží inú verziu (inak by sa joby
     rozišli ticho: jeden stavia na 21, druhý na 17),
  4. spustenie s orezom na región nemá `--bounds` a `--polygon` naraz.

ŠTVRTÁ JE ĎALŠIA TICHÁ. `Bounds` v Planetileri si `tileExtents` (to, čo
o dlaždici rozhoduje) spočíta už v konštruktore – teda z `--bounds` a s
prázdnym tvarom – a `setShape()` prepočet nespustí. Polygón je preto v logu
vidieť („argument: polygon=…"), Planetiler nepovie ani slovo a NEOREŽE NIČ.
Namerané na Monaku (maxzoom 15): bez orezu 27 dlaždíc, `--polygon` na polovicu
územia 17, `--polygon` **aj** `--bounds` zase 27. Mapa by potom v aplikácii
zase siahala za stiahnutý región – a jediné, čo by na to upozornilo, je toto.

Job, ktorý má `setup-java` a Planetiler nepúšťa, sa nehlási – Java môže raz
byť aj pod niečím iným. Chýbajúci krok je tvrdá chyba, prebytočný nie.

Spustiť sa dá aj lokálne:
    python3 workers/lint/planetiler.py
"""
import glob
import os
import re
import subprocess
import sys
import tempfile

import yaml

SCRIPT = "workers/lib/planetiler.sh"
JE_TO_PLANETILER = re.compile(r"planetiler\.jar|lib/planetiler\.sh")
# SPUSTENÝ skript, nie spomenutý. Cesta musí byť prvé slovo príkazu (nanajvýš
# za `bash`, `sh`, `source` alebo `.`) – inak by sa za volajúceho rátal aj job
# `lint`, ktorý si tie isté cesty len ČÍTA (krok „Vrstvy podávajú kľúč výrezu"
# grepuje `workers/contours-rocks/build.sh`, ale nepúšťa ho).
CESTA_SKRIPTU = re.compile(
    r"^\s*(?:(?:bash|sh|source|\.)\s+)?(workers/[\w./-]+\.sh)\b", re.M)


def bez_komentarov(s):
    """Riadok, ktorý sa začína `#`, nič nepúšťa – ani v bashi, ani v `run:`."""
    return "\n".join(l for l in s.split("\n") if not re.match(r"^\s*#", l))


def s_volanymi(text, videne=None):
    """Text kroku plus text každého `workers/*.sh`, ktorý sa v ňom spomína.

    Mapa sveta púšťa Planetiler cez `workers/world/build.sh`, ktorý si volá
    `workers/lib/planetiler.sh` – keby sa kontrola pozerala len na `run:`,
    práve ten job by jej ušiel. Ide sa do hĺbky, nie o úroveň nižšie."""
    videne = videne if videne is not None else set()
    out = [text]
    for cesta in CESTA_SKRIPTU.findall(bez_komentarov(text)):
        if cesta in videne or not os.path.exists(cesta):
            continue
        videne.add(cesta)
        with open(cesta, encoding="utf-8") as f:
            out.append(s_volanymi(f.read(), videne))
    return "\n".join(out)


bad = []

with open(SCRIPT, encoding="utf-8") as f:
    zdroj = f.read()
m = re.search(r'^JAVA_MIN="\$\{JAVA_MIN:-(\d+)\}"', zdroj, re.M)
if not m:
    print(f"::error file={SCRIPT}::nemá riadok `JAVA_MIN=\"${{JAVA_MIN:-<číslo>}}\"`. "
          f"Je to jediné miesto, kde je napísané, akú Javu Planetiler chce – "
          f"bez neho sa nedá overiť, či ju joby naozaj nastavujú.")
    sys.exit(1)
CHCE = m.group(1)
print(f"{SCRIPT}: Planetiler chce Javu {CHCE}")

for path in sorted(glob.glob(".github/workflows/*.yml")):
    with open(path, encoding="utf-8") as f:
        wf = yaml.safe_load(f) or {}
    for job_name, job in (wf.get("jobs") or {}).items():
        steps = job.get("steps") or []

        java = [s for s in steps
                if "actions/setup-java" in str(s.get("uses") or "")]
        for st in java:
            ver = str((st.get("with") or {}).get("java-version") or "")
            if ver != CHCE:
                bad.append(
                    f"{path}: job '{job_name}' nastavuje Javu {ver or '?'}, ale "
                    f"Planetiler chce {CHCE} (`JAVA_MIN` v {SCRIPT}). Dve verzie "
                    f"vedľa seba znamenajú, že jeden job stavia inak než ostatné.")

        pusta = any(JE_TO_PLANETILER.search(bez_komentarov(s_volanymi(
            str(s.get("run") or "")))) for s in steps)
        if pusta and not java:
            bad.append(
                f"{path}: job '{job_name}' púšťa Planetiler, ale nemá krok "
                f"`actions/setup-java`. Runner má Javu 17 a jar je preložený "
                f"pre {CHCE} – `java -jar` spadne na UnsupportedClassVersionError, "
                f"a to až po tom, čo job odpracoval všetko pred ním. Pridaj "
                f"`- uses: actions/setup-java@v5` s `distribution: temurin` a "
                f"`java-version: \"{CHCE}\"` (tak, ako to majú joby v build-map-region.yml).")

# ---- 4. `--bounds` a `--polygon` naraz (rozpis v hlavičke) ----
# Hľadá sa v texte skriptov, nie v YAMLe: samotné volanie Planetileru je
# vo `workers/<job>/build.sh` a orez doňho chodí cez `workers/lib/region-clip.sh`.
for cesta in sorted(glob.glob("workers/*/*.sh")):
    with open(cesta, encoding="utf-8") as f:
        text = bez_komentarov(f.read())
    if not JE_TO_PLANETILER.search(text):
        continue
    # Buď priamo v príkaze, alebo tak, že ich obe vypíše `region-clip.sh`.
    spolu = s_volanymi(text)
    ma_polygon = "--polygon" in bez_komentarov(spolu)
    ma_bounds = "--bounds" in bez_komentarov(spolu)
    # `region-clip.sh` obe MENUJE (jedno v každej vetve) – tam sa kontroluje,
    # že ich nevypíše naraz, a to je vidieť z toho, že sú v rôznych vetvách.
    if cesta.endswith("region-clip.sh"):
        continue
    if ma_polygon and ma_bounds and "region-clip.sh" not in text:
        bad.append(
            f"{cesta}: púšťa Planetiler s `--polygon` AJ `--bounds`. Tvar sa "
            f"tým ticho vypne (rozpis v hlavičke tejto kontroly aj vo "
            f"workers/lib/region-clip.sh) a mapa bude siahať za región. Nechaj "
            f"len jedno – orez skladá `workers/lib/region-clip.sh`.")

# Samotný `region-clip.sh` sa neprečíta, ale SPUSTÍ – raz s polygónom, raz bez
# neho. Staticky by sa „obe naraz" hľadalo v podmienkach a to je presne to
# miesto, kde by sa kontrola dala obísť nedopatrením.
CLIP = "workers/lib/region-clip.sh"
with tempfile.TemporaryDirectory() as tmp:
    poly = os.path.join(tmp, "region.poly")
    with open(poly, "w", encoding="utf-8") as f:
        f.write("test\n1\n  19.0 49.0\n  20.0 49.0\n  20.0 50.0\nEND\nEND\n")
    # Tretí riadok je VYPÍNAČ `region_clip`. Vypnutý orez musí dať `--bounds`
    # (bez neho by si Planetiler vzal bbox z hlavičky PBF, čo po `osmium
    # extract` nemusí sedieť) a NESMIE pri tom vypísať `--polygon` – obe naraz
    # znamenajú ticho vypnutý tvar, rozpis v hlavičke tejto kontroly. A štvrtý
    # stráži, že vypnúť sa to dá len NAPÍSANÍM: keď premenná nepríde vôbec,
    # orez je zapnutý.
    for popis, args, env, musi, nesmie in (
        ("s polygónom", [CLIP, "19,48,20,49", poly], {}, "--polygon", "--bounds"),
        ("bez polygónu", [CLIP, "19,48,20,49", os.path.join(tmp, "niet.poly")],
         {}, "--bounds", "--polygon"),
        ("s vypnutým orezom", [CLIP, "19,48,20,49", poly],
         {"OPT_REGION_CLIP": "false"}, "--bounds", "--polygon"),
        ("s prázdnym OPT_REGION_CLIP", [CLIP, "19,48,20,49", poly],
         {"OPT_REGION_CLIP": ""}, "--polygon", "--bounds"),
    ):
        r = subprocess.run(args, capture_output=True, text=True,
                           env={**os.environ, **env})
        if r.returncode != 0:
            bad.append(f"{CLIP} ({popis}) spadol: {r.stderr.strip()[:200]}")
            continue
        if musi not in r.stdout:
            bad.append(f"{CLIP} ({popis}) nevypísal `{musi}`: {r.stdout!r}")
        if nesmie in r.stdout:
            bad.append(
                f"{CLIP} ({popis}) vypísal `{nesmie}` – s `--polygon` sa "
                f"`--bounds` dávať NESMIE (tvar sa tým ticho vypne, rozpis "
                f"v hlavičke tejto kontroly), a bez polygónu niet čím orezať.")

for b in bad:
    print(f"::error::{b}")
print(f"Planetiler a Java: {len(bad)} chýb")
sys.exit(1 if bad else 0)
