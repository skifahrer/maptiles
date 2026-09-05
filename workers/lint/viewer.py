#!/usr/bin/env python3
"""Viewer sa musí na Pages celý nasadiť – každý súbor, ktorý si pýta.

`deploy/site.sh` mal vymenovaný zoznam súborov a ten sa s priečinkom rozišiel:
prehliadač na 404 zahodí celý modulový graf, takže sa nespustí ani `app.js`
a na stránke ostane biela plocha. Build je pritom zelený.

  1. každý relatívny import v grafe od `index.html` musí existovať;
  2. `site.sh` musí kopírovať celý priečinok, nie vymenovaný zoznam.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# `workers/lint/` → koreň repozitára. Hĺbka je vždy jedna úroveň (CLAUDE.md).
_ROOT = os.path.dirname(os.path.dirname(_HERE))
WEB = os.path.join(_ROOT, "poc", "web")
SITE_SH = os.path.join(_ROOT, "workers", "deploy", "site.sh")

# `from "./x.js"`, `import "./x.js"`, `import("./x.js")` aj `src="./x.js"`.
IMPORT = re.compile(r'(?:from|import)\s*\(?\s*["\']\./([A-Za-z0-9._-]+\.js)["\']')
SRC = re.compile(r'src="\.?/?([A-Za-z0-9._-]+\.js)"')


def graf():
    """Súbory, ktoré viewer naozaj potrebuje – od `index.html` cez importy."""
    videne, fronta, chyby = set(), ["index.html"], []
    while fronta:
        meno = fronta.pop()
        if meno in videne:
            continue
        videne.add(meno)
        cesta = os.path.join(WEB, meno)
        if not os.path.exists(cesta):
            continue
        text = open(cesta, encoding="utf-8").read()
        for m in IMPORT.findall(text) + (SRC.findall(text) if meno.endswith(".html") else []):
            fronta.append(m)
    return videne, chyby


def main():
    bad = []
    potrebne, _ = graf()

    # 1) existuje všetko, čo si viewer pýta?
    for meno in sorted(potrebne):
        if not os.path.exists(os.path.join(WEB, meno)):
            bad.append(
                f"::error file=poc/web::viewer si importuje `{meno}`, ale ten "
                f"v `poc/web/` nie je. Prehliadač na 404 zahodí celý modulový "
                f"graf – nespustí sa ani `app.js` a na stránke bude biela plocha."
            )

    # 2) kopíruje `site.sh` celý priečinok, alebo si zase drží zoznam?
    try:
        sh = open(SITE_SH, encoding="utf-8").read()
    except OSError as exc:
        bad.append(f"::error file=workers/deploy/site.sh::nedá sa prečítať: {exc}")
        sh = ""

    cp = [r for r in sh.splitlines() if r.strip().startswith("cp ") and "poc/web" in r]
    if not cp:
        bad.append(
            "::error file=workers/deploy/site.sh::nenašiel sa `cp` z `poc/web/` "
            "do `_site` – bez neho na Pages nie je viewer vôbec."
        )
    radok = " ".join(cp)
    # Zoznam po súboroch je to, čo sa rozišlo minule. Vzor (`*.js`) sa rozísť nemá.
    if cp and "poc/web/*.js" not in radok:
        bad.append(
            "::error file=workers/deploy/site.sh::`cp` z `poc/web/` vymenúva "
            "jednotlivé `.js` namiesto `poc/web/*.js`. Presne tak sa stratil "
            "`layer-style.js`: pribudol do priečinka, do zoznamu ho nikto "
            "nedopísal a mapa prestala fungovať bez jediného slova."
        )

    # 3) a naozaj sa tým dostane von všetko, čo graf chce?
    if cp and "poc/web/*.js" in radok:
        for meno in sorted(potrebne):
            if meno.endswith(".js"):
                continue
            if meno not in radok and not meno.endswith(".html"):
                bad.append(
                    f"::error file=workers/deploy/site.sh::`{meno}` je v grafe "
                    f"viewera, ale `cp` ho do `_site` nedostane."
                )

    for r in bad:
        print(r)
    print(f"viewer na Pages: {len(bad)} chýb "
          f"({len(potrebne)} súborov v grafe: {', '.join(sorted(potrebne))})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
