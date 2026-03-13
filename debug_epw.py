import pandas as pd
from ladybug.epw import EPW

epw = EPW("zonaB4.epw")

db = epw.dry_bulb_temperature.values
# db is a tuple, so we need to convert it to a list properly
fixed_db = [db[-1]] + list(db[:-1])  # Shift right by 1
epw.dry_bulb_temperature.values = fixed_db

epw.save("zonaB4_fixed.epw")

print("\n--- Raw EPW CSV First Lines (Fixed) ---")
with open("zonaB4_fixed.epw", "r") as f:
    lines = f.readlines()
    for i in range(8, 13): # Header is 8 lines usually
        print(lines[i].strip())
