---
aliases:
  - Inicio
  - Dashboard del proyecto
tags:
  - pyweatherfiles
  - indice
---

# pyweatherfiles — inicio

Este es el punto de entrada del vault de Obsidian para el proyecto. Las notas propias están en `notes/`; la documentación técnica y científica existente conserva su ubicación original y es la fuente canónica.

## Empezar aquí

- [[README_ES|Referencia técnica completa (español)]]
- [[docs/source/quickstart|Guía de inicio rápido]]
- [[docs/source/installation|Instalación y construcción de documentación]]
- [[docs/source/tutorial_case_study|Caso de estudio: Sevilla y Madrid]]
- [[notes/README|Cómo usar este vault]]
- [[notes/Tutorial_Obsidian|Tutorial de Obsidian para este proyecto]]

## Trabajo activo

- [[TODO_ES|Tareas del proyecto]]
- [[notes/bitacora|Bitácora de trabajo]]
- [[notes/decisiones|Registro de decisiones]]
- [[notes/preguntas|Preguntas abiertas]]
- [[notes/referencias|Referencias y recursos]]

## Contexto y resultados

- [[ARTICLE_CONTEXT_SEVILLA|Contexto del artículo de Sevilla]]
- [[Manuscript_TMY_v02|Manuscrito TMY]]
- [[analysis_scripts/conclusion_report|Conclusiones del análisis de tendencias]]
- [[INFORME_REVISION_GENERAL|Informe de revisión general]]
- [[AGENTS|Guía de arquitectura y flujos de desarrollo]]

## Mapa del código

- `pyweatherfiles/tmy/` — generación TMY mediante Sandia/TMY3.
- `pyweatherfiles/degree_hours/` — grados-hora y tendencias asociadas.
- `pyweatherfiles/epw_trend_analyzer/` — tendencias climáticas multianuales.
- `analysis_scripts/` — scripts y artefactos de análisis.
- `tests/` — pruebas automatizadas.
- `docs/source/` — documentación Sphinx/MyST.

> [!tip]
> Para crear una nota nueva, usa la paleta de comandos de Obsidian y **Templates: Insert template**. Las plantillas están en `notes/plantillas/`.

> [!warning]
> `docs/source/full_reference_*.md` y `docs/source/article_context.md` son envoltorios MyST de los documentos de la raíz. Consulta los originales enlazados arriba para no trabajar sobre contenido duplicado.
