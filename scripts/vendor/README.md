# vendor/ — copias verificadas, no reimplementaciones

`vertical_cropper.py` viene de:

    /Volumes/Medios/Repos/CleanVideos/video_pipeline/scripts/vertical_cropper.py

Está copiado aquí, y no importado desde allá, por una razón operativa medida el
2026-09-22: el agente implementador **no puede leer fuera de su repositorio**
—opencode deniega `external_directory` en modo headless— así que una regla que
le exigiera usar el original le impedía trabajar. Tres intentos seguidos
terminaron en `OPERATIONAL_LIMIT` con diff vacío.

Copiar crea el riesgo de divergencia, así que la aceptación lo vigila: el caso
A2 compara el sha256 de esta copia con el del original y **falla si difieren**.
La copia no puede quedarse atrás en silencio.

sha256 en el momento de copiar: `70d7e39ad81efbbaf5494c06a37c11d36b45ed19f908001ca0b09e4ecdca8fc7`
