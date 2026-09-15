#!/usr/bin/env python3
"""Etapa 5 del pipeline de ClipFactory: corta cada clip y quema captions.

Lee clip_plan.json (Etapa 4), matches.json (Etapa 3) y transcript.json (Etapa 2), y por
cada clip sin needs_review:

1. Arma un .srt mezclando dos fuentes de texto (decisión tomada 2026-08-11, ver
   PIPELINE.md § Etapa 5):
   - la cita marcada [CÁMARA B] usa el texto del GUION (ya validado en Etapa 3), como una
     sola línea que cubre [match_start_sec, match_end_sec];
   - el resto del clip (contexto antes/después) usa la TRANSCRIPCIÓN CRUDA de WhisperX,
     agrupada por oración (segments[] de WhisperX) y partida en líneas de máximo
     --max-words-per-line palabras. Puede traer errores de ASR ocasionales — riesgo
     aceptado a cambio de no requerir alinear todo el guion contra el audio real.
2. Corta el clip del video fuente (`ffmpeg -ss start -to end`) y quema el .srt con el
   filtro `subtitles` (requiere libass — el ffmpeg de Homebrew por defecto NO lo trae,
   hace falta `brew install ffmpeg-full`; ver nota de infraestructura en ARRANQUE.md).

Los clips con needs_review=true se listan en el resumen pero no se procesan — necesitan
revisión humana antes de tener un timestamp confiable para cortar.

Output: por clip, `<id>.srt` y `<id>.mp4` en --output-dir.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_FFMPEG = "ffmpeg"


def fmt_srt_time(t: float) -> str:
    t = max(0.0, t)
    hh = int(t // 3600)
    mm = int((t % 3600) // 60)
    ss = int(t % 60)
    ms = round((t - int(t)) * 1000)
    if ms == 1000:
        ms = 0
        ss += 1
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def flatten_words_with_segment(transcript: dict) -> list[dict]:
    words = []
    for seg_idx, seg in enumerate(transcript.get("segments", [])):
        for w in seg.get("words", []):
            if w.get("start") is None or w.get("end") is None:
                continue
            words.append({"word": w["word"], "start": w["start"], "end": w["end"], "seg_idx": seg_idx})
    words.sort(key=lambda w: w["start"])
    return words


def overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return a_start < b_end and b_start < a_end


def build_cues(
    clip: dict, match: dict, words: list[dict], max_words_per_line: int
) -> list[dict]:
    clip_start, clip_end = clip["start"], clip["end"]
    quote_start, quote_end = match.get("match_start_sec"), match.get("match_end_sec")

    clip_words = [w for w in words if clip_start <= w["start"] < clip_end]

    cues = []
    context_run: list[dict] = []

    def flush_context():
        if not context_run:
            return
        for i in range(0, len(context_run), max_words_per_line):
            chunk = context_run[i : i + max_words_per_line]
            cues.append(
                {
                    "start": max(clip_start, chunk[0]["start"]),
                    "end": min(clip_end, chunk[-1]["end"]),
                    "text": " ".join(w["word"] for w in chunk),
                }
            )
        context_run.clear()

    quote_emitted = False
    last_seg_idx = None
    for w in clip_words:
        in_quote = quote_start is not None and overlaps(w["start"], w["end"], quote_start, quote_end)
        if in_quote:
            flush_context()
            if not quote_emitted:
                cues.append(
                    {
                        "start": max(clip_start, quote_start),
                        "end": min(clip_end, quote_end),
                        "text": match["quote"],
                    }
                )
                quote_emitted = True
            continue
        if last_seg_idx is not None and w["seg_idx"] != last_seg_idx:
            flush_context()
        context_run.append(w)
        last_seg_idx = w["seg_idx"]
    flush_context()

    cues.sort(key=lambda c: c["start"])
    return cues


def write_srt(cues: list[dict], clip_start: float, path: Path) -> None:
    lines = []
    for i, cue in enumerate(cues, start=1):
        start = cue["start"] - clip_start
        end = cue["end"] - clip_start
        if end <= start:
            continue
        lines.append(str(i))
        lines.append(f"{fmt_srt_time(start)} --> {fmt_srt_time(end)}")
        lines.append(cue["text"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def escape_ffmpeg_filter_path(path: Path) -> str:
    s = str(path.resolve())
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def render_clip(
    ffmpeg: str, video: Path, clip: dict, srt_path: Path, out_path: Path, font_size: int
) -> None:
    vf = f"subtitles={escape_ffmpeg_filter_path(srt_path)}:force_style='FontSize={font_size},Alignment=2,MarginV=60'"
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        str(clip["start"]),
        "-to",
        str(clip["end"]),
        "-i",
        str(video),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip_plan", type=Path, help="Ruta a clip_plan.json (Etapa 4)")
    parser.add_argument("matches", type=Path, help="Ruta a matches.json (Etapa 3)")
    parser.add_argument("transcript", type=Path, help="Ruta a transcript.json de WhisperX (Etapa 2)")
    parser.add_argument("video", type=Path, help="Video fuente del que se cortan los clips")
    parser.add_argument("--output-dir", type=Path, default=None, help="Carpeta de salida (default: junto a clip_plan.json / clips)")
    parser.add_argument("--max-words-per-line", type=int, default=10)
    parser.add_argument("--font-size", type=int, default=28)
    parser.add_argument("--ffmpeg", default=DEFAULT_FFMPEG, help="Ruta al binario de ffmpeg (necesita libass)")
    parser.add_argument("--ids", nargs="*", default=None, help="Si se pasa, solo procesa estos ids")
    args = parser.parse_args()

    for p in (args.clip_plan, args.matches, args.transcript, args.video):
        if not p.exists():
            print(f"Error: no existe {p}", file=sys.stderr)
            return 1

    if shutil.which(args.ffmpeg) is None and not Path(args.ffmpeg).exists():
        print(f"Error: no se encontró el binario ffmpeg en '{args.ffmpeg}'.", file=sys.stderr)
        return 1

    clip_plan = json.loads(args.clip_plan.read_text(encoding="utf-8"))
    matches = {m["id"]: m for m in json.loads(args.matches.read_text(encoding="utf-8"))}
    transcript = json.loads(args.transcript.read_text(encoding="utf-8"))
    words = flatten_words_with_segment(transcript)

    output_dir = args.output_dir or (args.clip_plan.parent / "clips")
    output_dir.mkdir(parents=True, exist_ok=True)

    ids_filter = set(args.ids) if args.ids else None

    done, skipped, failed = [], [], []
    for clip in clip_plan:
        cid = clip["id"]
        if ids_filter is not None and cid not in ids_filter:
            continue
        if clip.get("needs_review") or clip.get("start") is None:
            skipped.append(cid)
            continue
        match = matches.get(cid)
        if match is None:
            print(f"ADVERTENCIA: {cid} no tiene entrada en matches.json, se omite.", file=sys.stderr)
            skipped.append(cid)
            continue

        cues = build_cues(clip, match, words, args.max_words_per_line)
        srt_path = output_dir / f"{cid}.srt"
        write_srt(cues, clip["start"], srt_path)

        out_path = output_dir / f"{cid}.mp4"
        try:
            render_clip(args.ffmpeg, args.video, clip, srt_path, out_path, args.font_size)
            done.append(cid)
        except subprocess.CalledProcessError as exc:
            print(f"ERROR cortando {cid}: {exc.stderr[-2000:]}", file=sys.stderr)
            failed.append(cid)

    print(f"{len(done)} clip(s) renderizado(s) en {output_dir}: {done}")
    if skipped:
        print(f"{len(skipped)} omitido(s) (needs_review o sin match): {skipped}")
    if failed:
        print(f"{len(failed)} fallido(s): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
