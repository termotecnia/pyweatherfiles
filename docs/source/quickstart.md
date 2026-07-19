# Quickstart

This page shows the shortest path from raw hourly weather data to a TMY EPW
file and a degree-hours table. It mirrors the real workflow used in
`generating epws seville.py` (see {doc}`article_context`) and in the
{doc}`tutorial` notebook.

## 1. Generate a Typical Meteorological Year (TMY)

```python
from pyweatherfiles import tmy

gen = tmy.TMYGenerator(
    file_path="weather_data.csv",   # clean hourly series, one row per hour
    cdf_method="daily",             # fast candidate-month selection
    data_frequency="hourly",
    hourly_file_path="weather_data.csv",  # keeps hourly resolution for assembly/smoothing
    weighting_method="sandia",
    datetime_col="time",
    col_temp="Dry-bulb temperature",
    col_dew="Dew Point temperature",
    col_wind="Wind Speed",
    col_ghi="Global Horizontal Irradiance ",
    col_dni="Beam Normal Irradiance ",
)
gen.generate_tmy(use_persistence=True)
gen.export_tmy("tmy_output.csv")
```

## 2. Convert the TMY (or any clean hourly series) to EPW

```python
from pyweatherfiles import hourly_epw_converter

converter = hourly_epw_converter.HourlyEPWConverter(
    file_path="tmy_output.csv",
    base_epw_path="template.epw",   # provides lat/lon/elevation/time zone
)
converter.process(output_pattern="city_tmy.epw")
```

## 3. Compute heating/cooling degree-hours

```python
from pyweatherfiles.degree_hours import DegreeHoursCalculator

calc = DegreeHoursCalculator("city_tmy.epw")
results = calc.calculate("building_model.idf", frequency=["monthly"], mode="both")
print(results["monthly"])
calc.export_results("degree_hours.xlsx")
```

## Next steps

- Read the full API details in {doc}`full_reference_en` / {doc}`full_reference_es`.
- Run the {doc}`tutorial` notebook end-to-end with the sample data bundled in this repository.
- Browse the auto-generated {doc}`API reference <api/modules>`.

