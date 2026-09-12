---
aliases:
  - Tutorial de Obsidian
  - Manual de Obsidian
tags:
  - pyweatherfiles
  - documentacion
  - obsidian
---

# Tutorial de Obsidian para `pyweatherfiles`

Este vault usa la raíz del repositorio como espacio de conocimiento. Obsidian complementa el código y la documentación existente: no sustituye los README, los TODO ni la documentación Sphinx.

## 1. Dónde está cada cosa

| Ubicación | Uso |
|---|---|
| [[Home|`Home.md`]] | Punto de entrada y mapa del proyecto. Ábrelo al comenzar. |
| [[README_ES|`README_ES.md`]] | Referencia técnica canónica en español. |
| [[TODO_ES|`TODO_ES.md`]] | Seguimiento oficial de tareas. |
| `docs/source/` | Fuentes de la documentación Sphinx/MyST. |
| `notes/` | Notas de trabajo, decisiones, dudas y referencias. |
| `notes/plantillas/` | Plantillas para crear notas consistentes. |
| `notes/adjuntos/` | Imágenes, PDF u otros adjuntos creados desde Obsidian. |

> [!warning]
> No edites `docs/source/full_reference_*.md` ni `docs/source/article_context.md` como fuente principal: son envoltorios MyST de documentos de la raíz. Usa los originales enlazados desde [[Home]].

## 2. Flujo de trabajo recomendado

### Al iniciar una sesión

1. Abre [[Home|Inicio]].
2. Revisa [[TODO_ES|las tareas oficiales]] y la última entrada de [[notes/bitacora|la bitácora]].
3. En `notes/bitacora.md`, añade una entrada nueva al principio con [[notes/plantillas/Nota diaria|la plantilla de sesión]].
4. En la entrada, deja un objetivo verificable y enlaza solo los archivos necesarios.

### Mientras trabajas

- Usa enlaces internos de formato wiki para conectar código, documentación y resultados.
- Marca pasos concretos con `- [ ]` y `- [x]`.
- Si tomas una decisión de diseño o reproducibilidad, regístrala en [[notes/decisiones|Decisiones]].
- Si surge una duda no resuelta, añádela a [[notes/preguntas|Preguntas abiertas]].
- Para una fuente externa, dataset, norma o paper, usa [[notes/referencias|Referencias]].

### Al terminar

1. Escribe qué cambió, qué validación ejecutaste y cuál es el siguiente paso en [[notes/bitacora|la bitácora]].
2. Actualiza `TODO_ES.md` si el estado oficial de una tarea cambió.
3. Si la nota debe compartirse, inclúyela en el próximo commit de Git.

## 3. Escribir y enlazar notas

### Enlaces wiki

Usa enlaces wiki para evitar copiar contexto:

- `[[README_ES]]` enlaza la referencia técnica.
- `[[README_ES|referencia técnica]]` cambia el texto visible.
- `[[notes/decisiones#D-001]]` enlaza una sección concreta.
- `[[analysis_scripts/conclusion_report]]` enlaza resultados de análisis.

Cuando escribas `[[`, Obsidian ofrece archivos existentes. Elige el resultado de la lista para evitar crear enlaces rotos.

### Markdown esencial

```markdown
# Título
## Sección

- Lista
- [ ] Tarea pendiente
- [x] Tarea terminada

**texto importante**
`código o ruta`

> Nota o cita
```

Los adjuntos arrastrados o pegados se guardan en `notes/adjuntos/` por la configuración actual del vault. Revisa siempre tamaño, procedencia y licencia antes de añadirlos a Git.

### Propiedades y etiquetas

Cada nota puede empezar con propiedades YAML entre `---`. Úsalas para información estable, por ejemplo `tipo`, `fecha` o `estado`. Las etiquetas son útiles para temas transversales y breves:

- `#tmy`
- `#epw`
- `#tendencias`
- `#decision`
- `#documentacion`

No uses etiquetas para repetir toda la estructura de carpetas ni para sustituir enlaces entre documentos.

## 4. Crear notas con plantillas

El complemento nativo **Templates** está activado y busca plantillas en `notes/plantillas/`.

1. Crea una nota nueva; se guardará en `notes/` por defecto.
2. Abre la paleta de comandos con `Ctrl+P`.
3. Ejecuta **Templates: Insert template**.
4. Elige `Nota diaria` para una sesión de trabajo o `Registro de decisión` para una decisión persistente.
5. Completa los campos vacíos y añade enlaces a la evidencia.

Puedes usar también el explorador de archivos para duplicar una plantilla y renombrarla.

## 5. Encontrar información rápidamente

- **Búsqueda global:** `Ctrl+Shift+F`. Busca términos, etiquetas, nombres de clase o texto de una decisión.
- **Selector rápido:** `Ctrl+O`. Abre un archivo por nombre; escribe `Home`, `bitacora`, `TODO_ES` o un módulo.
- **Backlinks:** abre el panel de enlaces entrantes de una nota para ver qué documentos la usan.
- **Enlaces salientes:** comprueba si una nota importante ya conduce a la evidencia adecuada.
- **Grafo local:** úsalo desde una nota concreta para explorar relaciones sin el ruido de todo el repositorio.

## 6. Usar Obsidian para reducir contexto y tokens

La bitácora debe ser la memoria compacta del trabajo. Una entrada útil suele tener entre 5 y 12 líneas:

```markdown
## 2026-09-12 — Revisar tendencia de grados-hora

- Objetivo: validar el estimador global.
- Archivos: [[pyweatherfiles/degree_hours/group_trend_analyzer]], [[INFORME_REVISION_GENERAL]].
- Hallazgo: ...
- Validación: `python -m pytest tests/...`
- Próximo paso: ...
```

Para pedir ayuda en una sesión nueva, indica la nota que debe leerse y limita el alcance. Ejemplo:

```text
Lee `notes/bitacora.md` y solo los archivos enlazados que sean necesarios.
Continúa la entrada más reciente.
Objetivo: [resultado concreto].
No modifiques archivos fuera de: [rutas].
Al terminar, actualiza la bitácora con cambios, validación y siguiente paso.
```

Esto permite recuperar el contexto relevante desde el vault en lugar de repetir antecedentes, resultados y decisiones en el chat.

### Contexto automático en el chat

El repositorio incluye `.github/copilot-instructions.md`. En tareas no triviales, Copilot consulta la entrada relevante más reciente de [[notes/bitacora|la bitácora]] y, solo si aplica, las decisiones, preguntas y documentos enlazados. Por tanto, puedes mantener tu flujo habitual: pide la tarea directamente por el chat.

La instrucción evita cargar todas las notas para preguntas simples o generales. Si alguna vez quieres limitar o evitar ese contexto, dilo explícitamente, por ejemplo: “responde sin consultar notas” o “usa únicamente `archivo.md`”. Las instrucciones explícitas de cada mensaje prevalecen sobre el protocolo del vault.

## 7. Git y seguridad

- Las notas de `notes/` y `Home.md` son documentos del proyecto y pueden compartirse mediante Git.
- `.obsidian/` está ignorado: guarda interfaz, complementos y preferencias locales de esta instalación.
- `sync_branch.bat` protege `Home.md` y `notes/` al ejecutar su limpieza, pero **puede borrar otros archivos no rastreados**. No lo ejecutes si tienes resultados, datos o código no guardados en Git fuera de esas rutas.
- Antes de compartir una nota, elimina rutas sensibles, credenciales, información personal o resultados provisionales que no deban publicarse.

## 8. Lista de comprobación rápida

- [ ] Empecé desde [[Home]].
- [ ] Registré objetivo, evidencia y próximo paso en [[notes/bitacora|la bitácora]].
- [ ] Guardé una decisión duradera en [[notes/decisiones|Decisiones]], si correspondía.
- [ ] Actualicé el TODO canónico si una tarea cambió de estado.
- [ ] Revisé qué notas y adjuntos deben incluirse en Git.

## Enlaces relacionados

- [[notes/README|Guía breve del vault]]
- [[notes/bitacora|Bitácora]]
- [[notes/decisiones|Decisiones]]
- [[notes/preguntas|Preguntas abiertas]]
- [[notes/referencias|Referencias]]
- [[Home|Inicio]]
