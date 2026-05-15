from pyweatherfiles.degree_hours import DegreeHoursCalculator

calc = DegreeHoursCalculator('madrid_tmy.epw')

# Ver consignas antes del cálculo
calc.plot('SF_Detached_D_min_South.idf', period='day', period_value=['06-10', '06-11'], show_air_temp=True)
calc.plot('SF_Detached_D_min_South.idf', period='month', period_value=[1])

# Calcular
results = calc.calculate('SF_Detached_D_min_South.idf', frequency=['hourly', 'daily', 'monthly'], mode='both')
print(results['monthly'])

# Exportar
calc.export_results('grados_hora.xlsx')
