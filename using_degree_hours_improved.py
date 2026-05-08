# -*- coding: utf-8 -*-
"""
Ejemplo: Uso de DegreeHoursCalculator con archivo IDF

Demuestra cómo:
1. Visualizar consignas antes de calcular
2. Acceder a los atributos de la clase
3. Calcular grados-hora
"""

from pyweatherfiles import DegreeHoursCalculator
import os

print("\n" + "="*70)
print("EJEMPLO: Usando DegreeHoursCalculator con IDF")
print("="*70 + "\n")

calc = DegreeHoursCalculator()

# Verificar archivos disponibles
idf_path = 'SF_Detached_B_min_South.idf'
epw_path = 'madrid_tmy.epw'

print(f"Buscando archivos...")
print(f"  IDF: {idf_path} {'✓' if os.path.exists(idf_path) else '✗'}")
print(f"  EPW: {epw_path} {'✓' if os.path.exists(epw_path) else '✗'}\n")

if os.path.exists(idf_path) and os.path.exists(epw_path):

    # PASO 1: VISUALIZAR CONSIGNAS ANTES DE CALCULAR
    # ================================================================
    print("PASO 1: Visualizando consignas del IDF")
    print("-" * 70)

    setpoints = calc.preview_setpoints(
        setpoint_source=idf_path,
        plot=False,  # Cambiar a True para generar gráfico
        sample_days=['2000-01-15', '2000-07-15']  # Invierno y verano
    )

    print("\nAtributos de clase después de preview_setpoints():")
    print(f"  - temperatures: {type(calc.temperatures)} {len(calc.temperatures) if calc.temperatures is not None else 'None'} valores")
    print(f"  - setpoints: {type(calc.setpoints)} {len(calc.setpoints) if calc.setpoints is not None else 'None'} valores")
    print(f"  - result: {type(calc.result)} {calc.result}\n")

    # PASO 2: CALCULAR GRADOS-HORA
    # ================================================================
    print("\nPASO 2: Calculando grados-hora")
    print("-" * 70)

    result = calc.calculate(
        epw_path=epw_path,
        setpoint_source=idf_path,
        frequency='monthly',
        mode='both'
    )

    # PASO 3: ACCEDER A LOS ATRIBUTOS GUARDADOS
    # ================================================================
    print("\n\nPASO 3: Accediendo a atributos de la clase")
    print("-" * 70)

    print(f"\nTemperaturas (primeras 24 horas):")
    print(calc.temperatures.head(24))

    print(f"\n\nConsignas (primeras 24 horas):")
    print(calc.setpoints.head(24))

    print(f"\n\nResultados (grados-hora mensuales):")
    print(calc.result)

    # PASO 4: ANÁLISIS
    # ================================================================
    print("\n\nPASO 4: Análisis de resultados")
    print("-" * 70)

    print(f"\nTemperaturas del EPW:")
    print(f"  Mínima: {calc.temperatures.min():.2f} °C")
    print(f"  Máxima: {calc.temperatures.max():.2f} °C")
    print(f"  Promedio: {calc.temperatures.mean():.2f} °C")

    print(f"\nConsignas de temperatura:")
    print(f"  Mínima: {calc.setpoints.min():.2f} °C")
    print(f"  Máxima: {calc.setpoints.max():.2f} °C")
    print(f"  Promedio: {calc.setpoints.mean():.2f} °C")

    print(f"\nDemanda energética (grados-hora):")
    total_heating = calc.result['heating'].sum()
    total_cooling = calc.result['cooling'].sum()
    print(f"  Total calefacción: {total_heating:,.1f} °C·h")
    print(f"  Total refrigeración: {total_cooling:,.1f} °C·h")
    print(f"  Ratio Cal/Ref: {total_heating/total_cooling:.2f}x" if total_cooling > 0 else "  Ratio: N/A (sin refrigeración)")

    # PASO 5: EXPORTAR
    # ================================================================
    print("\n\nPASO 5: Exportando resultados")
    print("-" * 70)

    output_file = calc.export_results('grados_hora_idf.xlsx')
    print(f"✓ Resultados guardados en: {output_file}")

    # Exportar también las consignas y temperaturas
    comparison_data = calc.result.copy()
    comparison_data['temp_media_diaria'] = calc.temperatures.resample('d').mean()
    comparison_data['consigna_media_diaria'] = calc.setpoints.resample('d').mean()
    comparison_data.to_excel('analisis_detallado.xlsx')
    print(f"✓ Análisis detallado guardado en: analisis_detallado.xlsx")

else:
    print("[ERROR] No se encontraron los archivos requeridos.")
    print("\nPara este ejemplo necesitas:")
    print(f"  1. {idf_path} (archivo de modelo de EnergyPlus)")
    print(f"  2. {epw_path} (archivo de clima EPW)")
    print("\nPuedes usar archivos disponibles como:")
    print("  - SF_Detached_D_min_South.idf")
    print("  - madrid_2018.epw, seville_tmy.epw, etc.")

