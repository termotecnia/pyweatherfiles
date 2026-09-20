from pyweatherfiles import hourly_epw_converter, met_epw_converter, tmy

## Long term
converter_longterm = hourly_epw_converter.HourlyEPWConverter(
    file_path='Sevilla_Definitivo_para_convertir_a_epw.xlsx',
    base_epw_path='ESP_Sevilla.083910_IWEC.epw',
)

converter_longterm.process(output_pattern='seville_{year}.epw')

## met

converter_met = met_epw_converter.convert_met_to_epw(
    met_path='seville.met',
    base_epw_path='ESP_Sevilla.083910_IWEC.epw',
    epw_path='seville_met.epw',
    replace_unused_with_missing=True
)

## tmy

converter_tmy = tmy.TMYGenerator(
    file_path='Sevilla_Definitivo_para_convertir_a_epw.xlsx',
    cdf_method='daily',
    data_frequency='hourly',
    weighting_method='sandia',
    save_validation_dfs=True,
    hourly_file_path='Sevilla_Definitivo_para_convertir_a_epw.xlsx',

    # --- AQUÍ MAPEAS LAS VARIABLES SEGÚN LOS HEADINGS DEL EXCEL ---
    datetime_col='time',
    col_temp='Dry-bulb temperature',
    col_dew='Dew Point temperature',
    col_wind='Wind Speed',
    col_ghi='Global Horizontal Irradiance ',  # Nota: fíjate si tiene espacio al final en tu excel
    col_dni='Beam Normal Irradiance '
)

converter_tmy.generate_tmy(use_persistence=True)
converter_tmy.export_tmy('seville_tmy_3.csv')

##
converter_tmy_to_epw = hourly_epw_converter.HourlyEPWConverter(
    file_path='seville_tmy_3.csv',
    base_epw_path='ESP_Sevilla.083910_IWEC.epw',
)

converter_tmy_to_epw.process(output_pattern='seville_tmy.epw')

## Optional next steps (not run automatically by this script):
##  - Compare the generated TMY EPW against a reference file with
##    `pyweatherfiles.epw_comparator.create_comparison_hourly_dataframe(...)`.
##  - Run an EnergyPlus simulation against the generated EPW(s) with
##    `besos.eplus_funcs.run_energyplus(building_path=..., epw=..., out_dir=...)`
##    (requires the optional `besos`/`eppy` dependencies, see `pyproject.toml` extras).

