from pyweatherfiles.epw_comparator import explore_epw_structure

# Llama a la función de exploración con tu archivo EPW base o el generado.
explore_epw_structure('Seville_Present.epw')

##

import pyweatherfiles.epw_comparator as epw_comparator

df_epw_compared = epw_comparator.compare_epw_files(
    base_epw_path='Seville_Present.epw',
    generated_epw_path='zonaB4.epw'
)

comparison_hourly_dataframe = epw_comparator.create_comparison_hourly_dataframe(
    base_epw_path='Seville_Present.epw',
    generated_epw_path='zonaB4.epw'
)

comparison_dataframe = epw_comparator.create_comparison_dataframe(
    base_epw_path='Seville_Present.epw',
    generated_epw_path='zonaB4.epw'
)

##

