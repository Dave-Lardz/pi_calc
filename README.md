# π Stream (pi_calc.py)

**Endless digits of π (Pi), calculated and streamed live to disk with a clean terminal HUD.**

This project is a Python script that continuously generates digits of π using the Rabinowitz–Wagon spigot algorithm and saves them into a text file.  
It’s built to run indefinitely, checkpointing state along the way so it can **resume after crashes or power outages** without losing progress.

---

## ✨ Features
- **Resumable** → Saves state to a JSON file; restarts exactly where it left off.
- **Terminal HUD** → Displays live stats (digits written, rate, file size, free disk, CPU/RAM usage).
- **Safe writing** → Periodic checkpoints and fsyncs protect against data loss.
- **Disk safety** → Option to pause if free disk space falls below a threshold.
- **Configurable** → Adjust checkpoint frequency, HUD refresh interval, line width in output, etc.
- **Portable** → Defaults to the folder you run it from (or specify `--out`).

---

## 🛠 Requirements
- Python 3.8+
- Optional: [`psutil`](https://pypi.org/project/psutil/) for CPU/RAM monitoring in the HUD

Install psutil with:
```bash
pip install psutil
