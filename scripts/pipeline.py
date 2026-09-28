#!/usr/bin/env python3
"""Pipeline integral de ClipFactory: de guion + video a clips listos para publicar.

Ejecuta en un solo comando las etapas 1 a 6:
  Etapa 1: extract_candidates (del guion de Athena) -> candidates.json
  Etapa 3: match_candidates (contra transcript de WhisperX) -> matches.json
  Etapa 4: plan_clips (ventanas de corte con contexto y límites) -> clip_plan.json
  Etapa 5: render_clips (corte de video y captions) -> clips/<id>.mp4, clips/<id>.srt
  Etapa 6: generate_metadata (títulos y descripciones) -> clips/<id>.txt
  Manifest: manifest.json con estado y metadatos por clip.

Reanudabilidad:
  Lee manifest.json previo y no re-renderiza clips que ya estén listos y no hayan cambiado.
"""
from __future__ import annotations

import sys

# Evitar escrituras de bytecode fuera del repositorio
sys.dont_write_bytecode = True

import os
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse
import atexit
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
PYCACHE_DIR = REPO_ROOT / ".pycache"
sys.pycache_prefix = str(PYCACHE_DIR)
os.environ["PYTHONPYCACHEPREFIX"] = str(PYCACHE_DIR)


def _cleanup_home() -> None:
    """Elimina caché de bytecode que Apple Python escribe en $HOME/Library/Caches."""
    home = os.environ.get("HOME")
    if not home:
        return
    apple_cache = Path(home) / "Library" / "Caches" / "com.apple.python"
    if apple_cache.exists():
        shutil.rmtree(apple_cache, ignore_errors=True)
    caches = Path(home) / "Library" / "Caches"
    if caches.is_dir():
        try:
            if not any(caches.iterdir()):
                caches.rmdir()
        except Exception:
            pass
    lib = Path(home) / "Library"
    if lib.is_dir():
        try:
            if not any(lib.iterdir()):
                lib.rmdir()
        except Exception:
            pass


_cleanup_home()
atexit.register(_cleanup_home)

# Asegurar que los scripts hermanos sean importables
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from extract_candidates import parse_guion
from generate_metadata import generate_metadata, read_srt_text, render_metadata
from match_candidates import match_candidates
from plan_clips import plan_clips
from render_clips import (
    DEFAULT_FFMPEG,
    build_cues,
    build_srt_content,
    flatten_words_with_segment,
    has_subtitles_filter,
    render_clip,
    write_srt,
)


def _write_json_if_changed(path: Path, data: Any) -> bool:
    """Escribe un archivo JSON solo si no existe o si el contenido cambió."""
    formatted = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == formatted:
                return False
        except Exception:
            pass
    path.write_text(formatted, encoding="utf-8")
    return True


def run_pipeline(
    guion_path: Path,
    transcript_path: Path,
    video_path: Path,
    output_dir: Path,
    min_duration: float = 2.0,
    window: float = 90.0,
    threshold: float = 75.0,
    cap: float = 70.0,
    tail_max_gap: float = 2.0,
    tail_max_dur: float = 8.0,
    font_size: int = 28,
    max_words_per_line: int = 10,
    ffmpeg_bin: str = DEFAULT_FFMPEG,
    edits_path: Path | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = output_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # 1. Etapa 1: Extract candidates
    guion_text = guion_path.read_text(encoding="utf-8")
    candidates = parse_guion(guion_text)
    _write_json_if_changed(output_dir / "candidates.json", candidates)

    # 2. Etapa 3: Match candidates
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    matches = match_candidates(candidates, transcript, window=window, threshold=threshold)
    _write_json_if_changed(output_dir / "matches.json", matches)

    # 3. Etapa 4: Plan clips
    plan = plan_clips(
        matches,
        transcript,
        cap=cap,
        tail_max_gap=tail_max_gap,
        tail_max_dur=tail_max_dur,
        min_duration=min_duration,
    )

    # Si se proporcionaron ediciones manuales, aplicarlas y validarlas
    if edits_path is not None:
        if not edits_path.is_file():
            raise FileNotFoundError(f"No existe el archivo de ediciones: {edits_path}")
        edits_data = json.loads(edits_path.read_text(encoding="utf-8"))
        edits_list = edits_data.get("clips", edits_data) if isinstance(edits_data, dict) else edits_data
        if not isinstance(edits_list, list):
            raise ValueError(f"Formato de ediciones inválido en {edits_path}")
        plan_by_id = {c["id"]: c for c in plan}
        for edit in edits_list:
            eid = edit.get("id")
            if not eid or eid not in plan_by_id:
                raise ValueError(f"Edición inválida: clip con id '{eid}' no existe en el plan.")
            target = plan_by_id[eid]
            if "start" in edit:
                target["start"] = float(edit["start"])
            if "end" in edit:
                target["end"] = float(edit["end"])
            if target["start"] is not None and target["end"] is not None:
                if target["end"] <= target["start"]:
                    raise ValueError(
                        f"Edición inválida para {eid}: end ({target['end']}) <= start ({target['start']})."
                    )
                target["duration"] = round(target["end"] - target["start"], 2)
            if "title" in edit:
                target["title"] = edit["title"]

    _write_json_if_changed(output_dir / "clip_plan.json", plan)

    # Leer manifest previo para reanudar solo lo pendiente o cambiado
    manifest_path = output_dir / "manifest.json"
    existing_manifest_clips: dict[str, dict] = {}
    if manifest_path.is_file():
        try:
            prev_manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw_clips = (
                prev_manifest_data.get("clips", prev_manifest_data)
                if isinstance(prev_manifest_data, dict)
                else prev_manifest_data
            )
            if isinstance(raw_clips, list):
                for c in raw_clips:
                    if isinstance(c, dict) and "id" in c:
                        existing_manifest_clips[c["id"]] = c
        except Exception:
            existing_manifest_clips = {}

    # 4. Etapa 5: Render clips
    can_burn = has_subtitles_filter(ffmpeg_bin)
    words = flatten_words_with_segment(transcript)
    matches_map = {m["id"]: m for m in matches}

    try:
        video_stat = video_path.stat()
        video_sig = f"{video_stat.st_size}:{getattr(video_stat, 'st_mtime_ns', video_stat.st_mtime)}"
    except Exception:
        video_sig = str(video_path)

    rendered_count = 0
    skipped_count = 0
    manifest_clips = []
    for clip in plan:
        cid = clip["id"]
        start, end = clip.get("start"), clip.get("end")
        if start is None or end is None:
            manifest_clips.append(
                {
                    "id": cid,
                    "path": None,
                    "start": None,
                    "end": None,
                    "duration": None,
                    "state": "skipped",
                    "source_signature": None,
                    "needs_review": True,
                    "notes": clip.get("note") or "Sin ventana de corte calculada",
                }
            )
            continue

        match = matches_map.get(cid)
        cues = build_cues(clip, match, words, max_words_per_line)
        srt_path = clips_dir / f"{cid}.srt"
        new_srt_content = build_srt_content(cues, start)

        out_path = clips_dir / f"{cid}.mp4"
        prev_entry = existing_manifest_clips.get(cid, {})

        srt_hash = hashlib.sha256(new_srt_content.encode("utf-8")).hexdigest()[:16]
        current_sig = f"{video_sig}:{start}:{end}:{srt_hash}"

        # Determinar si se puede omitir el re-render:
        # Solo re-renderizar si el estado previo no es 'done' (o 'rendered') o si cambió la firma de origen / timestamps
        prev_state = prev_entry.get("state")
        prev_sig = prev_entry.get("source_signature")

        sig_matches = (prev_sig == current_sig) if prev_sig else (
            prev_entry.get("start") == start and prev_entry.get("end") == end
        )

        can_skip = (
            out_path.is_file()
            and out_path.stat().st_size > 0
            and srt_path.is_file()
            and prev_state in ("done", "rendered")
            and sig_matches
        )
        if can_skip:
            try:
                if srt_path.read_text(encoding="utf-8") != new_srt_content:
                    can_skip = False
            except Exception:
                can_skip = False

        if not can_skip:
            write_srt(cues, start, srt_path)
            render_clip(
                ffmpeg_bin,
                video_path,
                clip,
                srt_path,
                out_path,
                font_size,
                burn_subtitles=can_burn,
            )
            rendered_count += 1
        else:
            skipped_count += 1

        # 5. Etapa 6: Generate metadata
        context = read_srt_text(srt_path)
        meta = generate_metadata(clip, context)
        txt_path = clips_dir / f"{cid}.txt"
        txt_content = render_metadata(clip, meta, bool(context))
        if not txt_path.exists() or txt_path.read_text(encoding="utf-8") != txt_content:
            txt_path.write_text(txt_content, encoding="utf-8")

        note_parts = []
        if clip.get("note"):
            note_parts.append(str(clip["note"]))
        if not can_burn:
            note_parts.append("ffmpeg sin filtro subtitles: subtítulos no quemados en video")

        state = "done"
        manifest_clips.append(
            {
                "id": cid,
                "path": f"clips/{cid}.mp4",
                "start": start,
                "end": end,
                "duration": clip.get("duration"),
                "state": state,
                "source_signature": current_sig,
                "needs_review": bool(clip.get("needs_review")),
                "notes": "; ".join(note_parts) if note_parts else None,
            }
        )

    manifest_data = {"clips": manifest_clips}
    _write_json_if_changed(output_dir / "manifest.json", manifest_data)
    return manifest_data


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--guion", required=True, type=Path, help="Ruta al guion .md (Etapa 1)")
    parser.add_argument(
        "--transcript", required=True, type=Path, help="Ruta a transcript.json de WhisperX (Etapa 2)"
    )
    parser.add_argument("--video", required=True, type=Path, help="Video fuente del que se cortan los clips")
    parser.add_argument("--output", required=True, type=Path, help="Directorio de salida para todos los artefactos")
    parser.add_argument(
        "--min-duration",
        type=float,
        default=2.0,
        help="Duración mínima en segundos de un clip (default: 2.0)",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=90.0,
        help="Ventana de búsqueda de matching en segundos (default: 90.0)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=75.0,
        help="Score mínimo para matching confiable (default: 75.0)",
    )
    parser.add_argument(
        "--cap",
        type=float,
        default=70.0,
        help="Tope de retroceso en segundos desde la cita (default: 70.0)",
    )
    parser.add_argument(
        "--tail-max-gap",
        type=float,
        default=2.0,
        help="Pausa máxima (s) para incluir oración siguiente como remate (default: 2.0)",
    )
    parser.add_argument(
        "--tail-max-dur",
        type=float,
        default=8.0,
        help="Duración máxima (s) de la oración de remate (default: 8.0)",
    )
    parser.add_argument("--font-size", type=int, default=28, help="Tamaño de fuente de subtítulos")
    parser.add_argument(
        "--max-words-per-line", type=int, default=10, help="Máximo de palabras por línea en SRT"
    )
    parser.add_argument(
        "--ffmpeg", default=DEFAULT_FFMPEG, help="Ruta o binario de ffmpeg a utilizar"
    )
    parser.add_argument(
        "--edits", type=Path, default=None, help="Ruta a archivo opcional edits.json con modificaciones"
    )
    args = parser.parse_args()

    for p in (args.guion, args.transcript, args.video):
        if not p.is_file():
            print(f"Error: no existe el archivo requerido: {p}", file=sys.stderr)
            return 1

    if shutil.which(args.ffmpeg) is None and not Path(args.ffmpeg).exists():
        print(f"Error: no se encontró el binario ffmpeg en '{args.ffmpeg}'.", file=sys.stderr)
        return 1

    try:
        manifest = run_pipeline(
            guion_path=args.guion,
            transcript_path=args.transcript,
            video_path=args.video,
            output_dir=args.output,
            min_duration=args.min_duration,
            window=args.window,
            threshold=args.threshold,
            cap=args.cap,
            tail_max_gap=args.tail_max_gap,
            tail_max_dur=args.tail_max_dur,
            font_size=args.font_size,
            max_words_per_line=args.max_words_per_line,
            ffmpeg_bin=args.ffmpeg,
            edits_path=args.edits,
        )
    except Exception as exc:
        print(f"Error durante la ejecución del pipeline: {exc}", file=sys.stderr)
        return 1

    clips = manifest.get("clips", [])
    rendered = [c for c in clips if c.get("state") in ("done", "rendered", "needs_review") and c.get("path")]
    print(f"Pipeline completado con éxito en {args.output}.")
    print(f"{len(rendered)} clip(s) procesados de {len(clips)} candidato(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
