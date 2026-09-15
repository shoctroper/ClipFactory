# ARRANQUE — ClipFactory

Punto de entrada para retomar el proyecto en una sesión nueva. Lee esto primero. Para profundidad: `README.md` (contexto/objetivo del proyecto), `PIPELINE.md` (diseño técnico completo de las 8 etapas, con el detalle de cada script y su validación), `VALIDACION-WHISPERX.md` (resultados de la prueba real en el server).

## Qué es esto

Pipeline para extraer clips cortos (Shorts/TikTok/Reels) de los videos largos del canal, partiendo del guion que produce Athena (marca con `[CÁMARA B]` las frases candidatas a clip), sin editar clip por clip a mano.

## Estado actual (2026-08-12)

**Pipeline de generación (Etapas 1-6) implementado y validado end-to-end.** Cada etapa se validó primero por separado, y también las 6 juntas sobre un caso real: guion escrito a mano con citas verbatim del video `VideoConGuionYouTube.mp4` (ver detalle en `PIPELINE.md` § Validación end-to-end). El video vertical real sigue pendiente (ver Pendientes) — esta corrida usó el horizontal como stand-in.

| Etapa | Script | Estado |
|---|---|---|
| 1. Extraer candidatos del guion | `scripts/extract_candidates.py` (stdlib) | ✅ probado con `guiones/ejemplo.md` + 3 casos límite |
| 2. Transcribir + alinear (WhisperX) | corre en el server, no es script de este repo | ✅ validado, ver `VALIDACION-WHISPERX.md` |
| 3. Fuzzy-match cita → timestamp real | `scripts/match_candidates.py` (`rapidfuzz`) | ✅ probado contra transcript real, 4 casos sintéticos |
| 4. Ventana de corte | `scripts/plan_clips.py` (stdlib) | ✅ probado, incluye clamp contra clips vecinos |
| 5. Cortar + quemar captions | `scripts/render_clips.py` (FFmpeg) | ✅ probado contra video real, verificado visualmente |
| 6. Generar metadata (título+descripción) | `scripts/generate_metadata.py` (stdlib) | ✅ probado contra los 4 clips reales |
| **1→6 juntas (end-to-end)** | — | ✅ corrida real completa el 2026-08-11/12, ver `PIPELINE.md` |
| 7. Revisión humana | — | manual, decisión de Mario, no se automatiza |
| 8. Programación/subida | — | fuera de alcance técnico por ahora |

Decisiones de diseño ya cerradas (no volver a discutir salvo que algo falle en la práctica):

- Los clips se cortan del **video largo ya editado**, no de footage crudo de cámara B vía EDL (más simple, elegido para v1).
- El **reencuadre a 9:16 no lo hace ClipFactory** — el NLE del usuario exporta el mismo timeline en 2 perfiles (horizontal YouTube + vertical ya reencuadrado). ClipFactory solo corta (`ffmpeg -ss/-to`) del export vertical. Los timestamps se calculan una sola vez (alineando con WhisperX el audio del export horizontal) y valen igual para el vertical porque comparten el mismo edit/timing.
- **Etapa 4**: v1 no tiene el timestamp real de inicio de cada Bloque (solo el de las citas marcadas), así que "retroceder hasta el inicio del Bloque" se aproxima con un tope de duración (`--cap`, default 70s) en vez de un límite de Bloque real.
- **Etapa 5 / captions**: la cita `[CÁMARA B]` usa texto del guion (ya alineado en Etapa 3); el resto del clip (contexto antes/después) usa la transcripción cruda de WhisperX agrupada por oración — decisión tomada con el usuario el 2026-08-11 para evitar tener que alinear todo el guion contra el audio real. Riesgo aceptado: algún error de ASR ocasional en el contexto (no en la cita destacada). `pycaps` evaluado para animación karaoke — alpha, un mantenedor, depende de Playwright/Chromium — queda como mejora de estilo opcional post-v1, no en la ruta crítica.
- **No se integra DaVinci Resolve al pipeline** (decisión 2026-08-12, investigada con evidencia empírica real, ver `output/_research/davinci/findings.md`): la versión gratuita instalada no soporta `SmartReframe()` (requiere Resolve Studio, US$295) y FFmpeg ya resuelve corte + crop + captions mejor (más simple, determinista, sin la sobrecarga de una app pesada). Reabrir solo si algún día se compra Resolve Studio con una razón concreta.
- **Etapa 6 / metadata: solo plantilla determinista, sin LLM** (decisión 2026-08-12, ver `PIPELINE.md` § Etapa 6 y `output/_research/metadata/`): se probó un LLM local (Ollama `qwen2.5:3b` en el server `athena`) y dio peor calidad que la plantilla en los 4 casos de prueba, incluyendo una alucinación real. La plantilla no inventa nada (usa texto ya validado del guion) a cambio de títulos truncados en citas largas y hashtags placeholder. El explorador de Ollama queda disponible como herramienta opcional de segundo borrador, nunca como fuente única.

Herramientas evaluadas y descartadas: **Clipify** (`GetRepliq/Clipify`) — prototipo sin terminar, licencia contradictoria, heurística de selección poco confiable. Detalle en `README.md` § Herramientas evaluadas.

## Infraestructura

**Regla dura**: todo el trabajo de ClipFactory vive dentro de esta carpeta (`CLAUDE.md`, se carga solo al trabajar aquí) — nada se escribe fuera de la raíz de este repositorio.

**Local:**
- `.venv/` del proyecto (Python 3.11 vía `uv venv`, `rapidfuzz` instalado — ver `scripts/requirements.txt`) para `match_candidates.py`. `plan_clips.py`, `render_clips.py` y `generate_metadata.py` son stdlib puro, corren con cualquier Python 3.9+.
- `ffmpeg-full` de Homebrew instalado el 2026-08-11 en `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` (keg-only, no pisa el `ffmpeg` normal que también quedó instalado por separado). Necesario porque el `ffmpeg` normal de Homebrew no trae `libass`/`freetype` — sin eso no existe el filtro `subtitles` que usa `render_clips.py` para quemar captions. Pasarle siempre `--ffmpeg /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` al script (no se tocó `~/.zshrc` para no afectar nada fuera de este proyecto).
- **⚠️ Disco local casi lleno** (detectado 2026-08-12): el volumen de datos de esta Mac (Apple M4, 16GB RAM) llegó a 0 bytes libres durante esta sesión — no por ClipFactory (el repo entero pesa <1GB), sino porque el disco de 228GB ya estaba en el límite (196GB usados) antes de empezar. Se liberaron ~4.6GB borrando una descarga parcial rota de un modelo de Ollama, quedando ~4.8GB libres — **sigue muy ajustado**. No descargar modelos grandes ni generar archivos pesados en esta Mac sin chequear espacio primero (`df -h /`); para cualquier cómputo pesado (modelos LLM, etc.) preferir el server `athena` (ver abajo), que tiene 55GB libres.
- `codex` CLI (OpenAI Codex, `~/.local/bin/codex`) instalado y en uso — se usó en esta sesión como "equipo" de investigación/prototipado (vía `codex exec`, en background) para las decisiones sobre DaVinci Resolve y metadata. Tiene acceso a internet real (`web.run`) y puede operar en modo no interactivo con `-s workspace-write -C <dir> --skip-git-repo-check`.

**Remoto**: server accesible con `ssh athena` (Ubuntu 26.04 LTS, GPU NVIDIA RTX 3050 Ti Laptop 4GB VRAM, 16GB RAM, comparte GPU con ComfyUI/Ollama que a veces corren ahí). Entorno ya instalado en `~/clipfactory/` del server:
- FFmpeg 8.0.1 (único paso que usó `sudo`).
- `uv` en `~/.local/bin` (sin sudo).
- venv Python 3.11.15 en `~/clipfactory/.venv` con WhisperX 3.8.6 + PyTorch 2.8.0+cu128.
- Video de prueba en `~/clipfactory/videos/VideoConGuionYouTube.mp4` (4K, 4:23 min) — copiado también en local a `output/VideoConGuionYouTube/video_horizontal.mp4` y su transcripción a `output/VideoConGuionYouTube/transcript.json`, usados como fixtures reales para probar las Etapas 3-6.
- **Ollama 0.32.6 ya instalado**, con el modelo `qwen2.5:3b` (1.9GB) ya descargado. 55GB libres en disco. Usado en la investigación de la Etapa 6 (ver `output/_research/metadata/ollama_findings.md`) — quedó descartado como fuente única de metadata por calidad/alucinaciones, pero la infraestructura queda lista para reintentar con otro modelo si aparece uno mejor.
- La contraseña de sudo del server **no está guardada en ningún archivo** — pedirla de nuevo si hace falta otro paso con sudo.

## Pendiente / próximo paso

- [x] **Correr el pipeline completo end-to-end** con un guion real + video real. Hecho el 2026-08-11: guion escrito a mano (`guiones/VideoConGuionYouTube.md`) con citas `[CÁMARA B]` tomadas verbatim del transcript real de `VideoConGuionYouTube.mp4`, corrido por las 5 etapas de corte sin errores — 4/4 clips con match confiable (scores 98.3-100), 0 `needs_review`, sincronía de captions verificada visualmente. Detalle en `PIPELINE.md` § Validación end-to-end.
- [x] **Etapa 6 — metadata por clip**. Hecho el 2026-08-12: investigado con un equipo de Codex si DaVinci Resolve podía automatizar el corte/multi-formato (descartado) y si un LLM local vía Ollama mejoraba la metadata (descartado por calidad/alucinaciones). `scripts/generate_metadata.py` (solo plantilla) implementado y corrido contra los 4 clips reales. Detalle en `PIPELINE.md` § Etapa 6.
- [ ] Conseguir el **export vertical** real de algún video (hoy solo tenemos el horizontal, usado como stand-in en la corrida end-to-end) y confirmar en la práctica que comparte el mismo timing que el horizontal (supuesto ya documentado, no verificado con un archivo vertical real todavía). Este es el próximo hito natural.
- [ ] Liberar espacio en el disco local (ver ⚠️ en Infraestructura) — no es bloqueante para seguir trabajando, pero está al límite.
- Resto de pendientes abiertos (formato de entrada del guion a futuro, tope de duración por plataforma, título truncado en citas largas de Etapa 6, hashtags placeholder, herramienta de programación/calendario para la Etapa 8, etc.) están listados al final de `PIPELINE.md` — revisar ahí antes de asumir que algo ya se decidió.

## Reglas activas

- Todo el trabajo de ClipFactory se queda dentro de esta carpeta (`CLAUDE.md`, se carga solo al trabajar aquí). Excepción puntual aprobada por Mario el 2026-08-12: un agente de Codex abrió DaVinci Resolve en modo headless y creó un proyecto de prueba descartable (fuera de la carpeta, en la base de datos interna de Resolve) para investigar su API — se limpió/no se llegó a crear por bloqueo de sandbox, ver `output/_research/davinci/`. No asumir esta excepción como permiso permanente; volver a pedirla si hace falta repetir algo similar.
- Athena/el Arquitecto no aprueba ni publica contenido — la revisión humana (Etapa 7) y la programación de subida (Etapa 8) siguen siendo decisión de Mario, no automatizables.
