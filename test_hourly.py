import sys
from pyweatherfiles.hourly_epw_converter import HourlyEPWConverter, BatchHourlyEPWConverter

def main():
    print("--- DEMO DE LA CLASE MASIVA 'BatchHourlyEPWConverter' ---")
    
    # Podemos consultar en cualquier momento qué llaves son obligatorias:
    claves_requeridas = BatchHourlyEPWConverter.get_mandatory_config_keys()
    print(f"Claves de configuración obligatorias para cada ciudad: {claves_requeridas}")
    print("\n---------------------------------------------------------")
    
    # 1. Creamos la configuración MASIVA usando el asistente automático 'suggest_config'
    #    Le damos identificadores, y sabe buscar en las listas (o carpetas)
    identificadores = ['MADRID']
    
    # Supongamos que esta es tu carpeta o lista de Excels de datos:
    data_files = ['d:\\Python\\pyweatherfiles\\MADRID_horario.xlsx']
    
    # Y aquí tu carpeta o lista de EPWs que sirven como constructores base:
    base_epw_files = ['d:\\Python\\pyweatherfiles\\Seville_Present.epw', 'd:\\Python\\pyweatherfiles\\MADRID_Present.epw']
    
    print("Buscando parejas y extrayendo ubicación (lat, lon, elev, tz)...")
    cities_config = BatchHourlyEPWConverter.suggest_config(
        identifiers=identificadores,
        data_files=data_files,
        base_epw_files=base_epw_files
    )
    
    if not cities_config:
        print("No se encontró ninguna configuración válida para procesar. Saliendo...")
        return
        
    # ATENCIÓN: A esta lista 'cities_config' autogenerada, puedes editarla
    # e inyectarle variables tuyas (como 'clima' o 'zona') mediante un bucle for
    for c in cities_config:
        c['zona'] = 'Centro'  # Se la añadimos a todas para que la usen en el patrón
        c['clima'] = 'C3'     # Faltaba añadir 'clima' que requiere el output_pattern
        c['years'] = [2013]   # Para que el test tarde poco
    
    # 2. Inicializamos el convertidor MASIVO
    batch_converter = BatchHourlyEPWConverter(
        cities_config=cities_config,
        output_dir='d:\\Python\\pyweatherfiles\\'
    )
    
    # 4. Procesamos TODAS LAS CIUDADES con un solo patrón unificado
    #    Observa que usamos llaves dinámicas que sacamos del diccionario ({zona}, {clima})
    resultados = batch_converter.process_all(
        output_pattern="BATCH_Clima_{zona}_{clima}_{basename}_{year}.epw",
        max_interpolate_limit=24
    )

if __name__ == '__main__':
    main()
