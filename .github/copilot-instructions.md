# Instrucciones de contexto para Copilot

## Uso automático del vault de Obsidian

El vault de Obsidian es la raíz del repositorio. Para solicitudes no triviales de desarrollo, análisis, depuración, documentación o planificación recibidas por chat, recupera el contexto sin pedir al usuario que lo repita:

1. Lee `AGENTS.md` y la entrada más reciente relevante de `notes/bitacora.md` antes de investigar o modificar archivos.
2. Lee `notes/decisiones.md`, `notes/preguntas.md` y las notas enlazadas desde la bitácora solo cuando sean pertinentes para la tarea. No recorras todo el vault por defecto.
3. Trata `README.md` y `README_ES.md` como referencia técnica canónica, `TODO.md` y `TODO_ES.md` como seguimiento oficial, y `docs/source/` como fuentes de documentación Sphinx/MyST. No dupliques su contenido en las notas.
4. Tras un cambio significativo en el repositorio, añade o actualiza una entrada breve en `notes/bitacora.md`: objetivo, archivos afectados, hallazgo o decisión, validación y siguiente paso. Si corresponde, registra decisiones duraderas en `notes/decisiones.md` y preguntas sin resolver en `notes/preguntas.md`.

Para preguntas simples, explicaciones generales o peticiones que no requieran contexto del proyecto, responde directamente sin cargar notas innecesarias. Las instrucciones explícitas del usuario siempre prevalecen: si pide no leer o no actualizar una nota, respétalo.

## Alcance técnico

Copilot trabaja con los archivos Markdown del vault; no necesita controlar la interfaz gráfica de Obsidian. Usa enlaces wiki existentes para navegar y conserva las notas concisas. La configuración local `.obsidian/` está ignorada por Git y no debe modificarse salvo que el usuario lo solicite.
