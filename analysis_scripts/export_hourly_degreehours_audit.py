# -*- coding: utf-8 -*-
"""
Export an auditable hourly Degree-Hours workbook (HDH/CDH/NCDH) for one city.

This script creates an .xlsx file with:
- hourly_<city>: one row per hour and year, including hourly HDH20/CDH25/NCDH_25
- yearly_sum_<city>: annual sums computed from hourly values
- yearly_reference: optional reference values from climate_trend_variables.csv
- yearly_diff_vs_reference: annual differences (sum - reference), if reference exists

NCDH_25 formula (night cooling potential, corrected):
    NCDH_25_h = max(0, 25 - T_h) * (hour in 0-8, inclusive) * (month in Jul-Sep)
i.e. the degrees still MISSING to reach 25 degC (cooling potential/deficit),
NOT the degrees above it (that would be a classic overheating CDH). Matches
the audited formula in the reference workbook's 'hourly_leon' sheet, column
'NCDH_25' (``=IF((25-T)>0,(25-T),0)*IF(AND(month>=7,month<=9,hour<=8),1,0)``).

Run from repository root:
    python analysis_scripts/export_hourly_degreehours_audit.py --city leon
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import pandas as pd

from pyweatherfiles.degree_hours import DegreeHoursCalculator

SETPOINTS = {"type": "constant", "heating": 20.0, "cooling": 25.0}
NIGHT_HOURS = list(range(0, 9))       # 00:00-08:00, inclusive (9 hourly values)
SUMMER_MONTHS = [7, 8, 9]             # July-September, inclusive


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export hourly HDH/CDH/NCDH to XLSX for city-year EPW files."
    )
    parser.add_argument(
        "--city",
        default="leon",
        help="City/group prefix in EPW names (example: leon for leon_2015.epw).",
    )
    parser.add_argument(
        "--epw-dir",
        default=None,
        help="Path to folder with longterm EPWs. Default: <repo>/longterm_epw",
    )
    parser.add_argument(
        "--reference-csv",
        default=None,
        help="Path to reference yearly CSV. Default: <repo>/analysis_scripts/climate_trend_variables.csv",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output XLSX path. Default: <repo>/analysis_scripts/<city>_hourly_degreehours_audit.xlsx",
    )
    return parser.parse_args()


def discover_epw_paths(epw_dir: Path, city: str) -> List[Path]:
    paths = sorted(epw_dir.glob(f"{city}_*.epw"))
    if not paths:
        raise FileNotFoundError(f"No EPW files found for city '{city}' in: {epw_dir}")
    return paths


def year_from_path(path: Path) -> int:
    # Expected pattern: city_YYYY.epw
    year_str = path.stem.split("_")[-1]
    return int(year_str)


def build_hourly_table(epw_paths: List[Path], city: str) -> pd.DataFrame:
    hourly_parts = []

    for epw_path in epw_paths:
        year = year_from_path(epw_path)
        calc = DegreeHoursCalculator(str(epw_path), year=year)

        all_day = calc.calculate(
            setpoint_source=SETPOINTS,
            frequency=["hourly"],
            mode="both",
            save_session=False,
        )["hourly"]

        night = calc.calculate(
            setpoint_source=SETPOINTS,
            frequency=["hourly"],
            mode="cooling",
            hours=NIGHT_HOURS,
            months=SUMMER_MONTHS,
            invert_cooling=True,   # cooling POTENTIAL (25 - T), not excess (T - 25)
            save_session=False,
        )["hourly"]

        # Reindex night-only series to all hours so annual sums stay auditable.
        ncdh_full = night["cooling_dh"].reindex(all_day.index, fill_value=0.0)

        part = pd.DataFrame(
            {
                "city": city,
                "year": year,
                "datetime": all_day.index,
                "month": all_day.index.month,
                "day": all_day.index.day,
                "hour": all_day.index.hour,
                "dry_bulb_temperature": calc.temperatures.reindex(all_day.index).values,
                "HDH20_all_day": all_day["heating_dh"].values,
                "CDH25_all_day": all_day["cooling_dh"].values,
                "NCDH_25": ncdh_full.values,
            }
        )
        hourly_parts.append(part)

    hourly = pd.concat(hourly_parts, ignore_index=True)
    return hourly


def build_yearly_sum(hourly: pd.DataFrame) -> pd.DataFrame:
    return (
        hourly.groupby(["city", "year"], as_index=False)[
            ["HDH20_all_day", "CDH25_all_day", "NCDH_25"]
        ]
        .sum()
        .sort_values(["city", "year"])
    )


def load_reference_table(reference_csv: Path, city: str) -> pd.DataFrame:
    if not reference_csv.exists():
        return pd.DataFrame()

    ref = pd.read_csv(str(reference_csv))
    required = {"group", "year", "heating_dh_allday", "cooling_dh_allday", "cooling_dh_night_potential_jul_sep"}
    if not required.issubset(ref.columns):
        return pd.DataFrame()

    ref_city = (
        ref.loc[ref["group"].str.lower() == city.lower(), [
            "group",
            "year",
            "heating_dh_allday",
            "cooling_dh_allday",
            "cooling_dh_night_potential_jul_sep",
        ]]
        .rename(
            columns={
                "group": "city",
                "heating_dh_allday": "HDH20_ref",
                "cooling_dh_allday": "CDH25_ref",
                "cooling_dh_night_potential_jul_sep": "NCDH_25_ref",
            }
        )
        .sort_values(["city", "year"])
    )
    return ref_city


def main() -> None:
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    city = args.city.strip().lower()
    epw_dir = Path(args.epw_dir) if args.epw_dir else repo_root / "longterm_epw"
    reference_csv = (
        Path(args.reference_csv)
        if args.reference_csv
        else script_dir / "climate_trend_variables.csv"
    )
    out_xlsx = (
        Path(args.out)
        if args.out
        else script_dir / f"{city}_hourly_degreehours_audit.xlsx"
    )

    epw_paths = discover_epw_paths(epw_dir, city)
    print(f"[INFO] Found {len(epw_paths)} EPW files for city '{city}'.")

    hourly = build_hourly_table(epw_paths, city)
    yearly_sum = build_yearly_sum(hourly)

    reference = load_reference_table(reference_csv, city)

    diff = pd.DataFrame()
    if not reference.empty:
        diff = yearly_sum.merge(reference, on=["city", "year"], how="left")
        diff["HDH20_diff"] = diff["HDH20_all_day"] - diff["HDH20_ref"]
        diff["CDH25_diff"] = diff["CDH25_all_day"] - diff["CDH25_ref"]
        diff["NCDH_25_diff"] = diff["NCDH_25"] - diff["NCDH_25_ref"]

    with pd.ExcelWriter(str(out_xlsx), engine="openpyxl") as writer:
        hourly.to_excel(writer, sheet_name=f"hourly_{city}", index=False)
        yearly_sum.to_excel(writer, sheet_name=f"yearly_sum_{city}", index=False)
        if not reference.empty:
            reference.to_excel(writer, sheet_name="yearly_reference", index=False)
            diff.to_excel(writer, sheet_name="yearly_diff_vs_reference", index=False)

    print(f"[OK] Audit workbook written to: {out_xlsx}")
    print("[INFO] You can verify annual totals in sheet yearly_sum_* and compare with yearly_reference.")


if __name__ == "__main__":
    main()


