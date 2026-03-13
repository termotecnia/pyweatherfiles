import pandas as pd
from ladybug.epw import EPW

epw_fixed = EPW("zonaB4_fixed.epw")
db = epw_fixed.dry_bulb_temperature.values
print(f"Read DB Hourly Time Array head: {db[:5]}")
print(f"Read DB Hourly Time Array tail: {db[-5:]}")
