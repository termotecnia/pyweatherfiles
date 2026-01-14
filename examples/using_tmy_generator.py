import pytmy
import pandas as pd
import os

# Define weights matching your columns
# weights = {
#     'T_air_max': 1/24, 'T_air_min': 1/24, 'T_air_mean': 2/24,
#     'T_dew_max': 1/24, 'T_dew_min': 1/24, 'T_dew_mean': 2/24,
#     'Wind_speed_max': 2/24, 'Wind_speed_mean': 2/24,
#     'GHI_sum': 12/24
# }

# Load data (assuming data is in the parent directory)
data_path = os.path.join(os.path.dirname(__file__), '..', 'MADRID.xlsx')
# Only reading to show columns, not strictly necessary if passing path to TMYGenerator
# df = pd.read_excel(data_path) 
# columns = df.columns


# Map Excel columns to clean names
column_mapping = {
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


tmy_gen = pytmy.TMYGenerator(
    file_path=data_path,
    cdf_method='daily',
    data_frequency='daily',
    column_mapping=column_mapping,
    weighting_method='tmy3',
    save_validation_dfs=True
)
# Run generation (can disable persistence if not needed/applicable for custom cols)
tmy_gen.generate_tmy(use_persistence=True)
tmy_gen.export_tmy('MADRID_TMY_persistence_tmy3.csv')

tmy_gen.plot_persistence_runs(month=1, years=tmy_gen.candidate_months[1])