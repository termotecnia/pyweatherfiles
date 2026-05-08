# Degree Hours Calculator - Guía de Uso

## Descripción

`DegreeHoursCalculator` es una clase para calcular grados-hora de calefacción (HDD) y refrigeración (CDD) desde archivos EPW usando consignas de temperatura basadas en:
- Archivos IDF (EnergyPlus) 
- Configuraciones personalizadas (diarias, semanales, estacionales)

## Instalación

La clase está en `pyweatherfiles.degree_hours` y se puede importar como:

```python
from pyweatherfiles import DegreeHoursCalculator
```

## Uso Básico

### 1. Con Consignas Estacionales

```python
from pyweatherfiles import DegreeHoursCalculator

calculator = DegreeHoursCalculator()

setpoints_config = {
    'tipo': 'estacional',
    'invierno': 21.0,      # Temperatura consigna invierno
    'transicion': 23.5,    # Temperatura consigna transición
    'verano': 26.0,        # Temperatura consigna verano
    'fechas_invierno': ('01-01', '03-20'),
    'fechas_transicion': ('03-21', '06-20'),
    'fechas_verano': ('06-21', '09-22'),
}

result = calculator.calculate(
    epw_path='madrid_2000.epw',
    setpoint_source=setpoints_config,
    frequency='monthly',  # 'hourly', 'daily', or 'monthly'
    mode='both'           # 'heating', 'cooling', or 'both'
)

print(result)
```

### 2. Con Consignas Semanales (Patrones Típicos)

```python
setpoints_weekly = {
    'tipo': 'semanal',
    'patrones': {
        'invierno': {
            'weekday': 21,    # Entre semana
            'weekend': 18     # Fin de semana
        },
        'verano': {
            'weekday': 26,
            'weekend': 28
        }
    },
    'periodos': {
        'invierno': ('01-01', '04-30'),
        'verano': ('05-01', '12-31')
    }
}

result = calculator.calculate(
    epw_path='madrid_2000.epw',
    setpoint_source=setpoints_weekly,
    frequency='monthly'
)
```

### 3. Con Consignas Diarias

```python
setpoints_daily = {
    'tipo': 'diaria',
    'valores': [21.0]*365  # 365 valores, uno por día del año
}

result = calculator.calculate(
    epw_path='madrid_2000.epw',
    setpoint_source=setpoints_daily,
    frequency='daily'
)
```

### 4. Desde Archivo IDF

(Requiere eppy instalado: `pip install eppy`)

```python
result = calculator.calculate(
    epw_path='madrid_2000.epw',
    setpoint_source='building_model.idf',  # Ruta a archivo IDF
    frequency='monthly',
    zone_name='Living Room'  # Opcional: específica zona. Si no, promedia todas
)
```

## Parámetros Principales

### `calculate()`

| Parámetro | Tipo | Descrición | Por defecto |
|-----------|------|-----------|-------------|
| `epw_path` | str | Ruta al archivo EPW | Requerido |
| `setpoint_source` | str\|dict | IDF o diccionario de consignas | Requerido |
| `frequency` | str | 'hourly', 'daily', 'monthly' | 'monthly' |
| `hours` | list | Horas a considerar [0-23] | None (todas) |
| `year` | int | Año específico | None (todos) |
| `mode` | str | 'heating', 'cooling', 'both' | 'both' |
| `zone_name` | str | Zona específica del IDF | None (promedia) |

## Ejemplo Completo: Horario Laboral

```python
from pyweatherfiles import DegreeHoursCalculator

calculator = DegreeHoursCalculator()

# Consignas para horario laboral (8:00 - 18:00)
setpoints_config = {
    'tipo': 'estacional',
    'invierno': 21.0,
    'verano': 26.0,
    'fechas_invierno': ('10-01', '04-30'),
    'fechas_verano': ('05-01', '09-30'),
}

# Calcular solo para horas de trabajo
result = calculator.calculate(
    epw_path='madrid_2000.epw',
    setpoint_source=setpoints_config,
    frequency='daily',
    hours=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    mode='cooling'
)

# Exportar resultados
calculator.export_results('grados_hora_laboral.xlsx')

print(f"\nTotal grados-hora de refrigeración: {result['degree_hours'].sum():.1f}")
```

## Salida de Resultados

Según la `frequency` solicitada:

### Mensual (por defecto)
```
            heating    cooling
2000-01-31  11485.7      0.0
2000-02-29   9739.6      0.0
2000-03-31   8778.0     19.4
...
```

### Diario
```
            heating    cooling
2000-01-01    270.8      0.0
2000-01-02    303.0      0.0
2000-01-03    274.1      0.0
...
```

### Horario
```
                     degree_hours
2000-01-01 08:00:00           0.0
2000-01-01 09:00:00           0.0
2000-01-01 10:00:00           1.2
...
```

## Exportación

```python
# A Excel
calculator.export_results('resultados_grados_hora.xlsx')

# A CSV (usando pandas)
calculator.result.to_csv('resultados.csv')

# A gráfico
import matplotlib.pyplot as plt
calculator.result['cooling'].plot(figsize=(12, 6))
plt.title('Grados-hora de Refrigeración Mensuales')
plt.ylabel('Grados-hora (°C·h)')
plt.show()
```

## Método de Cálculo

### Grados-hora de Calefacción (Heating)
```
HDD_h = max(0, T_consigna - T_aire)
```
Solo se acumula cuando T_aire < T_consigna

### Grados-hora de Refrigeración (Cooling)
```
CDD_h = max(0, T_aire - T_consigna)
```
Solo se acumula cuando T_aire > T_consigna

### Agregación Temporal
- **Horario**: Valor calculado para cada hora
- **Diario**: Suma de 24 horas
- **Mensual**: Suma de todos los días del mes

## Notas Técnicas

1. **Unidades**: Todas las temperaturas en °C. Resultado en °C·horas
2. **Año del EPW**: Si no se especifica `year`, se utiliza el año disponible en el EPW
3. **Años bisiestos**: Manejados automáticamente
4. **Datos faltantes**: Se interpolan usando forward fill si es necesario
5. **IDF parsing**: Automático con `eppy` si está disponible; fallback a parsing básico

## Ejemplos de Casos de Uso

### 1. Demanda energética de edificio
```python
result = calculator.calculate(
    epw_path='clima.epw',
    setpoint_source='building.idf',
    frequency='monthly',
    mode='both'
)
```

### 2. Comparar años diferentes
```python
for year in [2018, 2019, 2020]:
    result = calculator.calculate(
        epw_path=f'data_{year}.epw',
        setpoint_source=setpoints,
        frequency='monthly'
    )
    print(f"{year}: {result['cooling'].sum()} GDD totales")
```

### 3. Análisis por estación
```python
result = calculator.calculate(
    epw_path='madrid_2000.epw',
    setpoint_source=setpoints,
    frequency='daily'
)

# Separar por estación
import pandas as pd
result['mes'] = result.index.month
verano = result[(result['mes'] >= 6) & (result['mes'] <= 8)]
print(f"Grados-hora verano: {verano['cooling'].sum()}")
```

## Troubleshooting

### Error: "EPW file not found"
Verificar la ruta al archivo EPW es correcta y accesible.

### Error: "eppy no instalado"
Para parseado avanzado de IDF:
```bash
pip install eppy
```

### Resultados vacíos
Verificar que `frequency` sea 'hourly', 'daily' o 'monthly', y que los años del EPW coincidan con las fechas configuradas.

### Resultados cero para cooling en modo 'both'
Normal si las temperaturas nunca superan la consigna de refrigeración. Especificar `mode='heating'` o `mode='cooling'` según sea necesario.

