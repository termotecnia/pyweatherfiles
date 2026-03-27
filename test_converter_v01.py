import os
import traceback
from pyweatherfiles.hourly_epw_converter import HourlyEPWConverter

base_path = "ESP_Madrid.082210_IWEC.epw"
excel_path = "Madrid_Definitivo_para_convertir_a_epw.xlsx"

# # Configure the mappings to match the provided excel columns
# custom_mapping = {
#     'temp': 'Dry-bulb temperature',
#     'dew': 'Dew Point temperature',
#     'wind_speed': 'Wind Speed',
#     'ghi': 'Global Horizontal Irradiance ',
#     'dni': 'Beam Normal Irradiance ',
#     'dhi': 'Diffuse Horizontal Irradiance',
#     'pres': 'Pressure',
#     'wind_dir': 'Wind Direction',
#     'rh': 'Relative Humidity',
#     'cloud_cover': 'Total Cloud Cover',
#     'irh': 'IRh'
# }

print("Testing HourlyEPWConverter Instantiation...")
converter = HourlyEPWConverter(
    file_path=excel_path,
    lat=40.4168,
    lon=-3.7038,
    elev=667,
    tz_hour=1,
    # column_mapping=custom_mapping,
    preserve_extra=True
)

# Process the first year available to test transform_to_epw
# year = converter.available_years[0]
# df_y = converter.get_year_data(year)
# output_path = f"TEST_output_{year}.epw"
# print(f"Testing transform_to_epw for year {year}...")
# success = converter.transform_to_epw(df_y, base_path, output_path)
# if success:
#     print(f"Success! Output file generated: {output_path}")
# else:
#     print("Failed during transform_to_epw")

# Process all available years
success_list = converter.process(base_epw_path=base_path, output_pattern='{city}_{year}.epw', city='madrid')
print(f"Success for years: {success_list}")

##

from pyweatherfiles.hourly_epw_converter import BatchHourlyEPWConverter

cities_config = BatchHourlyEPWConverter.suggest_config(
    identifiers=['madrid'],
    data_files=['Madrid_Definitivo_para_convertir_a_epw.xlsx'],
    base_epw_files=['ESP_Madrid.082210_IWEC.epw']
)

converter = BatchHourlyEPWConverter(cities_config=cities_config)

converter.process_all(
    output_pattern='{city}_{year}.epw', city='madrid'
)


##
from besos.eplus_funcs import run_building, run_energyplus
from besos.eppy_funcs import get_building

# building = get_building('ALJARAFE CENTER_mod.idf')

# building.run()
#
# run_building(
#     building=building,
#
# )

run_energyplus(
    building_path='SF_Detached_D_min_South.idf',
    epw='madrid_2025.epw',
    out_dir='eplus_results'
)

##

from pyweatherfiles.epw_comparator import create_comparison_hourly_dataframe

df = create_comparison_hourly_dataframe(
    base_epw_path='madrid_2005.epw',
    generated_epw_path='Madrid_Definitivo_para_convertir_a_epw_2005.epw'
)