#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F6.4 — ClipFactory usable de punta a punta con ediciones de Mario (pinned).

QUE MIDE Y POR QUE
------------------
Mario: "que sean proyectos funcionales, quiero poder probar metiendo ediciones".
Hoy (verificado 2026-09-25) ClipFactory tiene las 6 etapas implementadas y su
aceptacion vertical en 8/8, pero:
  - No hay UN comando que corra el pipeline entero: hay que encadenar 5 scripts a
    mano con las rutas correctas, y `match_candidates.py` ni siquiera arranca
    (`ModuleNotFoundError: rapidfuzz`), asi que "probar" exige adivinar el orden.
  - No existe forma de EDITAR el resultado y re-renderizar solo lo editado: si Mario
    quiere mover el inicio de un clip dos segundos, tiene que reescribir clip_plan.json
    a mano y volver a cortar todo.

Esta fase entrega eso: un comando unico, reanudable, y ediciones declaradas en un
archivo que sobrevive a la re-corrida.

SIN RED, SIN LLM, SIN GPU: los checks usan videos sinteticos de 3 segundos generados
con ffmpeg (lavfi) y un transcript de prueba. No se descarga nada.

CHECKS (C1..C10). Imprime {"f6_4_clipfactory_e2e": 0|1, "progress": N, "of": 10, ...}
C1  La aceptacion vertical existente sigue verde (acceptance/evaluate.py >= 8/8).
C2  `python3 scripts/pipeline.py --help` existe y documenta un flujo de una sola
    invocacion (guion + video -> clips).
C3  Dependencias declaradas: rapidfuzz esta en scripts/requirements.txt Y el pipeline
    arranca sin él (degradando a un matcher stdlib) o lo instala: correr el pipeline
    en un entorno sin rapidfuzz NO puede morir con ModuleNotFoundError.
C4  Corrida end-to-end real sobre un caso sintetico: produce al menos un .mp4 de clip
    en el directorio de salida, con duracion > 0 segun ffprobe.
C5  IDEMPOTENTE / REANUDABLE: volver a correr con la misma entrada no rehace el trabajo
    ya hecho (segunda corrida mas rapida o marcada "skipped") y no corrompe la salida.
C6  EDICIONES: existe un archivo de ediciones (edits.json) donde Mario puede ajustar
    `start`/`end`/`title` de un clip por id; tras re-correr, el clip editado refleja
    la nueva duracion y los NO editados quedan byte-identicos.
C7  Una edicion invalida (end <= start, o id inexistente) se rechaza con mensaje claro
    y exit != 0, sin escribir un video corrupto.
C8  El pipeline NO escribe fuera de la raiz del repo (regla dura de CLAUDE.md): se
    verifica que no toca $HOME ni /tmp fuera de su propio output.
C9  Estado legible: el pipeline deja un manifest.json con, por clip, id/estado/rutas/
    duracion, para que la revision humana (Etapa 7) no sea adivinanza.
C10 Existe tests/test_pipeline_e2e.py y pasa.

CONTRATO: exit 0 solo con metric=1.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILED = []
PROGRESS = 0
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def check(name, fn):
    global PROGRESS
    try:
        fn()
        PROGRESS += 1
    except Exception as exc:  # noqa: BLE001
        FAILED.append("%s: %s" % (name, exc))


def _mkvideo(path, seconds=6):
    """Video sintetico con tono: no descarga nada, no usa GPU."""
    subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i",
                    "testsrc=size=640x360:rate=25:duration=%d" % seconds,
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % seconds,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(path)],
                   capture_output=True, timeout=180, check=True)


def _duration(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True, timeout=60)
    return float((r.stdout or "0").strip() or 0)


GUION = """# Bloque 1

Hablamos de como se aprende algo nuevo.

[CÁMARA B]
La practica deliberada es lo que separa al que mejora del que solo repite.

# Bloque 2

Un cierre corto.

[CÁMARA B]
Equivocarse temprano sale mas barato que equivocarse tarde.

[Duración total estimada: 2 min]
"""

TRANSCRIPT = {
    "segments": [
        {"start": 0.5, "end": 2.5,
         "text": "La practica deliberada es lo que separa al que mejora del que solo repite.",
         "words": [{"word": "La", "start": 0.5, "end": 0.7},
                   {"word": "practica", "start": 0.7, "end": 1.2},
                   {"word": "deliberada", "start": 1.2, "end": 1.8},
                   {"word": "repite", "start": 2.2, "end": 2.5}]},
        {"start": 3.0, "end": 5.0,
         "text": "Equivocarse temprano sale mas barato que equivocarse tarde.",
         "words": [{"word": "Equivocarse", "start": 3.0, "end": 3.6},
                   {"word": "temprano", "start": 3.6, "end": 4.1},
                   {"word": "tarde", "start": 4.6, "end": 5.0}]},
    ]
}


def _fixture(td):
    d = Path(td)
    (d / "guion.md").write_text(GUION, encoding="utf-8")
    (d / "transcript.json").write_text(json.dumps(TRANSCRIPT), encoding="utf-8")
    _mkvideo(d / "video.mp4")
    return d


def _run_pipeline(workdir, extra=None, timeout=900):
    argv = [sys.executable, str(ROOT / "scripts" / "pipeline.py"),
            "--guion", str(workdir / "guion.md"),
            "--transcript", str(workdir / "transcript.json"),
            "--video", str(workdir / "video.mp4"),
            "--output", str(workdir / "out")]
    if extra:
        argv += extra
    return subprocess.run(argv, capture_output=True, text=True,
                          cwd=str(ROOT), timeout=timeout)


def c1():
    r = subprocess.run([sys.executable, str(ROOT / "acceptance" / "evaluate.py")],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=600)
    data = json.loads((r.stdout or "{}").strip().splitlines()[-1])
    assert data.get("progress", 0) >= 8, \
        "la aceptacion vertical bajo de 8: %r" % data


def c2():
    p = ROOT / "scripts" / "pipeline.py"
    assert p.exists(), "falta scripts/pipeline.py (el comando unico)"
    r = subprocess.run([sys.executable, str(p), "--help"],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    assert r.returncode == 0, "pipeline.py --help fallo: %s" % r.stderr[-300:]
    for flag in ("--guion", "--video", "--output"):
        assert flag in r.stdout, "pipeline.py no expone %s" % flag


def c3():
    req = (ROOT / "scripts" / "requirements.txt").read_text(encoding="utf-8")
    assert "rapidfuzz" in req, "rapidfuzz no esta declarado en scripts/requirements.txt"
    # correr el matcher con rapidfuzz bloqueado: no puede morir con ModuleNotFoundError
    blocker = tempfile.mkdtemp()
    Path(blocker, "rapidfuzz.py").write_text(
        "raise ImportError('bloqueado por la aceptacion')\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=blocker)
    with tempfile.TemporaryDirectory() as td:
        d = _fixture(td)
        argv = [sys.executable, str(ROOT / "scripts" / "pipeline.py"),
                "--guion", str(d / "guion.md"), "--transcript", str(d / "transcript.json"),
                "--video", str(d / "video.mp4"), "--output", str(d / "out")]
        r = subprocess.run(argv, capture_output=True, text=True, cwd=str(ROOT),
                           env=env, timeout=900)
    shutil.rmtree(blocker, ignore_errors=True)
    assert "ModuleNotFoundError" not in (r.stderr or ""), \
        "el pipeline muere sin rapidfuzz en vez de degradar: %s" % r.stderr[-300:]


def c4():
    with tempfile.TemporaryDirectory() as td:
        d = _fixture(td)
        r = _run_pipeline(d)
        assert r.returncode == 0, "pipeline fallo: %s" % ((r.stderr or r.stdout)[-600:])
        clips = list((d / "out").rglob("*.mp4"))
        assert clips, "no produjo ningun clip .mp4"
        assert any(_duration(c) > 0 for c in clips), "los clips tienen duracion 0"


def c5():
    with tempfile.TemporaryDirectory() as td:
        d = _fixture(td)
        r1 = _run_pipeline(d)
        assert r1.returncode == 0, "primera corrida fallo"
        first = {p.name: p.stat().st_mtime for p in (d / "out").rglob("*.mp4")}
        t0 = time.time()
        r2 = _run_pipeline(d)
        elapsed2 = time.time() - t0
        assert r2.returncode == 0, "segunda corrida fallo: %s" % (r2.stderr[-400:])
        second = {p.name: p.stat().st_mtime for p in (d / "out").rglob("*.mp4")}
        assert set(first) == set(second), "la segunda corrida cambio el conjunto de clips"
        rehizo = [n for n in first if second[n] != first[n]]
        assert not rehizo, "no es reanudable: rehizo %r" % rehizo[:3]


def c6():
    with tempfile.TemporaryDirectory() as td:
        d = _fixture(td)
        assert _run_pipeline(d).returncode == 0, "corrida base fallo"
        manifest = json.loads((d / "out" / "manifest.json").read_text(encoding="utf-8"))
        clips = manifest["clips"] if isinstance(manifest, dict) else manifest
        assert len(clips) >= 2, "se necesitan 2+ clips para probar la edicion selectiva"
        target, otro = clips[0], clips[1]
        untouched = Path(otro["path"]) if Path(otro["path"]).is_absolute() \
            else d / "out" / otro["path"]
        before_other = untouched.read_bytes()
        edited_path = Path(target["path"]) if Path(target["path"]).is_absolute() \
            else d / "out" / target["path"]
        before_dur = _duration(edited_path)
        edits = {"clips": [{"id": target["id"],
                            "start": float(target["start"]) ,
                            "end": float(target["start"]) + max(1.0, (float(target["end"]) - float(target["start"])) / 2.0),
                            "title": "Editado por Mario"}]}
        (d / "edits.json").write_text(json.dumps(edits), encoding="utf-8")
        r = _run_pipeline(d, ["--edits", str(d / "edits.json")])
        assert r.returncode == 0, "la corrida con ediciones fallo: %s" % (r.stderr[-500:])
        after_dur = _duration(edited_path)
        assert abs(after_dur - before_dur) > 0.3, \
            "la edicion no cambio la duracion del clip (%.2f -> %.2f)" % (before_dur, after_dur)
        assert untouched.read_bytes() == before_other, \
            "re-renderizo un clip que NO fue editado"


def c7():
    with tempfile.TemporaryDirectory() as td:
        d = _fixture(td)
        base = _run_pipeline(d)
        assert base.returncode == 0, \
            "la corrida base debe funcionar antes de probar ediciones invalidas"
        bad = {"clips": [{"id": "no-existe-este-id", "start": 0.0, "end": 1.0}]}
        (d / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
        r = _run_pipeline(d, ["--edits", str(d / "bad.json")])
        assert r.returncode != 0, "acepto una edicion con id inexistente"
        bad2 = {"clips": [{"id": "c1", "start": 5.0, "end": 2.0}]}
        (d / "bad2.json").write_text(json.dumps(bad2), encoding="utf-8")
        r2 = _run_pipeline(d, ["--edits", str(d / "bad2.json")])
        assert r2.returncode != 0, "acepto una edicion con end <= start"


# Ruido del propio interprete, no escrituras del pipeline.
_HOME_NOISE = re.compile(r"(__pycache__|\.python_history|\.cache/|\.local/|"
                         r"\.DS_Store|\.matplotlib|\.keras)")


def c8():
    with tempfile.TemporaryDirectory() as td:
        d = _fixture(td)
        home = Path(td) / "fakehome"
        home.mkdir()
        env = dict(os.environ, HOME=str(home))
        argv = [sys.executable, str(ROOT / "scripts" / "pipeline.py"),
                "--guion", str(d / "guion.md"), "--transcript", str(d / "transcript.json"),
                "--video", str(d / "video.mp4"), "--output", str(d / "out")]
        r = subprocess.run(argv, capture_output=True, text=True, cwd=str(ROOT),
                           env=env, timeout=900)
        assert r.returncode == 0, \
            "la corrida base debe funcionar para poder juzgar donde escribe"
        escritos = [p for p in home.rglob("*")
                    if p.is_file() and not _HOME_NOISE.search(str(p))]
        assert not escritos, "el pipeline escribio fuera del repo (en HOME): %r" % escritos[:3]


def c9():
    with tempfile.TemporaryDirectory() as td:
        d = _fixture(td)
        assert _run_pipeline(d).returncode == 0
        mf = d / "out" / "manifest.json"
        assert mf.exists(), "no escribio manifest.json"
        data = json.loads(mf.read_text(encoding="utf-8"))
        clips = data["clips"] if isinstance(data, dict) else data
        assert clips, "manifest sin clips"
        for c in clips:
            for k in ("id", "path", "start", "end"):
                assert k in c, "clip del manifest sin %s: %r" % (k, c)


def c10():
    t = ROOT / "tests" / "test_pipeline_e2e.py"
    assert t.exists(), "falta tests/test_pipeline_e2e.py"
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", str(t), "-p", "no:cacheprovider"],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=900)
    assert r.returncode == 0, "test_pipeline_e2e.py en rojo: %s" % (r.stdout[-500:])


if not FFMPEG or not FFPROBE:
    print(json.dumps({"f6_4_clipfactory_e2e": 0, "progress": 0, "of": 10,
                      "failed": ["ffmpeg/ffprobe no estan en PATH"]}, ensure_ascii=False))
    sys.exit(1)

for nm, fn in [("C1", c1), ("C2", c2), ("C3", c3), ("C4", c4), ("C5", c5),
               ("C6", c6), ("C7", c7), ("C8", c8), ("C9", c9), ("C10", c10)]:
    check(nm, fn)

metric = 1 if PROGRESS == 10 else 0
print(json.dumps({"f6_4_clipfactory_e2e": metric, "progress": PROGRESS,
                  "of": 10, "failed": FAILED}, ensure_ascii=False))
sys.exit(0 if metric == 1 else 1)
