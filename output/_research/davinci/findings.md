# Investigación DaVinci Resolve 21.0.1 Free para ClipFactory

Fecha: 2026-08-11. Equipo: Mac Apple Silicon. Instalación detectada: DaVinci Resolve gratuito `21.0.1.0011`.

## Resumen ejecutivo

Esta sesión **no pudo completar las pruebas dentro de Resolve** porque el sandbox impidió que la aplicación escribiera en su propio directorio de soporte y bloqueó el lanzamiento vía LaunchServices. El bloqueo ocurrió antes de crear un proyecto: no se modificó ningún proyecto existente, no se creó ningún proyecto descartable y no hubo nada que limpiar. Se dejó un arnés reproducible con limpieza en `finally` para ejecutar desde una Terminal normal.

| Pregunta | Resultado | Evidencia |
|---|---|---|
| 1. Headless end-to-end | **No fue posible en esta sesión** | El binario con `-nogui` vivió 5–10 s, imprimió versión 21.0.1 y falló al abrir el log de Resolve fuera del sandbox. `open ... --args -nogui` devolvió `-10827`. La API devolvió exactamente `{'connected': False, 'version': None}`. Véase `command_transcript.md`. |
| 2. Cuatro cortes por timestamp | **No confirmado empíricamente; preparado según API instalada** | El arnés usa `CreateTimelineFromClips` y 24 fps obtenidos por `ffprobe`. Cuantización prevista: c1 1870 frames/77.9167 s; c2 1586/66.0833 s; c3 635/26.4583 s; c4 422/17.5833 s. Registra duración y frames fuente reales devueltos por cada `TimelineItem`. |
| 3. Fusion crop 9:16 sin Studio | **No confirmado empíricamente** | El arnés crea una comp con `AddFusionComp`, inserta `Transform`, conecta `MediaIn → Transform → MediaOut`, centra y renderiza 360×640. La documentación instalada expone estas APIs sin marcarlas Studio; esto no sustituye una prueba viva. `SmartReframe()` también se registra como control negativo. |
| 4. Batch render, dos formatos | **No confirmado empíricamente** | El arnés consulta formatos/códecs reales y encola una muestra H.264 MP4 640×360 de c3 y el c4 Fusion a 360×640 con `SetRenderSettings`, `AddRenderJob` y `StartRendering`; luego valida cada archivo con `ffprobe`. |
| 5. Quick Export local | **Nombres locales no disponibles; web oficial confirmada** | `GetQuickExportRenderPresets()` está instrumentado, pero requería conexión. Blackmagic documenta presets de YouTube, Vimeo y TikTok; Resolve 21 también anuncia subida directa a YouTube, TikTok, Vimeo y X. No se encontró un preset nativo con nombre específico “YouTube Shorts” o “Instagram Reels”; sí hay resoluciones verticales destinadas a ambos. |
| 6. SRT externo + BurnIn | **No confirmado empíricamente; ruta pública incierta** | El arnés intenta `ImportMedia(c1.srt)`, crea pista `subtitle`, intenta `AppendToTimeline` y solo renderiza con `SubtitleFormat: BurnIn` si encuentra items reales en esa pista. La API instalada documenta importar SRT al Media Pool y renderizar subtítulos, pero no documenta explícitamente insertar un MediaPoolItem SRT en una pista; un `False` sería una limitación real, no un éxito. |
| 7. Studio: costo/beneficio | **Confirmado por web oficial** | Blackmagic vende Resolve Studio 21 por **US$295**. La documentación oficial de funciones identifica como Studio Smart Reframe, Magic Mask, Speed Warp, Super Scale y Voice Isolation, entre otras. |

## Evidencia local y reproducibilidad

- Material inspeccionado: `video_horizontal.mp4`, H.264 3840×2160, 24 fps, 263.17 s; audio AAC.
- Plan inspeccionado: cuatro rangos reales; el arnés redondea inicio y fin al frame más cercano y usa fin inclusivo.
- `run_live_tests.py`: registra todo en `live_events.jsonl`/`live_results.json`; usa un nombre de proyecto único y elimina render jobs y proyecto en `finally`.
- `resolve_headless.log`: salida real del único proceso Resolve que llegó a arrancar.
- `command_transcript.md`: comandos y devoluciones exactas.

## Quick Export en 2026

La página oficial de [Quick Export de Blackmagic](https://www.blackmagicdesign.com/products/davinciresolve/cut) enumera YouTube, Vimeo y TikTok, además de H.264/H.265 y ProRes. La página oficial [What's New de Resolve 21](https://www.blackmagicdesign.com/products/davinciresolve/whatsnew) enumera subida a YouTube, TikTok, Vimeo y X, y separadamente resoluciones verticales para TikTok, Instagram, X, YouTube Shorts y Snapchat. La lectura prudente es: **TikTok sí es un preset/servicio nativo; Shorts y Reels son destinos soportados mediante resolución vertical y exportación/subida general, no presets Quick Export específicos demostrados con esos nombres**.

## Studio: referencia de costo y funciones

El sitio oficial lista [DaVinci Resolve Studio 21 a US$295](https://www.blackmagicdesign.com/products/davinciresolve/studio), como compra de licencia de escritorio (activation key/dongle/cloud licensing; no se presenta como suscripción). Funciones Studio relevantes para ClipFactory:

1. **Smart Reframe**: seguimiento automático del sujeto al cambiar a formato vertical.
2. **Magic Mask / object isolation and tracking**: detección y seguimiento de persona/objeto para layouts más sofisticados.
3. **Voice Isolation** (y herramientas AI de diálogo): limpieza de voz para material ruidoso.

La [matriz oficial de funciones Studio](https://documents.blackmagicdesign.com/uk/SupportNotes/DaVinci_Resolve_Studio_20_Features.pdf?_v=1751871610000) también marca Smart Reframe, Speed Warp, Super Scale, Voice Isolation y transcripción/subtítulos desde audio como Studio.

## Recomendación

**No integrar Resolve como motor principal de corte + multi-formato + captions por ahora.** Aun si el arnés funcionara fuera del sandbox, FFmpeg ya resuelve de forma más simple, determinista, portable y observable los cortes exactos, el crop/scale 9:16, los renders múltiples y el burn-in de nuestros SRT. Resolve añade una aplicación pesada, base de proyectos, tiempos de arranque y una API con un hueco importante para insertar SRT externos.

Mantener FFmpeg como camino de producción y considerar Resolve solo como adaptador opcional cuando aporte algo que FFmpeg no ofrece bien: acabados/color/Fusion diseñados por un editor o, si algún día se adquiere Studio, Smart Reframe/Magic Mask. Antes de cualquier integración, ejecutar `run_live_tests.py` una vez desde una Terminal normal para resolver empíricamente los puntos 2–6 y capturar la lista local exacta de Quick Export.
