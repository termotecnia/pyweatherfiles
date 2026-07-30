# epw_comparator.py
"""
epw_comparator.py
==================

Structural, statistical and hourly comparison tools for pairs of EPW files.

This module answers a recurring question in the package's workflow: *"how
close is the EPW I generated (TMY, converted from ``.met``, or an individual
year) to a reference EPW?"* It offers four independent, free (non-class)
functions, from a quick diagnostic dump to a full hour-by-hour DataFrame
suitable for statistical testing or plotting:

- :func:`explore_epw_structure` — dumps the shape of ``EPW.to_dict()`` for a
  single file; a debugging helper for locating where Ladybug stores what.
- :func:`compare_epw_files` — prints a console report (via ``tabulate``)
  comparing header metadata and the descriptive statistics of the difference
  (generated - base) for 9 key climate variables.
- :func:`create_comparison_dataframe` — builds a side-by-side DataFrame from
  Ladybug's ``EPW.to_dict()['data_collections']``, with Spanish column names
  suffixed ``_Base``/``_Generado``.
- :func:`create_comparison_hourly_dataframe` — the most commonly used
  function: reads both EPW files directly as CSV (skipping the 8 header
  lines) and returns a single DataFrame with ``Base_*``/``Generated_*``
  columns for all 35 official EPW data-dictionary fields, aligned hour by
  hour.

Example
-------
Comparing a generated TMY against the official reference EPW used to build it::

    from pyweatherfiles import epw_comparator

    epw_comparator.compare_epw_files("ESP_Sevilla.083910_IWEC.epw", "sevilla_tmy.epw")

    df = epw_comparator.create_comparison_hourly_dataframe(
        base_epw_path="ESP_Sevilla.083910_IWEC.epw",
        generated_epw_path="sevilla_tmy.epw",
    )
    print(df[["Base_DryBulbTemp", "Generated_DryBulbTemp"]].describe())
"""

import pandas as pd
from .session_manager import save_function_session

try:
    from tabulate import tabulate
except ImportError:
    raise ImportError(
        "The 'tabulate' library is not installed. It is required by epw_comparator "
        "for console report formatting. Install it with: pip install tabulate "
        "(or: pip install pyweatherfiles[comparator])"
    )

try:
    from ladybug.epw import EPW
except ImportError:
    raise ImportError("La librería 'ladybug-core' no está instalada. Por favor, instálala con: pip install ladybug-core")


def explore_epw_structure(epw_path: str):
    """
    Load an EPW file and print the structure of the underlying Ladybug
    object (via ``EPW.to_dict()``): every top-level key, its Python type, and
    a short value preview.

    This is primarily a **debugging/discovery** helper, useful when working
    with a new/unexpected Ladybug version to figure out where the hourly
    data collections live inside the dict (look for keys whose preview says
    "List with 8760 elements").

    Args:
        epw_path (str): Path to the EPW file to inspect.

    Returns:
        None: Everything is printed to the console; nothing is returned.

    Example:
        >>> from pyweatherfiles import epw_comparator
        >>> epw_comparator.explore_epw_structure("sevilla_tmy.epw")  # doctest: +SKIP
        --- Explorando la Estructura del Archivo EPW: 'sevilla_tmy.epw' ---
        ...
    """
    print(f"\n--- Explorando la Estructura del Archivo EPW: '{epw_path}' ---")
    try:
        epw = EPW(epw_path)
    except Exception as e:
        print(f"No se pudo cargar el archivo EPW: {e}")
        return

    print("\n[1] Intentando volcar el objeto a un diccionario con .to_dict()")
    try:
        epw_dict = epw.to_dict()
        print("  -> .to_dict() se ejecutó con éxito.")
    except Exception as e:
        print(f"  -> .to_dict() falló con el error: {e}")
        return

    print("\n[2] Claves encontradas en el diccionario y tipo de valor asociado:")
    if not isinstance(epw_dict, dict):
        print(f"  -> El resultado de .to_dict() NO es un diccionario, es un: {type(epw_dict)}")
        return

    if not epw_dict:
        print("  -> El diccionario está vacío.")
        return

    for key, value in epw_dict.items():
        value_type = type(value)
        value_preview = ""
        if isinstance(value, list):
            value_preview = f"(Lista con {len(value)} elementos)"
        elif isinstance(value, dict):
            value_preview = f"(Diccionario con {len(value)} claves)"
        else:
            value_preview = f"({str(value)[:50]}...)"  # Muestra los primeros 50 caracteres

        print(f"  - Clave: '{key}'".ljust(40) + f"| Tipo: {value_type.__name__}".ljust(25) + f"| Vista Previa: {value_preview}")

    print("\n--- Exploración Finalizada ---")
    print("Por favor, usa la información de arriba para identificar la clave que contiene los datos horarios (listas de 8760 elementos).")


def compare_epw_files(base_epw_path: str, generated_epw_path: str):
    """
    Print a console report (via ``tabulate``) comparing a base/reference EPW
    against a generated one: first their header metadata (city, latitude,
    longitude, time zone, elevation, comments), then descriptive statistics
    (count of changed values, mean/std/min/max) of the hourly difference
    (*generated - base*) for 9 key climate variables (dry-bulb and dew-point
    temperature, relative humidity, atmospheric pressure, direct-normal and
    diffuse-horizontal radiation, horizontal infrared radiation, wind speed
    and direction).

    Both files are loaded with ``ladybug.epw.EPW``; any field that cannot be
    read is reported as ``"Error al leer"`` instead of raising.

    Args:
        base_epw_path (str): Path to the reference/base EPW file.
        generated_epw_path (str): Path to the EPW file to compare against
            the base (e.g. a TMY you just generated).

    Returns:
        None: The comparison is printed to the console; nothing is returned.

    Example:
        >>> from pyweatherfiles import epw_comparator
        >>> epw_comparator.compare_epw_files(
        ...     "ESP_Sevilla.083910_IWEC.epw", "sevilla_tmy.epw"
        ... )  # doctest: +SKIP
        --- Iniciando Comparación de Archivos EPW ---
        ...
    """
    print("--- Iniciando Comparación de Archivos EPW ---")
    print(f"  Archivo Base:      '{base_epw_path}'")
    print(f"  Archivo Generado:  '{generated_epw_path}'")
    print("-" * 40)

    try:
        epw_base = EPW(base_epw_path)
        epw_gen = EPW(generated_epw_path)
    except FileNotFoundError as e:
        print(f"Error Crítico: No se pudo encontrar uno de los archivos. {e}")
        return
    except Exception as e:
        print(f"Error al cargar los archivos EPW con Ladybug: {e}")
        return

    print("\n[1] Comparación de Metadatos (Cabecera)\n")
    header_data = [
        ["Ciudad", epw_base.location.city, epw_gen.location.city],
        ["Latitud", epw_base.location.latitude, epw_gen.location.latitude],
        ["Longitud", epw_base.location.longitude, epw_gen.location.longitude],
        ["Zona Horaria (TZ)", epw_base.location.time_zone, epw_gen.location.time_zone],
        ["Elevación (m)", epw_base.location.elevation, epw_gen.location.elevation],
        ["Comentario 1", epw_base.comments_1, epw_gen.comments_1],
        ["Comentario 2", epw_base.comments_2, epw_gen.comments_2],
    ]
    print(tabulate(header_data, headers=["Parámetro", "Valor en Base", "Valor en Generado"], tablefmt="grid"))
    
    # Nota: Para la comparación estadística rápida en consola, seguimos usando getattr
    # porque es solo para visualización rápida de campos estándar.
    print("\n[2] Resumen Estadístico de la Diferencia (Generado - Base)\n")
    fields_to_compare = [
        "dry_bulb_temperature", "dew_point_temperature", "relative_humidity",
        "atmospheric_station_pressure", "direct_normal_radiation",
        "diffuse_horizontal_radiation", "horizontal_infrared_radiation_intensity",
        "wind_speed", "wind_direction"
    ]
    stats_results = []
    for field in fields_to_compare:
        try:
            data_base = getattr(epw_base, field).values
            data_gen = getattr(epw_gen, field).values
            series_base = pd.Series(data_base)
            series_gen = pd.Series(data_gen)
            difference = series_gen - series_base
            stats = difference.describe()
            if difference.abs().sum() == 0:
                stats_results.append([field, "Sin cambios", "-", "-", "-", "-"])
            else:
                stats_results.append([
                    field, stats['count'], stats['mean'], stats['std'], stats['min'], stats['max']
                ])
        except Exception:
            stats_results.append([field, "Error al leer", "-", "-", "-", "-"])

    print(tabulate(
        stats_results,
        headers=["Variable Climática", "Valores Cambiados", "Media(Dif)", "Std(Dif)", "Min(Dif)", "Max(Dif)"],
        tablefmt="grid", floatfmt=".2f"
    ))
    print("\n--- Comparación Finalizada ---")


def create_comparison_dataframe(base_epw_path: str, generated_epw_path: str) -> pd.DataFrame:
    """
    Build a single, side-by-side pandas DataFrame comparing two EPW files,
    using Ladybug's structured ``EPW.to_dict()['data_collections']`` as the
    data source (as opposed to :func:`create_comparison_hourly_dataframe`,
    which parses the raw CSV bytes directly).

    For each of 9 mapped climate variables (see the ``column_map`` in the
    source code, e.g. ``"Dry Bulb Temperature" -> "TempBulboSeco"``), two
    columns are added: ``{short_name}_Base`` and ``{short_name}_Generado``.
    The DataFrame index is built from the ``year``/``month``/``day``/``hour``
    columns found in the base file's data collections when possible,
    otherwise a plain numeric index is used (with a warning printed).

    Args:
        base_epw_path (str): Path to the reference/base EPW file.
        generated_epw_path (str): Path to the EPW file to compare against
            the base.

    Returns:
        pandas.DataFrame: Side-by-side comparison DataFrame with
        Spanish-named, ``_Base``/``_Generado``-suffixed columns. Returns an
        **empty** DataFrame if either file cannot be loaded or parsed (errors
        are printed to the console).

    Example:
        >>> from pyweatherfiles import epw_comparator
        >>> df = epw_comparator.create_comparison_dataframe(
        ...     "ESP_Sevilla.083910_IWEC.epw", "sevilla_tmy.epw"
        ... )  # doctest: +SKIP
        >>> df[["TempBulboSeco_Base", "TempBulboSeco_Generado"]].head()  # doctest: +SKIP
    """
    print("\n--- Creando DataFrame Comparativo (Método Ladybug) ---")
    try:
        epw_base = EPW(base_epw_path)
        epw_gen = EPW(generated_epw_path)
    except Exception as e:
        print(f"Error al cargar archivos EPW: {e}")
        return pd.DataFrame()

    try:
        base_collections = epw_base.to_dict()['data_collections']
        gen_collections = epw_gen.to_dict()['data_collections']

        # --- CORRECCIÓN AQUÍ: Usamos .get('name') para ser más seguros ---
        # Intentamos obtener el nombre. Si 'header' es un dict, buscamos 'name'.
        # Si 'header' es un string (versiones antiguas), lo usamos directamente.
        def get_header_name(collection):
            """Return the human-readable variable name of a Ladybug data
            collection dict, handling both the modern (``header`` is a dict
            with a ``'name'`` key) and legacy (``header`` is already a
            string) ``EPW.to_dict()`` formats."""
            header = collection.get('header')
            if isinstance(header, dict):
                return header.get('name', 'Unknown')
            return str(header)

        data_dict_base = {get_header_name(col): col['values'] for col in base_collections}
        data_dict_gen = {get_header_name(col): col['values'] for col in gen_collections}

        df_base = pd.DataFrame(data_dict_base)
        df_gen = pd.DataFrame(data_dict_gen)

    except Exception as e:
        print(f"Error al procesar diccionarios de Ladybug: {e}")
        return pd.DataFrame()

    # Mapeo de nombres (ajustado a los nombres estándar que suele devolver Ladybug en 'name')
    # Nota: Las claves aquí deben coincidir con lo que devuelve get_header_name
    column_map = {
        "Dry Bulb Temperature": "TempBulboSeco",
        "Dew Point Temperature": "TempPuntoRocio",
        "Relative Humidity": "HumedadRelativa",
        "Atmospheric Station Pressure": "PresionAtmosferica",
        "Direct Normal Radiation": "RadDirectaNormal",
        "Diffuse Horizontal Radiation": "RadDifusaHorizontal",
        "Horizontal Infrared Radiation Intensity": "RadInfrarrojaHorizontal",
        "Wind Speed": "VelocidadViento",
        "Wind Direction": "DireccionViento"
    }

    df_final = pd.DataFrame()
    
    try:
        # Intentamos construir el índice de tiempo
        # Nota: Si esto falla, devolveremos el DF sin índice de tiempo o usaremos un genérico
        dates = pd.to_datetime(df_base[['year', 'month', 'day']])
        hours_timedelta = pd.to_timedelta(df_base['hour'], unit='h')
        df_final.index = dates + hours_timedelta
        df_final.index.name = 'Timestamp'
    except Exception:
        print("Advertencia: No se pudo crear el índice de tiempo exacto. Se usará índice numérico.")

    # Poblar el DataFrame final
    for original_name, short_name in column_map.items():
        # Búsqueda insensible a mayúsculas/minúsculas por si acaso
        col_base = next((col for col in df_base.columns if col.lower() == original_name.lower()), None)
        col_gen = next((col for col in df_gen.columns if col.lower() == original_name.lower()), None)

        if col_base and col_gen:
            df_final[f'{short_name}_Base'] = df_base[col_base]
            df_final[f'{short_name}_Generado'] = df_gen[col_gen]

    print("DataFrame creado con éxito.")
    return df_final


def create_comparison_hourly_dataframe(base_epw_path: str, generated_epw_path: str, save_session: bool = True, session_dir: str = None) -> pd.DataFrame:
    """
    Build a single, side-by-side hourly DataFrame comparing two EPW files by
    reading both **directly as CSV** (the 8 EPW header lines are skipped, and
    all 35 official EPW data-dictionary field names are assigned manually),
    rather than going through Ladybug's object model.

    This is **the function used in the article's Seville case study** for
    hour-by-hour comparisons: it is faster than the Ladybug-based
    :func:`create_comparison_dataframe`, does not depend on Ladybug's
    ``to_dict()`` internal structure, and reads with ``encoding='latin-1'``
    so accented characters in Spanish-origin EPW files (city names, comments)
    do not raise a ``UnicodeDecodeError``.

    Every one of the 35 EPW fields gets two columns in the result:
    ``Base_{field}`` and ``Generated_{field}`` (e.g. ``Base_DryBulbTemp``,
    ``Generated_GlobalHorzRad``), aligned row-by-row (hour-by-hour) between
    the two files.

    Args:
        base_epw_path (str): Path to the reference/base EPW file.
        generated_epw_path (str): Path to the EPW file to compare against
            the base.
        save_session (bool, optional): If ``True`` (default), save a
            reproducible ``.pkl``/``.json`` session (inputs + resulting
            DataFrame's shape/columns) via
            :func:`~pyweatherfiles.session_manager.save_function_session`.
        session_dir (str, optional): Directory to write the session files
            to. Defaults to the directory of *base_epw_path*.

    Returns:
        pandas.DataFrame: The hourly comparison DataFrame with
        ``Base_*``/``Generated_*`` columns. Returns an **empty** DataFrame if
        either file cannot be read (errors are printed to the console).

    Example:
        >>> from pyweatherfiles import epw_comparator
        >>> df = epw_comparator.create_comparison_hourly_dataframe(
        ...     base_epw_path="ESP_Sevilla.083910_IWEC.epw",
        ...     generated_epw_path="sevilla_tmy.epw",
        ... )  # doctest: +SKIP
        >>> (df["Generated_DryBulbTemp"] - df["Base_DryBulbTemp"]).describe()  # doctest: +SKIP
    """
    print("\n--- Comparando Archivos EPW con Nombres de Columna Descriptivos ---")

    EPW_DATA_COLUMNS = [
        'Year', 'Month', 'Day', 'Hour', 'Minute', 'UncertaintyFlags',
        'DryBulbTemp', 'DewPointTemp', 'RelHum', 'AtmosPressure',
        'ExtHorzRad', 'ExtDirectNormalRad', 'HorzInfraredRad',
        'GlobalHorzRad', 'DirectNormalRad', 'DiffuseHorzRad',
        'GlobalHorzIllum', 'DirectNormalIllum', 'DiffuseHorzIllum',
        'ZenithLuminance', 'WindDirection', 'WindSpeed',
        'TotalSkyCover', 'OpaqueSkyCover', 'Visibility', 'CeilingHeight',
        'PresentWeatherObs', 'PresentWeatherCodes', 'PrecipitableWater',
        'AerosolOpticalDepth', 'SnowDepth', 'DaysSinceSnow', 'Albedo',
        'LiquidPrecipDepth', 'LiquidPrecipRate'
    ]

    try:
        # --- CORRECCIÓN DE CODIFICACIÓN AQUÍ ---
        # Usamos 'latin-1' que acepta tildes y caracteres especiales comunes en archivos EPW españoles
        df_base = pd.read_csv(base_epw_path, skiprows=8, header=None, encoding='latin-1')
        df_gen = pd.read_csv(generated_epw_path, skiprows=8, header=None, encoding='latin-1')
        print("  -> Archivos leídos con éxito como CSV.")

    except FileNotFoundError as e:
        print(f"Error: No se pudo encontrar uno de los archivos: {e}")
        return pd.DataFrame()
    except Exception as e:
        print(f"Error al leer los archivos con Pandas: {e}")
        return pd.DataFrame()

    if df_base.shape[1] != len(EPW_DATA_COLUMNS):
        print(f"Advertencia: El archivo base tiene {df_base.shape[1]} columnas, se esperaban {len(EPW_DATA_COLUMNS)}.")
    
    df_comparison = pd.DataFrame()
    num_columns = min(df_base.shape[1], df_gen.shape[1])
    
    for i in range(num_columns):
        if i < len(EPW_DATA_COLUMNS):
            col_name = EPW_DATA_COLUMNS[i]
        else:
            col_name = f'ExtraCol_{i}'

        df_comparison[f'Base_{col_name}'] = df_base[i]
        df_comparison[f'Generated_{col_name}'] = df_gen[i]

    print("DataFrame de comparación con nombres descriptivos creado con éxito.")

    # --- Session persistence ---
    if save_session and not df_comparison.empty:
        _inputs = {
            "base_epw_path": base_epw_path,
            "generated_epw_path": generated_epw_path,
        }
        _extra = {"shape": list(df_comparison.shape), "columns": list(df_comparison.columns)}
        import os
        _dir = session_dir or os.path.dirname(os.path.abspath(base_epw_path)) or os.getcwd()
        try:
            save_function_session(
                "create_comparison_hourly_dataframe",
                _inputs,
                result=df_comparison,
                session_dir=_dir,
                extra=_extra,
            )
        except Exception as _e:
            print(f"[SESSION] No se pudo guardar la sesión: {_e}")

    return df_comparison