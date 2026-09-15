# Prototipo de metadata por clip

## Decisiones de diseño

- **Salida en texto plano.** Cada clip produce `preview/<clip_id>.txt` con tres bloques: `TÍTULO`, `DESCRIPCIÓN` y `ORIGEN`. Título y descripción quedan listos para copiar y pegar; `ORIGEN` conserva trazabilidad sin mezclarse con el copy publicable. JSON sería más cómodo para automatización, pero peor para el uso humano inmediato de este prototipo.
- **Título breve y en formato gancho.** Las reglas temáticas prefieren preguntas y el script impone un máximo de 69 caracteres. El fallback recorta por palabra y añade elipsis cuando hace falta.
- **Descripción de tres líneas.** La primera da contexto, la segunda contiene un CTA genérico y la tercera deja hashtags editables. Es una estructura válida para Shorts, TikTok y Reels sin introducir lógica específica por plataforma.
- **SRT opcional.** El script busca `clips/<clip_id>.srt` junto al `clip_plan.json`, elimina índices y timestamps y usa todo el diálogo como contexto para seleccionar la regla. Así, `c2` puede mencionar la diferencia entre IA débil y general, y `c3` el debate sobre LLM, aunque esos matices no estén completos en `quote`. Si falta el SRT, genera metadata solo con `quote` y `block`.
- **Seguridad y alcance.** Los clips con `needs_review=true` se omiten, los IDs se validan antes de usarlos como nombres de archivo y cualquier `--output-dir` fuera de `output/_research/metadata/` se rechaza.
- **Sin dependencias.** El modo template usa únicamente la biblioteca estándar y es determinista. Las reglas son deliberadamente pequeñas; no se creó una arquitectura de proveedores antes de tener un proveedor real.

## Modos y tradeoffs

### Template (default)

Ventajas: funciona sin API key, no cuesta por ejecución, no añade latencia de red, es reproducible y resulta sencillo auditar por qué produjo cada texto. Para este fixture de IA, las cuatro reglas temáticas entregan borradores razonables.

Limitaciones: no entiende intención, tono de marca ni matices. Las reglas que funcionan bien aquí no generalizan automáticamente a videos de otros temas; el fallback (`La idea clave de <bloque>...`) es correcto pero poco atractivo y puede repetir demasiado el transcript. También usa hashtags genéricos. Mantener calidad en muchos dominios implicaría acumular reglas frágiles.

### LLM (hook opcional)

`generate_via_llm(clip, context)` documenta el contrato y el prompt sugerido, pero por ahora lanza un error claro y no llama a ninguna API. Una implementación real debería pedir JSON estructurado, limitar el título, prohibir afirmaciones no presentes en las fuentes y validar la respuesta antes de escribirla.

Ventajas esperadas: mejores ganchos, síntesis más natural del SRT, adaptación al tema y menos necesidad de reglas manuales. Costos: API key y dependencia de proveedor, precio por clip, latencia, resultados variables, posibles alucinaciones y necesidad de validación/reintentos. Para controlar calidad convendría usar temperatura baja y conservar revisión humana durante la calibración.

## Ejemplos generados con el fixture real

### c1

```text
TÍTULO
¿Qué es la inteligencia artificial según la UNESCO?

DESCRIPCIÓN
La IA ya media muchas tareas cotidianas. Esta definición de la UNESCO explica qué tienen en común esos sistemas.
¿Qué opinas? Cuéntamelo en comentarios y sigue la cuenta para ver más.
#IA #InteligenciaArtificial #Tecnología

ORIGEN
Clip: c1 | Sección: Bloque 1 | Contexto SRT: sí
```

### c2

```text
TÍTULO
¿Qué pasaría si la IA supera la inteligencia humana?

DESCRIPCIÓN
La IA débil ya resuelve tareas específicas; la IA general sigue siendo hipotética y podría exceder nuestras capacidades.
¿Qué opinas? Cuéntamelo en comentarios y sigue la cuenta para ver más.
#IA #InteligenciaArtificial #Tecnología

ORIGEN
Clip: c2 | Sección: Bloque 1 | Contexto SRT: sí
```

### c3

```text
TÍTULO
¿La IA podría provocar una singularidad tecnológica?

DESCRIPCIÓN
Los LLM actuales reabren el debate sobre una IA capaz de igualar o superar la inteligencia humana y sus posibles consecuencias.
¿Qué opinas? Cuéntamelo en comentarios y sigue la cuenta para ver más.
#IA #InteligenciaArtificial #Tecnología

ORIGEN
Clip: c3 | Sección: Bloque 2 | Contexto SRT: sí
```

### c4

```text
TÍTULO
ChatGPT, Copilot, Gemini y Claude: ¿qué tienen en común?

DESCRIPCIÓN
Los modelos generativos aprenden patrones para crear contenido nuevo. Estos son cuatro de sus ejemplos más conocidos.
¿Qué opinas? Cuéntamelo en comentarios y sigue la cuenta para ver más.
#IA #InteligenciaArtificial #Tecnología

ORIGEN
Clip: c4 | Sección: Bloque 2 | Contexto SRT: sí
```

## Recomendación

El modo template alcanza para una **v1 de borradores con revisión humana** y sirve como fallback sin red. No alcanza para prometer metadata publicable sin edición humana en videos de temas variados: los buenos resultados de este fixture dependen de reglas temáticas específicas y el fallback es mediocre. Si “listo para subir” significa realmente cero edición, conviene conectar un LLM desde el arranque, mantener el template como respaldo y validar ambos contra una muestra diversa antes de automatizar la publicación.
