#!/usr/bin/env python3
"""Render vertical 9:16 de ClipFactory.

Genera el corto vertical (Shorts/Reels/TikTok) a partir del video fuente
(export horizontal o vertical del NLE) REUTILIZANDO `vertical_cropper` de
CleanVideos, que vive copiado en `scripts/vendor/` (ver `vendor/README.md`).
No se reimplementa la detección del sujeto: `detect_person_centers` ya la hace
con el modelo de seguimiento de CleanVideos, y la copia vendorizada está
vigilada por el caso A2b de la aceptación para no divergir del original.

Pasos:
1. Comprueba que ffmpeg exista — si no, falla con un mensaje claro en vez de
   reventar con un error raro (caso A7 de la aceptación).
2. Detecta el centro de la persona a lo largo del video y suaviza la
   trayectoria (ventana de 5 frames, en vertical_cropper).
3. Escribe `crop_plan.json` en el processing_dir: los centros usados por el
   recorte, el fps, las dimensiones fuente y la resolución de salida. Tener
   más de una posición demuestra que el recorte sigue al sujeto (caso A4).
4. Genera el `crop.txt` (sendcmd para ffmpeg) y renderiza el vertical.

El vertical se escribe en la ruta que pase el operador; no pisa los clips
horizontales existentes (el canal de YouTube sigue vivo).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
OUT_WIDTH_DEFAULT = 2160
OUT_HEIGHT_DEFAULT = 3840


def check_ffmpeg(ffmpeg: str) -> str:
    """Comprueba que ffmpeg exista y devuelve la ruta a usar.

    Lanza FileNotFoundError con un mensaje claro si el binario no está:
    en ningún PATH ni en la ruta explícita que pase el operador. Eso es lo
    que la aceptación espera del caso A7: fallar diciendo por qué, no
    reventar con un error opaco del subproceso.
    """
    if shutil.which(ffmpeg) is None and not Path(ffmpeg).exists():
        raise FileNotFoundError(
            f"No se encontró el binario ffmpeg en '{ffmpeg}' "
            "(no encontrado). Instalá ffmpeg o pasá --ffmpeg con la ruta al "
            "binario (el de Homebrew por defecto no trae libass; para "
            "captions hace falta ffmpeg-full)."
        )
    return ffmpeg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Video fuente (export del NLE)")
    parser.add_argument("processing_dir", type=Path,
                        help="Carpeta de trabajo: crop_plan.json y crop.txt")
    parser.add_argument("output_path", type=Path,
                        help="Salida vertical 9:16 (no toca los clips horizontales)")
    parser.add_argument("--clean-audio", type=Path, default=None,
                        help="Audio limpio para el vertical (opcional)")
    parser.add_argument("--out-width", type=int, default=OUT_WIDTH_DEFAULT)
    parser.add_argument("--out-height", type=int, default=OUT_HEIGHT_DEFAULT)
    parser.add_argument("--sample-stride", type=int, default=3,
                        help="Procesar 1 de cada N frames para detectar al sujeto")
    parser.add_argument("--ffmpeg", default="ffmpeg",
                        help="Ruta al binario de ffmpeg")
    args = parser.parse_args()

    if not args.video.is_file():
        print(f"Error: no existe {args.video}", file=sys.stderr)
        return 1

    try:
        check_ffmpeg(args.ffmpeg)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(VENDOR_DIR))
    try:
        import vertical_cropper
    except Exception as exc:
        print(f"Error: no se puede cargar vertical_cropper desde "
              f"{VENDOR_DIR}: {exc}", file=sys.stderr)
        return 1

    args.processing_dir.mkdir(parents=True, exist_ok=True)

    centers, fps, src_w, src_h = vertical_cropper.detect_person_centers(
        str(args.video), sample_stride=args.sample_stride)

    crop_plan = {
        "centers": centers,
        "fps": fps,
        "src_width": src_w,
        "src_height": src_h,
        "sample_stride": args.sample_stride,
        "out_width": args.out_width,
        "out_height": args.out_height,
    }
    plan_path = args.processing_dir / "crop_plan.json"
    plan_path.write_text(json.dumps(crop_plan), encoding="utf-8")

    crop_w = round(src_h * args.out_width / args.out_height)
    crop_w = min(crop_w, src_w)

    crop_txt = args.processing_dir / "crop.txt"
    vertical_cropper.generate_sendcmd(
        centers, args.sample_stride, fps, src_w, crop_w, str(crop_txt))

    try:
        vertical_cropper.crop_vertical(
            str(args.video),
            str(args.clean_audio) if args.clean_audio else None,
            str(crop_txt),
            str(args.output_path),
            crop_w,
            src_h,
            args.out_width,
            args.out_height,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"Error al renderizar el vertical con ffmpeg: {exc}", file=sys.stderr)
        return 1

    print(f"Vertical 9:16 listo en {args.output_path} (plan: {plan_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())