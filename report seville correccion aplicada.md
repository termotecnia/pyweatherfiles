Ran command: `python tmy_seville_revision.py 2>&1 | Out-File -FilePath tmy_revision_output.txt -Encoding utf8; Get-Content tmy_revision_output.txt`

El script se ejecutó correctamente. Aquí está el análisis completo de los resultados:

---

## Resultados del Diagnóstico — TMY3 Sevilla (Meses de Verano)

### Composición del TMY
| Mes | Año seleccionado |
|-----|-----------------|
| **Junio** | 2007 |
| **Julio** | 2014 |
| **Agosto** | 2011 |

---

### Hallazgos críticos

#### 🔴 **JULIO (2014) — ANOMALÍA PRINCIPAL**
- **Posición FS**: #5 de 21 años → es el **peor candidato** del top-5
- **T_air media**: 25.63°C vs. media histórica de 27.20°C → **diferencia de −1.57°C**
- **Percentil**: 10% → es uno de los julios **más fríos** de toda la serie
- El año 2014 fue seleccionado a pesar de tener el peor FS del grupo, probablemente porque el **Proximity Ranking lo priorizó** (menor desviación de media/mediana histórica), pero después la **Persistence lo mantuvo** aunque en realidad la temperatura media mensual sea inusualmente baja

#### 🟡 **JUNIO (2007)**
- **Posición FS**: #5 de 21 años → también el peor del top-5
- **T_air media**: diferencia de −0.32°C respecto a la media → aceptable
- Percentil 33% → ligeramente frío pero dentro de lo razonable

#### ✅ **AGOSTO (2011)**
- **Posición FS**: #2 de 21 años → buen candidato
- Diferencia de temperatura: +0.12°C → prácticamente en la media
- Percentil 19% → algo frío, pero con FS excelente

---

### Causa probable de la anomalía de Sevilla

**El problema central está en Julio 2014**: el algoritmo de Proximity Ranking lo seleccionó como #1 dentro de los 5 candidatos FS porque sus métricas de desviación media/mediana eran bajas en los datos diarios, pero la temperatura media mensual real (25.63°C vs. 27.20°C histórico) es muy baja para la serie larga. Esto explicaría por qué Sevilla no muestra el efecto de calentamiento de verano al comparar el TMY vs. el `.MET` — **el Julio del TMY es atípicamente frío** (percentil 10%).

**Acción recomendada**: Revisar manualmente la selección de Julio e imponer el año con mayor representatividad térmica del top-5, o ajustar los pesos del Proximity Ranking para dar más peso a la temperatura media mensual.

Las figuras guardadas son:
- `seville_tmy_summer_trend.png` — tendencia temporal con marca del año TMY
- `seville_tmy_summer_daily_series.png` — series diarias T_air
- `seville_tmy_summer_daily_ghi.png` — series diarias GHI