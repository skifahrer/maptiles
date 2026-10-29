# Computed traffic signs – default speeds by road context

Ticket 2490 (booked in skifahrer/rikimaps). Most roads carry no `maxspeed`: their limit
is what the country's law sets for a built-up area, outside one, a motorway… This work
gives every road that limit, and later draws it on the map as a sign.

## The split: context in the road, number in the app

| Where | What | Why there |
|---|---|---|
| map pipeline (here) | each road's **context**: `urban`, `rural`, `motorway`, `urban_motorway`, `motorroad`, `urban_motorroad`, `living_street` | needs built-up areas and the whole PBF; done once per region |
| skifahrer/traffic-signs | `regulations/<country>.json`: the limit per context and vehicle, with the section of the law | a change of law is one file, no map is rebuilt |
| Riki Maps | signed `maxspeed`, else the regulations' limit for the context and the vehicle | a truck and a car differ on the same road |

The number is never baked: limits differ per vehicle (Slovakia: motorway 130 for a car,
100 for a bus, 90 for a lorry) and laws change.

## How a road's context is decided (`workers/routing/context.py`)

1. Only motor roads get one (`MOTOR`); a footway has no default car speed.
2. What a mapper wrote wins: `maxspeed:type`, `source:maxspeed`, `zone:maxspeed`,
   `zone:traffic` or `maxspeed` as `<country>:<zone>` (`SK:urban`, `DE:rural`,
   `SK:motorway`, `CZ:living_street`).
3. `highway=living_street` is `living_street`; `highway=motorway(_link)` is a motorway,
   `motorroad=yes` a motor road, the rest a plain road.
4. Built-up or not, where no tag says: an edge with at least half its length inside
   `landuse=residential|commercial|retail` is urban. The areas are buffered by 30 m so the
   gardens and a church between two residential areas don't break a village.

## Plan

| # | Step | Where | State |
|---|---|---|---|
| 1 | `regulations.schema.json` | skifahrer/schemas#25 | PR |
| 2 | `regulations/sk.json` from Zákon 8/2009 § 16, § 59 | skifahrer/traffic-signs#53 | PR |
| 3 | `speed_context` on every motor edge of the routing tiles | #357 | merged |
| 4 | the app reads dictionary `f1abaa00` and still reads `e97d6ec6` archives; `RoutingCost` takes the limit from the regulations | skifahrer/rikimaps#2490 | merged |
| 5 | the regulations reach the phone: `regulations.sh` copies `regulations/<country>.json` from traffic-signs as `tiles/<region>-regulations.json`, manifest key `regulations`, in the roads package and the base map | #361 | PR |
| 5b | the app reads the installed region's regulations before its own | skifahrer/rikimaps | to do |
| 6 | the same context on the roads layer: `transport/speed.py` writes it on each way of the roads' PBF | #358 | merged |
| 7 | computed sign points where the context changes along a road, layer `computed_sign`; style layer `road-sign-computed` asks for image `computed.<country>.<context>`, which the app draws with the law's number for a car | #358, #359, rikimaps#2499 | merged |
| 7b | `traffic_sign=city_limit` nodes as the stronger evidence for a village's start and end | #360 | PR |
| 8 | the other dictionary countries' regulations (CZ, AT, HU, PL, DE, UA, SI, CH, HR, RO), each from its law's text | skifahrer/traffic-signs | to do |

## Computed signs (`computed_sign` in the roads package)

A point stands 15 m past the junction where a road carries on (same `ref`, `name` or
class) into a stretch of another context, and faces the traffic entering it: `direction`
in degrees, `speed_context` and `country` to look the limit up by, `osm_way` of the
stretch. None where the stretch is signed (`maxspeed`), against a one-way, or on a side
street. The roads layer is per way, so a way running out of a village is one context.

Where a town sign (`traffic_sign=city_limit`) stands on a road, its signs win: one each way,
15 m from it, the village's context going in and the open road's going out. The village side
is the one the sign faces (a begin sign faces the traffic entering, `city_limit=end` the
traffic leaving), else the side with clearly more built-up land in its first 300 m; with
neither, no sign. Junction signs within 250 m of a town sign are dropped.

## Rollout: the app first

Adding `speed_context` changes the dictionary id (`e97d6ec6` → `f1abaa00`), and today's
app refuses an archive of another id. The key is appended last, so every older index still
means the same: an app that knows `f1abaa00` can read an `e97d6ec6` archive as it is. Step 4
ships that first; only then does step 3 merge and regions get rebuilt.

## Known limits of the first version

- One context per edge. An edge running from a village into fields is whichever covers
  more of it; step 7 splits it where the context changes.
- Town signs (`traffic_sign=city_limit`) aren't read yet.
- The country is the archive's (`--country`), not the edge's, as in `docs/routing-tiles.md`.
