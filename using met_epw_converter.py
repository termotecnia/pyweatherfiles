

from pyweatherfiles.met_epw_converter import convert_met_to_epw

success = convert_met_to_epw(
    met_path='zonaB4.met',
    epw_path='zonaB4.epw',
    base_epw_path='Seville_Present.epw',
    replace_unused_with_999=True
)

##

from pyweatherfiles.epw_comparator import create_comparison_hourly_dataframe

x = create_comparison_hourly_dataframe(base_epw_path='Seville_Present.epw', generated_epw_path='zonaB4.epw')