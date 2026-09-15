#!/usr/bin/env python3
"""Etapa 1 del pipeline de ClipFactory: extrae candidatos a clip de un guion de Athena.

Lee un guion aprobado (markdown con encabezados '# Bloque N' y marcas '[CÁMARA B]',
terminado en la línea '[Duración total estimada: N min]') y produce un candidates.json
con, por cada marca [CÁMARA B]: la frase siguiente (la cita candidata a clip), el bloque
al que pertenece, y un timestamp estimado.

El timestamp estimado es una PISTA de búsqueda para la Etapa 3 (fuzzy-match contra la
transcripción real de WhisperX), no un timestamp final. Se calcula proporcional a la
posición de la marca en el conteo total de palabras habladas del guion (no por índice de
sección, a diferencia de PublicationKitBuilder de Athena, porque un bloque puede tener
varias marcas y necesitamos distinguir su posición relativa dentro del bloque).

No requiere dependencias externas (solo stdlib) ni toca AthenaFramework: el guion entra
como archivo de texto plano copiado/exportado a ClipFactory/guiones/.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MARKER = "[CÁMARA B]"
HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
DURATION_RE = re.compile(r"\[Duraci[oó]n total estimada:\s*(\d+)\s*min\]", re.IGNORECASE)
WORD_RE = re.compile(r"\S+")
NEXT_PARAGRAPH_RE = re.compile(r"\S.*?(?=\n\s*\n|\Z)", re.DOTALL)


class GuionFormatError(ValueError):
    """El guion no respeta el contrato de formato que produce Athena's ScriptPipeline."""


def parse_guion(text: str) -> list[dict]:
    duration_match = DURATION_RE.search(text)
    if not duration_match:
        raise GuionFormatError(
            "No se encontró la línea '[Duración total estimada: N min]'. "
            "¿Es el guion completo tal como lo exporta Athena?"
        )
    minutes = int(duration_match.group(1))
    total_seconds = minutes * 60

    # El texto hablado es todo lo anterior a la línea de duración.
    body = text[: duration_match.start()]

    headings = [(m.start(), m.group(1).strip()) for m in HEADING_RE.finditer(body)]
    if not headings:
        raise GuionFormatError("El guion no contiene encabezados '# Bloque'/'# Hook'/etc.")

    def block_for_offset(offset: int) -> str:
        current = None
        for pos, name in headings:
            if pos <= offset:
                current = name
            else:
                break
        return current or "(antes del primer encabezado)"

    words = list(WORD_RE.finditer(body))
    total_words = len(words)
    if total_words == 0:
        raise GuionFormatError("El guion no tiene texto hablado.")

    def cumulative_words_before(offset: int) -> int:
        # Guiones son cortos (unos pocos miles de palabras); lineal es suficiente.
        count = 0
        for w in words:
            if w.start() >= offset:
                break
            count += 1
        return count

    marker_positions = [m.start() for m in re.finditer(re.escape(MARKER), body)]
    if not marker_positions:
        raise GuionFormatError(f"El guion no contiene ninguna marca '{MARKER}'.")

    candidates = []
    skipped = 0
    for i, pos in enumerate(marker_positions, start=1):
        after = body[pos + len(MARKER) :]
        match = NEXT_PARAGRAPH_RE.search(after)
        quote = re.sub(r"\s+", " ", match.group(0)).strip() if match else ""

        if not quote or quote.startswith(MARKER):
            print(
                f"ADVERTENCIA: marca {MARKER} #{i} sin frase siguiente "
                "(¿dos marcas consecutivas o marca al final del guion?). Se omite.",
                file=sys.stderr,
            )
            skipped += 1
            continue

        cum_words = cumulative_words_before(pos)
        estimated_ts = round(total_seconds * cum_words / total_words, 1)
        candidates.append(
            {
                "id": f"c{len(candidates) + 1}",
                "block": block_for_offset(pos),
                "quote": quote,
                "estimated_ts_sec": estimated_ts,
            }
        )

    if skipped:
        print(f"Total omitidas: {skipped}. Candidatas válidas: {len(candidates)}.", file=sys.stderr)

    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("guion", type=Path, help="Ruta al guion .md (ej. ClipFactory/guiones/<video-id>.md)")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Ruta de salida del candidates.json (default: ClipFactory/output/<stem>/candidates.json)",
    )
    args = parser.parse_args()

    if not args.guion.exists():
        print(f"Error: no existe el archivo {args.guion}", file=sys.stderr)
        return 1

    text = args.guion.read_text(encoding="utf-8")

    try:
        candidates = parse_guion(text)
    except GuionFormatError as exc:
        print(f"Error de formato: {exc}", file=sys.stderr)
        return 1

    output_path = args.output
    if output_path is None:
        repo_root = Path(__file__).resolve().parent.parent
        output_path = repo_root / "output" / args.guion.stem / "candidates.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{len(candidates)} candidato(s) escrito(s) en {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
