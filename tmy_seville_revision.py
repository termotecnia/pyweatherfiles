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

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
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

# ==============================================================================
# PASO 1: GENERACIÓN DEL TMY (completa, guardando datos de validación)
# ==============================================================================
print("=" * 70)
print("PASO 1: Generando TMY completo con datos de validación...")
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

converter_tmy.generate_tmy(use_persistence=True)

converter_tmy.export_tmy('seville_tmy_3.csv')

# ==============================================================================
# PASO 2: RESUMEN DE COMPOSICIÓN DEL TMY
# ==============================================================================
print("\n" + "=" * 70)
print("PASO 2: Composición del TMY — Mes seleccionado por mes")
print("=" * 70)

if converter_tmy.validation_st4_df_tmy_composition is not None:
    df_comp = converter_tmy.validation_st4_df_tmy_composition.copy()
    print(df_comp.set_index('Month').to_string())
    print()
    # Destacar meses de verano
    summer_comp = df_comp[df_comp['Month_Num'].isin(SUMMER_MONTHS)]
    print(">>> MESES DE VERANO seleccionados:")
    print(summer_comp[['Month_Num', 'Month', 'Source_Year']].to_string(index=False))
else:
    print("No se pudo obtener la tabla de composición.")
    # Construirla manualmente desde selected_months
    for m in range(1, 13):
        print(f"  Mes {m:02d}: Año {converter_tmy.selected_months.get(m, 'N/A')}")

# ==============================================================================
# PASO 3: RANKING FS COMPLETO PARA LOS MESES DE VERANO
# ==============================================================================
print("\n" + "=" * 70)
print("PASO 3: Ranking FS COMPLETO para los meses de verano")
print("=" * 70)

for month in SUMMER_MONTHS:
    print(f"\n--- {MONTH_NAMES[month]} (Mes {month}) ---")
    df_rank = converter_tmy.validate_full_ranking_for_month(month)
    if df_rank is not None:
        print(f"\nTodos los anos disponibles (ordenados por FS, mejor -> peor):")
        print(df_rank.to_string(float_format="%.4f"))
        selected_year = converter_tmy.selected_months.get(month)
        if selected_year is not None:
            rank_row = df_rank[df_rank['Year'] == selected_year]
            if not rank_row.empty:
                rank_pos = int(rank_row.iloc[0]['Rank'])
                fs_val   = rank_row.iloc[0]['Total_W_FS']
                print(f"\n  >> ANO SELECCIONADO PARA EL TMY: {selected_year} "
                      f"| Posicion FS: #{rank_pos} | FS ponderado: {fs_val:.4f}")
            else:
                print(f"\n  [!] ANO SELECCIONADO ({selected_year}) no aparece en el ranking FS.")

# ==============================================================================
# PASO 4: TABLA DE DECISIÓN PERSISTENCE PARA MESES DE VERANO
# ==============================================================================
print("\n" + "=" * 70)
print("PASO 4: Decisión de Persistence para los meses de verano")
print("=" * 70)

# Método sequential
if converter_tmy.validation_st3_persistence_sequential_details:
    for month in SUMMER_MONTHS:
        df_pers = converter_tmy.validation_st3_persistence_sequential_details.get(month)
        if df_pers is not None:
            print(f"\n--- {MONTH_NAMES[month]} (Mes {month}) — Detalle de Persistence (Sequential) ---")
            print(df_pers.to_string(index=False, float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else str(x)))
# Método scoring
elif converter_tmy.validation_st3_persistence_score_details:
    for month in SUMMER_MONTHS:
        df_pers = converter_tmy.validation_st3_persistence_score_details.get(month)
        if df_pers is not None:
            print(f"\n--- {MONTH_NAMES[month]} (Mes {month}) — Detalle de Persistence (Score) ---")
            print(df_pers.to_string(index=False, float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else str(x)))

# ==============================================================================
# PASO 5: ESTADÍSTICAS DESCRIPTIVAS — COMPARATIVA SERIE LARGA vs. AÑO TMY
# ==============================================================================
print("\n" + "=" * 70)
print("PASO 5: Estadísticas descriptivas — Serie larga vs. Año TMY (verano)")
print("=" * 70)

df_daily  = converter_tmy.df_daily
df_hourly = converter_tmy.df_hourly

# Variables disponibles en df_daily para análisis comparativo
t_col   = 'T_air_mean'  if 'T_air_mean'   in df_daily.columns else 'T_air'
ghi_col = 'GHI_sum'     if 'GHI_sum'      in df_daily.columns else 'GHI'

for month in SUMMER_MONTHS:
    selected_year = converter_tmy.selected_months.get(month)
    month_name    = MONTH_NAMES[month]

    lt_data  = df_daily[df_daily.index.month == month]
    sel_data = df_daily[(df_daily.index.month == month) & (df_daily.index.year == selected_year)]

    print(f"\n  {month_name} - Ano seleccionado: {selected_year}")
    print(f"  {'Estadistico':<22} {'Serie Larga':>15} {'Anno {}'.format(selected_year):>15} {'Diferencia':>12}")
    print("  " + "-" * 66)

    for col, label in [(t_col, 'T_air media (degC)'), (ghi_col, 'GHI (Wh/m2/dia)')]:
        if col not in lt_data.columns:
            continue
        lt_mean  = lt_data[col].mean()
        lt_med   = lt_data[col].median()
        sel_mean = sel_data[col].mean() if not sel_data.empty else np.nan
        sel_med  = sel_data[col].median() if not sel_data.empty else np.nan
        print(f"  {label + ' (media)':<22} {lt_mean:>15.2f} {sel_mean:>15.2f} {sel_mean - lt_mean:>+12.2f}")
        print(f"  {label + ' (mediana)':<22} {lt_med:>15.2f} {sel_med:>15.2f} {sel_med - lt_med:>+12.2f}")

# ==============================================================================
# PASO 6: EVOLUCIÓN TEMPORAL DE T_air MEDIA EN VERANO (SERIE LARGA)
#         — Detectar tendencia y ver en qué año cae el TMY
# ==============================================================================
print("\n" + "=" * 70)
print("PASO 6: Tendencia temporal de T_air media de verano (serie larga)")
print("=" * 70)

fig_trend, ax_trend = plt.subplots(figsize=(14, 5))

for month in SUMMER_MONTHS:
    selected_year = converter_tmy.selected_months.get(month)
    lt_data = df_daily[df_daily.index.month == month]

    if t_col not in lt_data.columns:
        continue

    yearly_mean = lt_data.groupby(lt_data.index.year)[t_col].mean()

    ax_trend.plot(yearly_mean.index, yearly_mean.values,
                  marker='o', label=f'{MONTH_NAMES[month]}', linewidth=1.5, alpha=0.8)

    # Marca el año seleccionado para el TMY
    if selected_year in yearly_mean.index:
        ax_trend.scatter([selected_year], [yearly_mean[selected_year]],
                         s=150, zorder=5, marker='*',
                         label=f'TMY ({MONTH_NAMES[month]}={selected_year})')

# Línea de tendencia general (todos los veranos)
summer_data = df_daily[df_daily.index.month.isin(SUMMER_MONTHS)]
if t_col in summer_data.columns:
    yearly_summer = summer_data.groupby(summer_data.index.year)[t_col].mean()
    z = np.polyfit(yearly_summer.index, yearly_summer.values, 1)
    p = np.poly1d(z)
    ax_trend.plot(yearly_summer.index, p(yearly_summer.index),
                  'k--', linewidth=2, label=f'Tendencia verano ({z[0]:+.3f} degC/anno)')

ax_trend.set_title('Evolución de T_air media mensual en verano — Sevilla\n'
                    '(* = Año seleccionado para el TMY)', fontsize=13)
ax_trend.set_xlabel('Año')
ax_trend.set_ylabel('T_air media diaria (°C)')
ax_trend.legend(fontsize=9, ncol=2)
ax_trend.grid(True, linestyle=':', alpha=0.7)
plt.tight_layout()
plt.savefig('seville_tmy_summer_trend.png', dpi=150)
plt.show()
print("  Figura guardada: seville_tmy_summer_trend.png")

# ==============================================================================
# PASO 7: CDFs DE TODOS LOS AÑOS vs. LARGO PLAZO (MESES DE VERANO)
# ==============================================================================
print("\n" + "=" * 70)
print("PASO 7: CDFs de todos los candidatos vs. Largo plazo (meses de verano)")
print("=" * 70)

for month in SUMMER_MONTHS:
    selected_year = converter_tmy.selected_months.get(month)
    all_years     = sorted(df_daily[df_daily.index.month == month].index.year.unique())

    print(f"  Generando CDFs para {MONTH_NAMES[month]}...")
    converter_tmy.plot_cdfs(
        month_to_plot=month,
        years_to_plot=all_years
    )

# ==============================================================================
# PASO 8: COMPARATIVA GRÁFICA — Serie diaria de T_air de cada año de verano
#         vs. el año seleccionado por el TMY (panel por mes)
# ==============================================================================
print("\n" + "=" * 70)
print("PASO 8: Series diarias T_air — todos los años vs. TMY seleccionado")
print("=" * 70)

if t_col in df_daily.columns:
    fig_ts, axes_ts = plt.subplots(1, 3, figsize=(20, 6), sharey=True)

    for ax, month in zip(axes_ts, SUMMER_MONTHS):
        selected_year = converter_tmy.selected_months.get(month)
        lt_data = df_daily[df_daily.index.month == month]
        all_years = sorted(lt_data.index.year.unique())
        colors    = cm.Blues(np.linspace(0.3, 0.9, len(all_years)))

        for yr, col_c in zip(all_years, colors):
            yr_data = lt_data[lt_data.index.year == yr]
            if yr_data.empty:
                continue
            lw = 2.5 if yr == selected_year else 0.7
            ls = '-'  if yr == selected_year else '-'
            alpha = 1.0 if yr == selected_year else 0.35
            clr   = 'red' if yr == selected_year else col_c
            ax.plot(yr_data.index.day, yr_data[t_col].values,
                    linewidth=lw, linestyle=ls, color=clr, alpha=alpha,
                    label=str(yr) if yr == selected_year else None)

        # Media larga serie
        lt_mean_by_day = lt_data.groupby(lt_data.index.day)[t_col].mean()
        ax.plot(lt_mean_by_day.index, lt_mean_by_day.values,
                'k--', linewidth=2.0, label='Media larga serie')

        ax.set_title(f'{MONTH_NAMES[month]}\n(TMY → {selected_year})', fontsize=12)
        ax.set_xlabel('Día del mes')
        ax.set_ylabel('T_air media diaria (°C)')
        ax.legend(fontsize=9)
        ax.grid(True, linestyle=':', alpha=0.6)

    fig_ts.suptitle('Sevilla — T_air media diaria (todos los años vs. TMY seleccionado)',
                     fontsize=13)
    plt.tight_layout()
    plt.savefig('seville_tmy_summer_daily_series.png', dpi=150)
    plt.show()
    print("  Figura guardada: seville_tmy_summer_daily_series.png")

# ==============================================================================
# PASO 9: COMPARATIVA GHI — Series diarias de verano
# ==============================================================================
print("\n" + "=" * 70)
print("PASO 9: Series diarias GHI — todos los años vs. TMY seleccionado")
print("=" * 70)

if ghi_col in df_daily.columns:
    fig_ghi, axes_ghi = plt.subplots(1, 3, figsize=(20, 6), sharey=True)

    for ax, month in zip(axes_ghi, SUMMER_MONTHS):
        selected_year = converter_tmy.selected_months.get(month)
        lt_data   = df_daily[df_daily.index.month == month]
        all_years = sorted(lt_data.index.year.unique())
        colors    = cm.Oranges(np.linspace(0.3, 0.9, len(all_years)))

        for yr, col_c in zip(all_years, colors):
            yr_data = lt_data[lt_data.index.year == yr]
            if yr_data.empty:
                continue
            lw    = 2.5  if yr == selected_year else 0.7
            alpha = 1.0  if yr == selected_year else 0.35
            clr   = 'red' if yr == selected_year else col_c
            ax.plot(yr_data.index.day, yr_data[ghi_col].values,
                    linewidth=lw, color=clr, alpha=alpha,
                    label=str(yr) if yr == selected_year else None)

        # Media larga serie
        lt_mean_by_day = lt_data.groupby(lt_data.index.day)[ghi_col].mean()
        ax.plot(lt_mean_by_day.index, lt_mean_by_day.values,
                'k--', linewidth=2.0, label='Media larga serie')

        ax.set_title(f'{MONTH_NAMES[month]}\n(TMY → {selected_year})', fontsize=12)
        ax.set_xlabel('Día del mes')
        ax.set_ylabel('GHI diario (Wh/m²)')
        ax.legend(fontsize=9)
        ax.grid(True, linestyle=':', alpha=0.6)

    fig_ghi.suptitle('Sevilla — GHI diario (todos los años vs. TMY seleccionado)',
                      fontsize=13)
    plt.tight_layout()
    plt.savefig('seville_tmy_summer_daily_ghi.png', dpi=150)
    plt.show()
    print("  Figura guardada: seville_tmy_summer_daily_ghi.png")

# ==============================================================================
# PASO 10: RESUMEN NUMÉRICO FINAL — Posición FS del año seleccionado
# ==============================================================================
print("\n" + "=" * 70)
print("PASO 10: RESUMEN FINAL — Diagnóstico meses de verano Sevilla")
print("=" * 70)

for month in SUMMER_MONTHS:
    selected_year = converter_tmy.selected_months.get(month)
    month_name    = MONTH_NAMES[month]

    # Ranking FS completo
    df_rank_full = converter_tmy.validation_st2_df_fs_ranking_by_month.get(month)

    # Top-5 candidatos (post proximity ranking)
    top5_years = converter_tmy.candidate_months.get(month, [])

    print(f"\n  {'='*50}")
    print(f"  {month_name.upper()}")
    print(f"  {'='*50}")
    print(f"  Ano seleccionado para el TMY: {selected_year}")
    print(f"  Top-5 candidatos (post Proximity Ranking): {top5_years}")

    if df_rank_full is not None:
        rank_row = df_rank_full[df_rank_full['Year'] == selected_year]
        if not rank_row.empty:
            rank_pos  = int(rank_row.iloc[0]['Rank'])
            total_fs  = rank_row.iloc[0]['Total_W_FS']
            n_years   = len(df_rank_full)
            print(f"  Posicion FS del ano seleccionado: #{rank_pos} de {n_years} anos disponibles")
            print(f"  FS ponderado: {total_fs:.4f}")
        else:
            print(f"  [!] El ano {selected_year} no aparece en el ranking FS completo.")

    # Comparativa con la media historica de temperatura
    lt_data  = df_daily[df_daily.index.month == month]
    sel_data = df_daily[(df_daily.index.month == month) &
                         (df_daily.index.year == selected_year)]
    if t_col in lt_data.columns and not sel_data.empty:
        lt_mean  = lt_data[t_col].mean()
        sel_mean = sel_data[t_col].mean()
        diff     = sel_mean - lt_mean
        # Percentil del ano seleccionado respecto a las medias anuales
        yearly_means = lt_data.groupby(lt_data.index.year)[t_col].mean()
        pctil_yr = (yearly_means < sel_mean).mean() * 100
        print(f"  T_air media serie larga: {lt_mean:.2f} degC")
        print(f"  T_air media ano {selected_year}:    {sel_mean:.2f} degC  (diferencia: {diff:+.2f} degC)")
        print(f"  Percentil del ano {selected_year} entre medias anuales: {pctil_yr:.0f}%")
        if abs(diff) > 1.5:
            print(f"  [!] ATENCION: Diferencia > 1.5 degC -> posible anomalia en la seleccion.")
        if pctil_yr > 75:
            print(f"  [!] ATENCION: El ano seleccionado esta en el cuartil superior de temperatura.")
        if pctil_yr < 25:
            print(f"  [!] ATENCION: El ano seleccionado esta en el cuartil INFERIOR de temperatura.")

print("\n" + "=" * 70)
print("Revision completada (diagnostico). Revisa las figuras y los mensajes [!].")
print("=" * 70)

# ==============================================================================
# PASO 11: CORRECCIÓN — Selección óptima por temperatura para meses anómalos
#          y regeneración del TMY corregido
# ==============================================================================
print("\n" + "=" * 70)
print("PASO 11: Correccion de meses anomalos y regeneracion del TMY")
print("=" * 70)

# ──────────────────────────────────────────────────────────────────────────────
# 11a. Para cada mes de verano, evaluar TODOS los candidatos del top-5 y
#      seleccionar el que minimiza |T_air_media_candidato - T_air_media_larga|
# ──────────────────────────────────────────────────────────────────────────────

# Umbral: si la diferencia de temperatura del año seleccionado supera este
# valor, se sustituye por el candidato óptimo del top-5.
TEMP_DIFF_THRESHOLD = 1.0   # degC

original_selection = dict(converter_tmy.selected_months)
corrected_selection = dict(converter_tmy.selected_months)
corrections_made = {}

print("\nEvaluando candidatos del top-5 para cada mes de verano:\n")

for month in SUMMER_MONTHS:
    candidates      = converter_tmy.candidate_months.get(month, [])
    lt_data         = df_daily[df_daily.index.month == month]
    lt_mean         = lt_data[t_col].mean() if t_col in lt_data.columns else None
    original_year   = original_selection.get(month)
    month_name      = MONTH_NAMES[month]

    if lt_mean is None or not candidates:
        print(f"  {month_name}: no se pueden evaluar candidatos (datos insuficientes).")
        continue

    print(f"  {month_name} — Media historica larga: {lt_mean:.2f} degC")
    print(f"  {'Candidato':<12} {'Prox.Rank':<12} {'T_media(degC)':<16} {'Diff(degC)':<14} {'Percentil':<10}")
    print("  " + "-" * 64)

    candidate_stats = []
    yearly_means_all = lt_data.groupby(lt_data.index.year)[t_col].mean()

    for rank, yr in enumerate(candidates):
        yr_data  = lt_data[lt_data.index.year == yr]
        yr_mean  = yr_data[t_col].mean() if not yr_data.empty else np.nan
        diff_yr  = yr_mean - lt_mean
        pctil_yr = (yearly_means_all < yr_mean).mean() * 100
        marker   = " <-- ORIGINAL" if yr == original_year else ""
        print(f"  {yr:<12} #{rank + 1:<11} {yr_mean:<16.2f} {diff_yr:<+14.2f} {pctil_yr:<10.0f}%{marker}")
        candidate_stats.append({'year': yr, 'prox_rank': rank, 'mean': yr_mean, 'diff': abs(diff_yr), 'pctil': pctil_yr})

    # Comprobar si el original es anómalo
    orig_diff = abs(
        lt_data[lt_data.index.year == original_year][t_col].mean() - lt_mean
    ) if original_year in lt_data.index.year else 9999

    if orig_diff > TEMP_DIFF_THRESHOLD:
        # Seleccionar el candidato con menor |diff| respecto a la media larga
        best = min(candidate_stats, key=lambda x: x['diff'])
        if best['year'] != original_year:
            corrected_selection[month] = best['year']
            corrections_made[month] = {'original': original_year, 'corrected': best['year'],
                                        'orig_diff': orig_diff, 'new_diff': best['diff']}
            print(f"\n  [CORRECCION] Mes {month_name}: {original_year} -> {best['year']}")
            print(f"     Diferencia temp. original: {orig_diff:+.2f} degC")
            print(f"     Diferencia temp. corregida: {best['diff']:+.2f} degC")
        else:
            print(f"\n  [OK] Mes {month_name}: el original ({original_year}) ya es el mejor candidato.")
    else:
        print(f"\n  [OK] Mes {month_name}: seleccion original ({original_year}) dentro del umbral "
              f"(diff={orig_diff:.2f} degC).")
    print()

# ──────────────────────────────────────────────────────────────────────────────
# 11b. Aplicar la selección corregida y regenerar el TMY
# ──────────────────────────────────────────────────────────────────────────────

if corrections_made:
    print("=" * 70)
    print("Regenerando TMY con la seleccion corregida...")
    print("=" * 70)

    # Inyectar la selección corregida en el objeto TMYGenerator
    converter_tmy.selected_months = corrected_selection

    # Reconstruir el TMY raw y aplicar suavizado
    converter_tmy._create_raw_tmy()
    converter_tmy._apply_smoothing()

    # Exportar
    output_corrected = 'seville_tmy_3_corrected.csv'
    converter_tmy.export_tmy(output_corrected)
    print(f"\nTMY corregido exportado como: {output_corrected}")

    # ──────────────────────────────────────────────────────────────────────────
    # 11c. Comparativa gráfica: TMY original vs. TMY corregido (T_air verano)
    # ──────────────────────────────────────────────────────────────────────────
    print("\nGenerando comparativa grafica TMY original vs. corregido...")

    # Leer el original
    df_orig      = pd.read_csv('seville_tmy_3.csv', index_col=0, parse_dates=True)
    df_corrected = pd.read_csv(output_corrected,    index_col=0, parse_dates=True)

    # Identificar la columna de temperatura en el CSV exportado
    t_csv_col = None
    for candidate_col in ['Dry-bulb temperature', 'T_air']:
        if candidate_col in df_orig.columns:
            t_csv_col = candidate_col
            break

    if t_csv_col is None:
        print("  No se pudo identificar la columna de temperatura en el CSV exportado.")
    else:
        fig_comp, axes_comp = plt.subplots(1, 3, figsize=(20, 6), sharey=True)

        for ax, month in zip(axes_comp, SUMMER_MONTHS):
            month_name    = MONTH_NAMES[month]
            orig_month    = df_orig[df_orig.index.month == month][t_csv_col]
            corr_month    = df_corrected[df_corrected.index.month == month][t_csv_col]
            lt_data_month = df_daily[df_daily.index.month == month]
            lt_mean_month = lt_data_month[t_col].mean() if t_col in lt_data_month.columns else None

            # Resample a diario
            orig_daily = orig_month.resample('D').mean()
            corr_daily = corr_month.resample('D').mean()

            ax.plot(orig_daily.index.day, orig_daily.values,
                    color='steelblue', linewidth=2.0, label=f'TMY original ({original_selection[month]})')
            ax.plot(corr_daily.index.day, corr_daily.values,
                    color='tomato', linewidth=2.0, linestyle='--',
                    label=f'TMY corregido ({corrected_selection[month]})')
            if lt_mean_month is not None:
                ax.axhline(lt_mean_month, color='black', linestyle=':', linewidth=1.5,
                           label=f'Media historica ({lt_mean_month:.1f} degC)')

            ax.set_title(f'{month_name}', fontsize=12)
            ax.set_xlabel('Dia del mes')
            ax.set_ylabel('T_air (degC)')
            ax.legend(fontsize=8)
            ax.grid(True, linestyle=':', alpha=0.6)

        fig_comp.suptitle('Sevilla — Comparativa TMY original vs. TMY corregido\nT_air media diaria en meses de verano',
                           fontsize=13)
        plt.tight_layout()
        plt.savefig('seville_tmy_comparison_corrected.png', dpi=150)
        plt.show()
        print("  Figura guardada: seville_tmy_comparison_corrected.png")

    # ──────────────────────────────────────────────────────────────────────────
    # 11d. Tabla resumen de correcciones aplicadas
    # ──────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("RESUMEN DE CORRECCIONES APLICADAS")
    print("=" * 70)
    print(f"  {'Mes':<10} {'Año original':<15} {'Año corregido':<16} {'Diff orig':<12} {'Diff nuevo'}")
    print("  " + "-" * 64)
    for month, info in corrections_made.items():
        print(f"  {MONTH_NAMES[month]:<10} {info['original']:<15} {info['corrected']:<16} "
              f"{info['orig_diff']:>+8.2f} degC  {info['new_diff']:>+8.2f} degC")

    # Meses sin corrección
    for month in SUMMER_MONTHS:
        if month not in corrections_made:
            yr = original_selection[month]
            lt_data_m = df_daily[df_daily.index.month == month]
            d = abs(lt_data_m[lt_data_m.index.year == yr][t_col].mean() - lt_data_m[t_col].mean())
            print(f"  {MONTH_NAMES[month]:<10} {yr:<15} {'(sin cambio)':<16} {d:>+8.2f} degC")

else:
    print("\nNo se requieren correcciones: todos los meses de verano estan dentro del umbral.")
    print(f"(Umbral usado: |diff| <= {TEMP_DIFF_THRESHOLD} degC)")

print("\n" + "=" * 70)
print("PASO 11 COMPLETADO.")
print("=" * 70)