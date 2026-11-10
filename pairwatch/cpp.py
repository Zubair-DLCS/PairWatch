"""Compile and test C++ code with g++ (bundled MinGW, or one already on the laptop)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW: no black console flashes

COMMON_WINDOWS_GXX = [
    r"C:\msys64\ucrt64\bin", r"C:\msys64\mingw64\bin", r"C:\mingw64\bin", r"C:\MinGW\bin",
    r"C:\Program Files (x86)\Dev-Cpp\MinGW64\bin", r"C:\Program Files\Dev-Cpp\MinGW64\bin",
    r"C:\Program Files\CodeBlocks\MinGW\bin", r"C:\Program Files (x86)\CodeBlocks\MinGW\bin",
]


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


def find_gxx() -> str | None:
    exe = "g++.exe" if sys.platform == "win32" else "g++"
    bundled = app_dir() / "mingw64" / "bin" / exe
    if bundled.exists():
        return str(bundled)
    found = shutil.which("g++")
    if found:
        return found
    if sys.platform == "win32":
        for d in COMMON_WINDOWS_GXX:
            p = Path(d) / exe
            if p.exists():
                return str(p)
    return None


@dataclass
class TestResult:
    stdin: str
    expected: str
    got: str
    passed: bool
    note: str = ""


@dataclass
class RunResult:
    compiled: bool
    compile_output: str = ""
    tests: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(t.passed for t in self.tests)

    @property
    def solved(self) -> bool:
        return self.compiled and bool(self.tests) and all(t.passed for t in self.tests)


def _norm(s: str) -> list[str]:
    return s.replace("\r\n", "\n").strip().split()


def _env_for(gxx: str) -> dict:
    env = dict(os.environ)
    env["PATH"] = str(Path(gxx).parent) + os.pathsep + env.get("PATH", "")  # MinGW runtime DLLs
    return env


def run_tests(code: str, tests: list[tuple[str, str]], gxx: str | None = None,
              compile_timeout: float = 30, run_timeout: float = 2.0) -> RunResult:
    gxx = gxx or find_gxx()
    if not gxx:
        return RunResult(False, "No C++ compiler found. Reinstall PairWatch, or install MinGW / Dev-C++.")
    env = _env_for(gxx)
    with tempfile.TemporaryDirectory(prefix="pairwatch_") as td:
        src, exe = Path(td) / "main.cpp", Path(td) / ("main.exe" if sys.platform == "win32" else "main")
        src.write_text(code, encoding="utf-8")
        try:
            c = subprocess.run([gxx, "-std=c++17", "-O1", "-o", str(exe), str(src)], capture_output=True,
                               text=True, timeout=compile_timeout, env=env, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return RunResult(False, "Compiling took too long.")
        if c.returncode != 0:
            msg = (c.stderr or c.stdout).replace(str(src), "main.cpp")
            return RunResult(False, msg.strip()[-3000:])
        res = RunResult(True, (c.stderr or "").replace(str(src), "main.cpp").strip()[-1500:])
        for stdin, expected in tests:
            try:
                r = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True,
                                   timeout=run_timeout, env=env, creationflags=NO_WINDOW)
                got = r.stdout
                note = "" if r.returncode == 0 else f"program ended with code {r.returncode}"
            except subprocess.TimeoutExpired:
                got, note = "", f"no answer within {run_timeout:g} s (endless loop, or waiting for input?)"
            res.tests.append(TestResult(stdin, expected, got.strip()[:500], _norm(got) == _norm(expected), note))
        return res
