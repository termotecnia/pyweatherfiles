---
aliases:
  - Guía del vault
  - Uso de Obsidian
tags:
  - pyweatherfiles
  - documentacion
---

# Cómo usar el vault de `pyweatherfiles`

## Propósito

Este vault organiza el conocimiento de trabajo alrededor del código sin sustituir la documentación oficial:

- `README.md` y `README_ES.md` son la referencia técnica autoritativa.
- `TODO.md` y `TODO_ES.md` contienen el seguimiento oficial de tareas.
- `docs/source/` alimenta la documentación Sphinx/MyST publicada.
- `notes/` reúne contexto, decisiones y seguimiento que complementan esas fuentes.

## Flujo recomendado

1. Abre [[Home|Inicio]] al comenzar una sesión.
2. Registra el avance y los comandos o resultados relevantes en [[bitacora|Bitácora]].
3. Cuando una elección afecte al diseño, consérvala en [[decisiones|Registro de decisiones]].
4. Mantén las incertidumbres investigables en [[preguntas|Preguntas abiertas]].
5. Añade fuentes, datasets y lecturas a [[referencias|Referencias y recursos]].
6. Al cerrar una tarea, actualiza el `TODO` canónico correspondiente si procede.

## Convenciones de las notas

- Enlaza archivos internos con enlaces wiki; usa una etiqueta descriptiva cuando ayude a la lectura: `[[README_ES|referencia técnica]]`.
- Usa las etiquetas existentes de forma breve: `#tmy`, `#epw`, `#tendencias`, `#documentacion` y `#decision`.
- No copies secciones extensas de los README o de Sphinx: enlaza a su fuente canónica.
- Las plantillas de `plantillas/` proporcionan la estructura mínima para notas de sesión y decisiones.

## Git y seguridad

- El contenido de `notes/` **puede versionarse**: añade a Git únicamente las notas que deban compartirse.
- `.obsidian/` contiene configuración de interfaz, complementos y estado de esta instalación; está ignorado deliberadamente.
- `sync_branch.bat` protege `Home.md` y `notes/` de su limpieza `git clean -fd`, incluso si aún no los has añadido a Git.
- Los adjuntos creados desde Obsidian se guardan en `notes/adjuntos/`. Revisa su tamaño y licencia antes de versionarlos.

> [!note]
> Para usar este repositorio como vault, selecciona **Open folder as vault** en Obsidian y abre la raíz `D:\Python\pyweatherfiles`.
