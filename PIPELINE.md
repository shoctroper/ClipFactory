# Pipeline completo — diseño

Decisión tomada (2026-08-11): los clips se cortan del **video largo ya editado y exportado** (una sola pista), no del footage crudo de cámara B vía EDL. Más simple para v1; si el encuadre resulta un problema recurrente (el editor no siguió las marcas `[CÁMARA B]`), la migración a footage crudo + EDL queda documentada como fase 2 en Pendientes.

Actualización (2026-08-11): el reencuadre a 9:16 **no lo hace ClipFactory**. El NLE exporta el mismo timeline editado en dos perfiles — uno horizontal (YouTube) y otro vertical ya reencuadrado (para clips/shorts). Como ambos exports comparten el mismo edit, comparten el mismo timing: alineamos con WhisperX una sola vez (el audio es igual en los dos) y esos timestamps sirven para cortar directo del **export vertical**, sin crop de nuestra parte. Esto elimina el problema del crop centrado estático (la limitación que tenía Clipify) y toda la discusión de tracking de rostro — ya no aplica.

## Vista general

```
guion aprobado (Athena)        export horizontal (YouTube, .mp4)   export vertical (9:16, ya reencuadrado por el NLE)
        │                              │                                       │
        ▼                              ▼                                       │
[1] Extraer candidatos      [2] Transcribir + alinear (WhisperX)                │
        │                              │                                       │
        └──────────────┬───────────────┘                                       │
                        ▼                                                      │
              [3] Fuzzy-match candidato → timestamp real                       │
                        ▼                                                      │
              [4] Definir ventana de corte                                     │
                        │                                                      │
                        └──────────────────────┬───────────────────────────────┘
                                                ▼
                                  [5] Cortar + captions (FFmpeg, sobre el export vertical)
                                                ▼
                                  [6] Generar metadata (título + descripción por clip)
                                                ▼
                                  [7] Revisión humana (gate manual)
                                                ▼
                                  [8] Programación / subida (fuera de este repo)
```

**Nota (2026-08-12):** se investigó si DaVinci Resolve (vía su Scripting API) podía reemplazar a FFmpeg como motor de corte + multi-formato + captions, automatizando todo desde la app de edición. Conclusión, con evidencia empírica real (ver `output/_research/davinci/findings.md`): **no vale la pena.** La versión gratuita instalada no soporta `SmartReframe()` (reencuadre IA, requiere Resolve Studio, US$295), y FFmpeg ya resuelve el corte/crop/captions de forma más simple, determinista y sin la sobrecarga de una app pesada + base de proyectos. Decisión cerrada — no reabrir salvo que algún día se compre Resolve Studio y aparezca una razón concreta (ej. Smart Reframe) que FFmpeg no pueda cubrir.

## Etapa 1 — Extraer candidatos del guion ✅ implementada

**Script:** `scripts/extract_candidates.py` (solo stdlib, sin dependencias). Uso:

```bash
python3 scripts/extract_candidates.py guiones/<video-id>.md
# escribe output/<video-id>/candidates.json
```

Probado contra `guiones/ejemplo.md` (guion sintético con el formato exacto de Athena) y contra 3 casos límite: guion sin línea de duración (error claro), marcas `[CÁMARA B]` consecutivas sin frase entre medio (warning + se omite, no crashea), guion sin ninguna marca (error claro).

**Nota de diseño:** el timestamp estimado se calcula por **posición en el conteo total de palabras** del guion, no por índice de sección como hace `PublicationKitBuilder` de Athena — un bloque puede tener 2-4 marcas y necesitamos distinguir su posición relativa dentro del bloque, no solo a qué bloque pertenecen.

**Input:** texto del Draft aprobado (markdown con encabezados `# Bloque N` y marcas `[CÁMARA B]`), pegado/exportado a un archivo en `ClipFactory/guiones/<video-id>.md`.

**Qué hace:** parser determinista (sin LLM) que recorre el texto y por cada `[CÁMARA B]` captura:
- la frase inmediatamente siguiente (la "cita" candidata a clip),
- el bloque/sección a la que pertenece,
- un timestamp estimado (el mismo cálculo proporcional que ya usa `PublicationKitBuilder` de Athena: reparte `[Duración total estimada: N min]` entre encabezados) — **solo sirve como pista de búsqueda**, no como verdad.

**Output:** `candidates.json`
```json
[{"id": "c1", "block": "Bloque 2", "quote": "texto exacto de la frase...", "estimated_ts_sec": 340}]
```

**Dónde vive:** script propio dentro de `ClipFactory/` (Python, ya que WhisperX también es Python). No toca `AthenaFramework` — respeta la regla de alcance de este repo. El guion entra como archivo de texto plano copiado/exportado, no por integración directa con Athena (eso sería una mejora futura, no bloqueante).

## Etapa 2 — Transcribir + alinear el video real

**Input:** `video_largo.mp4`.

**Herramienta:** WhisperX — `whisperx --model medium --language es --compute_type int8 --batch_size 1 --device cuda` (ajustar a `cpu` si el GPU de 4GB se satura). Sin diarización.

**Output:** `transcript.json` con timestamps por palabra (decenas de ms de precisión). Es el paso más caro en cómputo — se corre **una vez por video** y se cachea; no se repite si solo cambian los candidatos.

## Etapa 3 — Fuzzy-match candidato → timestamp real ✅ implementada

**Script:** `scripts/match_candidates.py` (usa `rapidfuzz`, instalado en el venv del proyecto `.venv/`). Setup (una vez):

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv -r scripts/requirements.txt
```

Uso:

```bash
.venv/bin/python3 scripts/match_candidates.py output/<video-id>/candidates.json <transcript.json>
# escribe matches.json junto a candidates.json (o donde indique --output)
```

**Qué hace:** por cada `quote` de `candidates.json`, recorre `segments[].words` del transcript (no `word_segments`: ese puede omitir palabras que WhisperX no logró alinear, ver hueco documentado en `README.md`), restringe la búsqueda a las palabras cuyo timestamp cae dentro de `estimated_ts_sec ± --window` (default 90s), y desliza ventanas de N±2/3 palabras comparando texto normalizado (sin tildes/puntuación) contra la cita vía `rapidfuzz.fuzz.ratio`. Se queda con la mejor subsecuencia.

**Output:** `matches.json` — por candidato, `match_start_sec`/`match_end_sec` (bordes de la mejor subsecuencia encontrada), `score` (0-100), `matched_text` (para revisión humana) y `needs_review`.

**Regla dura:** si el score queda debajo de `--threshold` (default **75**, ver validación abajo) o no hay ninguna palabra dentro de la ventana de tiempo, el candidato se marca `needs_review` en vez de cortarse a ciegas — no queremos clips mal cortados silenciosamente.

**Validación (2026-08-11):** probado contra el `transcript.json` real de `VideoConGuionYouTube.mp4` (la misma corrida de la Etapa 2, copiada a `output/VideoConGuionYouTube/transcript.json`) con 4 candidatos sintéticos en `output/_test_etapa3/`:
- cita exacta con el estimado desviado 28s → encontrada, score 100.
- cita con paráfrasis leve (una palabra distinta a la real) → encontrada, score 90.5.
- cita que nunca se dijo en el video → `needs_review`, score 54.7 (mejor calce espurio dentro de la ventana).
- cita real pero cuya ventana de búsqueda no llega a cubrir su ubicación real → `needs_review`, score 51.9 (no confunde con el momento equivocado).

Con esta única muestra el umbral 75 separa limpio matches buenos (~90-100) de ruido (~50-55); a confirmar/ajustar cuando pasen guiones reales por el pipeline.

## Etapa 4 — Definir ventana de corte ✅ implementada

**Script:** `scripts/plan_clips.py` (solo stdlib). Uso:

```bash
.venv/bin/python3 scripts/plan_clips.py output/<video-id>/matches.json <transcript.json>
# escribe clip_plan.json junto a matches.json (o donde indique --output)
```

**Qué hace:** a partir del `match_start_sec`/`match_end_sec` real de cada cita (Etapa 3), arma la ventana del clip:
- retrocede desde `match_start_sec` hasta el límite de oración (`segments[]` de WhisperX) más lejano que no supere `--cap` segundos (default 70) hacia atrás;
- avanza desde `match_end_sec` hasta el final de esa oración, y si la oración siguiente empieza a pocos segundos (`--tail-max-gap`, default 2s) y es corta (`--tail-max-dur`, default 8s), la incluye como remate/payoff;
- recorta contra el clip vecino (anterior/siguiente por orden temporal) para que dos clips nunca se superpongan.

**Simplificación de v1, documentada a propósito:** la spec original decía "retrocede hasta el inicio del Bloque que la contiene". No implementamos eso literal porque v1 no tiene el timestamp real del inicio de cada Bloque en el video — Etapa 1 solo da un `estimated_ts_sec` proporcional (una pista, no verdad) y Etapa 3 solo resuelve el timestamp real de las citas marcadas, no el de los encabezados de Bloque. El tope `--cap` hace ese trabajo en su lugar: limita cuánto contexto se agrega hacia atrás sin necesitar saber dónde empieza el Bloque. Si en la práctica los clips resultantes arrancan a mitad de una idea del Bloque anterior (en vez de dar contexto propio), habría que sumar un timestamp real de inicio de Bloque — pendiente si esto pasa.

**Candidatos con `needs_review=true`** (o sin `match_start_sec`) en `matches.json` no se procesan — se listan igual en `clip_plan.json` con `start/end/duration: null` para que la revisión humana (Etapa 6) los vea, pero no se corta a ciegas sobre un match que Etapa 3 ya marcó como dudoso.

**Output:** `clip_plan.json` — lista de `{id, block, quote, start, end, duration, needs_review, note}` por clip.

**Validación (2026-08-11):** probado contra `matches.json` real (transcript de `VideoConGuionYouTube.mp4`) con los 4 casos de la Etapa 3 (2 con match confiable, 2 `needs_review` que se pasaron sin ventana) y un caso adicional de dos citas separadas por ~17s reales: el clip anterior quedó recortado exactamente donde empieza el siguiente (sin solapamiento ni hueco), confirmando el recorte contra vecinos.

## Etapa 5 — Cortar + captions ✅ implementada

**Script:** `scripts/render_clips.py`. **Sin reencuadre** — el export vertical ya viene resuelto por el NLE (perfil 9:16 del mismo timeline editado). Uso:

```bash
.venv/bin/python3 scripts/render_clips.py output/<video-id>/clip_plan.json output/<video-id>/matches.json <transcript.json> export_vertical.mp4 \
  --ffmpeg /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg
# escribe <id>.srt y <id>.mp4 por clip en output/<video-id>/clips/
```

**Herramienta:** FFmpeg — pero **no el `ffmpeg` normal de Homebrew**: ese build no trae `libass`/`freetype`, así que no tiene el filtro `subtitles` para quemar captions. Hace falta `brew install ffmpeg-full` (keg-only, queda en `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`, no pisa el `ffmpeg` normal). Instalado localmente el 2026-08-11.

- Corte: `ffmpeg -ss start -to end -i export_vertical.mp4 -vf subtitles=... ...` por cada clip de `clip_plan.json` sin `needs_review`. Los timestamps salen de la Etapa 3/4 (calculados sobre el export horizontal, pero válidos para el vertical porque comparten el mismo edit/timing).
- Captions — **decisión tomada 2026-08-11** (ver pregunta al usuario, opción elegida: "cita = guion, contexto = ASR crudo"): el `.srt` mezcla dos fuentes de texto:
  - la cita `[CÁMARA B]` en sí: **texto del guion** (el `quote` ya validado en Etapa 3), como una sola línea con el `match_start_sec`/`match_end_sec` real;
  - el resto del clip (contexto antes/después que agrega la Etapa 4 para dar aire): **transcripción cruda de WhisperX**, agrupada por oración (`segments[]`) y partida en líneas de máximo `--max-words-per-line` (default 10) palabras, con timing por palabra real.
  - Riesgo aceptado: el contexto puede traer algún error de ASR puntual (ej. "cognositivas", "povos" vistos en la prueba real) — se prefirió esto a tener que alinear todo el guion contra el audio real, que hubiera requerido releer el guion por Bloque completo y un algoritmo de alineación palabra-a-palabra nuevo (evaluado y descartado para v1 por complejidad/riesgo de desalinearse con improvisaciones del hablante).
- Evaluado `pycaps` (github.com/francozanardi/pycaps) para animación karaoke — acepta transcripts externos, pero es alpha/un solo mantenedor y depende de Playwright+Chromium. Se deja como mejora de estilo opcional post-v1, no como dependencia de la ruta crítica. El estilo actual es mínimo (`force_style` de libass: tamaño de fuente, centrado abajo), sin animación.

**Validación (2026-08-11):** corrido contra el video real (`VideoConGuionYouTube.mp4`, usado como stand-in del export vertical porque todavía no hay uno real — ver pendientes) con el `clip_plan.json` de la Etapa 4 (2 clips con match confiable, 2 `needs_review` correctamente omitidos). Se extrajeron frames en los segundos 3 y 9 del clip `t1.mp4` con `ffmpeg -ss ... -frames:v 1` y se inspeccionaron visualmente: el caption en pantalla coincide con lo que la persona está diciendo en ese instante exacto, confirmando que el timing (guion + ASR) está bien sincronizado.

**Output:** un `.srt` y un `.mp4` (vertical cuando el input lo sea) con captions quemados por clip, en `ClipFactory/output/<video-id>/clips/`.

## Validación end-to-end (Etapas 1-5 juntas) ✅ 2026-08-11

Hasta este punto cada etapa se había validado por separado (con datos sintéticos o el `_test_etapa3/` aislado). Esta corrida encadena las 5 sobre un caso real de principio a fin:

- **Guion:** `guiones/VideoConGuionYouTube.md`, escrito a mano con el formato exacto de Athena (Hook/Introducción/Bloque N/Conclusión/CTA + `[Duración total estimada: N min]`), usando 4 citas `[CÁMARA B]` tomadas **verbatim** del transcript real de `output/VideoConGuionYouTube/transcript.json` (video sobre inteligencia artificial, 4:23 min) — necesario porque el guion sintético `guiones/ejemplo.md` no tiene relación con el contenido de ningún video real disponible y hubiera dado `needs_review` en las 4 citas.
- **Video:** `output/VideoConGuionYouTube/video_horizontal.mp4`, usado como stand-in del export vertical (todavía no existe uno real, ver Pendientes).
- **Resultado:**
  - Etapa 1: 4 candidatos extraídos, `estimated_ts_sec` dentro de ~10s del timestamp real en los 4 casos.
  - Etapa 3: 4/4 matches confiables, 0 `needs_review`. Scores: 100, 100, 100, 98.3. El de 98.3 es el caso interesante — la cita del guion dice "Claude de Anthropic" pero WhisperX transcribió "Cloud de Anthropic" (error de ASR ya documentado en Etapa 5); el fuzzy-match lo absorbió sin marcar revisión.
  - Etapa 4: clips de 77.9s, 66.1s, 26.5s y 17.6s — los clips 2/3 y 3/4 quedan exactamente pegados sin solaparse (recorte contra vecino funcionando).
  - Etapa 5: 4 pares `.mp4`/`.srt` generados en `output/VideoConGuionYouTube/clips/`. Verificado visualmente un frame del clip `c4` en el segundo 12: el caption en pantalla coincide con lo que dice la persona en ese instante, y muestra "Claude" (texto del guion) y no "Cloud" (texto crudo del ASR) — confirma que la sustitución cita-guion/contexto-ASR de la Etapa 5 funciona como está diseñada.
- **Conclusión:** las 5 etapas se conectan sin fricción sobre datos reales. Sigue pendiente repetir esto con un export vertical real (no el horizontal) para cerrar del todo el pendiente de la Etapa 5.

## Etapa 6 — Generar metadata (título + descripción) ✅ implementada

**Script:** `scripts/generate_metadata.py` (solo stdlib). Uso:

```bash
python3 scripts/generate_metadata.py output/<video-id>/clip_plan.json
# escribe <id>.txt junto a <id>.mp4/<id>.srt en output/<video-id>/clips/
```

**Qué hace:** por cada clip sin `needs_review`, genera un título (a partir de la `quote` del guion, la misma cita ya usada como cita destacada en la Etapa 5) y una descripción corta con la cita completa + un CTA genérico + un placeholder de hashtags, en un `.txt` legible listo para copiar/pegar al subir el clip.

**Decisión de diseño — solo plantilla determinista, sin LLM (2026-08-12):** se investigó conectar un LLM para mejorar la calidad (ver `output/_research/metadata/`, investigación hecha con un equipo de Codex). Dos caminos evaluados:
- **LLM en la nube**: no se llegó a implementar — se priorizó primero explorar un modelo local.
- **LLM local vía Ollama** (`qwen2.5:3b`, corriendo en el server `athena` sobre su GPU de 4GB, sin costo por uso ni exposición de red): probado contra los 4 clips reales de `VideoConGuionYouTube`, con resultado **peor que la plantilla en los 4 casos** — más genérico, y en un caso (`c2`) inventó una promesa ("aprende a programar agentes inteligentes") que no está en la fuente. Detalle completo en `output/_research/metadata/ollama_findings.md`.

Con esa evidencia, el script de producción usa **solo la plantilla**: no inventa nada (extrae texto ya validado del guion/Etapa 1), es gratis, no depende de infraestructura externa, y su límite conocido es que en citas largas el título queda truncado en vez de resumido con criterio (no hay forma de resumir con criterio sin un LLM). El explorador de Ollama queda disponible como herramienta opcional para pedir un segundo borrador (`output/_research/metadata/generate_metadata_ollama.py`, hay que correrlo vía `ssh athena`), **siempre con revisión humana obligatoria** — nunca como fuente única, dado el riesgo de alucinación confirmado.

**Candidatos con `needs_review=true`** (o sin `start`) se omiten, igual que en la Etapa 5.

**Output:** un `.txt` por clip (`TÍTULO`/`DESCRIPCIÓN`/`ORIGEN`) en `ClipFactory/output/<video-id>/clips/`, junto al `.mp4`/`.srt` de la Etapa 5.

**Validación (2026-08-12):** corrido contra los 4 clips reales de `VideoConGuionYouTube` (mismo caso end-to-end validado en Etapas 1-5). Los 4 `.txt` se generaron correctamente, títulos dentro del límite de 69 caracteres, descripciones con la cita completa (sin fragmentos truncados a mitad de frase, a diferencia de una versión intermedia del script que usaba el contexto crudo del SRT como texto principal y a veces tomaba el inicio del clip en vez de la parte relevante — corregido para usar siempre la cita como fuente principal de la descripción).

## Etapa 7 — Revisión humana

Gate manual antes de programar publicación. Athena/Arquitecto no aprueba ni publica contenido (regla ya establecida) — este paso sigue siendo de Mario. v1 no necesita herramienta especial: carpeta de clips numerados + `matches.json` con los scores de confianza + el `.txt` de metadata (Etapa 6, siempre a revisar/editar antes de publicar) es suficiente para revisar rápido cuáles pasan.

## Etapa 8 — Programación / subida

Fuera del alcance técnico de este documento por ahora. Se resuelve con una herramienta de calendario (Buffer/Later/nativo) que toma los clips ya aprobados — no es parte del pipeline de generación, es la siguiente fase.

## Stack por etapa

| Etapa | Herramienta |
|---|---|
| 1. Candidatos | script propio (Python) |
| 2. Transcripción/alineación | WhisperX |
| 3. Fuzzy-match | `rapidfuzz` |
| 4. Ventana de corte | `scripts/plan_clips.py` (stdlib) |
| 5. Corte/captions | `scripts/render_clips.py` + FFmpeg (`ffmpeg-full` de Homebrew, por `libass`) |
| 6. Metadata | `scripts/generate_metadata.py` (stdlib, plantilla determinista) |
| 7. Revisión | manual |
| 8. Programación | por definir, fuera de este repo |

## Pendiente / próximas decisiones

- [x] Validar WhisperX en el servidor real con un video de prueba (medium/int8 en 4GB VRAM) — ver `VALIDACION-WHISPERX.md`. Resultado: ~1.76GB VRAM pico, 2.6x más rápido que real-time, timestamps por palabra confirmados en español.
- [x] Definir umbral de confianza del fuzzy-match para marcar `needs_review` — default **75** (rapidfuzz `fuzz.ratio`, 0-100), validado con una muestra sintética contra transcript real (ver Etapa 3 arriba). Revisar cuando haya guiones/videos reales pasando por el pipeline.
- [x] Definir tope de duración del clip — implementado en Etapa 4 como `--cap 70` (retroceso) + hasta `--tail-max-dur 8` de remate opcional, o sea clips de hasta ~70-78s. Sigue siendo un default sin contrastar contra los límites reales de cada plataforma (Shorts/TikTok/Reels difieren) — ajustar cuando haya un objetivo de plataforma concreto.
- [ ] Decidir formato de entrada del guion a `ClipFactory/guiones/` (¿copiar manualmente el Draft, o construir un export desde Athena más adelante?).
- [ ] Confirmar que el export horizontal y el vertical del NLE quedan siempre timing-idénticos (mismo edit, solo distinto aspecto) — si el flujo de exportación algún día introduce diferencias de duración/cortes entre ambos, los timestamps dejarían de ser válidos para el vertical.
- [ ] Definir herramienta de programación/calendario para la Etapa 8.
- [x] Investigar si DaVinci Resolve podía automatizar corte + multi-formato + captions vía su Scripting API — descartado, ver nota en § Vista general y `output/_research/davinci/findings.md`. FFmpeg se queda como motor de producción.
- [ ] Mejorar el título de Etapa 6 para citas largas (hoy se trunca a 69 caracteres en un límite de palabra, lo que a veces corta la idea a mitad de camino en vez de resumir con criterio) — solo resoluble con un LLM confiable; no vale la pena mientras el único candidato probado (Ollama local `qwen2.5:3b`) alucina. Reevaluar si se prueba un modelo más grande o un LLM en la nube.
- [ ] Reemplazar el placeholder de hashtags de Etapa 6 (`#agregar #hashtags #relevantes`) por algo real — hoy es intencionalmente genérico porque no hay forma confiable de generar hashtags específicos del tema sin LLM.
