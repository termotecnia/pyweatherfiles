import sys
from pyweatherfiles.hourly_epw_converter import HourlyEPWConverter

def main():
    print("Inicializando convertidor y analizando archivo...")
    # Parámetros básicos constantes para Madrid
    lat = 40.4168
    lon = -3.7038
    elev = 660.0
    tz = +1.0
    
    # 1. Creamos la instancia
    converter = HourlyEPWConverter(
        file_path='d:\\Python\\pyweatherfiles\\MADRID_horario.xlsx',
        lat=lat, lon=lon, elev=elev, tz_hour=tz,
        datetime_col='DATETIME_UTC', col_temp='Dry-bulb temperature',
        col_dew='Dew Point temperature', col_wind='Wind speed',
        col_ghi='GHI', col_dni='BNI/DNI'
    )
    
    # 2. Mostramos los atributos que pidió incluir (años disponibles)
    print("\n--- ATRIBUTOS CARGADOS AUTOMÁTICAMENTE ---")
    print("Años disponibles detectados en el archivo:", converter.available_years)
    
    # 3. Podemos generar y ver las estadísticas de forma independiente
    print("\n--- ESTADÍSTICAS DEL ARCHIVO ---")
    stats = converter.get_missing_data_stats()
    print(stats.to_string(index=False))
    
    # ------------------------------------------------------------
    # MÉTODO A: Ejecución paso a paso simulando un año específico
    # ------------------------------------------------------------
    print("\n--- MÉTODO A: EJECUCIÓN PASO A PASO (Elegimos el 2013) ---")
    year_to_test = 2013
    
    # Extraemos el df directamente del interior de la clase
    df_2013 = converter.get_year_data(year_to_test)
    print("Filas iniciales:", len(df_2013))
    
    # Rellenamos de forma manual un paso individual
    df_2013_filled = converter.fill_missing_values(df_2013)
    
    # Exportamos un EPW independiente
    base_epw = 'd:\\Python\\pyweatherfiles\\Seville_Present.epw'
    out_epw_manual = f'd:\\Python\\pyweatherfiles\\MADRID_{year_to_test}_paso_a_paso.epw'
    
    success = converter.transform_to_epw(df_2013_filled, base_epw, out_epw_manual)
    if success:
         print(f"Éxito ejecutando paso a paso para {year_to_test}. Archivo guardado: {out_epw_manual}")
         
    # ------------------------------------------------------------
    # MÉTODO B: Ejecución general directa "todo en uno"
    # ------------------------------------------------------------
    print("\n--- MÉTODO B: EJECUCIÓN DIRECTA CON PATRÓN PERSONALIZADO (Múltiples Años) ---")
    years_to_process = [2014, 2017] # Procesamos los dos restantes de prueba
    
    # Ejecutamos con una sola llamada la conversión masiva.
    # Aquí puedes jugar con el output_pattern dictando nombres y pasando las variables que quieras.
    results = converter.process(
        base_epw_path=base_epw, 
        output_dir='d:\\Python\\pyweatherfiles\\', 
        years=years_to_process,
        output_pattern="Clima_{zona}_{basename}_{year}_Personalizado.epw",
        zona="Centro"
    )
    print(f"\nAños convertidos exitosamente mediante proceso directo: {results}")

if __name__ == '__main__':
    main()
