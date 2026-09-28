# -*- coding: utf-8 -*-
"""Tests end-to-end para el pipeline integral de ClipFactory."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

GUION_SAMPLE = """# Bloque 1

Hablamos de cómo se aprende algo nuevo.

[CÁMARA B]
La práctica deliberada es lo que separa al que mejora del que solo repite.

# Bloque 2

Un cierre corto.

[CÁMARA B]
Equivocarse temprano sale más barato que equivocarse tarde.

[Duración total estimada: 2 min]
"""

TRANSCRIPT_SAMPLE = {
    "segments": [
        {
            "start": 0.5,
            "end": 2.5,
            "text": "La práctica deliberada es lo que separa al que mejora del que solo repite.",
            "words": [
                {"word": "La", "start": 0.5, "end": 0.7},
                {"word": "práctica", "start": 0.7, "end": 1.2},
                {"word": "deliberada", "start": 1.2, "end": 1.8},
                {"word": "repite", "start": 2.2, "end": 2.5},
            ],
        },
        {
            "start": 3.0,
            "end": 5.0,
            "text": "Equivocarse temprano sale más barato que equivocarse tarde.",
            "words": [
                {"word": "Equivocarse", "start": 3.0, "end": 3.6},
                {"word": "temprano", "start": 3.6, "end": 4.1},
                {"word": "tarde", "start": 4.6, "end": 5.0},
            ],
        },
    ]
}


def create_synthetic_video(path: Path, seconds: int = 6) -> None:
    """Genera video sintético para pruebas locales sin descargar recursos ni usar GPU."""
    assert FFMPEG is not None, "ffmpeg no disponible en PATH"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=640x360:rate=25:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


def probe_duration(path: Path) -> float:
    """Obtiene la duración en segundos de un archivo multimedia usando ffprobe."""
    assert FFPROBE is not None, "ffprobe no disponible en PATH"
    r = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float((r.stdout or "0").strip() or 0)


@pytest.fixture
def test_workspace(tmp_path: Path) -> Path:
    """Fixture que prepara un directorio temporal con guion, transcript y video sintético."""
    (tmp_path / "guion.md").write_text(GUION_SAMPLE, encoding="utf-8")
    (tmp_path / "transcript.json").write_text(
        json.dumps(TRANSCRIPT_SAMPLE, ensure_ascii=False), encoding="utf-8"
    )
    create_synthetic_video(tmp_path / "video.mp4", seconds=6)
    return tmp_path


def run_pipeline_cli(
    workspace: Path, extra_args: list[str] | None = None, env: dict | None = None
) -> subprocess.CompletedProcess:
    """Ejecuta el script pipeline.py con los argumentos del workspace."""
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "pipeline.py"),
        "--guion",
        str(workspace / "guion.md"),
        "--transcript",
        str(workspace / "transcript.json"),
        "--video",
        str(workspace / "video.mp4"),
        "--output",
        str(workspace / "out"),
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
    )


def test_six_stages_e2e(test_workspace: Path):
    """Verifica la ejecución integral de las 6 etapas del pipeline y sus artefactos."""
    res = run_pipeline_cli(test_workspace)
    assert res.returncode == 0, f"Error en pipeline: {res.stderr}\n{res.stdout}"

    out_dir = test_workspace / "out"
    assert (out_dir / "candidates.json").is_file(), "Etapa 1: candidates.json no generado"
    assert (out_dir / "matches.json").is_file(), "Etapa 3: matches.json no generado"
    assert (out_dir / "clip_plan.json").is_file(), "Etapa 4: clip_plan.json no generado"

    clips = list((out_dir / "clips").glob("*.mp4"))
    assert len(clips) >= 2, f"Etapa 5: se esperaban al menos 2 clips mp4, encontrados: {len(clips)}"

    for clip_path in clips:
        dur = probe_duration(clip_path)
        assert dur > 0, f"El clip {clip_path.name} tiene duración {dur} <= 0"
        cid = clip_path.stem
        assert (out_dir / "clips" / f"{cid}.srt").is_file(), f"Etapa 5: falta SRT para {cid}"
        assert (out_dir / "clips" / f"{cid}.txt").is_file(), f"Etapa 6: falta metadata TXT para {cid}"

    mf_path = out_dir / "manifest.json"
    assert mf_path.is_file(), "Manifest: manifest.json no generado"
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    mf_clips = mf.get("clips", mf)
    assert len(mf_clips) >= 2, "Manifest sin clips válidos"
    for item in mf_clips:
        for k in ("id", "path", "start", "end", "duration", "state"):
            assert k in item, f"Manifest item sin clave {k}: {item}"


def test_resume_idempotence(test_workspace: Path):
    """Verifica que una segunda corrida no re-renderice clips finalizados."""
    res1 = run_pipeline_cli(test_workspace)
    assert res1.returncode == 0, f"Primera corrida falló: {res1.stderr}"

    out_dir = test_workspace / "out"
    clips_before = {p.name: (p.stat().st_mtime, p.read_bytes()) for p in (out_dir / "clips").glob("*.mp4")}
    assert clips_before, "No se generaron clips en la primera corrida"

    t0 = time.time()
    res2 = run_pipeline_cli(test_workspace)
    elapsed = time.time() - t0
    assert res2.returncode == 0, f"Segunda corrida falló: {res2.stderr}"

    clips_after = {p.name: (p.stat().st_mtime, p.read_bytes()) for p in (out_dir / "clips").glob("*.mp4")}
    assert set(clips_before) == set(clips_after), "El conjunto de clips cambió tras re-correr"

    for name in clips_before:
        mtime_before, bytes_before = clips_before[name]
        mtime_after, bytes_after = clips_after[name]
        assert mtime_before == mtime_after, f"Clip {name} fue re-renderizado innecesariamente (mtime cambió)"
        assert bytes_before == bytes_after, f"Clip {name} cambió su contenido binario"


def test_edits_partial_rerender(test_workspace: Path):
    """Verifica que una edición en edits.json re-renderice solo el clip editado dejando el resto idéntico."""
    res_base = run_pipeline_cli(test_workspace)
    assert res_base.returncode == 0, f"Corrida base falló: {res_base.stderr}"

    out_dir = test_workspace / "out"
    mf = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    clips = mf.get("clips", mf)
    assert len(clips) >= 2, "Se requieren al menos 2 clips para probar re-render selectivo"

    target_clip = clips[0]
    untouched_clip = clips[1]

    untouched_path = out_dir / untouched_clip["path"]
    target_path = out_dir / target_clip["path"]

    untouched_bytes_before = untouched_path.read_bytes()
    untouched_mtime_before = untouched_path.stat().st_mtime
    target_dur_before = probe_duration(target_path)

    # Editar duración del target clip
    new_start = float(target_clip["start"])
    new_end = new_start + max(1.0, (float(target_clip["end"]) - new_start) / 2.0)
    edits = {
        "clips": [
            {
                "id": target_clip["id"],
                "start": new_start,
                "end": new_end,
                "title": "Editado por Mario",
            }
        ]
    }
    edits_file = test_workspace / "edits.json"
    edits_file.write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")

    res_edits = run_pipeline_cli(test_workspace, extra_args=["--edits", str(edits_file)])
    assert res_edits.returncode == 0, f"Corrida con ediciones falló: {res_edits.stderr}"

    target_dur_after = probe_duration(target_path)
    assert abs(target_dur_after - target_dur_before) > 0.3, (
        f"La duración del clip editado no cambió: {target_dur_before} -> {target_dur_after}"
    )

    # El clip no editado debe permanecer byte-idéntico y con mtime intacto
    assert untouched_path.read_bytes() == untouched_bytes_before, "Clip no editado fue modificado binariamente"
    assert untouched_path.stat().st_mtime == untouched_mtime_before, "Clip no editado fue tocado/re-renderizado"


def test_invalid_edits_rejected_no_corruption(test_workspace: Path):
    """Verifica que ediciones inválidas fallen con exit != 0 sin corromper artefactos existentes."""
    res_base = run_pipeline_cli(test_workspace)
    assert res_base.returncode == 0, f"Corrida base falló: {res_base.stderr}"

    out_dir = test_workspace / "out"
    clips_before = {p.name: p.read_bytes() for p in (out_dir / "clips").glob("*.mp4")}

    # Caso 1: ID desconocido
    bad_id = {"clips": [{"id": "clip-inexistente-123", "start": 0.0, "end": 1.5}]}
    bad_id_file = test_workspace / "bad_id.json"
    bad_id_file.write_text(json.dumps(bad_id), encoding="utf-8")

    res_bad_id = run_pipeline_cli(test_workspace, extra_args=["--edits", str(bad_id_file)])
    assert res_bad_id.returncode != 0, "Aceptó edición con ID desconocido"
    assert "no existe" in res_bad_id.stderr.lower() or "inválida" in res_bad_id.stderr.lower()

    # Verificar que los clips existentes no se corrompieron
    for name, content in clips_before.items():
        assert (out_dir / "clips" / name).read_bytes() == content

    # Caso 2: end <= start
    bad_range = {"clips": [{"id": "c1", "start": 4.0, "end": 2.0}]}
    bad_range_file = test_workspace / "bad_range.json"
    bad_range_file.write_text(json.dumps(bad_range), encoding="utf-8")

    res_bad_range = run_pipeline_cli(test_workspace, extra_args=["--edits", str(bad_range_file)])
    assert res_bad_range.returncode != 0, "Aceptó edición con end <= start"
    assert "end" in res_bad_range.stderr.lower() or "inválida" in res_bad_range.stderr.lower()

    # Verificar nuevamente que los clips existentes no se corrompieron
    for name, content in clips_before.items():
        assert (out_dir / "clips" / name).read_bytes() == content


def test_no_writes_outside_repo(test_workspace: Path, tmp_path: Path):
    """Verifica que el pipeline no escriba en HOME ni fuera del repositorio."""
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    env = dict(os.environ, HOME=str(fake_home))
    res = run_pipeline_cli(test_workspace, env=env)
    assert res.returncode == 0, f"Pipeline con fake HOME falló: {res.stderr}"

    noise_re = re.compile(
        r"(__pycache__|\.python_history|\.cache/|\.local/|\.DS_Store|\.matplotlib|\.keras)"
    )
    written = [p for p in fake_home.rglob("*") if p.is_file() and not noise_re.search(str(p))]
    assert not written, f"El pipeline escribió fuera del repo en fake HOME: {written}"


def test_resume_rerenders_incomplete_or_changed_clips(test_workspace: Path):
    """Verifica que un clip cuyo estado previo no sea 'done' o cuya firma cambie sea re-renderizado."""
    res_base = run_pipeline_cli(test_workspace)
    assert res_base.returncode == 0, f"Corrida base falló: {res_base.stderr}"

    out_dir = test_workspace / "out"
    mf_path = out_dir / "manifest.json"
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    clips = mf.get("clips", mf)
    assert len(clips) >= 2, "Se requieren al menos 2 clips"

    target = clips[0]
    target["state"] = "pending"
    mf_path.write_text(json.dumps({"clips": clips}, ensure_ascii=False, indent=2), encoding="utf-8")

    untouched = clips[1]
    untouched_path = out_dir / untouched["path"]
    untouched_mtime_before = untouched_path.stat().st_mtime
    untouched_bytes_before = untouched_path.read_bytes()

    res_resume = run_pipeline_cli(test_workspace)
    assert res_resume.returncode == 0, f"Corrida de resume falló: {res_resume.stderr}"

    mf_after = json.loads(mf_path.read_text(encoding="utf-8"))
    target_after = next(c for c in mf_after["clips"] if c["id"] == target["id"])
    assert target_after["state"] == "done"

    assert untouched_path.stat().st_mtime == untouched_mtime_before
    assert untouched_path.read_bytes() == untouched_bytes_before

