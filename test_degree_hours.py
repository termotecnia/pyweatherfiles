# -*- coding: utf-8 -*-
"""
Test script for DegreeHoursCalculator
"""

from pyweatherfiles import DegreeHoursCalculator
import os

# Test 1: Using custom dictionary (default setpoints)
print("\n" + "="*70)
print("TEST 1: Calculando grados-hora con diccionario personalizado")
print("="*70)

try:
    calculator = DegreeHoursCalculator()

    # Define custom setpoints (constant values for the whole year)
    setpoints_config = {
        'tipo': 'estacional',
        'invierno': 21.0,
        'verano': 26.0,
        'transicion': 23.5,
        'fechas_invierno': ('01-01', '03-20'),
        'fechas_transicion': ('03-21', '06-20'),
        'fechas_verano': ('06-21', '09-22'),
    }

    # Look for an available EPW file
    epw_files = [
        'ESP_Madrid.082210_IWEC.epw',
        'ESP_Granada.084190_SWEC.epw',
        'ESP_Sevilla.083910_IWEC.epw'
    ]

    epw_path = None
    for epw_file in epw_files:
        if os.path.exists(epw_file):
            epw_path = epw_file
            break

    if epw_path is None:
        # Check in onedrive_backup
        for epw_file in ['ESP_Madrid.082210_IWEC.epw', 'ESP_Sevilla.083910_IWEC.epw']:
            test_path = os.path.join('onedrive_backup', epw_file)
            if os.path.exists(test_path):
                epw_path = test_path
                break

    if epw_path:
        print(f"\n[TEST] Usando archivo EPW: {epw_path}")
        result_monthly = calculator.calculate(
            epw_path=epw_path,
            setpoint_source=setpoints_config,
            frequency='monthly',
            mode='both'
        )
        print(f"\nResultados mensuales:\n{result_monthly}\n")

        # Test daily frequency
        result_daily = calculator.calculate(
            epw_path=epw_path,
            setpoint_source=setpoints_config,
            frequency='daily',
            mode='both'
        )
        print(f"Primeros 10 días:\n{result_daily.head(10)}\n")

        # Test hourly with specific hours (8 AM - 6 PM)
        result_hourly = calculator.calculate(
            epw_path=epw_path,
            setpoint_source=setpoints_config,
            frequency='hourly',
            hours=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            mode='cooling'
        )
        print(f"Primeras 24 horas (solo enfriamiento, 8-18h):\n{result_hourly.head(24)}\n")

        print("[PASS] TEST 1 completado exitosamente")
    else:
        print("[WARNING] No se encontró archivo EPW válido para TEST 1")

except Exception as e:
    print(f"[ERROR] TEST 1 falló: {e}")
    import traceback
    traceback.print_exc()

# Test 2: Testing weekly patterns
print("\n" + "="*70)
print("TEST 2: Calculando grados-hora con patrones semanales")
print("="*70)

try:
    calculator = DegreeHoursCalculator()

    setpoints_weekly = {
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

    if epw_path:
        print(f"\n[TEST] Usando patrones semanales")
        result = calculator.calculate(
            epw_path=epw_path,
            setpoint_source=setpoints_weekly,
            frequency='monthly',
            mode='both'
        )
        print(f"\nResultados mensuales (patrones semanales):\n{result}\n")
        print("[PASS] TEST 2 completado exitosamente")
    else:
        print("[WARNING] No se encontró archivo EPW válido para TEST 2")

except Exception as e:
    print(f"[ERROR] TEST 2 falló: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70)
print("PRUEBAS FINALIZADAS")
print("="*70)







