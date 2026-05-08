# -*- coding: utf-8 -*-
"""
Test rápido de nuevas funcionalidades
"""

from pyweatherfiles import DegreeHoursCalculator
import os

calc = DegreeHoursCalculator()

epw_path = 'onedrive_backup/ESP_Madrid.082210_IWEC.epw'

if os.path.exists(epw_path):
    print("\n=== TEST: preview_setpoints() ===\n")

    setpoints_config = {
        'tipo': 'estacional',
        'invierno': 21.0,
        'verano': 26.0,
        'fechas_invierno': ('01-01', '03-31'),
        'fechas_verano': ('06-01', '09-30'),
    }

    # Test 1: preview_setpoints sin gráfico
    print("TEST 1: preview_setpoints() sin gráfico")
    print("-" * 70)
    result_preview = calc.preview_setpoints(
        setpoint_source=setpoints_config,
        plot=False,
        sample_days=['2000-01-15', '2000-07-15']
    )

    print("\nAtributos después de preview_setpoints():")
    print(f"  temperatures: {calc.temperatures}")
    print(f"  setpoints: {type(calc.setpoints)} con {len(calc.setpoints)} valores")
    print(f"  result: {calc.result}\n")

    # Test 2: calculate()
    print("\nTEST 2: calculate()")
    print("-" * 70)
    result_calc = calc.calculate(
        epw_path=epw_path,
        setpoint_source=setpoints_config,
        frequency='monthly',
        mode='both'
    )

    print("\nAtributos después de calculate():")
    print(f"  temperatures: {type(calc.temperatures)} con {len(calc.temperatures)} valores")
    print(f"  setpoints: {type(calc.setpoints)} con {len(calc.setpoints)} valores")
    print(f"  result: {type(calc.result)} con shape {calc.result.shape}\n")

    print("Primeros valores de cada atributo:")
    print(f"\nTemperaturas (primeras 3 horas):\n{calc.temperatures.head(3)}")
    print(f"\nConsignas (primeras 3 horas):\n{calc.setpoints.head(3)}")
    print(f"\nResultados (primeros 3 meses):\n{calc.result.head(3)}")

    # Test 3: get_setpoints()
    print("\n\nTEST 3: get_setpoints()")
    print("-" * 70)
    setpoints_only = calc.get_setpoints(
        setpoint_source=setpoints_config,
        mode='both'
    )
    print(f"Retorna Series con {len(setpoints_only)} valores")
    print(f"Mín: {setpoints_only.min()}, Máx: {setpoints_only.max()}")

    print("\n✅ Todos los tests completados exitosamente!\n")

else:
    print(f"EPW no encontrado: {epw_path}")

