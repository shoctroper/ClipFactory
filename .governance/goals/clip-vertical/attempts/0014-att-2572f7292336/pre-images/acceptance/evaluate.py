# -*- coding: utf-8 -*-
"""Evaluador fijado de ClipFactory: cuantos casos de la aceptacion pasan.

Imprime una sola linea JSON. Un caso SALTADO cuenta como NO pasado: un skip
nunca es un verde, leccion pagada en G1 y G2.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

proc = subprocess.run(
    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
     "acceptance/test_vertical.py", "--tb=no"],
    cwd=str(ROOT), capture_output=True, text=True)
out = (proc.stdout or "") + (proc.stderr or "")

passed = int((re.search(r"(\d+) passed", out) or [0, 0])[1])
failed = int((re.search(r"(\d+) failed", out) or [0, 0])[1])
skipped = int((re.search(r"(\d+) skipped", out) or [0, 0])[1])
total = passed + failed + skipped

notes = []
if skipped:
    notes.append("%d caso(s) SALTADO(s), contados como NO pasados" % skipped)

print(json.dumps({
    "clipfactory_vertical_passing": passed,
    "progress": passed,
    "total": total or 8,
    "collected": total,
    "skipped": skipped,
    "notes": notes,
    "tail": out.strip().splitlines()[-2:],
}, ensure_ascii=False))
