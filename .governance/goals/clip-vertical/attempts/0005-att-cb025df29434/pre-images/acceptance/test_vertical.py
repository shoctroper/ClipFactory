# -*- coding: utf-8 -*-
"""Aceptacion fijada: ClipFactory entrega cortos verticales de verdad.

Escrita por el arquitecto ANTES de implementar, y DENEGADA al implementador.

El hecho que la origina esta medido, no supuesto: el 2026-09-21 un clip real de
ClipFactory media 3840x2160 con `ffprobe`, cuando el destino son Shorts, Reels y
TikTok. Y no era un reencuadre malo: `render_clips.py:136` aplica un unico
filtro de ffmpeg, `subtitles=`. La funcion no existia.

La capacidad SI existe en la casa: CleanVideos/video_pipeline/scripts/
vertical_cropper.py detecta a la persona con MediaPipe (pose_landmarker_lite),
suaviza el centro con una ventana de 5 frames y genera un sendcmd para que el
recorte SIGA al sujeto. Reimplementarla seria repetir trabajo hecho y crear una
segunda version que divergira. Por eso estos casos exigen REUTILIZARLA.
"""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEANVIDEOS = Path("/Volumes/Medios/Repos/CleanVideos/video_pipeline")
FFPROBE = shutil.which("ffprobe")


def _dims(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout.strip().splitlines()[0]
    w, h = (int(x) for x in out.split(",")[:2])
    return w, h


class A_Reencuadre(unittest.TestCase):
    """Lo que Mario publica tiene que caber en la pantalla de un telefono."""

    def test_A1_existe_un_renderizador_vertical(self):
        mod = ROOT / "scripts" / "render_vertical.py"
        self.assertTrue(mod.is_file(),
                        "falta el punto de entrada del render vertical")

    def test_A2_reutiliza_el_cropper_de_cleanvideos(self):
        """No se reimplementa el seguimiento de sujeto: se usa el que ya existe.

        Dos implementaciones del mismo recorte divergen, y la segunda empieza
        sin saber lo que la primera aprendio sobre suavizado y muestreo.
        """
        src = (ROOT / "scripts" / "render_vertical.py").read_text(encoding="utf-8")
        self.assertIn("vertical_cropper", src,
                      "debe importar/invocar vertical_cropper de CleanVideos")
        for inventado in ("mediapipe", "pose_landmarker"):
            self.assertNotIn(inventado, src,
                             "no reimplementes la deteccion: reutilizala (%s)" % inventado)

    def test_A3_la_salida_es_9_16(self):
        salida = ROOT / "output" / "_acceptance" / "vertical.mp4"
        if not salida.is_file():
            self.fail("no hay salida vertical que medir: %s" % salida)
        w, h = _dims(salida)
        self.assertLess(w, h, "un corto vertical tiene que ser mas alto que ancho")
        self.assertAlmostEqual(w / h, 9 / 16, places=2,
                               msg="la relacion no es 9:16 (%dx%d)" % (w, h))

    def test_A4_el_recorte_sigue_al_sujeto(self):
        """Un recorte fijo al centro deja a Mario fuera de cuadro cuando se mueve.

        La prueba no mira el video: mira que el plan de recorte tenga mas de una
        posicion. Un solo valor para todo el clip es un recorte fijo.
        """
        plan = ROOT / "output" / "_acceptance" / "crop_plan.json"
        self.assertTrue(plan.is_file(), "falta el plan de recorte")
        data = json.loads(plan.read_text(encoding="utf-8"))
        centros = data.get("centers") or data.get("x") or []
        self.assertGreater(len(centros), 1, "el plan solo tiene una posicion")
        self.assertGreater(len(set(round(c) for c in centros)), 1,
                           "el centro nunca cambia: es un recorte fijo disfrazado")

    def test_A5_los_subtitulos_caben_en_vertical(self):
        """MarginV=60 esta calculado para 2160 de alto; en 3840 queda pegado."""
        src = (ROOT / "scripts" / "render_vertical.py").read_text(encoding="utf-8")
        self.assertNotIn("MarginV=60", src,
                         "el margen horizontal no sirve en vertical")

    def test_A6_no_pisa_la_salida_horizontal(self):
        """El canal de YouTube sigue vivo: el vertical se anade, no sustituye."""
        src = (ROOT / "scripts" / "render_vertical.py").read_text(encoding="utf-8")
        self.assertNotIn("clips/c", src.replace("clips/vertical", ""),
                         "no escribas sobre los clips horizontales existentes")

    def test_A7_sin_ffmpeg_falla_diciendo_por_que(self):
        src = (ROOT / "scripts" / "render_vertical.py").read_text(encoding="utf-8")
        self.assertIn("ffmpeg", src)
        self.assertTrue("which" in src or "FileNotFoundError" in src
                        or "no encontrado" in src.lower(),
                        "debe comprobar ffmpeg y decirlo claro, no reventar")


if __name__ == "__main__":
    unittest.main()
