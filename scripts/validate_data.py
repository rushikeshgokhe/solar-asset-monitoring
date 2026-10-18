

import csv
from collections import Counter
from pathlib import Path

# Locate the generated CSV
PROJECT_DIR = Path(__file__).resolve().parent.parent
CSV_FILE = PROJECT_DIR / "data" / "solar_telemetry.csv"

if not CSV_FILE.exists():
    raise FileNotFoundError(
        f"CSV file not found: {CSV_FILE}\n"
        "Run generate_data.py first."
    )

# Read the CSV
with CSV_FILE.open(newline="", encoding="utf-8") as file:
    reader = csv.DictReader(file)
    rows = list(reader)

# Check required columns
required_columns = {
    "timestamp",
    "site_id",
    "inverter_id",
    "ac_power_kw",
    "dc_voltage_v",
    "inverter_temp_c",
    "ghi_w_m2",
    "energy_kwh_interval",
    "expected_scenario",
}

actual_columns = set(reader.fieldnames or [])
missing_columns = required_columns - actual_columns

assert not missing_columns, (
    f"Missing columns: {missing_columns}"
)

# Check record count
assert len(rows) == 3452, (
    f"Expected 3452 rows, got {len(rows)}"
)

# Check sites and inverters
sites = {row["site_id"] for row in rows}
inverters = {row["inverter_id"] for row in rows}

assert len(sites) == 4, f"Expected 4 sites, got {len(sites)}"
assert len(inverters) == 3, (
    f"Expected 3 inverter IDs, got {len(inverters)}"
)

# Count simulated scenarios
scenarios = Counter(
    row["expected_scenario"] for row in rows
)

assert scenarios["SIMULATED_ZERO_POWER"] == 12, (
    "Unexpected zero-power scenario count"
)

assert scenarios["SIMULATED_HIGH_TEMP"] == 12, (
    "Unexpected high-temperature scenario count"
)

# Check that numeric readings are valid
numeric_columns = [
    "ac_power_kw",
    "dc_voltage_v",
    "inverter_temp_c",
    "ghi_w_m2",
    "energy_kwh_interval",
]

for row_number, row in enumerate(rows, start=2):
    for column in numeric_columns:
        value = float(row[column])
        assert value >= 0, (
            f"Negative value in {column}, CSV row {row_number}"
        )

print("VALIDATION PASSED")
print(f"Total readings: {len(rows)}")
print(f"Solar sites: {len(sites)}")
print(f"Inverter IDs: {len(inverters)}")
print(f"Simulated zero-power readings: {scenarios['SIMULATED_ZERO_POWER']}")
print(f"Simulated high-temperature readings: {scenarios['SIMULATED_HIGH_TEMP']}")
print("Required columns and numeric checks passed.")

