
from pyweatherfiles.tmy import TMYGenerator
import pandas as pd
import numpy as np

# Mapping based on generating tmys.py
COLUMN_MAPPING = {
    'fecha': 'time',
    'Dry-bulb temperature_max': 'T_air_max',
    'Dry-bulb temperature_min': 'T_air_min',
    'Dry-bulb temperature_mean': 'T_air_mean',
    'Dew Point temperature_max': 'T_dew_max',
    'Dew Point temperature_min': 'T_dew_min',
    'Dew Point temperature_mean': 'T_dew_mean',
    'Wind speed_max': 'Wind_speed_max',
    'Wind speed_mean': 'Wind_speed_mean',
    'GHI_sum': 'GHI_sum',
    'DNI_sum': 'DNI_sum'
}

print("Iniciando verificación de TMYGenerator con diferentes métodos de CDF...")

results = []

for method in ['hazen', 'california', 'weibull']:
    print(f"\nProbando método: {method}...")
    tmy_gen = TMYGenerator(
        file_path='SEVILLA.xlsx',
        cdf_method='daily',
        data_frequency='daily',
        column_mapping=COLUMN_MAPPING,
        weighting_method='tmy3',
        save_validation_dfs=False,
        plotting_position_method=method
    )
    
    # Manually trigger step 1 and 2 logic to get FS for specific month/year without running full generation
    # Step 1: Load Data
    tmy_gen._load_and_prepare_real_data()
    
    # Access internal data directly
    # Month 1 (January), Year 2018
    month = 1
    year = 2018
    target_var = 'T_air_mean'
    
    long_term_data = tmy_gen.df_daily[tmy_gen.df_daily.index.month == month][target_var]
    candidate_data = tmy_gen.df_daily[(tmy_gen.df_daily.index.month == month) & (tmy_gen.df_daily.index.year == year)][target_var]
    
    # Calculate FS
    fs_val = tmy_gen._calculate_fs_statistic(candidate_data, long_term_data)
    
    print(f"  FS para T_air_mean (Enero 2018): {fs_val:.6f}")
    results.append({'Method': method, 'FS': fs_val})


output_lines = []
output_lines.append("\n" + "="*40)
output_lines.append("RESUMEN DE RESULTADOS")
output_lines.append("="*40)
for res in results:
    output_lines.append(f"Método {res['Method']:12}: FS = {res['FS']:.6f}")

output_lines.append("-" * 40)
output_lines.append(f"Safae (Objetivo)    : FS = 0.034990")
output_lines.append(f"Usuario (Previo)    : FS = 0.044641")
output_lines.append("="*40)

# Check Default Behavior
output_lines.append("\nVerificando comportamiento por defecto (debe ser hazen)...")
tmy_gen_default = TMYGenerator(
        file_path='SEVILLA.xlsx',
        cdf_method='daily',
        data_frequency='daily',
        column_mapping=COLUMN_MAPPING,
        weighting_method='tmy3',
        save_validation_dfs=False
        # No plotting_position_method specified
)
tmy_gen_default._load_and_prepare_real_data()
long_term_data = tmy_gen_default.df_daily[tmy_gen_default.df_daily.index.month == 1]['T_air_mean']
candidate_data = tmy_gen_default.df_daily[(tmy_gen_default.df_daily.index.month == 1) & (tmy_gen_default.df_daily.index.year == 2018)]['T_air_mean']
fs_default = tmy_gen_default._calculate_fs_statistic(candidate_data, long_term_data)
output_lines.append(f"FS Default:           {fs_default:.6f}")

if abs(fs_default - 0.034990) < 0.0001:
    output_lines.append("SUCCESS: El valor por defecto coincide con el de Safae (Hazen).")
else:
    output_lines.append("WARNING: El valor por defecto NO coincide con el de Safae.")

for line in output_lines:
    print(line)

with open('verification_results.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines))
