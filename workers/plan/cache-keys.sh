#!/usr/bin/env bash
# Cache keys of the whole build – in one place, for restore, save and rebuild.
#
# Three layers, three keys: a shared key meant a moved rock threshold threw
# away an hour of contours. Each key is `<layer settings>-<fingerprints>`; the
# first part goes out alone (`*_done`) as the prefix `reuse_layers=true`
# finds the newest layer with the same settings by.
#
# Tokens keep their former spelling (`store_token`, `store_area`), so the
# caches built before the English rename still match.

set -euo pipefail
# shellcheck source=workers/lib/store-area.sh
. "$(dirname "$0")/../lib/store-area.sh"
# the area computed from DEM – the test square for a test
B="$DEM_BBOXKEY"
# a store fingerprint per layer; a shared one would drop all three on any refill
DC="$DEMKEY_CONTOURS"
DR="$DEMKEY_ROCKS"
DT="$DEMKEY_TERRAIN"
CS="$(store_token "$OPT_CONTOUR_SOURCE")"
RS="$(store_token "$OPT_ROCK_SOURCE")"
TS="$(store_token "$OPT_SHADING_SOURCE")"
# the cut-out is in every layer's key, or Tatra rocks would return as the region's
RA=$(store_token "$AREA_IN" | tr -c 'a-zA-Z0-9' '_')

# ---------- layer settings (key prefixes) ----------
# size options sit mid-key: at the end the default's prefix would match them
# compared with the old defaults, so tiles built before them are never reused
CCAP="${OPT_CONTOUR_MAXZOOM_CAP:-14}"
LOWLAND="${OPT_CONTOUR_LOWLAND_M:-300}"
TBITS="${OPT_TERRAIN_FRAC_BITS:-auto}"
TFMT="${OPT_TERRAIN_FORMAT:-webp}"
C_OPT=""
if [ "$CCAP" != 16 ]; then C_OPT="${C_OPT}-zc${CCAP}"; fi
if [ "$LOWLAND" != 0 ]; then C_OPT="${C_OPT}-l${LOWLAND}"; fi
T_OPT=""
if [ "$TBITS" != auto ]; then T_OPT="${T_OPT}-b${TBITS}"; fi
if [ "$TFMT" != png ]; then T_OPT="${T_OPT}-${TFMT}"; fi
# v11: contours no longer carry rock settings; smoothing is in the key too,
# the three values live in dem-layers.yml `env:`, not in hashed files
C_SETTINGS="contours-v11-c$CS-$B-i${CONTOUR_INTERVAL}-z${OPT_CONTOUR_MAXZOOM}-s${OPT_CONTOUR_SMOOTHING}h${CONTOUR_DEM_LOWPASS}t${CONTOUR_SIMPLIFY}x${CONTOUR_SMOOTH}${C_OPT}-a$RA"
# `v3`: rocks clipped to the region polygon; `v2` reached to the whole bbox
R_SETTINGS="rocks-v3-r$RS-$B-z${OPT_ROCK_MAXZOOM}p${OPT_ROCK_SOLID}d${OPT_ROCK_FILL_HOLES}-s${ROCK_SLOPE}g${OPT_ROCK_RES}-${ROCK_ALGO}v${ROCK_VEC_RES}t${ROCK_SIMPLIFY}x${ROCK_SMOOTH}-a$RA-${OPT_ROCK_IMG_ASSET}"
# `v7`: flat past the region border; the asset name carries the same number (`workers/lint/terrain.py`)
T_SETTINGS="terrain-v7-t$TS${T_OPT}-$B-z${OPT_TERRAIN_MAXZOOM}"

{
  # ---------- whole keys: settings + fingerprints ----------
  echo "contours=$C_SETTINGS-d$DC-${SCHEMA_CONTOURS}"
  echo "rocks=$R_SETTINGS-d$DR-${SCHEMA_ROCKS}"
  echo "terrain=$T_SETTINGS-d$DT"
  # ---------- “already made” prefixes ----------
  # a trailing dash on purpose: without it `…-z1-` would hit `…-z15-…`
  echo "contours_done=$C_SETTINGS-"
  echo "rocks_done=$R_SETTINGS-"
  echo "terrain_done=$T_SETTINGS-"
  # ---------- keys from before the split ----------
  # entries from before the split are hours of work; an exact key, not a prefix
  LEGACY="contours-v10-c$CS$DC-r$RS$DR-$B-i${CONTOUR_INTERVAL}-z${OPT_CONTOUR_MAXZOOM}-rz${OPT_ROCK_MAXZOOM}p${OPT_ROCK_SOLID}d${OPT_ROCK_FILL_HOLES}-s${OPT_CONTOUR_SMOOTHING}h${CONTOUR_DEM_LOWPASS}t${CONTOUR_SIMPLIFY}x${CONTOUR_SMOOTH}-${ROCK_SLOPE}g${OPT_ROCK_RES}a$RA-${OPT_ROCK_IMG_ASSET}-${SCHEMA_HASH}"
  echo "contours_legacy=$LEGACY"
  # ---------- downloaded DEM tiles ----------
  # in a subfolder by source, so one job may hold two models; `v3`: own key per layer
  echo "demtiles_contours=demtiles-v3-c$CS$DC-$B"
  echo "demtiles_rocks=demtiles-v3-r$RS$DR-$B"
  echo "demtiles_terrain=demtiles-v2-t$TS$DT-$B"
  # the slope store: cut-out, model and grid change its parts; a prefix, saved
  # under prefix + run number and restored through `restore-keys`
  echo "slope=slope-v1-$(store_area "$AREA_KEY")-$RS-g${OPT_ROCK_RES}-"
} >> "$GITHUB_OUTPUT"
cat "$GITHUB_OUTPUT"
