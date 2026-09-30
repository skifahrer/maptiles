#!/usr/bin/env python3
"""Region border: exact from OSM, no overlap – and stored layers must carry it."""
import re
import sys

# file → variable that builds the store asset name
FILES = {
    "workers/terrain/build.sh": "asset_name",
    # the rock asset name is built in the second half of `contours-rocks/build.sh`
    "workers/contours-rocks/rocks.sh": "ROCK_ASSET",
}
SOURCE = "workers/plan/area.py"
POLY = "workers/plan/region-poly.py"
BORDER = "workers/plan/boundary.py"
PBF = "workers/plan/pbf.sh"
SEAM = "workers/plan/seam.py"

bad = []


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


text = read(SOURCE)
if not re.search(r"^BORDER_BUFFER_M\s*=\s*\d+", text, re.M):
    print(f"::error file={SOURCE}::`BORDER_BUFFER_M` isn't here – the overlap "
          f"beyond the region border must be defined in ONE place and taken "
          f"from here by everyone. If it moved, update this check too.")
    sys.exit(1)

for path, variable in FILES.items():
    text = read(path)
    # both `ROCK_ASSET="…"` and `asset_name() { … }` lines, plus the store `sed`
    lines = [r for r in text.splitlines()
             if variable in r and not r.lstrip().startswith("#")]
    name = "\n".join(lines)
    asks = "BORDER_BUFFER_M" in text
    in_name = re.search(r"-o\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", name) is not None
    if not asks or not in_name:
        bad.append(
            f"::error file={path}::The stored layer name (`{variable}`) "
            f"doesn't carry the overlap beyond the region border "
            f"(`BORDER_BUFFER_M` from {SOURCE} as `-o…`). Without it, after "
            f"a change of the overlap the store returns a layer cut the old "
            f"way, the run passes it as done and the map keeps a strip with "
            f"nothing under it.")
    else:
        print(f"{path}: `{variable}` carries the overlap beyond the border ✓")

pbf = read(PBF)
code = "\n".join(r for r in pbf.splitlines() if not r.lstrip().startswith("#"))
if "region-poly.py" not in code or "--from-pbf=" not in code:
    bad.append(
        f"::error file={PBF}::The region border isn't read from the PBF "
        f"(`region-poly.py --from-pbf=…`). Without it osm.fr's fallback "
        f"`.poly` is used, widened around the border – the map comes out "
        f"2 – 4 km larger than the region and nobody notices (rule 8).")
else:
    print(f"{PBF}: the border is read from the PBF (`--from-pbf`) ✓")

border = read(BORDER)
for name, why in (
        ("def borders_from_pbf",
         "there is no way to read the border relation from the PBF"),
        ("ST_Intersection",
         "the region isn't intersected with the state, so a broken region "
         "relation drags the map beyond the state border")):
    if name not in border:
        bad.append(f"::error file={BORDER}::`{name}` isn't here – {why}.")
if "ST_Buffer" in read(POLY):
    bad.append(
        f"::error file={POLY}::The region polygon is BUFFERED again (`ST_Buffer`). "
        f"The overlap stood in for osm.fr's imprecise `.poly`; with the exact "
        f"OSM border it only pushes the map and elevation layers kilometres "
        f"into the neighbouring region and beyond the state border.")

poly = read(POLY)
if "seam" not in poly or "measure_seam" not in poly:
    bad.append(
        f"::error file={POLY}::The seam with the neighbours is no longer measured "
        f"(`seam.measure_seam`). It is the only thing that tells whether two "
        f"neighbouring maps join – without it nobody learns of a gap until "
        f"someone sees it in the field.")
else:
    print(f"{POLY}: the seam with the neighbours is measured ✓")

seam = read(SEAM)
if '"overlap_m"' not in seam or '"gap_m"' not in seam:
    bad.append(
        f"::error file={SEAM}::Seam measurement doesn't give both numbers "
        f"(`gap_m` and `overlap_m`). While only the gap was measured, a 2 – 4 km "
        f"overlap into the neighbouring region read as “seam closed”.")
else:
    print(f"{SEAM}: both gap and overlap are measured ✓")

for m in bad:
    print(m)
sys.exit(1 if bad else 0)
