from pyweatherfiles import hourly_epw_converter, met_epw_converter, tmy

## Long term
converter_longterm = hourly_epw_converter.HourlyEPWConverter(
    file_path='Madrid_Definitivo_para_convertir_a_epw.xlsx',
    base_epw_path='ESP_Madrid.082210_IWEC.epw',
)

converter_longterm.process(output_pattern='madrid_{year}.epw')

## met

converter_met = met_epw_converter.convert_met_to_epw(
    met_path='madrid_SP.met',
    base_epw_path='ESP_Madrid.082210_IWEC.epw',
    epw_path='madrid_met.epw',
    replace_unused_with_missing=True
)

## tmy
from pyweatherfiles import tmy

converter_tmy = tmy.TMYGenerator(
    file_path='Madrid_Definitivo_para_convertir_a_epw.xlsx',
    cdf_method='daily',
    data_frequency='hourly',
    column_mapping=None,
    weighting_method='sandia',
    save_validation_dfs=True,
    hourly_file_path='Madrid_Definitivo_para_convertir_a_epw.xlsx'
)
converter_tmy.generate_tmy(use_persistence=True)

