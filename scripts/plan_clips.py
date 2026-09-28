#!/usr/bin/env python3
"""Etapa 4 del pipeline de ClipFactory: arma la ventana de corte de cada clip.

Lee matches.json (Etapa 3: timestamp real de cada cita, con needs_review de los que no
tienen match confiable) y transcript.json (Etapa 2: WhisperX, con segments[] ya separados
por oración/pausa) y para cada match calcula la ventana final del clip:

- retrocede desde match_start_sec hasta el límite de oración más lejano que no supere
  --cap segundos hacia atrás (aproximación del "inicio del Bloque" — v1 no tiene el
  timestamp real del inicio de Bloque, solo el de cada cita marcada, así que el tope de
  duración hace ese trabajo; ver nota en PIPELINE.md § Etapa 4);
- avanza desde match_end_sec hasta el final de esa oración, y si la oración siguiente
  empieza a pocos segundos (--tail-max-gap) y es corta (--tail-max-dur), la incluye como
  remate/payoff;
- recorta contra el clip vecino (anterior/siguiente por tiempo) para que dos clips nunca
  se superpongan, y contra los bordes del video.

Los candidatos con needs_review=true en matches.json (o sin match_start_sec) se pasan sin
ventana calculada — no se corta a ciegas sobre un match que Etapa 3 ya marcó como dudoso.

Output: clip_plan.json — lista de {id, block, quote, start, end, duration, needs_review, note}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_segments(transcript: dict) -> list[dict]:
    segs = sorted(transcript.get("segments", []), key=lambda s: s["start"])
    if not segs:
        raise ValueError("El transcript no tiene segments[].")
    return segs


def segment_containing(segs: list[dict], t: float) -> tuple[int, dict] | tuple[None, None]:
    for i, s in enumerate(segs):
        if s["start"] <= t <= s["end"]:
            return i, s
    return None, None


def raw_start(match_start: float, segs: list[dict], cap: float) -> float:
    limit = max(0.0, match_start - cap)
    boundaries = [s["start"] for s in segs if limit <= s["start"] <= match_start]
    if boundaries:
        return min(boundaries)
    return limit


def raw_end(
    match_end: float, segs: list[dict], video_end: float, tail_max_gap: float, tail_max_dur: float
) -> float:
    idx, containing = segment_containing(segs, match_end)
    end = containing["end"] if containing else match_end
    end = min(end, video_end)
    if idx is not None and idx + 1 < len(segs):
        nxt = segs[idx + 1]
        gap = nxt["start"] - end
        dur = nxt["end"] - nxt["start"]
        if 0 <= gap <= tail_max_gap and dur <= tail_max_dur and nxt["end"] <= video_end:
            end = nxt["end"]
    return end


def plan_clips(
    matches: list[dict],
    transcript: dict,
    cap: float,
    tail_max_gap: float,
    tail_max_dur: float,
    min_duration: float,
) -> list[dict]:
    segs = load_segments(transcript)
    video_end = segs[-1]["end"]

    usable = [m for m in matches if m.get("match_start_sec") is not None]
    usable.sort(key=lambda m: m["match_start_sec"])

    windows: dict[str, dict] = {}
    for m in usable:
        windows[m["id"]] = {
            "start": raw_start(m["match_start_sec"], segs, cap),
            "end": raw_end(m["match_end_sec"], segs, video_end, tail_max_gap, tail_max_dur),
        }

    # Recorte contra vecinos por orden temporal, para que ningún par se superponga.
    for i, m in enumerate(usable):
        w = windows[m["id"]]
        if i > 0:
            prev_end = windows[usable[i - 1]["id"]]["end"]
            w["start"] = max(w["start"], min(prev_end, m["match_start_sec"]))
        if i + 1 < len(usable):
            next_start = windows[usable[i + 1]["id"]]["start"]
            w["end"] = min(w["end"], max(next_start, m["match_end_sec"]))

    plan = []
    for m in matches:
        base = {
            "id": m["id"],
            "block": m.get("block"),
            "quote": m.get("quote"),
        }
        if m["id"] not in windows:
            plan.append(
                {
                    **base,
                    "start": None,
                    "end": None,
                    "duration": None,
                    "needs_review": True,
                    "note": "sin match confiable en Etapa 3, no se calculó ventana de corte",
                }
            )
            continue

        w = windows[m["id"]]
        start, end = w["start"], w["end"]
        duration = round(end - start, 2)
        needs_review = bool(m.get("needs_review"))
        note = None
        if duration < min_duration:
            needs_review = True
            note = f"duración {duration}s por debajo de min_duration ({min_duration}s), revisar solapamiento con clips vecinos"

        plan.append(
            {
                **base,
                "start": round(start, 2),
                "end": round(end, 2),
                "duration": duration,
                "needs_review": needs_review,
                "note": note,
            }
        )
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matches", type=Path, help="Ruta a matches.json (Etapa 3)")
    parser.add_argument("transcript", type=Path, help="Ruta a transcript.json de WhisperX (Etapa 2)")
    parser.add_argument(
        "--cap", type=float, default=70.0, help="Tope de retroceso en segundos desde la cita (default: 70)"
    )
    parser.add_argument(
        "--tail-max-gap",
        type=float,
        default=2.0,
        help="Pausa máxima (s) para incluir la oración siguiente como remate (default: 2)",
    )
    parser.add_argument(
        "--tail-max-dur",
        type=float,
        default=8.0,
        help="Duración máxima (s) de esa oración de remate (default: 8)",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=5.0,
        help="Duración mínima (s) del clip; por debajo se marca needs_review (default: 5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Ruta de salida de clip_plan.json (default: junto a matches.json)",
    )
    args = parser.parse_args()

    if not args.matches.exists():
        print(f"Error: no existe {args.matches}", file=sys.stderr)
        return 1
    if not args.transcript.exists():
        print(f"Error: no existe {args.transcript}", file=sys.stderr)
        return 1

    matches = json.loads(args.matches.read_text(encoding="utf-8"))
    transcript = json.loads(args.transcript.read_text(encoding="utf-8"))

    try:
        plan = plan_clips(
            matches, transcript, args.cap, args.tail_max_gap, args.tail_max_dur, args.min_duration
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path = args.output or (args.matches.parent / "clip_plan.json")
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    n_review = sum(1 for c in plan if c["needs_review"])
    print(f"{len(plan)} clip(s) planificado(s) -> {output_path}")
    print(f"{n_review} marcado(s) needs_review de {len(plan)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
