#!/usr/bin/env python3
"""Prototipo de metadata publicable a partir de un clip_plan.json.

Modo template (default): determinista, gratis y sin dependencias; sus reglas son
predecibles pero no entienden matices fuera de los temas contemplados.

Modo llm: usa un modelo local servido por Ollama y vuelve al template si la
respuesta no supera la validación después de dos intentos.
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


METADATA_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = METADATA_ROOT / "preview"
MAX_TITLE_LENGTH = 69
DEFAULT_OLLAMA_MODEL = "qwen3.5:9b"
OLLAMA_URL = "http://localhost:11434/api/chat"
METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["title", "description"],
    "additionalProperties": False,
}


def read_srt(path: Path) -> str:
    """Devuelve solo el diálogo de un SRT, sin índices ni timestamps."""
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return " ".join(
        line.strip()
        for line in lines
        if line.strip() and not line.strip().isdigit() and "-->" not in line
    )


def shorten(text: str, limit: int = MAX_TITLE_LENGTH) -> str:
    text = " ".join(text.split()).strip(" .")
    if len(text) <= limit:
        return text
    return text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def generate_via_template(clip: dict, context: str) -> dict[str, str]:
    """Genera copy repetible con reglas simples sobre cita, bloque y SRT."""
    quote = " ".join(str(clip.get("quote") or "").split())
    block = str(clip.get("block") or "el video")
    source = f"{quote} {context}".casefold()

    if "singularidad tecnológica" in source:
        title = "¿La IA podría provocar una singularidad tecnológica?"
        lead = (
            "Los LLM actuales reabren el debate sobre una IA capaz de igualar "
            "o superar la inteligencia humana y sus posibles consecuencias."
        )
    elif "ia general" in source and ("capacidades humanas" in source or "inteligencia humana" in source):
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
        excerpt = shorten(context or quote, 180)
        lead = f"En este fragmento de {block} exploramos una idea clave: {excerpt}"

    title = shorten(title)
    description = "\n".join(
        (
            lead,
            "¿Qué opinas? Cuéntamelo en comentarios y sigue la cuenta para ver más.",
            "#IA #InteligenciaArtificial #Tecnología",
        )
    )
    return {"title": title, "description": description}


def _validate_metadata(raw: str) -> dict[str, str]:
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"title", "description"}:
        raise ValueError("el JSON no tiene exactamente title y description")
    title, description = value["title"], value["description"]
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title no es texto o está vacío")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description no es texto o está vacío")
    title = " ".join(title.split()).strip()
    description = description.strip()
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"title excede {MAX_TITLE_LENGTH} caracteres")
    if len(description) > 600:
        raise ValueError("description excede 600 caracteres")
    return {"title": title, "description": description}


def generate_via_llm(
    clip: dict, context: str, model: str = DEFAULT_OLLAMA_MODEL, timeout: float = 120
) -> dict[str, str]:
    """Genera metadata vía Ollama; reintenta una vez y luego usa template."""
    prompt = f"""Crea metadata en español para un clip vertical (TikTok/Reels/Shorts).
Devuelve SOLO un objeto JSON con este esquema exacto:
{json.dumps(METADATA_SCHEMA, ensure_ascii=False)}

Reglas:
- title: gancho natural, específico y factual; máximo {MAX_TITLE_LENGTH} caracteres.
- description: breve, en 2 o 3 líneas; resume el valor del clip, incluye una CTA natural y termina con 3 hashtags relevantes.
- Usa únicamente hechos presentes en el material. No inventes cifras, promesas, nombres ni conclusiones.
- Evita títulos genéricos y sensacionalismo engañoso.

Sección: {clip.get('block') or '-'}
Cita elegida: {clip.get('quote') or '-'}
Transcripción SRT: {context or '-'}"""
    errors: list[str] = []
    started = time.perf_counter()
    for attempt in range(2):
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Eres editor de copy social en español. Sé fiel a la fuente.",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "format": METADATA_SCHEMA,
            "options": {
                "temperature": 0.6 if attempt == 0 else 0.2,
                "num_ctx": 4096,
                "num_predict": 220,
            },
        }
        try:
            request = urllib.request.Request(
                OLLAMA_URL,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                api_result = json.load(response)
            metadata = _validate_metadata(api_result["message"]["content"])
            metadata.update(
                _model=model,
                _attempts=str(attempt + 1),
                _fallback="no",
                _elapsed_seconds=f"{time.perf_counter() - started:.3f}",
                _ollama_seconds=f"{api_result.get('total_duration', 0) / 1e9:.3f}",
                _load_seconds=f"{api_result.get('load_duration', 0) / 1e9:.3f}",
            )
            return metadata
        except (KeyError, ValueError, json.JSONDecodeError, urllib.error.URLError, TimeoutError) as exc:
            errors.append(f"intento {attempt + 1}: {exc}")

    metadata = generate_via_template(clip, context)
    metadata.update(
        _model=model,
        _attempts="2",
        _fallback="sí: " + " | ".join(errors),
        _elapsed_seconds=f"{time.perf_counter() - started:.3f}",
        _ollama_seconds="-",
        _load_seconds="-",
    )
    return metadata


def render_metadata(clip: dict, metadata: dict[str, str], used_srt: bool) -> str:
    result = (
        f"TÍTULO\n{metadata['title']}\n\n"
        f"DESCRIPCIÓN\n{metadata['description']}\n\n"
        f"ORIGEN\nClip: {clip['id']} | Sección: {clip.get('block') or '-'} | "
        f"Contexto SRT: {'sí' if used_srt else 'no'}\n"
    )
    if "_model" in metadata:
        result += (
            f"Modelo: {metadata['_model']} | Intentos: {metadata['_attempts']} | "
            f"Fallback: {metadata['_fallback']}\n"
            f"Tiempo pared: {metadata['_elapsed_seconds']} s | "
            f"Ollama: {metadata['_ollama_seconds']} s | "
            f"Carga: {metadata['_load_seconds']} s\n"
        )
    return result


def safe_output_dir(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != METADATA_ROOT and METADATA_ROOT not in resolved.parents:
        raise ValueError(f"La salida debe estar dentro de {METADATA_ROOT}")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip_plan", type=Path, help="Ruta a clip_plan.json")
    parser.add_argument("--mode", choices=("template", "llm"), default="template")
    parser.add_argument("--model", default=DEFAULT_OLLAMA_MODEL, help="Modelo local de Ollama")
    parser.add_argument("--timeout", type=float, default=120, help="Timeout por llamada en segundos")
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directorio de previews"
    )
    args = parser.parse_args()

    if not args.clip_plan.is_file():
        print(f"Error: no existe {args.clip_plan}", file=sys.stderr)
        return 1

    try:
        clips = json.loads(args.clip_plan.read_text(encoding="utf-8"))
        if not isinstance(clips, list):
            raise ValueError("clip_plan.json debe contener una lista")
        output_dir = safe_output_dir(args.output_dir)
        generator = generate_via_template
        if args.mode == "llm":
            generator = lambda clip, context: generate_via_llm(
                clip, context, model=args.model, timeout=args.timeout
            )
        ready = [clip for clip in clips if not clip.get("needs_review")]
        for clip in ready:
            clip_id = str(clip.get("id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", clip_id):
                raise ValueError(f"id de clip inseguro o vacío: {clip_id!r}")

        output_dir.mkdir(parents=True, exist_ok=True)
        for clip in ready:
            clip_id = str(clip["id"])
            srt_path = args.clip_plan.parent / "clips" / f"{clip_id}.srt"
            context = read_srt(srt_path)
            metadata = generator(clip, context)
            if len(metadata["title"]) > MAX_TITLE_LENGTH:
                raise ValueError(f"título de {clip_id} excede {MAX_TITLE_LENGTH} caracteres")
            (output_dir / f"{clip_id}.txt").write_text(
                render_metadata(clip, metadata, bool(context)), encoding="utf-8"
            )
            if args.mode == "llm":
                print(
                    f"{clip_id}: {metadata['_elapsed_seconds']} s "
                    f"(Ollama {metadata['_ollama_seconds']} s, "
                    f"carga {metadata['_load_seconds']} s, fallback {metadata['_fallback']})"
                )
    except (OSError, json.JSONDecodeError, KeyError, ValueError, NotImplementedError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"{len(ready)} metadata(s) generada(s) en {output_dir}")
    print(f"{len(clips) - len(ready)} clip(s) needs_review omitido(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
