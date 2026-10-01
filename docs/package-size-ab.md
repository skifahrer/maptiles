# Package size: what each lever saves

Measured on 2026-10-01 from the packages on Drive (`maps.json` of 2026-09-29)
and from local re-runs of the pipeline's own code. Every lever is an option in
`workers/plan/options.py` with today's behaviour as the default, so a CI test
build in both versions is one `options` field apart.

## Contours vs rocks (measure first)

The old `contours-rocks` package, six of eight regions (Trenčín and Bratislava
were no longer downloadable):

| region | contours | rocks | rocks share |
|---|---|---|---|
| banskobystricky | 128.0 MB | 11.2 MB | 8 % |
| kosicky | 159.2 MB | 7.3 MB | 4 % |
| nitriansky | 64.2 MB | 0.8 MB | 1 % |
| presovsky | 182.1 MB | 16.8 MB | 8 % |
| trnavsky | 37.1 MB | 0.5 MB | 1 % |
| zilinsky | 127.3 MB | 25.6 MB | 17 % |
| **sum** | **697.9 MB** | **62.2 MB** | **8 %** |

Contours are 92 % of the package, so contour levers pay most. The package is
now split (`contours`, `rocks`), so rocks alone are a small download.

Contours climb above `contour_maxzoom` (14) while the budget has room, which
is why most regions end at z15 or z16.

| zoom | presovsky contours (z15 top) | trnavsky contours (z16 top) | presovsky rocks |
|---|---|---|---|
| z11–z12 | 2.6 % | 1.3 % | 2.8 % |
| z13 | 16.1 % | 9.7 % | 5.1 % |
| z14 | 27.5 % | 16.2 % | 11.8 % |
| z15 | 53.8 % | 28.0 % | 23.8 % |
| z16 | – | 44.8 % | 56.4 % |

## Levers

| lever | option for the test build | saves (measured) | costs |
|---|---|---|---|
| contours end at z13 | `contour_maxzoom_cap=13` | −81 % presovsky, −89 % trnavsky | contour stair steps of the z13 grid (≈1.5 m) when zoomed in |
| contours end at z14 | `contour_maxzoom_cap=14` | −54 % presovsky, −73 % trnavsky | z14 grid steps past z16 |
| 10 m contours in the lowland | `contour_lowland_m=300` | −15 % trnavsky (<200 m), −30 % (<300 m), −47 % (<500 m) | every second line gone below the threshold |
| rocks end at z15 | `rock_maxzoom=15` | −56 % of rocks | rock outlines from the z15 grid |
| rocks end at z14 | `rock_maxzoom=14` | −80 % of rocks | coarser rock outlines |
| height tiles end at z12 | `terrain_maxzoom=12` | −74 % of terrain (both regions) | softer shading past z12 |
| height in whole metres | `terrain_frac_bits=0` | −65 % presovsky, −77 % trnavsky | flat terraces on gentle slopes – `lint/terrain.py` explains why fractions were added |
| WebP lossless | `terrain_format=webp` | −30 % presovsky, −38 % trnavsky | none on iOS 14+ and current browsers; bit-exact |
| both | `terrain_frac_bits=0 terrain_format=webp` | −78 % presovsky, −85 % trnavsky | as above |
| house numbers only at z16 | `housenumber_minzoom=16` | −10.7 % of the base map tiles (trnavsky) | none: the style draws them from z17, overzoomed from z16 |
| Planetiler default simplification | `map_simplify=true` | −0.7 % (trnavsky) | sub-pixel detail past z16 |

Notes:

- Zoom and lowland figures drop levels or features from the published tiles;
  the lowland figure re-encodes tiles with and without the dropped lines.
- Terrain figures re-encode a random sample of 60 tiles per zoom (z11–z13,
  98 % of the bytes) per region with `terrain/tiles.py`'s own encoders,
  weighted by each zoom's share. Re-encoding at today's bits gave the
  published sizes exactly, so the encoder is the one CI runs. WebP uses
  `method=2`: the same size as 6 at 1/50 of the time (6 took ~2 s a tile).
- The base map figures are two local Planetiler runs over the osm.fr Trnava
  extract with the pipeline's flags, then `workers/tiles/drop-layer.py`.
  `velkost-balikov.md` guessed 10–25 % for the simplification flags; it is
  under 1 %.

## Running the A/B in CI

`Map · Build map region` twice on one region, the second with the option in
`options`, `publish=false` and the `publish_pages` switch off; the step summary of each job names the size.
`contour_*` and `terrain_*` options are in the layer cache keys, so the
variant never returns the default's tiles.
