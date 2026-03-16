

from pyweatherfiles.met_epw_converter import convert_met_to_epw

success = convert_met_to_epw(
    met_path='Sevilla-centro.met',
    epw_path='Sevilla-centro.epw',
    base_epw_path='Seville_Present.epw',
    replace_unused_with_missing=True
)

##

from pyweatherfiles.epw_comparator import create_comparison_hourly_dataframe

x = create_comparison_hourly_dataframe(base_epw_path='Seville_Present.epw', generated_epw_path='zonaB4.epw')

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
    building_path='viv unifamiliar aislada.idf',
    epw='Sevilla-centro.epw',
    out_dir='eplus_results'
)

