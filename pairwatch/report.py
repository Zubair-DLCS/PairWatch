"""HTML reports: one per pair, and one for the whole class."""
from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

import numpy as np

from .attribution import REGIONS
from .metrics import TICK, _f, save_summary, spearman
from .session import read_csv

CREDIT = "Developed by Malak Zubair, Assistant Professor, G.C.M.S Timergara"
BLUE, ORANGE, GREEN, PURPLE, GREY = "#2f6db5", "#e07b39", "#3a9b4f", "#8a5cc2", "#c9ccd1"
LOOK_COLOURS = {"top": "#9cc0ea", "middle": "#5b93d6", "bottom": "#2a5d9e", "partner": PURPLE, "away": GREY}

CSS = """
body{font-family:Segoe UI,Arial,sans-serif;max-width:1050px;margin:24px auto;padding:0 18px;color:#222}
h1{margin:0 0 4px}h2{margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}
.sub{color:#666}.cards{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0}
.card{border:1px solid #e3e3e3;border-radius:10px;padding:10px 14px;min-width:150px}
.card b{display:block;font-size:22px}.card span{color:#666;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #eee;padding:6px 8px;text-align:left}
.note{background:#f6f8fb;border-left:4px solid #2f6db5;padding:10px 14px;margin:16px 0;font-size:14px}
.warn{background:#fff7e8;border-left-color:#e07b39}img{max-width:100%}footer{margin-top:30px;color:#2f6db5;font-style:italic;font-size:13px}
"""


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _pct(x):
    return "–" if x is None else f"{100 * x:.0f}%"


def _runs(times, labels):
    """(start, length, label) runs of equal labels."""
    out, start, cur = [], None, None
    for t, lab in zip(list(times) + [None], list(labels) + [None]):
        if lab != cur:
            if cur not in (None, ""):
                out.append((start, (t if t is not None else start + TICK / 60) - start, cur))
            start, cur = t, lab
    return out


def timeline(session_dir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    feats = read_csv(session_dir / "features.csv")
    events = read_csv(session_dir / "events.csv")
    if not events:
        return None
    t0 = _f(events[0]["t"])
    ts = [(_f(r["t"]) - t0) / 60 for r in feats]
    fig, ax = plt.subplots(figsize=(11, 3.4))
    rows = ["Driver / typing", "Same part of code", "Right looks at", "Left looks at", "Right speaks", "Left speaks"]
    h = 0.7
    def bars(y, runs, colour_of):
        for s, w, lab in runs:
            ax.broken_barh([(s, w)], (y - h / 2, h), color=colour_of(lab), lw=0)
    bars(5, _runs(ts, ["x" if r["speaker"] in ("L", "both") else "" for r in feats]), lambda _: BLUE)
    bars(4, _runs(ts, ["x" if r["speaker"] in ("R", "both") else "" for r in feats]), lambda _: ORANGE)
    bars(3, _runs(ts, [r["look_L"] if r["face_L"] == "1" else "" for r in feats]), lambda l: LOOK_COLOURS.get(l, GREY))
    bars(2, _runs(ts, [r["look_R"] if r["face_R"] == "1" else "" for r in feats]), lambda l: LOOK_COLOURS.get(l, GREY))
    bars(1, _runs(ts, ["x" if r["look_L"] == r["look_R"] and r["look_L"] in REGIONS else "" for r in feats]), lambda _: GREEN)
    # driver periods
    drv = [(_f(e["t"]) - t0) / 60 for e in events if e["type"] in ("start", "driver")]
    who = [e["driver"] for e in events if e["type"] in ("start", "driver")]
    end = (_f(events[-1]["t"]) - t0) / 60
    for i, (s, d) in enumerate(zip(drv, who)):
        e = drv[i + 1] if i + 1 < len(drv) else end
        ax.broken_barh([(s, e - s)], (0 - h / 2, h), color=BLUE if d == "L" else ORANGE, alpha=0.35, lw=0)
    keys = np.array([(_f(e["t"]) - t0) / 60 for e in events if e["type"] == "key"])
    if len(keys):
        hist, edges = np.histogram(keys, bins=max(int(end * 6), 1), range=(0, max(end, 1e-3)))
        if hist.max() > 0:
            ax.bar(edges[:-1], hist / hist.max() * h, width=edges[1] - edges[0], bottom=-h / 2, align="edge", color="#333", alpha=0.6)
    for e in events:
        x = (_f(e["t"]) - t0) / 60
        if e["type"] == "task_start":
            ax.axvline(x, color="#999", lw=0.8, ls=":")
            ax.text(x, 5.65, e["task"], fontsize=7, color="#555", rotation=0)
        if e["type"] == "run" and json.loads(e["detail"] or "{}").get("solved"):
            ax.plot(x, 0.62, marker="*", color=GREEN, ms=11)
    ax.set_yticks(range(6), rows)
    ax.set_ylim(-0.6, 6.0)
    ax.set_xlim(0, max(end, 0.1))
    ax.set_xlabel("minutes")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    from matplotlib.patches import Patch
    handles = [Patch(color=c, label=k) for k, c in LOOK_COLOURS.items()] + [Patch(color=GREEN, label="same part")]
    ax.legend(handles=handles, ncol=6, fontsize=7, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.22))
    fig.tight_layout()
    out = _png(fig)
    plt.close(fig)
    return out


def pair_report(session_dir: Path) -> Path:
    m = save_summary(session_dir)
    img = timeline(session_dir)
    L, R = "Left student", "Right student"
    cards = [
        (f"{m['tasks_solved']} / {m['tasks_attempted']}", "tasks solved"),
        (f"{m['minutes']} min", "session length"),
        (_pct(m["talk_share_L"]) + " / " + (_pct(1 - m["talk_share_L"]) if m["talk_share_L"] is not None else "–"), "talk: left / right"),
        (_pct(m["typing_share_L"]) + " / " + (_pct(1 - m["typing_share_L"]) if m["typing_share_L"] is not None else "–"), "typing: left / right"),
        (_pct(m["joint_attention"]), f"looking at the same code (chance {_pct(m['joint_attention_chance'])})"),
        (str(m["driver_switches"]), "driver switches"),
        (f"{m['turns_per_minute']}", "speaking turns per minute"),
        (_pct(m["navigator_talk_share"]), "of talk by the navigator"),
    ]
    task_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{'✔ solved in ' + str(round(v['solved_after_s'] / 60, 1)) + ' min' if v['solved_after_s'] is not None else 'not solved'}</td>"
        f"<td>{v['best']} / {v['of']}</td><td>{v['runs']}</td><td>{v['compile_errors']}</td></tr>"
        for k, v in m["tasks"].items())
    warn = ""
    if m["both_faces_share"] < 0.6:
        warn += f"<div class='note warn'>Both faces were visible only {_pct(m['both_faces_share'])} of the time. Looking measures are less reliable; check the laptop's angle next time.</div>"
    if m["speech_minutes"] == 0:
        warn += "<div class='note warn'>No speech was detected. The microphone may have been off or blocked, so talk measures are empty.</div>"
    synth = "<div class='note warn'><b>Synthetic demo data.</b> This report was generated from simulated numbers to show what PairWatch produces.</div>" if m["synthetic"] else ""
    doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>PairWatch – {html.escape(m['pair'])}</title><style>{CSS}</style></head><body>
<h1>PairWatch report: {html.escape(m['pair'])}</h1><div class="sub">{html.escape(m['date'])} · {m['minutes']} minutes · {L} and {R} as seated</div>
{synth}{warn}
<div class="cards">{''.join(f'<div class="card"><b>{a}</b><span>{b}</span></div>' for a, b in cards)}</div>
<h2>Timeline</h2>{f'<img src="{img}">' if img else '<p>No data.</p>'}
<div class="note">Blue = left student, orange = right student. "Looks at" shows which part of the code (top / middle / bottom), the partner, or away. Green marks moments when both looked at the same part of the code. The bottom row shows who was driver (shaded) and how much was typed (dark bars); stars mark solved tasks.</div>
<h2>Tasks</h2><table><tr><th>Task</th><th>Result</th><th>Best tests passed</th><th>Test runs</th><th>Compile errors</th></tr>{task_rows}</table>
<h2>How to read this</h2>
<div class="note">These are signs of how the pair worked together, not grades. Looking is estimated from head direction with one webcam, so "same part of code" means roughly the same third of the screen. Talk is attributed by combining the microphone with mouth movement; quiet speech or a covered mouth can be missed. Use the report as a starting point for a conversation with the pair.<br><br>
No video or audio was recorded. The session folder holds only numbers and the pair's code.</div>
<footer>PairWatch · {CREDIT}</footer></body></html>"""
    out = session_dir / "report.html"
    out.write_text(doc, encoding="utf-8")
    return out


CLASS_MEASURES = [
    ("joint_attention_above_chance", "Looking at the same code (above chance)"),
    ("talk_balance", "Talk balance (1 = equal)"),
    ("typing_balance", "Typing balance (1 = equal)"),
    ("navigator_talk_share", "Share of talk by the navigator"),
    ("driver_switches", "Driver switches"),
    ("turns_per_minute", "Speaking turns per minute"),
]


def class_report(sessions_dir: Path, out: Path | None = None) -> Path | None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = []
    for d in sorted(p for p in sessions_dir.iterdir() if p.is_dir() and (p / "events.csv").exists()):
        try:
            rows.append(save_summary(d))
        except Exception:
            continue
    if not rows:
        return None
    synthetic = any(r.get("synthetic") for r in rows)
    solved = [r["tasks_solved"] for r in rows]
    fig, axs = plt.subplots(2, 3, figsize=(11, 6.4))
    rho_rows = ""
    for ax, (key, label) in zip(axs.ravel(), CLASS_MEASURES):
        x = [np.nan if r.get(key) is None else r[key] for r in rows]
        jitter = np.random.default_rng(0).uniform(-0.12, 0.12, len(solved))
        ax.scatter(x, np.array(solved) + jitter, color=BLUE, alpha=0.8)
        rho = spearman(x, solved)
        ax.set_title(f"{label}\nrho = {rho:+.2f}" if rho is not None else label, fontsize=9)
        ax.set_ylabel("tasks solved", fontsize=8)
        from matplotlib.ticker import MaxNLocator
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        rho_rows += f"<tr><td>{label}</td><td>{'–' if rho is None else f'{rho:+.2f}'}</td></tr>"
    fig.tight_layout()
    img = _png(fig)
    plt.close(fig)
    cols = [("pair", "Pair"), ("date", "Date"), ("tasks_solved", "Solved"), ("minutes", "Min"),
            ("talk_share_L", "Talk L"), ("typing_share_L", "Typing L"), ("joint_attention", "Same code"),
            ("joint_attention_above_chance", "… above chance"), ("driver_switches", "Switches"), ("navigator_talk_share", "Navigator talk")]
    def fmt(k, v):
        if v is None:
            return "–"
        if k in ("talk_share_L", "typing_share_L", "joint_attention", "navigator_talk_share"):
            return _pct(v)
        if k == "joint_attention_above_chance":
            return f"{100 * v:+.0f} pts"
        return html.escape(str(v))
    table = "<tr>" + "".join(f"<th>{c}</th>" for _, c in cols) + "</tr>" + "".join(
        "<tr>" + "".join(f"<td>{fmt(k, r.get(k))}</td>" for k, _ in cols) + "</tr>" for r in rows)
    synth = "<div class='note warn'><b>Synthetic demo data.</b> These pairs were simulated to show what the class report looks like.</div>" if synthetic else ""
    doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>PairWatch – class report</title><style>{CSS}</style></head><body>
<h1>PairWatch class report</h1><div class="sub">{len(rows)} pair sessions</div>{synth}
<h2>How collaboration relates to tasks solved</h2><img src="{img}">
<div class="note">Each dot is one pair. rho is Spearman's rank correlation with the number of tasks solved (+1: higher goes with more solved, −1: the opposite).
With {len(rows)} pairs these are patterns to discuss, not proof: a correlation does not show that one thing causes the other, and stronger students may simply both talk more and solve more.</div>
<table><tr><th>Measure</th><th>rho with tasks solved</th></tr>{rho_rows}</table>
<h2>All pairs</h2><table>{table}</table>
<footer>PairWatch · {CREDIT}</footer></body></html>"""
    out = out or (sessions_dir.parent / "class_report.html")
    out.write_text(doc, encoding="utf-8")
    return out
