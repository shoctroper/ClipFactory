# Validación de WhisperX en el server real

Fecha: 2026-08-11. Server: `ssh athena` (Ubuntu 26.04 LTS, GPU NVIDIA RTX 3050 Ti Laptop 4GB VRAM, 16GB RAM).

## Entorno instalado

- **FFmpeg** 8.0.1 vía `apt` (único paso que requirió `sudo`).
- **uv** (gestor de Python/paquetes) instalado sin sudo en `~/.local/bin`.
- **Python 3.11.15** aislado en `~/clipfactory/.venv` vía `uv venv --python 3.11` — evita el Python 3.14 del sistema (muy nuevo para las wheels de PyTorch/CTranslate2 en este momento).
- **WhisperX 3.8.6** con **PyTorch 2.8.0+cu128**, confirmado `torch.cuda.is_available() == True`, detecta `NVIDIA GeForce RTX 3050 Ti Laptop GPU`.
- Todo vive en `~/clipfactory/` en el server (venv, video de prueba, outputs) — carpeta dedicada, sin mezclar con ComfyUI ni otros proyectos que ya corren ahí.

## Video de prueba

`VideoConGuionYouTube.mp4` — 4K (3840×2160), H.264/AAC, **4:23 min** de duración, subido por `scp` desde una carpeta local.

## Comando usado

```bash
whisperx videos/VideoConGuionYouTube.mp4 \
  --model medium --language es \
  --compute_type int8 --batch_size 1 --device cuda \
  --output_dir output --output_format json
```

## Resultados

| Métrica | Valor |
|---|---|
| Tiempo total (wall clock) | **1:39** (99s) para 4:23 de video — incluye descarga única del modelo de alineación en español (360MB, ~12s) |
| Factor tiempo real | **~2.6x más rápido que real-time** |
| RAM del sistema (pico) | ~3.0 GB de 16 GB |
| **VRAM (pico)** | **1852 MiB** sobre una base de 91 MiB → **~1.76 GB usados de 4 GB disponibles** |
| Exit status | 0 (sin errores) |

## Calidad de los timestamps

Confirmado: JSON de salida trae **timestamps por palabra** con precisión de milisegundos y score de confianza por palabra. Ejemplo real:

```json
{"word": "Desde", "start": 8.96, "end": 9.86, "score": 0.488}
{"word": "asistentes", "start": 9.98, "end": 10.441, "score": 0.807}
{"word": "virtuales", "start": 10.521, "end": 11.001, "score": 0.823}
```

Esto es justo la granularidad necesaria para la Etapa 3 del pipeline (fuzzy-match de las frases `[CÁMARA B]` del guion contra la transcripción real).

## Conclusión

Validado: `medium` + `int8` + `batch_size 1` corre cómodo en la GPU de 4GB (usa menos de la mitad), a más de 2x velocidad real, con calidad de timestamp por palabra confirmada en español. No hace falta bajar a `small` ni preocuparse por compartir la GPU con otros procesos ligeros — con ~1.76GB de uso real hay margen incluso si algo más (ej. Ollama con un modelo chico) sigue corriendo.

Pendiente para una futura validación: probar con un video más largo (20-40 min, como el longform real de Athena) para confirmar que el tiempo escala linealmente y que no hay fugas de memoria en corridas largas.

## Notas de higiene

- La contraseña de sudo usada para instalar FFmpeg **no se guardó** en ningún archivo de este repo ni en memoria — quedó únicamente en el historial de chat de la sesión donde el usuario la compartió.
