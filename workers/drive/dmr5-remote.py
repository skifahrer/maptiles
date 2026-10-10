#!/usr/bin/env python3
"""
The remote DMR 5.0 raster: reading through /vsizip//vsicurl/, a probe and overviews.

Everything about OPENING the 151 GB raster in someone else's ZIP: the archive
listing, a probe, `.tfw` and `.ovr` sidecars – and two ways through overviews:

  `ovr_source`    the target is COARSER than the source → read `.ovr`, cheaper
                  (46 GB instead of 151 GB) and bit for bit the same.
  `ovr_fallback`  the main raster DIDN'T OPEN → try `.ovr` alone, a rescue
                  (run 31197330753 spent 87 min in one `gdalinfo`).

A module: `remote = load("dmr5_remote", "dmr5-remote.py")`.
"""
import importlib.util
import json
import os
import struct
import subprocess
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

# suffixes openable as a raster; sidecars aren't opened alone, GDAL finds them
RASTER_EXT = (".tif", ".tiff", ".img", ".vrt", ".dem")
SIDECAR = (".ovr", ".aux.xml", ".xml", ".tfw", ".prj", ".rrd")

# a `.tfw` carries no projection; the archive is `sjtsk03`, Krovák East North
FALLBACK_EPSG = 8353

GDAL_ENV = {
    **os.environ,
    # without PAM off, gdalinfo -stats would leave .aux.xml litter beside outputs
    "GDAL_PAM_ENABLED": "NO",
    # the tile cache: 2 GB of the runner's 16 is safe
    "GDAL_CACHEMAX": os.environ.get("GDAL_CACHEMAX", "2048"),
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": os.environ.get("VSI_CACHE_SIZE", str(256 * 1024 * 1024)),
    "GDAL_NUM_THREADS": "ALL_CPUS",
    # GDAL_DISABLE_READDIR_ON_OPEN is NOT set on purpose – it would hide sidecars
}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True,
                          env=GDAL_ENV, **kw)


def rx_bytes():
    """Bytes received from the network since boot (without loopback)."""
    total = 0
    try:
        for iface in os.listdir("/sys/class/net"):
            if iface == "lo":
                continue
            with open(f"/sys/class/net/{iface}/statistics/rx_bytes") as f:
                total += int(f.read().strip())
    except OSError:
        return None
    return total


class Heartbeat:
    """Says every few seconds that it lives – and HOW FAST, from the NIC's bytes."""

    def __init__(self, label, every=30, expect_bytes=None, watch=None):
        self.label = label
        self.every = every
        self.expect = expect_bytes
        self.watch = watch          # a file whose size is watched
        self.stop = threading.Event()
        self.t0 = time.time()
        self.rx0 = rx_bytes()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        last_rx, last_t = self.rx0, self.t0
        while not self.stop.wait(self.every):
            now = time.time()
            el = now - self.t0
            parts = [f"[{el / 60:5.1f} min] {self.label}"]
            rx = rx_bytes()
            if rx is not None and self.rx0 is not None:
                got = rx - self.rx0
                rate = (rx - last_rx) / max(now - last_t, 1e-6)
                parts.append(f"downloaded {got / 1e9:6.2f} GB")
                parts.append(f"({rate / 1e6:5.1f} MB/s)")
                if self.expect:
                    parts.append(f"of ~{self.expect / 1e9:.0f} GB")
                # an ETA only while really downloading – near zero it is thousands of minutes
                if self.expect and rate > 1e6 and got < self.expect:
                    eta = (self.expect - got) / rate
                    parts.append(f"~{eta / 60:.0f} min left")
                last_rx, last_t = rx, now
            if self.watch and os.path.exists(self.watch):
                parts.append(f"output {os.path.getsize(self.watch) / 1e6:.1f} MB")
            print("  " + "  ".join(parts), flush=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        rx = rx_bytes()
        if rx is not None and self.rx0 is not None:
            print(f"  … {self.label}: total {(rx - self.rx0) / 1e9:.2f} GB "
                  f"in {(time.time() - self.t0) / 60:.1f} min", flush=True)
        return False


def run_live(cmd, label=None, expect_bytes=None, watch=None):
    """Long steps log live – an hour of silence can't be told from a hang."""
    print("  $ " + " ".join(cmd), flush=True)
    if label is None:
        return subprocess.run(cmd, check=True, env=GDAL_ENV)
    with Heartbeat(label, expect_bytes=expect_bytes, watch=watch):
        return subprocess.run(cmd, check=True, env=GDAL_ENV)


def vsi_path(url, member):
    """`/vsizip//vsicurl/<url>/<path in the archive>`."""
    return f"/vsizip//vsicurl/{url}/{member}"


def pick_member(plan_path, explicit):
    """Which archive file is the raster; sidecars are skipped."""
    if explicit:
        return explicit
    with open(plan_path) as f:
        plan = json.load(f)
    best = None
    for e in plan["entries"]:
        low = e["name"].lower()
        if any(low.endswith(s) for s in SIDECAR):
            continue
        if not low.endswith(RASTER_EXT):
            continue
        if best is None or e["usize"] > best["usize"]:
            best = e
    if not best:
        raise SystemExit("::error::The plan has not one raster – see the "
                         "inventory in the run summary and give --member by hand.")
    return best["name"]


def load_remote_zip():
    spec = importlib.util.spec_from_file_location(
        "zip_remote", os.path.join(_HERE, "zip-remote.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tiff_layout(url, entry, log, timeout=60):
    """Where in the TIFF the tile directory (IFD) lies. Reads 16 BYTES."""
    # an IFD at the end of a deflated 151 GB member means opening unpacks all of it
    try:
        rz = load_remote_zip().RemoteZip(url, timeout=timeout, verbose=False)
        head = rz.head(entry, 64)
    except Exception as exc:
        log(f"::warning::The header of `{entry['name']}` couldn't be read: {exc}")
        return None
    if len(head) < 16 or head[:2] not in (b"II", b"MM"):
        log(f"  `{entry['name']}`: doesn't start like a TIFF ({head[:4]!r})")
        return None
    end = "<" if head[:2] == b"II" else ">"
    magic = struct.unpack(end + "H", head[2:4])[0]
    if magic == 42:
        kind, ifd = "TIFF", struct.unpack(end + "I", head[4:8])[0]
    elif magic == 43:
        kind, ifd = "BigTIFF", struct.unpack(end + "Q", head[8:16])[0]
    else:
        log(f"  `{entry['name']}`: unknown magic number {magic}")
        return None
    size = entry["usize"] or 1
    share = 100.0 * ifd / size
    log(f"  {kind}, {'little' if end == '<' else 'big'}-endian, "
        f"tile directory (IFD) at offset {ifd:,} of {size:,} "
        f"= {share:.1f} % of the file")
    return {"kind": kind, "ifd": ifd, "size": size, "share": share}


def read_tfw(url, entry, log, timeout=60):
    """A world file: 6 numbers georeferencing a raster without its header."""
    # pixel_x, rotation, rotation, pixel_y (negative), top-left pixel centre X, Y
    try:
        rz = load_remote_zip().RemoteZip(url, timeout=timeout, verbose=False)
        txt = rz.head(entry, 4096).decode("ascii", "replace")
    except Exception as exc:
        log(f"::warning::`{entry['name']}` can't be read: {exc}")
        return None
    vals = []
    for line in txt.splitlines():
        line = line.strip().replace(",", ".")
        if not line:
            continue
        try:
            vals.append(float(line))
        except ValueError:
            break
    if len(vals) < 6:
        log(f"::warning::`{entry['name']}` doesn't have 6 numbers ({len(vals)}).")
        return None
    log(f"  world file: pixel {vals[0]}×{abs(vals[3])} m, "
        f"top-left pixel at {vals[4]:.1f}, {vals[5]:.1f}")
    return vals[:6]


def probe(vsi, log, timeout=900, no_sidecars=False, expect_bytes=None):
    """The raster header; `timeout` stops an honest 151 GB unpack that looks like a hang."""
    t0 = time.time()
    env = dict(GDAL_ENV)
    if no_sidecars:
        # otherwise a costly sidecar would look like the main file's problem
        env["GDAL_DISABLE_READDIR_ON_OPEN"] = "EMPTY_DIR"
    try:
        # a heartbeat HERE too: run 31197330753 spent 87 silent minutes in this gdalinfo
        with Heartbeat("opening the raster", expect_bytes=expect_bytes):
            r = subprocess.run(["gdalinfo", "-json", vsi], check=True, env=env,
                               capture_output=True, text=True, timeout=timeout)
        info = json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        log(f"::error::`gdalinfo` didn't answer within {timeout / 60:.0f} min. "
            f"The file doesn't open – not a slow network, but GDAL reaching the "
            f"tile directory only by unpacking the whole archive member. See "
            f"the IFD offset above.")
        return None
    except subprocess.CalledProcessError as exc:
        log("::error::The raster can't be opened through /vsizip//vsicurl/: "
            f"{(exc.stderr or '').strip()[:400]}")
        return None
    band = info["bands"][0]
    gt = info["geoTransform"]
    wkt = (info.get("coordinateSystem") or {}).get("wkt", "")
    ovr = [o.get("size") for o in band.get("overviews", [])]
    out = {
        "size": info["size"],
        "geoTransform": gt,
        "wkt": wkt,
        "pixel": [abs(gt[1]), abs(gt[5])],
        "type": band["type"],
        "block": band.get("block"),
        "nodata": band.get("noDataValue"),
        "compression": (info.get("metadata", {}).get("IMAGE_STRUCTURE", {})
                        .get("COMPRESSION")),
        "crs": wkt.split('"')[1] if '"' in wkt else "?",
        "overviews": ovr,
        "seconds": round(time.time() - t0, 1),
    }
    log(f"Raster: {out['size'][0]}×{out['size'][1]} px, "
        f"grid {out['pixel'][0]}×{out['pixel'][1]}, {out['type']}")
    log(f"  CRS {out['crs']}, compression {out['compression']}, "
        f"tile {out['block']}, nodata {out['nodata']}")
    # with readdir off this is always zero – we open overviews ourselves
    note = ovr if ovr else "(GDAL doesn't see them here; we open .ovr ourselves)"
    log(f"  overview levels: {len(ovr)} {note}")
    log(f"  header read in {out['seconds']} s")
    return out


def find_sidecar(plan_path, member, suffix):
    """The plan entry of `member`'s sidecar, or None – suffix added or replaced."""
    try:
        with open(plan_path) as f:
            plan = json.load(f)
    except (OSError, ValueError):
        return None
    wants = [(member + suffix).lower()]
    if suffix:
        wants.append((os.path.splitext(member)[0] + suffix).lower())
    for want in wants:
        for e in plan.get("entries") or []:
            if e["name"].lower() == want:
                return e
    return None


def ovr_source(url, member, info, grid_m, work, log, plan_path, timeout=900):
    """For a coarser target, read the overviews (.ovr), georeferenced from the parent."""
    # not left to GDAL: missing it silently would read the whole raster
    src_cell = info["pixel"][0]
    if grid_m < 2 * src_cell:
        log(f"The {grid_m} m target grid is close to the source ({src_cell} m) – "
            f"reading full resolution.")
        return None, None
    side = find_sidecar(plan_path, member, ".ovr")
    if not side:
        log(f"::warning::The archive has no `{member}.ovr` – resampling "
            f"reads the full raster. It will take a while.")
        return None, None

    vsi = vsi_path(url, side["name"])
    env = dict(GDAL_ENV, GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR")
    try:
        r = subprocess.run(["gdalinfo", "-json", vsi], check=True, env=env,
                           capture_output=True, text=True, timeout=timeout)
        oi = json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        log(f"::warning::`{side['name']}` didn't open within "
            f"{timeout / 60:.0f} min – reading the full raster.")
        return None, None
    except subprocess.CalledProcessError as exc:
        log(f"::warning::`{side['name']}` can't be opened ({(exc.stderr or '')[:160]}) "
            f"– reading the full raster.")
        return None, None

    ow, oh = oi["size"]
    pw, ph = info["size"]
    factor = pw / ow
    # the parent's extent doesn't change, only its pixel count
    gt = info["geoTransform"]
    ulx, uly = gt[0], gt[3]
    lrx, lry = ulx + gt[1] * pw, uly + gt[5] * ph

    wkt_file = os.path.join(work, "parent.wkt")
    os.makedirs(work, exist_ok=True)
    with open(wkt_file, "w") as f:
        f.write(info["wkt"])
    vrt = os.path.join(work, "ovr.vrt")
    run(["gdal_translate", "-q", "-of", "VRT", "-a_srs", wkt_file,
         "-a_ullr", repr(ulx), repr(uly), repr(lrx), repr(lry), vsi, vrt])

    log(f"Reading from overviews: {side['name']}")
    log(f"  {ow}×{oh} px = grid {src_cell * factor:g} m "
        f"(the source has {pw}×{ph} px at {src_cell} m)")
    log(f"  {side['csize'] / 1e9:.2f} GB in the archive instead of the main "
        f"raster's {find_sidecar(plan_path, member, '')['csize'] / 1e9:.2f} GB")
    if oi["bands"][0].get("overviews"):
        log(f"  and it has further levels itself: "
            f"{[o['size'] for o in oi['bands'][0]['overviews']]}")
    return vrt, side["csize"]

def ovr_fallback(url, member, work, log, plan_path, timeout):
    """When the main raster DOESN'T OPEN, try the overviews alone, georeferenced from `.tfw`."""
    side = find_sidecar(plan_path, member, ".ovr")
    tfw = find_sidecar(plan_path, member, ".tfw")
    if not side:
        log("::error::The main raster didn't open and the archive has no "
            "`.ovr` – there is no other way from here.")
        return None, None, None
    if not tfw:
        log("::error::The main raster didn't open and without `.tfw` the "
            "`.ovr` can't be georeferenced.")
        return None, None, None

    log("Trying to get round it through overviews – the main raster didn't open.")
    w = read_tfw(url, tfw, log, timeout=60)
    if not w:
        return None, None, None

    vsi = vsi_path(url, side["name"])
    env = dict(GDAL_ENV, GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR")
    try:
        with Heartbeat("opening the overviews", expect_bytes=side["csize"]):
            r = subprocess.run(["gdalinfo", "-json", vsi], check=True, env=env,
                               capture_output=True, text=True, timeout=timeout)
        oi = json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        log(f"::error::Not even `.ovr` opened within {timeout / 60:.0f} min. "
            "This archive can't be read through /vsizip//vsicurl/.")
        return None, None, None
    except subprocess.CalledProcessError as exc:
        log(f"::error::`.ovr` can't be opened: {(exc.stderr or '')[:300]}")
        return None, None, None

    ow, oh = oi["size"]
    # `.tfw` describes the parent; the first overview is assumed 2×, checked by extent
    px, py = abs(w[0]), abs(w[3])
    factor = 2.0
    span_km = ow * px * factor / 1000.0
    log(f"  overview {ow}×{oh} px; at a {factor:g}× reduction that is a "
        f"{px * factor:g} m grid and {span_km:.0f} km wide")
    if not (200 <= span_km <= 900):
        log(f"::warning::A width of {span_km:.0f} km doesn't fit Slovakia – "
            f"the overview's georeferencing may be off.")

    ulx = w[4] - px / 2.0          # .tfw gives the pixel CENTRE, GDAL wants the corner
    uly = w[5] + py / 2.0
    lrx = ulx + ow * px * factor
    lry = uly - oh * py * factor
    os.makedirs(work, exist_ok=True)
    vrt = os.path.join(work, "ovr-fallback.vrt")
    run(["gdal_translate", "-q", "-of", "VRT",
         "-a_srs", f"EPSG:{FALLBACK_EPSG}",
         "-a_ullr", repr(ulx), repr(uly), repr(lrx), repr(lry), vsi, vrt])
    info = json.loads(run(["gdalinfo", "-json", vrt]).stdout)
    out = {
        "size": info["size"],
        "geoTransform": info["geoTransform"],
        "wkt": (info.get("coordinateSystem") or {}).get("wkt", ""),
        "pixel": [abs(info["geoTransform"][1]), abs(info["geoTransform"][5])],
        "type": info["bands"][0]["type"],
        "block": info["bands"][0].get("block"),
        "nodata": info["bands"][0].get("noDataValue"),
        "compression": None,
        "crs": f"EPSG:{FALLBACK_EPSG} (from .tfw)",
        "overviews": [o.get("size") for o in info["bands"][0].get("overviews", [])],
        "seconds": 0,
    }
    log(f"::warning::Going from overviews – the finest grid available is "
        f"{px * factor:g} m, not {px:g} m.")
    return vrt, side["csize"], out
