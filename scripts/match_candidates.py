#!/usr/bin/env python3
"""Etapa 3 del pipeline de ClipFactory: fuzzy-match de candidatos contra la transcripción real.

Lee el candidates.json de la Etapa 1 (frases marcadas [CÁMARA B] en el guion, con un
timestamp ESTIMADO por posición proporcional de palabras) y el transcript.json que produce
WhisperX en la Etapa 2 (timestamps reales por palabra, con score de alineación), y para cada
candidato busca la subsecuencia de palabras del transcript que mejor calza con la cita.

La búsqueda se restringe a una ventana de tiempo alrededor de estimated_ts_sec (± --window
segundos) para evitar falsos positivos si una frase parecida aparece más de una vez en el
video. Si el score de similaridad (rapidfuzz, 0-100) queda debajo de --threshold, el
candidato se marca needs_review en vez de asumir un corte silencioso mal ubicado.

Requiere rapidfuzz (instalado en el venv del proyecto: .venv/bin/python3 -m pip install
rapidfuzz, o `uv pip install --python .venv rapidfuzz`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

try:
    from rapidfuzz import fuzz
except ImportError:
    import difflib

    class _FuzzShim:
        @staticmethod
        def ratio(s1: str, s2: str) -> float:
            return difflib.SequenceMatcher(None, s1, s2).ratio() * 100.0

    fuzz = _FuzzShim()

WORD_LEN_SLACK = 3  # además de +-2, probamos algunas variantes más largas/cortas

PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
SPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = PUNCT_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def flatten_words(transcript: dict) -> list[dict]:
    """Todas las palabras del transcript, en orden, tal como las emite WhisperX.

    Se usa segments[].words en vez de word_segments porque WhisperX puede omitir de
    word_segments las palabras que no consiguió alinear (ver README.md, "Hueco
    documentado"); segments[].words conserva esas palabras (sin start/end) para que el
    texto de matching no tenga huecos, aunque no sirvan como ancla temporal.
    """
    words = []
    for seg in transcript.get("segments", []):
        words.extend(seg.get("words", []))
    if not words:
        words = transcript.get("word_segments", [])
    return words


def fill_approx_times(words: list[dict]) -> list[float | None]:
    """Devuelve un 'start' aproximado por palabra, rellenando huecos con el vecino más cercano."""
    approx: list[float | None] = [w.get("start") for w in words]
    last_known = None
    for i, t in enumerate(approx):
        if t is not None:
            last_known = t
        elif last_known is not None:
            approx[i] = last_known
    next_known = None
    for i in range(len(approx) - 1, -1, -1):
        if approx[i] is not None:
            next_known = approx[i]
        elif next_known is not None:
            approx[i] = next_known
    return approx


def best_match(
    quote: str,
    words: list[dict],
    approx_times: list[float | None],
    lo: float,
    hi: float,
) -> dict:
    quote_norm = normalize(quote)
    n = len(quote.split())
    if not quote_norm or n == 0:
        return {"score": 0.0, "start": None, "end": None, "matched_text": None}

    candidate_starts = [
        i for i, t in enumerate(approx_times) if t is not None and lo <= t <= hi
    ]
    if not candidate_starts:
        return {"score": 0.0, "start": None, "end": None, "matched_text": None}

    lengths = range(1, n + WORD_LEN_SLACK + 1)
    best = {"score": -1.0, "start": None, "end": None, "matched_text": None}
    for i in candidate_starts:
        for length in lengths:
            j = i + length  # exclusivo
            if j > len(words):
                break
            span = words[i:j]
            text_norm = normalize(" ".join(w["word"] for w in span))
            if not text_norm:
                continue
            score = fuzz.ratio(quote_norm, text_norm)
            if score > best["score"]:
                start = next((w["start"] for w in span if w.get("start") is not None), None)
                end = next(
                    (w["end"] for w in reversed(span) if w.get("end") is not None), None
                )
                best = {
                    "score": round(score, 1),
                    "start": start,
                    "end": end,
                    "matched_text": " ".join(w["word"] for w in span),
                }
    if best["score"] < 0:
        return {"score": 0.0, "start": None, "end": None, "matched_text": None}
    return best


def match_candidates(
    candidates: list[dict], transcript: dict, window: float, threshold: float
) -> list[dict]:
    words = flatten_words(transcript)
    if not words:
        raise ValueError("El transcript no tiene palabras (¿segments/word_segments vacíos?).")
    approx_times = fill_approx_times(words)

    matches = []
    for cand in candidates:
        ts = cand["estimated_ts_sec"]
        lo, hi = ts - window, ts + window
        result = best_match(cand["quote"], words, approx_times, lo, hi)
        needs_review = result["score"] < threshold or result["start"] is None
        matches.append(
            {
                "id": cand["id"],
                "block": cand.get("block"),
                "quote": cand["quote"],
                "estimated_ts_sec": ts,
                "match_start_sec": result["start"],
                "match_end_sec": result["end"],
                "score": result["score"],
                "matched_text": result["matched_text"],
                "needs_review": needs_review,
            }
        )
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", type=Path, help="Ruta a candidates.json (Etapa 1)")
    parser.add_argument("transcript", type=Path, help="Ruta a transcript.json de WhisperX (Etapa 2)")
    parser.add_argument(
        "--window",
        type=float,
        default=90.0,
        help="Ventana de búsqueda en segundos alrededor de estimated_ts_sec (default: 90)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=75.0,
        help=(
            "Score mínimo (0-100, rapidfuzz.fuzz.ratio) para no marcar needs_review "
            "(default: 75, valor inicial sin validar contra un lote real todavía)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Ruta de salida de matches.json (default: junto a candidates.json)",
    )
    args = parser.parse_args()

    if not args.candidates.exists():
        print(f"Error: no existe {args.candidates}", file=sys.stderr)
        return 1
    if not args.transcript.exists():
        print(f"Error: no existe {args.transcript}", file=sys.stderr)
        return 1

    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    transcript = json.loads(args.transcript.read_text(encoding="utf-8"))

    try:
        matches = match_candidates(candidates, transcript, args.window, args.threshold)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path = args.output or (args.candidates.parent / "matches.json")
    output_path.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")

    n_review = sum(1 for m in matches if m["needs_review"])
    print(f"{len(matches)} candidato(s) procesado(s) -> {output_path}")
    print(f"{n_review} marcado(s) needs_review de {len(matches)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
