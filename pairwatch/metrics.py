"""From a session's numbers to collaboration and performance measures.

Talk     who speaks how much, how often the turn passes, overlaps, and whether
         the navigator (not typing) or the driver does the talking.
Looking  how often each student looks at the code, at the partner, or away;
         joint visual attention = both looking at the same part of the code,
         compared with what chance alone would give.
Typing   who typed while being the driver; how often the roles switched.
Outcome  tasks solved, time to solve, test runs and compile errors.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .attribution import REGIONS
from .session import read_csv

TICK = 0.2


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _balance(a: float, b: float) -> float | None:
    """1 = perfectly shared, 0 = one person did everything."""
    tot = a + b
    return None if tot <= 0 else 1 - abs(a - b) / tot


def _segments(labels: list[str], min_len: int = 2) -> list[str]:
    """Speaker turns: runs of the same L/R label lasting at least min_len ticks."""
    out, cur, n = [], None, 0
    for lab in labels + [None]:
        if lab == cur:
            n += 1
            continue
        if cur in ("L", "R") and n >= min_len and (not out or out[-1] != cur):
            out.append(cur)
        cur, n = lab, 1
    return out


def compute(session_dir: Path) -> dict:
    feats = read_csv(session_dir / "features.csv")
    events = read_csv(session_dir / "events.csv")
    meta_p = session_dir / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    t0 = _f(events[0]["t"]) if events else (_f(feats[0]["t"]) if feats else 0)
    t1 = _f(events[-1]["t"]) if events else (_f(feats[-1]["t"]) if feats else 0)
    minutes = max((t1 - t0) / 60, 1e-6)
    m: dict = {"pair": meta.get("pair", session_dir.name), "date": meta.get("started", ""), "minutes": round(minutes, 1),
               "synthetic": bool(meta.get("synthetic", False))}

    # --- driver over time (from events) --------------------------------------------------
    drv_changes = [(_f(e["t"]), e["driver"]) for e in events if e["type"] in ("start", "driver")]

    def driver_at(t):
        d = "L"
        for tt, dd in drv_changes:
            if tt <= t:
                d = dd
            else:
                break
        return d

    # --- talk ---------------------------------------------------------------------------
    spk = [r["speaker"] for r in feats]
    secs = {k: spk.count(k) * TICK for k in ("L", "R", "both", "?")}
    talk_l, talk_r = secs["L"] + secs["both"] / 2, secs["R"] + secs["both"] / 2
    m["talk_seconds_L"], m["talk_seconds_R"] = round(talk_l, 1), round(talk_r, 1)
    m["talk_share_L"] = round(talk_l / (talk_l + talk_r), 3) if talk_l + talk_r else None
    m["talk_balance"] = _balance(talk_l, talk_r)
    m["overlap_seconds"] = round(secs["both"], 1)
    m["speech_minutes"] = round(sum(_f(r["speech"]) for r in feats) * TICK / 60, 2)
    m["turns_per_minute"] = round(max(len(_segments(spk)) - 1, 0) / minutes, 2)
    nav = drv = 0.0
    for r in feats:
        s = r["speaker"]
        if s in ("L", "R"):
            if s == driver_at(_f(r["t"])):
                drv += TICK
            else:
                nav += TICK
    m["navigator_talk_share"] = round(nav / (nav + drv), 3) if nav + drv else None

    # --- looking ------------------------------------------------------------------------
    both = [r for r in feats if r["face_L"] == "1" and r["face_R"] == "1"]
    m["both_faces_share"] = round(len(both) / len(feats), 3) if feats else 0.0
    for s in ("L", "R"):
        present = [r[f"look_{s}"] for r in feats if r[f"face_{s}"] == "1"]
        n = max(len(present), 1)
        m[f"on_code_{s}"] = round(sum(x in REGIONS for x in present) / n, 3)
        m[f"at_partner_{s}"] = round(present.count("partner") / n, 3)
    if both:
        ll, rr = [r["look_L"] for r in both], [r["look_R"] for r in both]
        jva = float(np.mean([a == b and a in REGIONS for a, b in zip(ll, rr)]))
        chance = sum((ll.count(g) / len(ll)) * (rr.count(g) / len(rr)) for g in REGIONS)
        m["joint_attention"] = round(jva, 3)
        m["joint_attention_chance"] = round(chance, 3)
        m["joint_attention_above_chance"] = round(jva - chance, 3)
        m["mutual_gaze"] = round(float(np.mean([a == "partner" and b == "partner" for a, b in zip(ll, rr)])), 3)
    else:
        m.update(joint_attention=None, joint_attention_chance=None, joint_attention_above_chance=None, mutual_gaze=None)

    # --- typing & roles -----------------------------------------------------------------
    keys = [e for e in events if e["type"] == "key"]
    kl, kr = sum(e["driver"] == "L" for e in keys), sum(e["driver"] == "R" for e in keys)
    m["keys_L"], m["keys_R"] = kl, kr
    m["typing_share_L"] = round(kl / (kl + kr), 3) if kl + kr else None
    m["typing_balance"] = _balance(kl, kr)
    m["driver_switches"] = sum(e["type"] == "driver" for e in events)

    # --- outcome ------------------------------------------------------------------------
    tasks: dict = {}
    for e in events:
        tid = e["task"]
        if e["type"] == "task_start" and tid not in tasks:
            tasks[tid] = {"start": _f(e["t"]), "runs": 0, "compile_errors": 0, "solved_after_s": None, "best": 0, "of": 0}
        if e["type"] == "run" and tid in tasks:
            d = json.loads(e["detail"] or "{}")
            k = tasks[tid]
            k["runs"] += 1
            k["compile_errors"] += 0 if d.get("compiled", True) else 1
            k["best"] = max(k["best"], d.get("passed", 0))
            k["of"] = d.get("of", k["of"])
            if d.get("solved") and k["solved_after_s"] is None:
                k["solved_after_s"] = round(_f(e["t"]) - k["start"], 1)
    m["tasks"] = tasks
    m["tasks_attempted"] = len(tasks)
    m["tasks_solved"] = sum(v["solved_after_s"] is not None for v in tasks.values())
    solved_t = [v["solved_after_s"] for v in tasks.values() if v["solved_after_s"] is not None]
    m["mean_minutes_per_solved_task"] = round(float(np.mean(solved_t)) / 60, 1) if solved_t else None
    m["test_runs"] = sum(v["runs"] for v in tasks.values())
    m["compile_errors"] = sum(v["compile_errors"] for v in tasks.values())
    return m


def save_summary(session_dir: Path) -> dict:
    m = compute(session_dir)
    (session_dir / "summary.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    return m


def spearman(x, y) -> float | None:
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < 4 or np.std(x) == 0 or np.std(y) == 0:
        return None
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1])
