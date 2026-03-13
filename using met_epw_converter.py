

from pyweatherfiles.met_epw_converter import convert_met_to_epw

success = convert_met_to_epw(
    met_path='zonaB4.met',
    epw_path='zonaB4.epw',
    base_epw_path='Seville_Present.epw'
)

