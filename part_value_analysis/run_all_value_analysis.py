"""Run all part value analysis scripts against the database."""

from cpu_value_analysis_db import run_cpu_value_analysis
from motherboard_value_analysis_db import run_motherboard_value_analysis
from power_supply_value_analysis_db import run_power_supply_value_analysis
from ram_value_analysis_db import run_ram_value_analysis
from video_card_analysis_db import run_video_card_value_analysis


def run_all() -> None:
    run_cpu_value_analysis()
    print("CPU done")

    run_motherboard_value_analysis()
    print("Motherboard done")

    run_power_supply_value_analysis()
    print("Power supply done")

    run_ram_value_analysis()
    print("RAM done")

    run_video_card_value_analysis()
    print("Video card done")


if __name__ == "__main__":
    run_all()
    print("All part value analyses complete.")
