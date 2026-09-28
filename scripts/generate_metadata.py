#!/usr/bin/env python3
"""Etapa 6 del pipeline de ClipFactory: genera metadata (título + descripción) por clip.

Lee clip_plan.json (Etapa 4) y, si existe, el .srt de cada clip (Etapa 5, mismo
directorio) como contexto adicional. Por cada clip sin needs_review, genera un título
gancho (a partir de la cita [CÁMARA B] del guion) y una descripción corta con CTA
genérico y espacio para hashtags, listos para copiar/pegar al subir el clip.

Decisión de diseño (ver PIPELINE.md § Etapa 6 y output/_research/metadata/ para el
detalle de la investigación): generación por plantilla determinista, sin dependencias
ni llamadas a un LLM. Se investigó un modo con LLM local (Ollama, qwen2.5:3b corriendo
en el server `athena`) y el resultado fue peor que la plantilla en los 4 casos de
prueba, incluyendo una alucinación (una promesa inventada que no estaba en la fuente).
No es seguro para publicar sin revisión humana estricta, así que no se promovió a este
script de producción; queda disponible como herramienta exploratoria opcional en
`output/_research/metadata/generate_metadata_ollama.py`.

Output: por clip, `<id>.txt` en --output-dir (default: junto a clip_plan.json / clips,
al lado de <id>.mp4 y <id>.srt de la Etapa 5).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAX_TITLE_LENGTH = 69
CTA = "¿Qué opinás? Contámelo en comentarios y seguí la cuenta para ver más."
HASHTAGS_PLACEHOLDER = "#agregar #hashtags #relevantes"


def read_srt_text(path: Path) -> str:
    """Devuelve solo el diálogo de un SRT, sin índices ni timestamps."""
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return " ".join(
        line.strip()
        for line in lines
        if line.strip() and not line.strip().isdigit() and "-->" not in line
    )


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split()).strip(" .")
    if len(text) <= limit:
        return text
    return text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def generate_metadata(clip: dict, context: str) -> dict[str, str]:
    quote = " ".join(str(clip.get("quote") or "").split())
    block = str(clip.get("block") or "el video")

    title = shorten(quote, MAX_TITLE_LENGTH) if quote else shorten(f"Un momento clave de {block}", MAX_TITLE_LENGTH)
    # La cita es el texto editorialmente elegido (Etapa 1); el SRT es contexto crudo de
    # todo el clip y puede arrancar lejos del punto interesante en clips largos, así que
    # solo se usa como respaldo si no hay cita.
    lead = quote if quote else (shorten(context, 220) if context else f"Un fragmento de {block}.")

    description = "\n".join((lead, CTA, HASHTAGS_PLACEHOLDER))
    return {"title": title, "description": description}


def render_metadata(clip: dict, metadata: dict[str, str], used_srt: bool) -> str:
    return (
        f"TÍTULO\n{metadata['title']}\n\n"
        f"DESCRIPCIÓN\n{metadata['description']}\n\n"
        f"ORIGEN\nClip: {clip['id']} | Sección: {clip.get('block') or '-'} | "
        f"Contexto SRT: {'sí' if used_srt else 'no'}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip_plan", type=Path, help="Ruta a clip_plan.json (Etapa 4)")
    parser.add_argument(
        "--output-dir", type=Path, default=None, help="Carpeta de salida (default: junto a clip_plan.json / clips)"
    )
    parser.add_argument("--ids", nargs="*", default=None, help="Si se pasa, solo procesa estos ids")
    args = parser.parse_args()

    if not args.clip_plan.is_file():
        print(f"Error: no existe {args.clip_plan}", file=sys.stderr)
        return 1

    clip_plan = json.loads(args.clip_plan.read_text(encoding="utf-8"))
    output_dir = args.output_dir or (args.clip_plan.parent / "clips")
    output_dir.mkdir(parents=True, exist_ok=True)

    ids_filter = set(args.ids) if args.ids else None

    done, skipped = [], []
    for clip in clip_plan:
        cid = clip["id"]
        if ids_filter is not None and cid not in ids_filter:
            continue
        if clip.get("start") is None or clip.get("end") is None:
            skipped.append(cid)
            continue

        srt_path = output_dir / f"{cid}.srt"
        context = read_srt_text(srt_path)
        metadata = generate_metadata(clip, context)
        (output_dir / f"{cid}.txt").write_text(
            render_metadata(clip, metadata, bool(context)), encoding="utf-8"
        )
        done.append(cid)

    print(f"{len(done)} metadata(s) generada(s) en {output_dir}: {done}")
    if skipped:
        print(f"{len(skipped)} omitido(s) (sin start/end): {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
