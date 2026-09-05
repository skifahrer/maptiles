#!/usr/bin/env python3
"""Spustí príkaz a je pri ňom počuť: postup, tep, pamäť, rast výstupu.

`gdal_contour` nad krajom beží desiatky minút a s `-q` je ticho – z logu sa
nedá odlíšiť „počíta" od „zaseklo sa". Rieši to dvoma vecami:

  1. GDAL píše postup bez konca riadku a Actions taký riadok neukážu, kým
     príkaz neskončí. Tu sa číta po bajtoch a každý krok sa vypíše hneď –
     a krokom je bodka (2,5 %), nie desiatka.
  2. Keď príkaz nehlási nič, beží popri ňom tep: čas, odhad konca, pamäť,
     CPU, I/O a rast výstupu. Ticho dlhšie než `--every` sekúnd nenastane.

    from watch import run_watched, Heartbeat, hms
    python3 workers/lib/watch.py --label="vrstevnice" -- gdal_contour …
"""
import argparse
import os
import re
import shlex
import subprocess
import sys
import threading
import time


def hms(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def gb(mb):
    """Pamäť tak, aby sa dala prečítať – 0,0 GB nepovie o procese nič."""
    return f"{mb:.0f} MB" if mb < 1024 else f"{mb / 1024:.1f} GB"


def o_kolkej(za_s):
    """Hodina, keď sa to podľa doterajšieho tempa skončí.

    „Zostáva ~1:47:10" treba prirátať k času v hlavičke riadku; hodina to
    povie rovno.
    """
    return time.strftime("%H:%M", time.localtime(time.time() + za_s))


def dir_mb(path):
    """Veľkosť súboru alebo celého priečinka v MB."""
    if os.path.isfile(path):
        return os.path.getsize(path) / 1048576
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1048576


def proc_rss_mb(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def proc_cpu_s(pid):
    """Koľko sekúnd procesor tomu procesu naozaj venoval.

    Odpovedá na „počíta sa, alebo sa čaká?": blízko 100 % je výpočet a treba
    zmenšiť prácu, blízko nule visí na I/O alebo sieti.
    """
    try:
        with open(f"/proc/{pid}/stat") as f:
            # 14. a 15. pole sú utime a stime; meno procesu môže mať medzery
            # a zátvorky, tak sa reže až za poslednou `)`
            polia = f.read().rpartition(")")[2].split()
        tiky = int(polia[11]) + int(polia[12])
        return tiky / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError):
        return 0.0


def proc_io_mb(pid):
    """(prečítané, zapísané) MB – rozlíši „čítam raster" od „nerobím nič"."""
    try:
        vals = {}
        with open(f"/proc/{pid}/io") as f:
            for line in f:
                k, _, v = line.partition(":")
                vals[k] = int(v)
        return vals.get("read_bytes", 0) / 1048576, vals.get("write_bytes", 0) / 1048576
    except (OSError, ValueError):
        return 0.0, 0.0


class Heartbeat(threading.Thread):
    """Každých `every` sekúnd povie, že sa stále niečo deje – a čo."""

    def __init__(self, label, pid=None, tmp=None, every=30, max_rss_mb=0,
                 max_s=0):
        super().__init__(daemon=True)
        self.label, self.pid, self.tmp = label, pid, tmp
        # sekunda je podlaha: pri `every=0` by z tepu bola nekonečná slučka –
        # a na tepe visí aj strop pamäte
        self.every = max(float(every), 1.0)
        self.max_rss_mb, self.max_s = max_rss_mb, max_s
        self.t0 = time.time()
        self.stop_flag = threading.Event()
        self.killed_for_memory = False
        self.killed_for_time = False
        # posledné percento od GDALu a kedy; tep z toho počíta odhad konca
        self.pct = 0.0
        self.pct_at = self.t0
        # predošlé percento – z neho nedávne tempo. Priemer od štartu pri
        # spomaľujúcom procese sľubuje koniec, ktorý nepríde.
        self.prev_pct = 0.0
        self.prev_at = self.t0
        # aby varovanie o spomalení nezaznelo pri každom tepe
        self.spomalenie_ohlasene = False
        # namerané čísla si tep drží aj pre záverečný riadok – po skončení
        # procesu `/proc/<pid>` zmizne
        self.rss_mb = 0.0
        self.peak_rss_mb = 0.0
        self.cpu_s = 0.0
        self.io = (0.0, 0.0)
        self.out_mb = 0.0
        self._last = (self.t0, 0.0, (0.0, 0.0), 0.0)  # čas, cpu, io, výstup

    def tempo(self):
        """(priemerné, nedávne) tempo v %/min; nedávne je z posledného kroku."""
        beh = max(time.time() - self.t0, 1e-6)
        priemer = self.pct / (beh / 60.0)
        dt = self.pct_at - self.prev_at
        dp = self.pct - self.prev_pct
        nedavne = dp / (dt / 60.0) if dt > 1 and dp > 0 else 0.0
        return priemer, nedavne

    def sample(self):
        """Odmeria proces a vráti jednu vetu o tom, čo práve robí."""
        now = time.time()
        beh = now - self.t0
        dt = max(now - self._last[0], 1e-6)
        # s rozpočtom sa hlási aj to, koľko z neho je preč: inak sa z „beží
        # 2:41:30" nedá poznať, či to smeruje do cieľa alebo do steny
        parts = [f"beží {hms(beh)}" + (
            f" z {hms(self.max_s)} ({100 * beh / self.max_s:.0f} %)"
            if self.max_s else "")]

        # odhad konca z nameraného postupu, nie z konštanty – tá sa mýli aj
        # osemdesiatnásobne
        if 0 < self.pct < 100:
            priemer, nedavne = self.tempo()
            zvysok = beh / (self.pct / 100.0) - beh
            # keď je nedávne tempo výrazne pod priemerom, proces spomaľuje
            # a odhad z priemeru je lož
            if nedavne and priemer and nedavne < priemer / 2:
                z_nedavneho = (100.0 - self.pct) / nedavne * 60.0
                parts.append(
                    f"{self.pct:g} %, tempo kleslo {priemer / nedavne:.1f}× "
                    f"({priemer:.2f} → {nedavne:.2f} %/min), pri terajšom "
                    f"tempe zostáva ~{hms(z_nedavneho)}")
            else:
                parts.append(f"{self.pct:g} %, zostáva ~{hms(zvysok)} "
                             f"(koniec ~{o_kolkej(zvysok)})")
        elif self.pct >= 100:
            parts.append("100 % – dopisuje výstup")

        rss = proc_rss_mb(self.pid) if self.pid else 0.0
        if rss:
            self.rss_mb = rss
            self.peak_rss_mb = max(self.peak_rss_mb, rss)
            strop = (f", strop {gb(self.max_rss_mb)}" if self.max_rss_mb else "")
            parts.append(f"pamäť {gb(rss)} "
                         f"(špička {gb(self.peak_rss_mb)}{strop})")

        # počíta, alebo čaká? Okamžitý podiel hovorí, čo robí teraz, priemer
        # to zasadí do súvislostí
        cpu = proc_cpu_s(self.pid) if self.pid else 0.0
        if cpu:
            self.cpu_s = cpu
            parts.append(f"CPU {100 * (cpu - self._last[1]) / dt:.0f} % "
                         f"(priemer {100 * cpu / max(beh, 1e-6):.0f} %)")
        r, w = proc_io_mb(self.pid) if self.pid else (0.0, 0.0)
        if r or w:
            dr, dw = r - self._last[2][0], w - self._last[2][1]
            self.io = (r, w)
            parts.append(f"disk {r:.0f}/{w:.0f} MB "
                         f"(+{dr / dt:.1f}/+{dw / dt:.1f} MB/s)")

        mb = dir_mb(self.tmp) if self.tmp and os.path.exists(self.tmp) else 0.0
        if mb:
            # rast výstupu je jediná stopa po fáze, ktorá percentá nehlási
            parts.append(f"výstup {mb:.0f} MB (+{(mb - self._last[3]) / dt:.1f} MB/s)")
            self.out_mb = mb

        self._last = (now, cpu, (r, w), mb)
        return ", ".join(parts)

    def run(self):
        while not self.stop_flag.wait(self.every):
            print(f"  … {self.label}: {self.sample()}", flush=True)
            rss = self.rss_mb
            beh = time.time() - self.t0
            if self.max_rss_mb and rss > self.max_rss_mb:
                self.killed_for_memory = True
                print(f"::error::{self.label} zabral {rss / 1024:.1f} GB pamäte "
                      f"(strop {self.max_rss_mb / 1024:.1f} GB) – zastavujem, "
                      f"inak by runner spadol na OOM bez hlášky.", flush=True)
                try:
                    os.kill(self.pid, 9)
                except OSError:
                    pass
                return
            # strop na čas sa zapína, nepredpokladá: má zmysel len tam, kde
            # sa po zastavení dá nadviazať (obrysy po blokoch). Pri jednom
            # nedeliteľnom priechode by zahodil hodiny práce a nevyrobil nič.
            if self.max_s and beh > self.max_s:
                self.killed_for_time = True
                print(f"::error::{self.label} beží {hms(beh)}, rozpočet je "
                      f"{hms(self.max_s)} – zastavujem. Radšej to povedať "
                      f"teraz než na timeoute celého jobu.", flush=True)
                try:
                    os.kill(self.pid, 9)
                except OSError:
                    pass
                return

    def stop(self):
        self.stop_flag.set()


# meradlo postupu GDALu je jediný riadok len z číslic a bodiek, takže sa dá
# odlíšiť od hlášky, ktorá tiež obsahuje čísla aj bodky
POSTUP = re.compile(rb"[\d.]+")


def percenta(line):
    """Percento z meradla postupu – aj medzi desiatkami (bodka je 2,5 %)."""
    m = re.match(rb"^.*?(\d+)(\.*)$", line, re.S)
    if not m:
        return None
    return min(100.0, int(m.group(1)) + 2.5 * len(m.group(2)))


def run_watched(cmd, label, tmp=None, max_rss_mb=0, every=30, max_s=0):
    """Spustí príkaz, priebežne hlási, že žije, a prekladá progress GDALu.

    `max_rss_mb` je strop pamäte (`MemoryError` – lepšie než OOM, po ktorom
    v logu nie je nič). `max_s` je strop času, vypnutý kým ho niekto nezapne;
    patrí len tam, kde sa po zastavení dá nadviazať.
    """
    t0 = time.time()
    every = max(float(every), 1.0)   # 0 by z tepu spravila nekonečnú slučku
    stropy = [f"pamäť do {gb(max_rss_mb)}"] if max_rss_mb else []
    stropy.append(f"čas do {hms(max_s)}" if max_s else
                  "bez stropu času (dobehne, aj keď to potrvá dlhšie, "
                  "než sa čakalo)")
    print(f"▶ {label}: {' '.join(shlex.quote(str(c)) for c in cmd)}", flush=True)
    print(f"  {label}: {', '.join(stropy)}, tep každých {every:g} s",
          flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    hb = Heartbeat(label, proc.pid, tmp, every=every, max_rss_mb=max_rss_mb,
                   max_s=max_s)
    hb.start()
    # bodky sú husté zámerne, ale krátky príkaz nemá zaplniť log riadkami
    # o ničom: desiatky idú vždy, medzikroky len po `krok_s` ticha
    krok_s = max(5.0, every / 3.0)
    line, last, last_at = b"", -1.0, 0.0
    try:
        while True:
            chunk = proc.stdout.read(1)
            if not chunk:
                break
            if chunk == b"\n":
                # riadok, ktorý nie je len meradlo postupu, sa nesmie stratiť
                txt = re.sub(rb"[\d.\s]|- done\.", b"", line)
                if txt.strip():
                    print(f"  {label}: {line.decode(errors='replace').strip()}",
                          flush=True)
                line, last, last_at = b"", -1.0, 0.0
                continue
            predtym, line = line, line + chunk
            if chunk == b".":
                # nová bodka = ďalších 2,5 %, číslo pred ňou je už celé
                pct = percenta(line) if POSTUP.fullmatch(line) else None
            elif not chunk.isdigit() and predtym[-1:].isdigit() \
                    and POSTUP.fullmatch(predtym):
                # číslo sa práve dopísalo – inak by posledné percento nezaznelo
                pct = percenta(predtym)
            else:
                continue          # číslica sa ešte dopisuje, alebo je to hláška
            if pct is None or pct <= last:
                continue
            last = pct
            teraz = time.time()
            beh = teraz - t0
            # tepu sa to podá, aby vedel dopočítať odhad aj medzi bodkami
            hb.prev_pct, hb.prev_at = hb.pct, hb.pct_at
            hb.pct, hb.pct_at = pct, teraz
            # spomaľuje? Povedať to hneď, nie až keď to niekto po hodine zruší:
            # `gdal_contour -p` nad jemným sklonom späť nezrýchli
            priemer, nedavne = hb.tempo()
            if (not hb.spomalenie_ohlasene and beh > 300
                    and nedavne and priemer and nedavne < priemer / 4):
                hb.spomalenie_ohlasene = True
                print(f"::warning::{label}: tempo kleslo {priemer / nedavne:.0f}× "
                      f"({priemer:.2f} → {nedavne:.2f} %/min pri {pct:g} %). "
                      f"Pri terajšom tempe zostáva ~"
                      f"{hms((100.0 - pct) / nedavne * 60.0)} a ďalej sa to "
                      f"bude predlžovať – jeden priechod `gdal_contour -p` sa "
                      f"nedá prerušiť, takže to buď dobehne, alebo padne na "
                      f"strope jobu. Zváž hrubší sklad (`rock_res`) alebo "
                      f"menší výrez (`area`).", flush=True)
            if pct % 10 and teraz - last_at < krok_s:
                continue
            last_at = teraz
            if 0 < pct < 100:
                zvysok = beh / (pct / 100.0) - beh
                tempo = (f", tempo {pct / (beh / 60):.1f} %/min"
                         if beh > 60 else "")
                kam = (f"{tempo}, zostáva ~{hms(zvysok)} "
                       f"(koniec ~{o_kolkej(zvysok)})")
            else:
                kam = ", dopisuje výstup"
            print(f"  … {label}: {pct:g} % (beží {hms(beh)}{kam})", flush=True)
    finally:
        proc.wait()
        hb.stop()
    if hb.killed_for_memory:
        raise MemoryError(label)
    if hb.killed_for_time:
        raise TimeoutError(label)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    took = time.time() - t0
    # namerané čísla na koniec – bez nich sa odhady nemajú z čoho opraviť
    konce = [f"hotovo za {hms(took)}"]
    if tmp and os.path.exists(tmp):
        konce.append(f"výstup {dir_mb(tmp):.0f} MB")
    if hb.peak_rss_mb:
        konce.append(f"špička pamäte {gb(hb.peak_rss_mb)}")
    if hb.cpu_s:
        konce.append(f"CPU {hms(hb.cpu_s)} ({100 * hb.cpu_s / max(took, 1e-6):.0f} %)")
    if any(hb.io):
        konce.append(f"disk {hb.io[0]:.0f} MB čítania / {hb.io[1]:.0f} MB zápisu")
    print(f"✔ {label}: {', '.join(konce)}", flush=True)


def main():
    ap = argparse.ArgumentParser(
        description="Spustí príkaz a hlási jeho postup, tep a rast výstupu.")
    ap.add_argument("--label", default="príkaz")
    ap.add_argument("--watch-file", default="",
                    help="súbor alebo priečinok, ktorého rast sa má hlásiť")
    ap.add_argument("--every", type=float, default=30.0)
    ap.add_argument("--max-rss-gb", type=float, default=0.0)
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="príkaz za `--`")
    args = ap.parse_args()

    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        print("::error::watch.py: chýba príkaz za `--`.", file=sys.stderr)
        return 2
    try:
        run_watched(cmd, args.label, tmp=args.watch_file or None,
                    max_rss_mb=args.max_rss_gb * 1024, every=args.every)
    except MemoryError:
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"::error::{args.label} zlyhal (kód {exc.returncode}).",
              file=sys.stderr)
        return exc.returncode or 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
