# Prueba de metadata con Ollama remoto

Fecha de la prueba: 2026-08-12.

## Resultado ejecutivo

`qwen2.5:3b` funciona bien como infraestructura remota y genera los cuatro borradores en 11.54 s, pero **no conviene como generador autónomo de metadata para v1**. En este fixture, el template fue más preciso y publicable en los cuatro clips. El modelo omitió la CTA en tres de cuatro respuestas antes del postproceso y produjo una promesa inventada en c2. Sí puede servir como candidato opcional para ideación con revisión humana, manteniendo el template como respaldo obligatorio.

## Arquitectura y ejecución

La Mac sólo inicia SSH y transfiere archivos pequeños. El script Python y Ollama corren en Athena; la API `http://localhost:11434/api/generate` nunca se expone fuera del server.

```text
Mac (fixtures + comando SSH)
  └─ scp/ssh → Athena: ~/clipfactory/_metadata_test/
                 ├─ generate_metadata_ollama.py
                 ├─ clip_plan.json + clips/*.srt
                 └─ Ollama localhost:11434 → qwen2.5:3b
  └─ scp ← preview_ollama/qwen2.5-3b/*.txt
```

Comandos equivalentes a los usados:

```bash
ssh athena 'mkdir -p "$HOME/clipfactory/_metadata_test/clips"'
scp generate_metadata_ollama.py clip_plan.json athena:clipfactory/_metadata_test/
scp clips/*.srt athena:clipfactory/_metadata_test/clips/
ssh athena 'cd "$HOME/clipfactory/_metadata_test" && python3 generate_metadata_ollama.py clip_plan.json --model qwen2.5:3b --output-dir preview_ollama/qwen2.5-3b'
scp 'athena:clipfactory/_metadata_test/preview_ollama/qwen2.5-3b/*.txt' preview_ollama/qwen2.5-3b/
```

El script usa sólo la biblioteca estándar. Solicita JSON estructurado, valida título, descripción y tres hashtags, reintenta una vez y luego usa las mismas reglas del template. Como el 3B suele devolver toda la descripción en una sola línea, el postproceso separa oraciones/hashtags. Si omite CTA pero el JSON restante es válido, añade la CTA estable del template y lo registra en el `.txt`.

## Entorno verificado

- `ssh athena 'ollama list'`: `qwen2.5:3b`, 1.9 GB, Ollama 0.32.6.
- Consulta simple: respondió `Hola` en 2.273 s; 2.174 s correspondieron a carga en frío.
- Antes de la prueba: 3,679 MiB de VRAM libres; ComfyUI mantenía un proceso de 82 MiB.
- Durante la residencia del modelo: Ollama usó 2,170 MiB; quedaron 1,504 MiB libres.
- Disco de Athena: 55 GB libres. No se instaló ni descargó nada en la Mac.
- Una conexión SSH vacía tardó 0.45 s. La API es local a Athena, así que ese costo se paga por lote, no por clip.

## Tiempos de la corrida canónica

Modelo caliente, ejecución secuencial, semilla fija. “Carga” es el tiempo que reporta Ollama dentro de cada llamada.

| Clip | Tiempo pared | Ollama | Carga | CTA añadida | Fallback |
|---|---:|---:|---:|---|---|
| c1 | 2.873 s | 2.863 s | 0.169 s | sí | no |
| c2 | 2.541 s | 2.538 s | 0.177 s | no | no |
| c3 | 3.546 s | 3.543 s | 0.168 s | sí | no |
| c4 | 2.584 s | 2.581 s | 0.173 s | sí | no |
| **Total / promedio** | **11.544 s / 2.886 s** | **11.525 s / 2.881 s** | **0.687 s** | **3/4** | **0/4** |

Un primer clip después de descargar el modelo de VRAM debe presupuestar aproximadamente 2 s adicionales de carga, según la consulta fría. El overhead SSH medido fue 0.45 s por conexión; conviene ejecutar todos los clips en una sola sesión, como hace el comando anterior.

## Comparación de calidad

### c1 — gana template

Template:

> **¿Qué es la inteligencia artificial según la UNESCO?**  
> La IA ya media muchas tareas cotidianas. Esta definición de la UNESCO explica qué tienen en común esos sistemas.

Ollama:

> **¿Qué es la Inteligencia Artificial?**  
> La IA son sistemas informáticos diseñados para emular capacidades humanas.

El template usa el detalle diferenciador (UNESCO) en el título. Ollama es correcto en términos generales, pero más genérico y menos natural (“La IA son…”).

### c2 — gana template por margen amplio

Template:

> **¿Qué pasaría si la IA supera la inteligencia humana?**  
> La IA débil ya resuelve tareas específicas; la IA general sigue siendo hipotética y podría exceder nuestras capacidades.

Ollama:

> **La IA General: Más Allá de las Capacidades Humanas**  
> ¡Aprende a programar agentes inteligentes que actúan y piensan de manera natural!

La promesa de aprender a programar agentes no está en el SRT y cambia el valor ofrecido por el clip. Es una alucinación publicable peligrosa que las validaciones estructurales no detectan.

### c3 — template más sobrio y fiel

Template:

> **¿La IA podría provocar una singularidad tecnológica?**

Ollama:

> **¿Podría Ocurrir una Singularidad Tecnológica?**  
> ¿Estás listo para ver cómo cambiará nuestro mundo?  
> #IAevolucionará #SingularidadTecnológica #IGA

Los títulos son comparables, pero Ollama convierte una posibilidad debatida en una insinuación más afirmativa y crea un hashtag poco natural. El template conserva mejor la cautela de la fuente.

### c4 — template más específico; cuerpo de Ollama aceptable

Template:

> **ChatGPT, Copilot, Gemini y Claude: ¿qué tienen en común?**

Ollama:

> **Modelos Generativos Aprendiendo Patrones**  
> Ejemplos como ChatGPT, Microsoft Copilot, Gemini de Google y Claude de Anthropic ilustran este proceso.

Ollama preserva los cuatro nombres y resume bien en el cuerpo, pero su título pierde el gancho concreto que ya entrega el template.

## Recomendación para v1

No reemplazar el template por `qwen2.5:3b`. Para una v1 segura:

1. Usar template como salida automática y fallback cuando SSH, Ollama o la GPU no estén disponibles.
2. Ofrecer Ollama como segundo borrador opcional para revisión humana, especialmente en temas sin regla template.
3. No publicar automáticamente sólo porque el JSON pasó validación: c2 demuestra que estructura válida no equivale a fidelidad factual.
4. Ejecutar metadata después de WhisperX/ComfyUI o con una cola. El modelo ocupa ~2.17 GB de una GPU de 4 GB; la concurrencia puede causar descarga de capas a CPU, mayor latencia, falta de memoria o interferencia con esos procesos.
5. Conservar timeout y fallback por clip para que una GPU ocupada no detenga el lote completo.

No se descargó un segundo modelo: con `qwen2.5:3b` residente sólo quedaban 1.5 GB de VRAM y ya había un proceso de ComfyUI. Una comparación mayor no justificaba introducir contención ni otra descarga para esta decisión de v1.
