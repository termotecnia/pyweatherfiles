---
aliases:
  - ADR
  - Decisiones arquitectónicas
tags:
  - pyweatherfiles
  - decision
---

# Registro de decisiones

Registra decisiones que cambien el diseño, la reproducibilidad, las fuentes de datos o las convenciones del proyecto. Añade las nuevas entradas al principio con [[notes/plantillas/Registro de decisión|la plantilla de decisión]].

---

## D-001 — Mantener Obsidian como capa documental no intrusiva

- **Fecha:** 2026-09-12
- **Estado:** aceptada
- **Contexto:** El proyecto ya dispone de README bilingües, seguimiento en TODO y documentación Sphinx/MyST. Se necesita un espacio de trabajo navegable para notas y relaciones entre documentos sin crear fuentes duplicadas.
- **Decisión:** Usar la raíz del repositorio como vault. Mantener las notas compartibles en `notes/`, conservar `Home.md` como índice y excluir `.obsidian/` del control de versiones.
- **Consecuencias:** La documentación canónica no se duplica. Cada instalación puede personalizar su interfaz de Obsidian. Las notas que se quieran compartir deben añadirse explícitamente a Git.
- **Enlaces:** [[Home]], [[README_ES]], [[docs/source/index]]
