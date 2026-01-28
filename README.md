# pyweatherfiles

A Python package to manage weather files and generate Typical Meteorological Year (TMY) data from historical records.

## Installation

```bash
pip install pyweatherfiles
```

## Usage

```python
from pyweatherfiles import tmy

# See examples/using_tmy_generator.py for a complete example.
generator = tmy.TMYGenerator("path/to/your/weather_data.csv")
# ... check the example file for more details
```

## Description
This tool allows you to:
- Load weather data from CSV or Excel.
- Calculate CDFs using daily or hourly methods.
- Apply weighting statistics (Sandia or TMY3).
- Select candidate months based on Finkelstein-Schafer statistics.
- Apply persistence criteria.
- Smooth the data at monthly junctions.
- Generate a final TMY file.

## License
MIT
