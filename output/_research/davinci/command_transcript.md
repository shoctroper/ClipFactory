# Transcripción de comandos — 2026-08-11

Directorio de trabajo en todos los casos:

```text
~/Repos/ClipFactory
```

## Inventario del medio

```sh
ffprobe -v error -show_entries stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,duration -show_entries format=duration -of json output/VideoConGuionYouTube/video_horizontal.mp4
```

Resultado relevante: H.264, `3840x2160`, `24/1 fps`, duración de video `263.166667 s`; AAC, duración `263.232 s`.

## Lanzamiento directo solicitado

```sh
'/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve' -nogui > output/_research/davinci/resolve_headless.log 2>&1 &
```

Resultados observados:

```text
resolve_pid=34270
alive_after_5s=yes
alive_after_10s=no
log4cxx: setFile(~/Library/Application Support/Blackmagic Design/DaVinci Resolve/logs/davinci_resolve.log,true) call failed.
log4cxx: IO Exception : status code = 1
```

Interpretación: la app arrancó y publicó `21.0.1.0011 macOS/Clang arm64`, pero el sandbox de esta sesión impidió escribir en su propio directorio de soporte y el proceso terminó.

## Lanzamiento mediante LaunchServices

```sh
open -na '/Applications/DaVinci Resolve/DaVinci Resolve.app' --args -nogui
```

Resultado:

```text
NSOSStatusErrorDomain Code=-10827 "kLSNoExecutableErr: The executable is missing"
```

Se verificó inmediatamente que el ejecutable sí existe, tiene permiso `rwxr-xr-x`, figura como `CFBundleExecutable=Resolve` y contiene binarios Mach-O `arm64` y `x86_64`. Por eso el mensaje se atribuye a la frontera del sandbox/LaunchServices, no a una ausencia física.

## Conexión API

```sh
export RESOLVE_SCRIPT_API='/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting'
export RESOLVE_SCRIPT_LIB='/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so'
export PYTHONPATH="$RESOLVE_SCRIPT_API/Modules"
python3 - <<'PY'
import DaVinciResolveScript as dvr
r = dvr.scriptapp('Resolve')
print({'connected': bool(r), 'version': r.GetVersionString() if r else None})
PY
```

Resultado exacto:

```text
{'connected': False, 'version': None}
```

## Ejecución pendiente fuera del sandbox

El arnés completo está en `run_live_tests.py`. Desde una Terminal normal, después de lanzar Resolve con `-nogui`:

```sh
cd ~/Repos/ClipFactory/output/_research/davinci
export RESOLVE_SCRIPT_API='/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting'
export RESOLVE_SCRIPT_LIB='/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so'
export PYTHONPATH="$RESOLVE_SCRIPT_API/Modules"
python3 run_live_tests.py
```

El script usa nombre único `ClipFactory_RESEARCH_*` y su bloque `finally` ejecuta `DeleteAllRenderJobs`, `CloseProject` y `DeleteProject`; también comprueba que el nombre ya no aparezca en la carpeta actual.
