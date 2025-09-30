#!/usr/bin/env python3
"""
pi_stream_cli.py
Stream digits of π to a file "forever" with a clean terminal HUD. No GUI.

Features
- Resumable (saves state to JSON alongside the digits file)
- Clean multi-line HUD that adapts to your terminal width
- Optional psutil for CPU/RAM stats (HUD shows n/a without it)
- Choose output directory via --out
- Safety: periodic fsync + atomic state writes
- Optional low-disk guard (--min-free-gb): auto-pause when below threshold

Usage examples
  python3 pi_stream_cli.py --out /Volumes/YourHDD/pi_out
  python3 pi_stream_cli.py --out ~/pi_out --min-free-gb 10 --checkpoint 50000 --fsync 50000

Stop with Ctrl+C; it checkpoints and exits cleanly.
"""

import os, sys, json, time, shutil, signal, argparse

# Optional psutil (CPU/RAM). Script works fine without it.
try:
    import psutil
except Exception:
    psutil = None

# ---------------- Spigot generator (Rabinowitz–Wagon), resumable ----------------
def pi_spigot_stateful(initial=None):
    if initial is None:
        q, r, t, k, n, l = 1, 0, 1, 1, 3, 3
    else:
        q = int(initial["q"]); r = int(initial["r"]); t = int(initial["t"])
        k = int(initial["k"]); n = int(initial["n"]); l = int(initial["l"])

    while True:
        if 4*q + r - t < n*t:
            yield n, {"q": 10*q,
                      "r": 10*(r - n*t),
                      "t": t,
                      "k": k,
                      "n": ((10*(3*q + r)) // t) - 10*n,
                      "l": l}
            q, r, t, k, n, l = 10*q, 10*(r - n*t), t, k, ((10*(3*q + r)) // t) - 10*n, l
        else:
            q, r, t, k, n, l = (q*k,
                                (2*q + r)*l,
                                t*l,
                                k + 1,
                                (q*(7*k + 2) + r*l) // (t*l),
                                l + 2)

# ---------------- Helpers ----------------
def atomic_write_json(path: str, data: dict):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic on POSIX

def count_digits_in_file(path: str) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, "r", errors="ignore") as f:
        data = f.read()
    i = data.find("3.")
    tail = data if i == -1 else data[i+2:]
    return sum(ch.isdigit() for ch in tail)

def human_bytes(n):
    for unit in ("B","KB","MB","GB","TB","PB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.0f} PB"

def clear_and_home():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

# ---------------- Main runner ----------------
def run(args):
    out_dir = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out_dir, exist_ok=True)

    out_file = os.path.join(out_dir, "pi_digits.txt")
    state_file = os.path.join(out_dir, "pi_state.json")

    # Try loading saved state
    state = None
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                state = json.load(f)
        except Exception:
            state = None

    if state and "digits_written" in state and all(k in state for k in ("q","r","t","k","n","l")):
        digits_written = int(state["digits_written"])
        alg_state = {k:int(state[k]) for k in ("q","r","t","k","n","l")}
        resumed = True
    else:
        digits_written = count_digits_in_file(out_file)
        alg_state = None
        resumed = False

    # Prepare output file; write "3." if fresh
    fresh = not os.path.exists(out_file) or os.path.getsize(out_file) == 0
    out = open(out_file, "a", buffering=1)
    if fresh:
        out.write("3.")
        out.flush()
        os.fsync(out.fileno())

    # Save initial state if none
    if not state:
        snapshot = {
            "q": alg_state["q"] if alg_state else 1,
            "r": alg_state["r"] if alg_state else 0,
            "t": alg_state["t"] if alg_state else 1,
            "k": alg_state["k"] if alg_state else 1,
            "n": alg_state["n"] if alg_state else 3,
            "l": alg_state["l"] if alg_state else 3,
            "digits_written": digits_written,
            "updated_at": time.time()
        }
        atomic_write_json(state_file, snapshot)

    gen = pi_spigot_stateful(alg_state)
    digits_on_line = 0
    last_checkpoint = digits_written
    last_fsync = digits_written

    # psutil proc
    proc = psutil.Process(os.getpid()) if psutil else None
    if psutil:
        proc.cpu_percent(interval=None)  # warm-up
        psutil.cpu_percent(interval=None)

    # HUD stats
    last_hud = time.time()
    last_hud_digits = digits_written
    ema_rate = 0.0

    # Signal handling
    stopping = False
    def _sig(_s,_f):
        nonlocal stopping
        stopping = True
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _sig)

    if resumed:
        clear_and_home()
        print(f"Resumed at digit #{digits_written} after '3.' — writing to:\n{out_file}")
        time.sleep(1)

    # Main loop
    try:
        while not stopping:
            # Optional low-disk guard: pause generation until free space recovers
            if args.min_free_gb is not None:
                try:
                    free_bytes = shutil.disk_usage(out_dir).free
                except Exception:
                    free_bytes = 0
                if free_bytes < args.min_free_gb * (1024**3):
                    # Show warning HUD and sleep a bit
                    draw_hud(out_dir, out_file, digits_written, ema_rate, 0.0, paused_reason=f"Free space < {args.min_free_gb} GB")
                    time.sleep(2.0)
                    continue

            # Generate next digit
            digit, next_state = next(gen)
            out.write(str(digit))
            digits_written += 1

            if args.line_width and args.line_width > 0:
                digits_on_line += 1
                if digits_on_line >= args.line_width:
                    out.write("\n")
                    digits_on_line = 0

            # Periodic fsync
            if digits_written - last_fsync >= args.fsync:
                out.flush()
                os.fsync(out.fileno())
                last_fsync = digits_written

            # Periodic checkpoint
            if digits_written - last_checkpoint >= args.checkpoint:
                snapshot = {**next_state, "digits_written": digits_written, "updated_at": time.time()}
                atomic_write_json(state_file, snapshot)
                last_checkpoint = digits_written

            # Advance algorithm state
            alg_state = next_state

            # HUD update
            now = time.time()
            if now - last_hud >= args.hud_interval:
                # instantaneous rate
                dt = now - last_hud
                inst_rate = max(0.0, (digits_written - last_hud_digits) / max(1e-6, dt))
                ema_rate = inst_rate if ema_rate == 0 else (args.ema_alpha * inst_rate + (1 - args.ema_alpha) * ema_rate)
                last_hud = now
                last_hud_digits = digits_written
                draw_hud(out_dir, out_file, digits_written, ema_rate, inst_rate)

    except StopIteration:
        pass
    finally:
        try:
            out.flush()
            os.fsync(out.fileno())
        except Exception:
            pass
        # Save final state
        final_state = {**alg_state, "digits_written": digits_written, "updated_at": time.time()}
        atomic_write_json(state_file, final_state)
        out.close()
        # Final HUD
        draw_hud(out_dir, out_file, digits_written, ema_rate, 0.0, footer="Saved checkpoint. Bye!")

def draw_hud(out_dir, out_file, digits_written, ema_rate, inst_rate, paused_reason=None, footer=None):
    # Gather sizes
    try:
        file_bytes = os.path.getsize(out_file) if os.path.exists(out_file) else 0
    except Exception:
        file_bytes = 0
    try:
        usage = shutil.disk_usage(out_dir)
        free_bytes = usage.free
    except Exception:
        free_bytes = 0

    # CPU/RAM if psutil
    if psutil:
        try:
            cpu_sys = psutil.cpu_percent(interval=None)
            proc = psutil.Process(os.getpid())
            cpu_proc = proc.cpu_percent(interval=None)
            mem_rss = proc.memory_info().rss
        except Exception:
            cpu_sys = cpu_proc = mem_rss = None
    else:
        cpu_sys = cpu_proc = mem_rss = None

    cols = shutil.get_terminal_size((80, 20)).columns

    lines = []
    header = "π Stream — Terminal HUD (no GUI)"
    lines.append(header[:cols])
    lines.append(f"Output: {out_file}"[:cols])

    state_line = f"Digits: {digits_written:,} | Rate: {inst_rate:,.0f}/s (avg {ema_rate:,.0f}/s)"
    lines.append(state_line[:cols])

    size_line = f"File: {human_bytes(file_bytes)} | Free: {human_bytes(free_bytes)}"
    lines.append(size_line[:cols])

    if cpu_proc is not None and cpu_sys is not None and mem_rss is not None:
        lines.append(f"CPU(proc/sys): {cpu_proc:4.1f}%/{cpu_sys:4.1f}% | RAM: {human_bytes(mem_rss)}"[:cols])

    if paused_reason:
        lines.append(f"Status: PAUSED — {paused_reason}"[:cols])
    else:
        lines.append("Status: RUNNING"[:cols])

    if footer:
        lines.append(footer[:cols])

    # Clear and draw, padding each line to width to prevent leftovers
    sys.stdout.write("\033[2J\033[H")
    for ln in lines:
        sys.stdout.write(ln.ljust(cols) + "\n")
    sys.stdout.flush()

# ---------------- CLI ----------------
def parse_args():
    p = argparse.ArgumentParser(description="Stream digits of π with a clean terminal HUD (resumable).")
    p.add_argument(
        "--out",
        default=os.getcwd(),   # <--- default to where you run it from
        help="Output directory (default: current working directory)"
    )
    p.add_argument("--checkpoint", type=int, default=50_000, help="Checkpoint every N digits (default 50000)")
    p.add_argument("--fsync", type=int, default=50_000, help="fsync output every N digits (default 50000)")
    p.add_argument("--hud-interval", type=float, default=0.5, dest="hud_interval", help="HUD refresh seconds (default 0.5)")
    p.add_argument("--ema-alpha", type=float, default=0.15, dest="ema_alpha", help="EMA smoothing factor for avg rate (0..1)")
    p.add_argument("--line-width", type=int, default=0, help="Digits per line in file (0 = disable line breaks)")
    p.add_argument("--min-free-gb", type=float, default=None, help="Auto-pause when free disk < this many GB")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    try:
        run(args)
    except Exception as e:
            sys.stderr.write(f"\nFatal error: {e}\n")
            sys.exit(1)
