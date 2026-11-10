import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pairwatch.attribution import Calibration, assign_sides, attribute_speaker  # noqa: E402
from pairwatch.cpp import find_gxx, run_tests  # noqa: E402
from pairwatch.metrics import compute, spearman  # noqa: E402
from pairwatch.report import class_report, pair_report  # noqa: E402
from pairwatch.session import Session  # noqa: E402
from pairwatch.tasks import TASKS  # noqa: E402

needs_gxx = pytest.mark.skipif(find_gxx() is None, reason="no g++")


@needs_gxx
@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_reference_solutions_pass(task):
    r = run_tests(task.solution, task.tests)
    assert r.compiled and r.solved, r.compile_output


@needs_gxx
def test_starter_compiles_but_fails_and_errors_are_reported():
    assert not run_tests(TASKS[0].starter, TASKS[0].tests).solved
    bad = run_tests("int main(){ x }", [("", "")])
    assert not bad.compiled and "main.cpp" in bad.compile_output
    loop = run_tests("int main(){ while(1){} }", [("", "1")], run_timeout=0.5)
    assert not loop.tests[0].passed and "no answer" in loop.tests[0].note


def test_speaker_attribution():
    assert attribute_speaker(False, 0.1, 0.1, 0.02, 0.02) == ""
    assert attribute_speaker(True, 0.08, 0.01, 0.02, 0.02) == "L"
    assert attribute_speaker(True, 0.01, 0.09, 0.02, 0.02) == "R"
    assert attribute_speaker(True, 0.05, 0.05, 0.02, 0.02) == "both"
    assert attribute_speaker(True, 0.0, 0.0, 0.02, 0.02) == "?"
    assert attribute_speaker(True, None, 0.05, 0.02, 0.02) == "R"


def test_sides_by_position():
    s = assign_sides([{"cx": 0.8}, {"cx": 0.3}])
    assert s["L"]["cx"] == 0.3 and s["R"]["cx"] == 0.8
    assert list(assign_sides([{"cx": 0.7}])) == ["R"]


def test_calibrated_regions_partner_and_away():
    c = Calibration()
    for _ in range(5):
        c.add("top", {"pitch": 0.40, "yaw": 0.0})
        c.add("middle", {"pitch": 0.55, "yaw": 0.0})
        c.add("bottom", {"pitch": 0.70, "yaw": 0.0})
    assert c.region({"pitch": 0.41, "yaw": 0.02}, +1) == "top"
    assert c.region({"pitch": 0.56, "yaw": 0.0}, +1) == "middle"
    assert c.region({"pitch": 0.69, "yaw": 0.0}, +1) == "bottom"
    assert c.region({"pitch": 0.55, "yaw": 0.6}, +1) == "partner"   # left student turns towards the right
    assert c.region({"pitch": 0.55, "yaw": -0.6}, +1) == "away"
    assert c.region({"pitch": 1.2, "yaw": 0.0}, +1) == "away"        # looking down at the desk


def _session(tmp_path):
    s = Session("Test pair", root=tmp_path, start_t=1000.0)
    s.task = "digits"
    s.event("task_start", t=1000.0)
    look = ["top", "middle", "bottom"]
    for i in range(300):  # 60 s
        t = 1000 + i * 0.2
        spk = "L" if (i // 25) % 2 == 0 else "R"
        s.feature({"t": t, "face_L": 1, "face_R": 1, "look_L": look[(i // 10) % 3], "look_R": look[(i // 10) % 3] if i < 150 else "away",
                   "speech": 1, "speaker": spk})
        if i % 2 == 0:
            s.event("key", t=t)
        if i == 150:
            s.driver = "R"
            s.event("driver", t=t)
    s.event("run", {"compiled": True, "passed": 4, "of": 4, "solved": True}, t=1045.0)
    s.close(t=1060.0)
    return s.dir


def test_metrics_on_known_session(tmp_path):
    m = compute(_session(tmp_path))
    assert m["minutes"] == 1.0
    assert abs(m["talk_share_L"] - 0.5) < 0.1 and m["turns_per_minute"] > 5
    assert abs(m["joint_attention"] - 0.5) < 0.02          # same region for the first half only
    assert abs(m["typing_share_L"] - 0.5) < 0.02 and m["driver_switches"] == 1
    assert m["tasks_solved"] == 1 and m["tasks"]["digits"]["solved_after_s"] == 45.0


def test_reports_are_written(tmp_path):
    d = _session(tmp_path)
    html = pair_report(d).read_text(encoding="utf-8")
    assert "Test pair" in html and "data:image/png;base64" in html and "Malak Zubair" in html
    assert json.loads((d / "summary.json").read_text())["tasks_solved"] == 1
    assert class_report(tmp_path, tmp_path / "class.html").exists()


def test_spearman():
    assert spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [1, 2, 3]) is None   # too few pairs to say anything
