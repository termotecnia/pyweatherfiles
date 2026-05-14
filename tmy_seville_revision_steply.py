# -*- coding: utf-8 -*-
"""
==============================================================================
   REVISIÓN DEL TMY3 DE SEVILLA — Diagnóstico de Meses de Verano
==============================================================================
Objetivo:
    Verificar manualmente que la selección de los meses de verano (junio,
    julio, agosto) en el TMY3 de Sevilla es correcta, detectando posibles
    anomalías en el proceso de generación (FS ranking, Proximity Ranking,
    Persistence Selection).

Metodología:
    1. Generar el TMY completo con save_validation_dfs=True.
    2. Inspeccionar el ranking FS completo para los 3 meses de verano.
    3. Ver la decisión de Persistence para esos meses.
    4. Comparar las medias mensuales de la serie larga vs. el año seleccionado.
    5. Plotear las CDFs de los 5 candidatos finales vs. largo plazo.
    6. Plotear las series temporales diarias del mes seleccionado vs. todos
       los años disponibles.
    7. Comparar la media de verano del TMY con la tendencia temporal de la
       serie larga (efecto "cambio climático").
"""

import sys
import warnings

# Force UTF-8 output so special chars don't crash on Windows cp1252 consoles
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

warnings.filterwarnings('ignore')

from pyweatherfiles import tmy

# ==============================================================================
# CONFIGURACIÓN
# ==============================================================================
SUMMER_MONTHS = [6, 7, 8]          # Junio, Julio, Agosto
MONTH_NAMES   = {6: 'Junio', 7: 'Julio', 8: 'Agosto'}
FILE_PATH     = 'Sevilla_Definitivo_para_convertir_a_epw.xlsx'

# Propuesta de pesos "weighted" para testeo: 4 componentes y suma total = 1.0
PROXIMITY_WEIGHTS = {
    't_mean': 0.30,
    't_median': 0.20,
    'ghi_mean': 0.30,
    'ghi_median': 0.20,
}


def run_case(proximity_method, weights=None):
    suffix = proximity_method

    print("=" * 70)
    print(f"PASO 1: Generando TMY con proximidad='{proximity_method}'...")
    print("=" * 70)

    converter_tmy = tmy.TMYGenerator(
        file_path=FILE_PATH,
        cdf_method='daily',
        data_frequency='hourly',
        weighting_method='sandia',
        save_validation_dfs=True,
        hourly_file_path=FILE_PATH,
        datetime_col='time',
        col_temp='Dry-bulb temperature',
        col_dew='Dew Point temperature',
        col_wind='Wind Speed',
        col_ghi='Global Horizontal Irradiance ',
        col_dni='Beam Normal Irradiance '
    )

    converter_tmy.generate_tmy(
        use_persistence=True,
        proximity_normalization_method=proximity_method,
        proximity_normalization_weights=weights
    )

    converter_tmy.export_tmy(f'seville_tmy_3_{suffix}.csv')

    # 1. Auditar
    df_audit = converter_tmy.analyze_selection(temp_diff_threshold=1.0)
    df_audit.to_excel(f'seville_tmy_3_audit_{suffix}.xlsx')

    # 2. Inspeccionar candidatos del mes problemático
    candidate_stats = converter_tmy.get_candidate_stats(month=7)
    candidate_stats.to_excel(f'seville_tmy_3_month_7_candidate_stats_{suffix}.xlsx')

    # 3. Guardar TMY original y corregir
    tmy_original = converter_tmy.tmy_final.copy()
    converter_tmy.correct_selection_by_temperature(
        months=[6, 7, 8],
        temp_diff_threshold=1.0,
        regenerate=False
    )
    converter_tmy.export_tmy(f'tmy_corrected_{suffix}.csv')

    # 4. Comparar versiones
    converter_tmy.compare_tmy_versions(
        tmy_original,
        months=[7],
        label_self=f'TMY corregido ({suffix})',
        label_other=f'TMY original ({suffix})'
    )

    for m in range(1, 13):
        fig = converter_tmy.plot_monthly_trend(months=[m], show_candidates=True)
        fig.savefig(f'seville_tmy_3_month_{m}_monthly_trend_{suffix}.png')

    converter_tmy.validation_step3_proximity_ranking.to_excel(
        f'seville_tmy_3_validation_step3_proximity_ranking_{suffix}.xlsx'
    )

    return converter_tmy


# Corrida base compatible con el flujo anterior
std_run = run_case('std')

# Corrida alternativa con métrica ponderada
weighted_run = run_case('weighted', weights=PROXIMITY_WEIGHTS)

# Alias heredados para no romper scripts/reportes previos
std_run.export_tmy('seville_tmy_3.csv')
std_run.validation_step3_proximity_ranking.to_excel('seville_tmy_3_validation_step3_proximity_ranking.xlsx')
