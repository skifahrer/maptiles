#!/usr/bin/env python3
"""Run a command and keep it audible: progress, heartbeat, memory, output growth.

    from watch import run_watched, Heartbeat, hms
    python3 workers/lib/watch.py --label="contours" -- gdal_contour …
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
    """Memory readable – 0.0 GB says nothing about a process."""
    return f"{mb:.0f} MB" if mb < 1024 else f"{mb / 1024:.1f} GB"


def eta_clock(in_s):
    """Clock time when it ends at the current pace."""
    return time.strftime("%H:%M", time.localtime(time.time() + in_s))


def dir_mb(path):
    """Size of a file or a whole folder in MB."""
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
    """CPU seconds the process really got – computing or waiting?"""
    try:
        with open(f"/proc/{pid}/stat") as f:
            # utime and stime; the process name may hold spaces and brackets
            fields = f.read().rpartition(")")[2].split()
        ticks = int(fields[11]) + int(fields[12])
        return ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError):
        return 0.0


def proc_io_mb(pid):
    """(read, written) MB – tells "reading a raster" from "doing nothing"."""
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
    """Every `every` seconds says something is still happening – and what."""

    def __init__(self, label, pid=None, tmp=None, every=30, max_rss_mb=0,
                 max_s=0):
        super().__init__(daemon=True)
        self.label, self.pid, self.tmp = label, pid, tmp
        # `every=0` would spin forever, and the memory cap hangs on the heartbeat
        self.every = max(float(every), 1.0)
        self.max_rss_mb, self.max_s = max_rss_mb, max_s
        self.t0 = time.time()
        self.stop_flag = threading.Event()
        self.killed_for_memory = False
        self.killed_for_time = False
        # last GDAL percent and when, for the end estimate
        self.pct = 0.0
        self.pct_at = self.t0
        # a slowing process makes the average from the start lie
        self.prev_pct = 0.0
        self.prev_at = self.t0
        self.slowdown_reported = False
        # kept for the final line: `/proc/<pid>` is gone after the process ends
        self.rss_mb = 0.0
        self.peak_rss_mb = 0.0
        self.cpu_s = 0.0
        self.io = (0.0, 0.0)
        self.out_mb = 0.0
        self._last = (self.t0, 0.0, (0.0, 0.0), 0.0)  # time, cpu, io, output

    def pace(self):
        """(average, recent) pace in %/min; recent is from the last step."""
        run = max(time.time() - self.t0, 1e-6)
        average = self.pct / (run / 60.0)
        dt = self.pct_at - self.prev_at
        dp = self.pct - self.prev_pct
        recent = dp / (dt / 60.0) if dt > 1 and dp > 0 else 0.0
        return average, recent

    def sample(self):
        """Measure the process and return one sentence on what it's doing."""
        now = time.time()
        run = now - self.t0
        dt = max(now - self._last[0], 1e-6)
        parts = [f"running {hms(run)}" + (
            f" of {hms(self.max_s)} ({100 * run / self.max_s:.0f} %)"
            if self.max_s else "")]

        if 0 < self.pct < 100:
            average, recent = self.pace()
            left = run / (self.pct / 100.0) - run
            if recent and average and recent < average / 2:
                from_recent = (100.0 - self.pct) / recent * 60.0
                parts.append(
                    f"{self.pct:g} %, pace dropped {average / recent:.1f}× "
                    f"({average:.2f} → {recent:.2f} %/min), at the current "
                    f"pace ~{hms(from_recent)} left")
            else:
                parts.append(f"{self.pct:g} %, ~{hms(left)} left "
                             f"(ends ~{eta_clock(left)})")
        elif self.pct >= 100:
            parts.append("100 % – writing the output")

        rss = proc_rss_mb(self.pid) if self.pid else 0.0
        if rss:
            self.rss_mb = rss
            self.peak_rss_mb = max(self.peak_rss_mb, rss)
            cap = (f", cap {gb(self.max_rss_mb)}" if self.max_rss_mb else "")
            parts.append(f"memory {gb(rss)} "
                         f"(peak {gb(self.peak_rss_mb)}{cap})")

        cpu = proc_cpu_s(self.pid) if self.pid else 0.0
        if cpu:
            self.cpu_s = cpu
            parts.append(f"CPU {100 * (cpu - self._last[1]) / dt:.0f} % "
                         f"(average {100 * cpu / max(run, 1e-6):.0f} %)")
        r, w = proc_io_mb(self.pid) if self.pid else (0.0, 0.0)
        if r or w:
            dr, dw = r - self._last[2][0], w - self._last[2][1]
            self.io = (r, w)
            parts.append(f"disk {r:.0f}/{w:.0f} MB "
                         f"(+{dr / dt:.1f}/+{dw / dt:.1f} MB/s)")

        mb = dir_mb(self.tmp) if self.tmp and os.path.exists(self.tmp) else 0.0
        if mb:
            # the only trace of a phase that reports no percent
            parts.append(f"output {mb:.0f} MB (+{(mb - self._last[3]) / dt:.1f} MB/s)")
            self.out_mb = mb

        self._last = (now, cpu, (r, w), mb)
        return ", ".join(parts)

    def run(self):
        while not self.stop_flag.wait(self.every):
            print(f"  … {self.label}: {self.sample()}", flush=True)
            rss = self.rss_mb
            run = time.time() - self.t0
            if self.max_rss_mb and rss > self.max_rss_mb:
                self.killed_for_memory = True
                print(f"::error::{self.label} took {rss / 1024:.1f} GB of memory "
                      f"(cap {self.max_rss_mb / 1024:.1f} GB) – stopping, "
                      f"otherwise the runner dies of OOM without a word.", flush=True)
                try:
                    os.kill(self.pid, 9)
                except OSError:
                    pass
                return
            # opt-in: only where a stopped run can be resumed (outlines by blocks)
            if self.max_s and run > self.max_s:
                self.killed_for_time = True
                print(f"::error::{self.label} running {hms(run)}, the budget is "
                      f"{hms(self.max_s)} – stopping. Better said now than at "
                      f"the whole job's timeout.", flush=True)
                try:
                    os.kill(self.pid, 9)
                except OSError:
                    pass
                return

    def stop(self):
        self.stop_flag.set()


# GDAL's progress meter is a line of digits and dots only
PROGRESS = re.compile(rb"[\d.]+")


def percent(line):
    """Percent from the progress meter – also between tens (a dot is 2.5 %)."""
    m = re.match(rb"^.*?(\d+)(\.*)$", line, re.S)
    if not m:
        return None
    return min(100.0, int(m.group(1)) + 2.5 * len(m.group(2)))


def run_watched(cmd, label, tmp=None, max_rss_mb=0, every=30, max_s=0):
    """Run a command, report it's alive and relay GDAL progress.

    `max_rss_mb` caps memory (`MemoryError` beats a silent OOM); `max_s` caps time.
    """
    t0 = time.time()
    every = max(float(every), 1.0)
    caps = [f"memory up to {gb(max_rss_mb)}"] if max_rss_mb else []
    caps.append(f"time up to {hms(max_s)}" if max_s else
                "no time cap (it finishes even if it takes longer "
                "than expected)")
    print(f"▶ {label}: {' '.join(shlex.quote(str(c)) for c in cmd)}", flush=True)
    print(f"  {label}: {', '.join(caps)}, heartbeat every {every:g} s",
          flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    hb = Heartbeat(label, proc.pid, tmp, every=every, max_rss_mb=max_rss_mb,
                   max_s=max_s)
    hb.start()
    # tens always, steps between them only after `step_s` of silence
    step_s = max(5.0, every / 3.0)
    line, last, last_at = b"", -1.0, 0.0
    try:
        while True:
            chunk = proc.stdout.read(1)
            if not chunk:
                break
            if chunk == b"\n":
                # a line that isn't just the progress meter must not be lost
                txt = re.sub(rb"[\d.\s]|- done\.", b"", line)
                if txt.strip():
                    print(f"  {label}: {line.decode(errors='replace').strip()}",
                          flush=True)
                line, last, last_at = b"", -1.0, 0.0
                continue
            before, line = line, line + chunk
            if chunk == b".":
                pct = percent(line) if PROGRESS.fullmatch(line) else None
            elif not chunk.isdigit() and before[-1:].isdigit() \
                    and PROGRESS.fullmatch(before):
                # a number just finished – else the last percent would never show
                pct = percent(before)
            else:
                continue          # a digit still being written, or a message
            if pct is None or pct <= last:
                continue
            last = pct
            now = time.time()
            run = now - t0
            hb.prev_pct, hb.prev_at = hb.pct, hb.pct_at
            hb.pct, hb.pct_at = pct, now
            # said at once: `gdal_contour -p` over a fine slope never speeds up again
            average, recent = hb.pace()
            if (not hb.slowdown_reported and run > 300
                    and recent and average and recent < average / 4):
                hb.slowdown_reported = True
                print(f"::warning::{label}: pace dropped {average / recent:.0f}× "
                      f"({average:.2f} → {recent:.2f} %/min at {pct:g} %). "
                      f"At the current pace ~"
                      f"{hms((100.0 - pct) / recent * 60.0)} is left and it "
                      f"will keep growing – one `gdal_contour -p` pass can't "
                      f"be interrupted, so it either finishes or dies at the "
                      f"job's cap. Consider a coarser store (`rock_res`) or a "
                      f"smaller cutout (`area`).", flush=True)
            if pct % 10 and now - last_at < step_s:
                continue
            last_at = now
            if 0 < pct < 100:
                left = run / (pct / 100.0) - run
                pace = (f", pace {pct / (run / 60):.1f} %/min"
                        if run > 60 else "")
                where = (f"{pace}, ~{hms(left)} left "
                         f"(ends ~{eta_clock(left)})")
            else:
                where = ", writing the output"
            print(f"  … {label}: {pct:g} % (running {hms(run)}{where})", flush=True)
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
    # measured numbers at the end, so estimates can be corrected
    ends = [f"done in {hms(took)}"]
    if tmp and os.path.exists(tmp):
        ends.append(f"output {dir_mb(tmp):.0f} MB")
    if hb.peak_rss_mb:
        ends.append(f"memory peak {gb(hb.peak_rss_mb)}")
    if hb.cpu_s:
        ends.append(f"CPU {hms(hb.cpu_s)} ({100 * hb.cpu_s / max(took, 1e-6):.0f} %)")
    if any(hb.io):
        ends.append(f"disk {hb.io[0]:.0f} MB read / {hb.io[1]:.0f} MB written")
    print(f"✔ {label}: {', '.join(ends)}", flush=True)


def main():
    ap = argparse.ArgumentParser(
        description="Run a command and report its progress, heartbeat and output growth.")
    ap.add_argument("--label", default="command")
    ap.add_argument("--watch-file", default="",
                    help="file or folder whose growth to report")
    ap.add_argument("--every", type=float, default=30.0)
    ap.add_argument("--max-rss-gb", type=float, default=0.0)
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="command after `--`")
    args = ap.parse_args()

    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        print("::error::watch.py: no command after `--`.", file=sys.stderr)
        return 2
    try:
        run_watched(cmd, args.label, tmp=args.watch_file or None,
                    max_rss_mb=args.max_rss_gb * 1024, every=args.every)
    except MemoryError:
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"::error::{args.label} failed (code {exc.returncode}).",
              file=sys.stderr)
        return exc.returncode or 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
