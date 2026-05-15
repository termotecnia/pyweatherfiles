from pyweatherfiles.degree_hours import EpwBatchAnalyzer

batch = EpwBatchAnalyzer(
    epw_paths=['madrid_tmy.epw', 'madrid_met.epw', 'madrid_2005.epw'],
    setpoint_source='SF_Detached_D_min_South.idf',          # o dict
    epw_variables={'global_horizontal_radiation': ['sum', 'mean']},
    hours={'morning':[0, 1, 2, 3, 4, 5, 6, 7, 8], 'all_day': [i for i in range(24)]},                  # horas 0-7; default
    mode='both',
    frequencies=['hourly', 'daily', 'monthly'],     # <--- Múltiples frecuencias
    start_date='01/06',                    # <--- Periodo de inicio (1 de junio)
    end_date='30/07',                       # <--- Periodo final (30 de sep))
)


results = batch.run()
# → DataFrame con MultiIndex (epw, variable):
#   month | Sevilla                          | Madrid           ...
#         | heating_dh_24h | cooling_dh_24h | heating_dh_0-8h | ...

batch.export('resultados_verano_2meses.xlsx')
# → Excel con hoja 'all_epws' + una hoja por EPW

##

from pyweatherfiles.degree_hours import DegreeHoursCalculator

calc = DegreeHoursCalculator('madrid_tmy.epw')

# Ver consignas antes del cálculo
calc.plot('SF_Detached_D_min_South.idf', period='day', period_value=['06-10', '06-11'], show_air_temp=True)
