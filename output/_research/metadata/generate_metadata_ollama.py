#!/usr/bin/env python3
"""Genera metadata de clips con Ollama local y fallback deterministico.

Pensado para ejecutarse en Athena, donde Ollama escucha en localhost:11434:
  python3 generate_metadata_ollama.py clip_plan.json --output-dir preview
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


OLLAMA_URL = "http://localhost:11434/api/generate"
MAX_TITLE_LENGTH = 69
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["title", "description"],
    "additionalProperties": False,
}


def read_srt(path: Path) -> str:
    if not path.exists():
        return ""
    return " ".join(
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.strip().isdigit() and "-->" not in line
    )


def shorten(text: str, limit: int = MAX_TITLE_LENGTH) -> str:
    text = " ".join(text.split()).strip(" .")
    if len(text) <= limit:
        return text
    return text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def generate_via_template(clip: dict, context: str) -> dict[str, str]:
    """Mismas reglas del prototipo template; respaldo sin Ollama."""
    quote = " ".join(str(clip.get("quote") or "").split())
    block = str(clip.get("block") or "el video")
    source = f"{quote} {context}".casefold()
    if "singularidad tecnologica" in source or "singularidad tecnológica" in source:
        title = "¿La IA podría provocar una singularidad tecnológica?"
        lead = (
            "Los LLM actuales reabren el debate sobre una IA capaz de igualar "
            "o superar la inteligencia humana y sus posibles consecuencias."
        )
    elif "ia general" in source and (
        "capacidades humanas" in source or "inteligencia humana" in source
    ):
        title = "¿Qué pasaría si la IA supera la inteligencia humana?"
        lead = (
            "La IA débil ya resuelve tareas específicas; la IA general sigue "
            "siendo hipotética y podría exceder nuestras capacidades."
        )
    elif "unesco" in source:
        title = "¿Qué es la inteligencia artificial según la UNESCO?"
        lead = (
            "La IA ya media muchas tareas cotidianas. Esta definición de la "
            "UNESCO explica qué tienen en común esos sistemas."
        )
    elif all(name in source for name in ("chatgpt", "copilot", "gemini", "claude")):
        title = "ChatGPT, Copilot, Gemini y Claude: ¿qué tienen en común?"
        lead = (
            "Los modelos generativos aprenden patrones para crear contenido "
            "nuevo. Estos son cuatro de sus ejemplos más conocidos."
        )
    else:
        title = shorten(f"La idea clave de {block}: {quote}")
        lead = f"En este fragmento de {block} exploramos una idea clave: {shorten(context or quote, 180)}"
    return {
        "title": shorten(title),
        "description": "\n".join(
            (
                lead,
                "¿Qué opinas? Cuéntamelo en comentarios y sigue la cuenta para ver más.",
                "#IA #InteligenciaArtificial #Tecnología",
            )
        ),
    }


def validate(raw: str) -> dict[str, str]:
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"title", "description"}:
        raise ValueError("el JSON no contiene exactamente title y description")
    title, description = value["title"], value["description"]
    if not isinstance(title, str) or not isinstance(description, str):
        raise ValueError("title y description deben ser texto")
    title = " ".join(title.split()).strip()
    description = description.replace("\\n", "\n").strip()
    hashtags = re.findall(r"(?<!\w)#[\wÁÉÍÓÚÜÑáéíóúüñ]+", description)
    body = re.sub(r"(?<!\w)#[\wÁÉÍÓÚÜÑáéíóúüñ]+", "", description).strip()
    if not body:
        raise ValueError("description no contiene resumen")
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if len(lines) == 1:
        lines = [part.strip() for part in re.split(r"(?<=[.!?])\s+", body) if part.strip()]
    if len(lines) > 3:
        lines = lines[:2] + [" ".join(lines[2:])]
    has_cta = bool(
        re.search(
            r"\b(comenta|cu[eé]ntanos|opina|sigue|comparte|guarda|descubre|mira|conoce|aprende)\b",
            body,
            re.IGNORECASE,
        )
    )
    if not has_cta:
        if len(lines) > 2:
            lines = lines[:1] + [" ".join(lines[1:])]
        lines.append("¿Qué opinas? Cuéntamelo en comentarios y sigue la cuenta para ver más.")
    if hashtags:
        lines.append(" ".join(hashtags))
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"title debe tener entre 1 y {MAX_TITLE_LENGTH} caracteres")
    if not 2 <= len(lines) <= 4:
        raise ValueError("description debe tener entre 2 y 4 líneas")
    if len(hashtags) != 3:
        raise ValueError("description debe contener exactamente 3 hashtags")
    return {"title": title, "description": "\n".join(lines), "cta_added": not has_cta}


def prompt_for(clip: dict, context: str, repair: str = "") -> str:
    return f"""Eres editor de copy para clips verticales en español.
Devuelve EXCLUSIVAMENTE JSON válido: {{"title":"...","description":"línea 1\\nlínea 2\\nlínea 3"}}.
Reglas:
- title: gancho natural, específico y fiel al material; menos de 70 caracteres.
- description: 2 a 4 líneas; resume el valor, incluye una CTA natural y deja una línea final con 3 hashtags relevantes.
- No inventes datos, nombres, promesas ni conclusiones. Evita clickbait engañoso.
Sección: {clip.get('block') or '-'}
Cita: {clip.get('quote') or '-'}
Transcripción: {context or '-'}
{repair}"""


def generate(clip: dict, context: str, model: str, timeout: float) -> dict[str, object]:
    started = time.perf_counter()
    errors: list[str] = []
    ollama_seconds = load_seconds = 0.0
    for attempt in range(2):
        repair = "Tu respuesta anterior fue inválida. Corrige el formato y respeta todos los límites." if attempt else ""
        payload = {
            "model": model,
            "prompt": prompt_for(clip, context, repair),
            "stream": False,
            "format": SCHEMA,
            "options": {
                "temperature": 0.2 if attempt == 0 else 0.1,
                "seed": 42 + attempt,
                "num_ctx": 4096,
                "num_predict": 220,
            },
        }
        try:
            request = urllib.request.Request(
                OLLAMA_URL,
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.load(response)
            ollama_seconds += result.get("total_duration", 0) / 1e9
            load_seconds += result.get("load_duration", 0) / 1e9
            metadata: dict[str, object] = validate(result["response"])
            metadata.update(attempts=attempt + 1, fallback="no")
            break
        except (KeyError, ValueError, json.JSONDecodeError, urllib.error.URLError, TimeoutError) as exc:
            errors.append(f"intento {attempt + 1}: {exc}")
    else:
        metadata = generate_via_template(clip, context)
        metadata.update(attempts=2, fallback="sí: " + " | ".join(errors))
    metadata.update(
        model=model,
        elapsed_seconds=round(time.perf_counter() - started, 3),
        ollama_seconds=round(ollama_seconds, 3),
        load_seconds=round(load_seconds, 3),
    )
    return metadata


def render(clip: dict, metadata: dict[str, object], used_srt: bool) -> str:
    return (
        f"TÍTULO\n{metadata['title']}\n\nDESCRIPCIÓN\n{metadata['description']}\n\n"
        f"ORIGEN\nClip: {clip['id']} | Sección: {clip.get('block') or '-'} | "
        f"Contexto SRT: {'sí' if used_srt else 'no'}\n"
        f"Modelo: {metadata['model']} | Intentos: {metadata['attempts']} | "
        f"Fallback: {metadata['fallback']}\n"
        f"CTA añadida por normalización: {'sí' if metadata.get('cta_added') else 'no'}\n"
        f"Tiempo pared: {metadata['elapsed_seconds']:.3f} s | "
        f"Ollama: {metadata['ollama_seconds']:.3f} s | "
        f"Carga: {metadata['load_seconds']:.3f} s\n"
    )


def self_check() -> None:
    sample = validate('{"title":"Título","description":"Resumen\\nComenta tu opinión\\n#IA #Tech #Video"}')
    assert sample["title"] == "Título" and len(sample["description"].splitlines()) == 3
    try:
        validate('{"title":"Título","description":"Sin hashtags"}')
    except ValueError:
        return
    raise AssertionError("la validación aceptó metadata inválida")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip_plan", nargs="?", type=Path)
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--output-dir", type=Path, default=Path("preview_ollama"))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        print("self-check: ok")
        return 0
    if not args.clip_plan or not args.clip_plan.is_file():
        parser.error("clip_plan debe ser un archivo existente")

    try:
        clips = json.loads(args.clip_plan.read_text(encoding="utf-8"))
        if not isinstance(clips, list):
            raise ValueError("clip_plan.json debe contener una lista")
        ready = [clip for clip in clips if not clip.get("needs_review")]
        for clip in ready:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", str(clip.get("id") or "")):
                raise ValueError(f"id de clip inseguro: {clip.get('id')!r}")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for clip in ready:
            context = read_srt(args.clip_plan.parent / "clips" / f"{clip['id']}.srt")
            metadata = generate(clip, context, args.model, args.timeout)
            (args.output_dir / f"{clip['id']}.txt").write_text(
                render(clip, metadata, bool(context)), encoding="utf-8"
            )
            print(
                f"{clip['id']}: {metadata['elapsed_seconds']:.3f} s "
                f"(Ollama {metadata['ollama_seconds']:.3f} s, fallback {metadata['fallback']})",
                flush=True,
            )
        print(f"{len(ready)} metadata(s) generada(s) en {args.output_dir}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
