# ClipFactory

Pipeline para extraer clips cortos (Shorts / TikTok / Instagram Reels) desde los videos largos del canal, sin edición manual, partiendo del guion que ya produce Athena.

## Contexto y objetivo

- Grabación a **2 cámaras**: 40mm equivalente (plano general / A-cam) y 85mm FF (plano cerrado / B-cam).
- El video largo se edita y exporta para el canal como hoy.
- Queremos que del mismo guion largo salgan automáticamente varios clips cortos verticales, listos para publicar, **sin sentarnos a editar clip por clip**.
- Premisa central: no necesitamos IA para "descubrir" qué momento es interesante — eso ya lo decide el guion al escribirse. Lo que falta es *ubicar* ese momento dentro del video ya grabado y cortarlo.

## Punto de partida: Athena ya marca los momentos clave

`AthenaFramework` (`src/Athena.Core/ScriptPipeline.cs`) genera el guion con estructura fija (`# Hook, # Introducción, # Bloque 1-3, # Conclusión, # CTA`) y el prompt exige **2-4 marcas `[CÁMARA B]` por bloque**, cada una justo antes de una frase contundente pensada para quedar sola. Esas marcas son, literalmente, las candidatas a clip — ya curadas por el proceso editorial de Athena, no por un modelo adivinando.

`PublicationKitBuilder` (`src/Athena.Infrastructure/Export/PublicationKitBuilder.cs`) ya calcula timestamps por sección repartiendo la duración estimada del guion (`[Duración total estimada: N min]`) proporcionalmente entre encabezados — determinista, sin llamar a un LLM, solo transforma el Draft ya aprobado (respeta la regla DU-014 de "no sintetiza nada nuevo"). Es el mismo patrón que usaríamos para un futuro "ClipKit": una transformación determinista del guion aprobado, no una síntesis nueva.

**Importante:** esos timestamps de Athena son estimados por proporción de minutos planeados, no el corte real del video editado. Sirven como *mapa de candidatos*, no como timestamp final.

Nota de scope: `AthenaFramework/CLAUDE.md` declara explícitamente que Athena "NO es un generador de TikTok". ClipFactory es una capa aparte que consume el guion de Athena, no una extensión del núcleo editorial.

## Pipeline propuesto (sin edición manual)

1. **Guion aprobado (Athena)** → ya trae las frases marcadas con `[CÁMARA B]` y su timestamp estimado.
2. **Transcripción + alineación forzada del video ya editado** con WhisperX → timestamps reales a nivel de palabra.
3. **Fuzzy-match** del texto exacto de cada frase `[CÁMARA B]` contra esa transcripción → timestamp real de inicio/fin en el video.
4. **Corte con FFmpeg** usando el feed de cámara B (ya es plano cerrado, más compatible con vertical que el A-cam) alrededor de cada timestamp real.
5. **Captions quemados** usando los mismos timestamps de palabra de WhisperX.
6. Export listo para revisión humana antes de programar/subir (la decisión de publicar sigue siendo humana, no automática).

### ¿Cuántos clips salen de un guion?

No es un número fijo: depende de cuántas marcas `[CÁMARA B]` tiene el guion (típicamente 6-20 candidatos crudos en un guion largo), filtrados después por duración mínima de contexto y no repetir el mismo Claim. De ahí normalmente saldrían entre 3 y 8 clips usables por video largo.

## Herramientas evaluadas

### Clipify (`GetRepliq/Clipify`) — descartado

Investigado a fondo el 2026-08-11. Prototipo Python de ~240 líneas útiles, `main.py` y `requirements.txt` vacíos, sin backend ni empaquetado. Selecciona "momentos importantes" ordenando frases por cantidad de palabras (no por relevancia real), asume 5 segundos por frase de forma arbitraria sin usar los timestamps reales de Whisper. No genera subtítulos ni hace reencuadre inteligente (crop 9:16 estático, desconectado del flujo). Licencia contradictoria: README dice MIT, el archivo `LICENSE` es GPL-3.0. Sin mantenimiento activo demostrable. **No sirve como base.**

Alternativas que sí quedaron en el radar como referencia: [FunClip](https://github.com/modelscope/FunClip) (open source, MIT, más completo), OpusClip API (SaaS), Descript Underlord (flujo editorial con revisión humana).

### WhisperX — recomendado para el paso de alineación

Investigado a fondo el 2026-08-11, considerando el servidor local disponible (**GPU de 4GB VRAM, 16GB RAM**).

- **Qué es:** VAD → transcripción batched (faster-whisper/CTranslate2) → **forced alignment con wav2vec2** (timestamps por palabra en decenas de ms, no los ±100-500ms del Whisper nativo) → diarización opcional (pyannote, no la necesitamos).
- **Hardware:** con 4GB VRAM el punto de partida realista es `--model medium --compute_type int8 --batch_size 1`; large-v2/v3 es "al límite", no cómodo. Fallback a CPU con `int8` es viable si el GPU se satura, sin cifra confiable de qué tan lento (no confirmado en la investigación).
- **Español:** cubierto de fábrica, modelo de alineación wav2vec2 incluido por defecto junto con en/fr/de/it.
- **Precisión:** favorable para nuestro caso — fuzzy-match de una frase ya conocida (la del guion) contra la transcripción, con boundaries de decenas de ms. Hueco documentado: palabras con números/símbolos fuera del diccionario del modelo de alineación no reciben timestamp.
- **Instalación:** `pip install whisperx`, requiere FFmpeg + Rust, CUDA reportado ≥12.8 para GPU (verificar en el servidor real al instalar). Sin imagen Docker oficial, solo comunitarias.
- **Licencia:** BSD-2-Clause, sin restricciones. (pyannote, si algún día se usa diarización, sí requiere aceptar términos en HuggingFace — no aplica a nuestro caso).
- **Mantenimiento:** activo (release mayo 2026, commits recientes).
- **Alternativa a comparar en paralelo:** `stable-ts` (DTW refinado, sin segundo modelo wav2vec2, menor huella de VRAM) — sin benchmark cuantitativo directo contra WhisperX en español encontrado; vale la pena probar ambas en el servidor real antes de comprometerse.

**Recomendación de arranque:** `whisperx --model medium --language es --compute_type int8 --batch_size 1 --device cuda`, sin diarización.

## Recursos disponibles

- Servidor local: GPU 4GB VRAM, 16GB RAM.

## Pendiente / próximas decisiones

- [ ] Validar WhisperX (y opcionalmente stable-ts) corriendo en el servidor real con un video de prueba.
- [ ] Diseñar dónde vive el paso de fuzzy-match (¿script aparte en ClipFactory, o una extensión tipo "ClipKit" dentro de AthenaFramework siguiendo el patrón de `PublicationKitBuilder`?).
- [ ] Definir la ventana de corte alrededor de cada timestamp real (cuánto contexto antes/después de la frase marcada).
- [ ] Definir el paso de revisión humana antes de programar publicación (Athena/Arquitecto no aprueba ni publica contenido — esta decisión sigue siendo de Mario).
- [ ] Definir calendario/cadencia de subida y qué herramienta la ejecuta (fuera del scope de Athena).

---

## Estado probado (verificado 2026-09-15, AL-DÍA Fase A)

| Etapa | Estado | Evidencia |
|---|---|---|
| 1. Candidatos desde el guion (`extract_candidates.py`) | Funciona hoy | re-ejecutada sobre el guion de prueba: `candidates.json` idéntico al guardado |
| 2. Transcripción con WhisperX (servidor GPU remoto) | Validada el 2026-08-11, no re-ejecutada | `VALIDACION-WHISPERX.md` (4:23 min en 99 s, 1,76 GB de VRAM) |
| 3. Emparejado difuso (`match_candidates.py`, rapidfuzz) | Funciona hoy | `matches.json` idéntico; 0 `needs_review` de 4 |
| 4. Plan de clips (`plan_clips.py`) | Funciona hoy | `clip_plan.json` idéntico |
| 5. Corte y subtítulos quemados (`render_clips.py`, FFmpeg con libass) | Funciona hoy | 4 clips re-renderizados con la misma duración y resolución que los guardados y `.srt` idénticos |
| Clips **verticales 9:16** | **No implementado** | `render_clips.py` corta el vídeo fuente sin reencuadre: los clips salen 3840×2160 |
| Metadatos con Ollama (`generate_metadata.py`) | Prototipo | notas en `output/_research/metadata/` |

**Dependencias reales:** Python 3.9+ (`rapidfuzz` sólo para la etapa 3), FFmpeg **con libass** (en macOS `brew install ffmpeg-full`, keg-only en `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`; el `ffmpeg` normal no trae el filtro `subtitles`), WhisperX 3.8 con GPU CUDA para la etapa 2. Si Homebrew actualiza `x265`, `ffmpeg-full` puede quedar enlazado a una biblioteca que ya no existe (ocurrió el 2026-09-15; se resolvió con `brew reinstall ffmpeg-full`).

**Entradas:** guion `.md` de Athena con marcas `[CÁMARA B]` (`guiones/`), vídeo editado y su `transcript.json` de WhisperX. **Salidas** (en `output/<video>/`, no versionadas): `candidates.json`, `matches.json`, `clip_plan.json`, `clips/*.mp4` + `.srt`.

**DaVinci Resolve:** decisión del 2026-08-11 de no usarlo como motor de corte (`output/_research/davinci/findings.md`); el flujo con Resolve Free vive en AutoEdit.
