# DegreeHoursCalculator - Guía: Visualización de Consignas y Atributos

## ¿Por qué los atributos estaban vacíos?

**Antes de esta actualización**, los atributos `temperatures` y `setpoints` se inicializaban en `None` pero se usaban solo como variables locales en el método `calculate()`. Ahora se guardan en los atributos de clase.

### Cambio Implementado

```python
# ANTES
def __init__(self):
    self.epw_data = None
    self.temperatures = None   # Nunca se asignaban
    self.setpoints = None       # Nunca se asignaban
    self.result = None

# AHORA
def calculate(...):
    temps = pd.Series(...)
    setpoints = pd.Series(...)
    # ... cálculos ...
    result = pd.DataFrame(...)
    
    # Guardar en atributos de clase ✓
    self.temperatures = temps
    self.setpoints = setpoints
    self.result = result

# También method preview_setpoints() asigna setpoints
def preview_setpoints(...):
    setpoints = self.get_setpoints(...)
    # ... visualización ...
    self.setpoints = setpoints  # ✓ Guardar
    return setpoints
```

## Atributos Disponibles

### 1. `calculator.temperatures`
**Tipo:** `pd.Series`  
**Contenido:** Temperatura del aire horaria del archivo EPW  
**Índice:** DatetimeIndex horario

```python
from pyweatherfiles import DegreeHoursCalculator

calc = DegreeHoursCalculator()
result = calc.calculate(
    epw_path='madrid.epw',
    setpoint_source={...},
    frequency='monthly'
)

# Acceder a temperaturas
print(calc.temperatures.head())
# 2000-01-01 00:00:00     9.8
# 2000-01-01 01:00:00     9.7
# 2000-01-01 02:00:00     9.7
# ...

# Estadísticas
print(f"Temp mín: {calc.temperatures.min():.1f}°C")
print(f"Temp máx: {calc.temperatures.max():.1f}°C")
print(f"Temp promedio: {calc.temperatures.mean():.1f}°C")
```

### 2. `calculator.setpoints`
**Tipo:** `pd.Series`  
**Contenido:** Temperatura de consigna horaria (calefacción/refrigeración)  
**Índice:** DatetimeIndex horario  
**Nota:** Se asigna en `calculate()` o `preview_setpoints()`

```python
# Acceder a consignas
print(calc.setpoints.head())
# 2000-01-01 00:00:00    21.0
# 2000-01-01 01:00:00    21.0
# 2000-01-01 02:00:00    21.0
# ...

# Comparar con temperaturas
comparacion = pd.DataFrame({
    'Temperatura': calc.temperatures,
    'Consigna': calc.setpoints,
    'Diferencia': calc.temperatures - calc.setpoints
})
print(comparacion.head(24))
```

### 3. `calculator.result`
**Tipo:** `pd.DataFrame`  
**Contenido:** Grados-hora según frecuencia solicitada  
**Columnas:** 'heating', 'cooling', o 'degree_hours'  
**Se asigna en:** `calculate()`

```python
# Acceder a resultados
print(calc.result)
# Ejemplo para frecuencia='monthly':
#             heating    cooling
# 2000-01-31  11485.7      0.0
# 2000-02-29   9739.6      0.0
# 2000-03-31   8128.0     29.4
```

## Nuevos Métodos

### 1. `get_setpoints()` - Obtener consignas sin calcular

Retorna solo las consignas sin hacer el cálculo de grados-hora.

```python
calc = DegreeHoursCalculator()

setpoints_config = {
    'tipo': 'estacional',
    'invierno': 21.0,
    'verano': 26.0,
    'fechas_invierno': ('01-01', '03-31'),
    'fechas_verano': ('06-01', '09-30'),
}

# Obtener consignas
setpoints = calc.get_setpoints(
    setpoint_source=setpoints_config,
    mode='both'
)

# Analizar sin calcular
print(f"Consigna mín: {setpoints.min()}")
print(f"Consigna máx: {setpoints.max()}")

# Setpoints se guardan en calc.setpoints
print(calc.setpoints.head())
```

### 2. `preview_setpoints()` - Visualizar antes de calcular

Muestra estadísticas y gráficos de las consignas.

```python
# Vista previa sin gráfico
setpoints = calc.preview_setpoints(
    setpoint_source='building.idf',
    plot=False,
    sample_days=['2000-01-15', '2000-07-15']
)

# Vista previa con gráfico (salva como 'preview_setpoints.png')
setpoints = calc.preview_setpoints(
    setpoint_source=setpoints_config,
    plot=True,
    sample_days=['2000-01-15', '2000-07-15']
)
```

**Salida incluye:**
- Estadísticas: mín, máx, promedio, desviación estándar
- Agregación diaria: mín/máx/promedio por día
- Muestra de horas (opcional): valores para fechas específicas
- Gráfico (opcional): 3 subplots con variación diaria/mensual/horaria

## Flujo de Trabajo Recomendado

### Opción 1: Visualizar luego calcular

```python
calc = DegreeHoursCalculator()

# PASO 1: Visualizar consignas
print("Visualizando consignas...")
calc.preview_setpoints(
    setpoint_source='building.idf',
    plot=True,
    sample_days=['2000-03-21', '2000-06-21', '2000-12-21']
)

# Acceder a las consignas visualizadas
print(f"\nConsignas: {calc.setpoints}")

# PASO 2: Calcular grados-hora
print("\nCalculando grados-hora...")
result = calc.calculate(
    epw_path='madrid.epw',
    setpoint_source='building.idf',
    frequency='monthly',
    mode='both'
)

# PASO 3: Análisis
print(f"\nTemperaturas del EPW:")
print(calc.temperatures.describe())

print(f"\nConsignas:")
print(calc.setpoints.describe())

print(f"\nResultados:")
print(calc.result)
```

### Opción 2: Solo obtener consignas

```python
calc = DegreeHoursCalculator()

# Obtener consignas sin visualización
setpoints = calc.get_setpoints(
    setpoint_source='building.idf',
    zone_name='Sala',
    mode='heating'
)

# Analizar
print(f"Consigna de calefacción promedio: {setpoints.mean():.2f}°C")
```

### Opción 3: Uso con diccionarios personalizados

```python
calc = DegreeHoursCalculator()

# Consignas semanales
setpoints_config = {
    'tipo': 'semanal',
    'patrones': {
        'invierno': {'weekday': 21, 'weekend': 18},
        'verano': {'weekday': 26, 'weekend': 28}
    },
    'periodos': {
        'invierno': ('01-01', '04-30'),
        'verano': ('05-01', '12-31')
    }
}

# Visualizar
setpoints = calc.preview_setpoints(
    setpoint_source=setpoints_config,
    plot=True
)

# Los atributos se actualizan
print(calc.setpoints)
```

## Ejemplo Completo: IDF + Visualización

```python
from pyweatherfiles import DegreeHoursCalculator
import pandas as pd

calc = DegreeHoursCalculator()

print("=== ANÁLISIS CON VISUALIZACIÓN ===\n")

# PASO 1: Preview
print("1. Visualizando consignas del IDF...")
setpoints = calc.preview_setpoints(
    setpoint_source='SF_Detached_B_min_South.idf',
    plot=False,
    sample_days=['2000-01-15', '2000-07-15']
)
print(f"   Consignas guardadas: {len(calc.setpoints)} valores\n")

# PASO 2: Calcular
print("2. Calculando grados-hora...")
result = calc.calculate(
    epw_path='madrid_tmy.epw',
    setpoint_source='SF_Detached_B_min_South.idf',
    frequency='monthly',
    mode='both'
)

# PASO 3: Análisis
print("\n3. Análisis de resultados:")

# Comparar temperaturas del EPW vs consignas
comparison = pd.DataFrame({
    'Temperatura_EPW': calc.temperatures.resample('d').mean(),
    'Consigna': calc.setpoints.resample('d').mean()
})
print("\nTemperatura diaria vs Consigna (primeros 10 días):")
print(comparison.head(10))

# Demanda por mes
print("\nDemanda mensual (grados-hora):")
print(result)

# Totales
print(f"\nTotales anuales:")
print(f"  Calefacción: {result['heating'].sum():,.0f} °C·h")
print(f"  Refrigeración: {result['cooling'].sum():,.0f} °C·h")

# PASO 4: Exportar
calc.export_results('analisis_completo.xlsx')
print(f"\n✓ Resultados exportados a: analisis_completo.xlsx")
```

## Troubleshooting

### Atributo aún es None después de `preview_setpoints()`

Asegúrate de que `preview_setpoints()` no genere excepciones. Verifica el output consola.

```python
# La versión actualizada debe funcionar así:
setpoints = calc.preview_setpoints(...)
print(calc.setpoints)  # Debe ser Series, no None
```

### Diferente número de valores entre temperatures y setpoints

Puede ocurrir si hay un año bisiesto. Ambas deben estar alineadas después de `calculate()`.

```python
print(f"Temperaturas: {len(calc.temperatures)}")
print(f"Consignas: {len(calc.setpoints)}")
print(f"Resultado: {len(calc.result)}")
```

### Cómo actualizar atributos manualmente

Si necesitas recalcular solo los grados-hora sin re-cargar EPW:

```python
# Usar temperatures y setpoints existentes
from pyweatherfiles.degree_hours import DegreeHoursCalculator

calc = DegreeHoursCalculator()
calc.temperatures = ...  # Tu serie
calc.setpoints = ...      # Tu serie

# Calcular y guardar
heating_dh = calc._calculate_hourly_degree_hours(..., mode='heating')
```

## Resumen

| Atributo | Tipo | Contenido | Cuando se asigna |
|----------|------|----------|-----------------|
| `temperatures` | Series | Temp horaria EPW | `calculate()` |
| `setpoints` | Series | Consigna horaria | `calculate()`, `preview_setpoints()`, `get_setpoints()` |
| `result` | DataFrame | Grados-hora | `calculate()` |

Todos los atributos están disponibles para análisis y exportación después de ejecutar los métodos correspondientes.

