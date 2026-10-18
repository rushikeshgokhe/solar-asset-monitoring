
import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

# Project directories
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Generate one day of readings at 5-minute intervals
start_time = datetime(2026, 10, 1, 0, 0)
interval_minutes = 5
total_intervals = 24 * 60 // interval_minutes

sites = ["SITE-101", "SITE-102", "SITE-103", "SITE-104"]
inverters = ["INV-01", "INV-02", "INV-03"]

readings = []

for interval in range(total_intervals):
    timestamp = start_time + timedelta(
        minutes=interval * interval_minutes
    )
    hour = timestamp.hour + timestamp.minute / 60

    # Simulated solar irradiance profile
    if 6 <= hour <= 18:
        ghi = max(
            0,
            850 * math.sin(math.pi * (hour - 6) / 12)
            + random.uniform(-25, 25),
        )
    else:
        ghi = 0

    for site in sites:
        for inverter in inverters:

            # Simulate four missing telemetry records
            if (
                site == "SITE-103"
                and inverter == "INV-01"
                and timestamp.hour == 12
                and timestamp.minute <= 15
            ):
                continue

            dc_voltage = round(random.uniform(580, 680), 2)
            temperature = round(random.uniform(35, 58), 2)

            ac_power = round(
                100 * (ghi / 1000) * random.uniform(0.88, 0.98),
                2,
            )

            scenario = "NORMAL"

            # Simulated zero-power event
            if (
                site == "SITE-104"
                and inverter == "INV-03"
                and timestamp.hour == 11
            ):
                ac_power = 0
                scenario = "SIMULATED_ZERO_POWER"

            # Simulated high-temperature event
            if (
                site == "SITE-102"
                and inverter == "INV-02"
                and timestamp.hour == 13
            ):
                temperature = round(random.uniform(82, 88), 2)
                scenario = "SIMULATED_HIGH_TEMP"

            energy_kwh = round(
                ac_power * interval_minutes / 60,
                3,
            )

            readings.append({
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "site_id": site,
                "inverter_id": inverter,
                "ac_power_kw": ac_power,
                "dc_voltage_v": dc_voltage,
                "inverter_temp_c": temperature,
                "ghi_w_m2": round(ghi, 2),
                "energy_kwh_interval": energy_kwh,
                "expected_scenario": scenario,
            })

# Write CSV output
output_file = DATA_DIR / "solar_telemetry.csv"

fieldnames = [
    "timestamp",
    "site_id",
    "inverter_id",
    "ac_power_kw",
    "dc_voltage_v",
    "inverter_temp_c",
    "ghi_w_m2",
    "energy_kwh_interval",
    "expected_scenario",
]

with output_file.open("w", newline="", encoding="utf-8") as file:
    writer = csv.DictWriter(file, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(readings)

print("Solar telemetry data generated successfully.")
print(f"Output file: {output_file}")
print(f"Total readings: {len(readings)}")
