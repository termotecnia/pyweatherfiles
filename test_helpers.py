from ladybug.epw import EPW
import numpy as np

epw = EPW("base.epw") if False else EPW("zonaB4.epw")

def get_epw_values(epw_obj, field_name):
    field = getattr(epw_obj, field_name)
    vals = list(field.values)
    if field.header.data_type.point_in_time:
        return vals[1:] + [vals[0]]
    return vals

def set_epw_values(epw_obj, field_name, vals):
    field = getattr(epw_obj, field_name)
    if field.header.data_type.point_in_time:
        shifted = [vals[-1]] + list(vals[:-1])
        field.values = tuple(shifted) if isinstance(field.values, tuple) else list(shifted)
    else:
        field.values = tuple(vals) if isinstance(field.values, tuple) else list(vals)

# Simulate full year list
db_vals = [15.1, 14.6, 14.1] + [0]*(8760-3)

set_epw_values(epw, 'dry_bulb_temperature', db_vals)
epw.save("test_out.epw")

print("--- EPW CSV Verification ---")
with open("test_out.epw") as f:
    lines = f.readlines()
    print("Row 1 (Hour 1) Dry Bulb:", lines[8].split(',')[6])
    print("Row 2 (Hour 2) Dry Bulb:", lines[9].split(',')[6])
    print("Row 8760 (Hour 24) Dry Bulb:", lines[8+8759].split(',')[6])

print("\n--- Reading back using helper verification ---")
epw2 = EPW("test_out.epw")
vals_read = get_epw_values(epw2, 'dry_bulb_temperature')
print("Read values[:3]:", vals_read[:3])
