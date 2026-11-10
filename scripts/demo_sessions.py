"""Create SIMULATED pair sessions, to see what the reports look like without a class.

    python scripts/demo_sessions.py            # 10 pairs into ./demo_sessions, then reports
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pairwatch.report import class_report, pair_report  # noqa: E402
from pairwatch.session import Session  # noqa: E402
from pairwatch.tasks import TASKS  # noqa: E402

LOOKS = ["top", "middle", "bottom", "away", "partner"]


def simulate_pair(name: str, root: Path, q: float, skill: float, seed: int, minutes: float = 25.0) -> Path:
    """q = how well the pair collaborates (0..1), skill = how strong they are (0..1)."""
    rng = np.random.default_rng(seed)
    t0 = 1_790_000_000.0 + seed * 7200
    s = Session(name, root=root, meta={"synthetic": True}, start_t=t0)
    n = int(minutes * 60 / 0.2)
    balance = 0.5 + rng.choice([-1, 1]) * (1 - q) * rng.uniform(0.15, 0.4)   # share of talk by L
    look = {"L": "middle", "R": "middle"}
    speaking, driver = "", "L"
    switch_every = (14 - 10 * q) * 60 * rng.uniform(0.8, 1.2)
    last_switch = 0.0
    # tasks
    task_i, task_t0, solved_at = 0, 0.0, None
    need = lambda lvl: 60 * (3 + 3.2 * lvl) * (1.7 - 0.6 * skill - 0.4 * q) * rng.uniform(0.7, 1.3)
    s.task = TASKS[0].id
    s.event("task_start", t=t0)
    target = need(TASKS[0].level)
    next_run = 120.0
    for i in range(n):
        t = i * 0.2
        # driver switches
        if t - last_switch > switch_every and rng.random() < 0.02:
            driver = "R" if driver == "L" else "L"
            s.driver = driver
            s.event("driver", t=t0 + t)
            last_switch = t
        # talk: a Markov chain over silence / L / R
        if speaking == "":
            if rng.random() < 0.06:
                speaking = "L" if rng.random() < balance else "R"
        elif rng.random() < 0.12:
            speaking = "" if rng.random() < 0.6 else ("R" if speaking == "L" else "L") if rng.random() < 0.4 + 0.5 * q else speaking
        spk = speaking
        if spk and rng.random() < 0.03:
            spk = "both"
        # looking: the driver leads; the navigator follows more often in good pairs
        for who in ("L", "R"):
            if rng.random() < 0.08:
                look[who] = rng.choice(LOOKS, p=[0.25, 0.35, 0.2, 0.12, 0.08])
        lead, follow = (driver, "R" if driver == "L" else "L")
        if rng.random() < 0.25 * q:
            look[follow] = look[lead]
        if spk in ("L", "R") and rng.random() < 0.1:
            look["R" if spk == "L" else "L"] = "partner"
        s.feature({"t": round(t0 + t, 2), "face_L": 1, "face_R": int(rng.random() > 0.03), "look_L": look["L"],
                   "look_R": look["R"], "speech": int(spk != ""), "speaker": spk})
        # typing by the driver
        if rng.random() < 0.35:
            s.event("key", t=t0 + t)
        # test runs and solving
        if task_i < len(TASKS) and t - task_t0 >= next_run:
            ok = t - task_t0 >= target
            tot = len(TASKS[task_i].tests)
            passed = tot if ok else int(rng.integers(0, tot))
            compiled = ok or rng.random() > 0.3
            s.event("run", {"compiled": compiled, "passed": passed if compiled else 0, "of": tot, "solved": ok}, t=t0 + t)
            next_run += rng.uniform(60, 180)
            if ok:
                task_i += 1
                if task_i < len(TASKS):
                    s.task = TASKS[task_i].id
                    s.event("task_start", t=t0 + t + 0.1)
                    task_t0, next_run, target = t, 120.0, need(TASKS[task_i].level)
    s.close(t=t0 + n * 0.2)
    return s.dir


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo_sessions")
    root.mkdir(exist_ok=True)
    rng = np.random.default_rng(42)
    dirs = []
    for k in range(10):
        q, skill = float(rng.uniform(0.1, 0.95)), float(rng.uniform(0.1, 0.95))
        dirs.append(simulate_pair(f"Pair {k + 1}", root, q, skill, seed=k))
    for d in dirs:
        pair_report(d)
    print("pair reports:", *[str(d / 'report.html') for d in dirs[:2]], "...")
    print("class report:", class_report(root, root / "class_report.html"))


if __name__ == "__main__":
    main()
