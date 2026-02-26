"""
setup_scheduler.py
==================
Run this ONCE to register the spider as a Windows Task Scheduler job.
After that, Windows will run it automatically on your chosen schedule.

Usage:
    python setup_scheduler.py

Requirements:
    - Run as Administrator (right-click → Run as administrator)
    - Python and Scrapy must be installed
"""

import subprocess
import sys
import os
from pathlib import Path


# ============================================================
# CONFIGURE YOUR SCHEDULE HERE
# ============================================================

# How often to run
SCHEDULE = "DAILY"       # Options: DAILY, WEEKLY, MONTHLY

# What time to run (24-hour format)
START_TIME = "09:00"

# For WEEKLY only — which day (MON, TUE, WED, THU, FRI, SAT, SUN)
WEEKLY_DAY = "MON"

# For MONTHLY only — which day of the month (1-28)
MONTHLY_DAY = 1

# Task name (shows up in Task Scheduler)
TASK_NAME = "NeweggPriceHistoryScraper"


def get_paths():
    """Auto-detect Python and project paths."""
    python_path  = sys.executable
    project_dir  = Path(__file__).parent.resolve()
    scrapy_path  = Path(python_path).parent / "Scripts" / "scrapy.exe"

    if not scrapy_path.exists():
        # Try conda or other layouts
        scrapy_path = Path(python_path).parent / "scrapy.exe"

    if not scrapy_path.exists():
        print("⚠ Could not find scrapy.exe automatically.")
        print("  Find it manually with: where scrapy")
        scrapy_path = input("  Enter full path to scrapy.exe: ").strip()

    return str(python_path), str(project_dir), str(scrapy_path)


def create_runner_bat(project_dir, scrapy_path):
    """
    Create a .bat file that Task Scheduler will call.
    This is more reliable than calling scrapy directly from the scheduler
    because it sets the working directory correctly first.
    """
    bat_path = Path(project_dir) / "run_spider.bat"
    bat_content = f"""@echo off
cd /d "{project_dir}"
"{scrapy_path}" crawl wayback_newegg >> "{project_dir}\\spider_log.txt" 2>&1
"""
    with open(bat_path, "w") as f:
        f.write(bat_content)

    print(f"✓ Created runner: {bat_path}")
    return str(bat_path)


def register_task(bat_path):
    """Register the task with Windows Task Scheduler using schtasks."""

    # Build the schedule part of the command
    if SCHEDULE == "DAILY":
        schedule_args = ["/SC", "DAILY", "/ST", START_TIME]
    elif SCHEDULE == "WEEKLY":
        schedule_args = ["/SC", "WEEKLY", "/D", WEEKLY_DAY, "/ST", START_TIME]
    elif SCHEDULE == "MONTHLY":
        schedule_args = ["/SC", "MONTHLY", "/D", str(MONTHLY_DAY), "/ST", START_TIME]
    else:
        print(f"⚠ Unknown schedule '{SCHEDULE}', defaulting to DAILY")
        schedule_args = ["/SC", "DAILY", "/ST", START_TIME]

    cmd = [
        "schtasks", "/Create",
        "/TN",  TASK_NAME,
        "/TR",  f'"{bat_path}"',
        "/RU",  "SYSTEM",           # Run as SYSTEM so it works even when logged out
        "/RL",  "HIGHEST",          # Highest privileges
        "/F",                       # Force overwrite if task already exists
    ] + schedule_args

    print(f"\nRegistering Task Scheduler job: {TASK_NAME}")
    print(f"  Schedule  : {SCHEDULE} at {START_TIME}")
    print(f"  Runner    : {bat_path}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"\n✓ Task '{TASK_NAME}' registered successfully!")
        print(f"  You can view/edit it in Task Scheduler (taskschd.msc)")
    else:
        print(f"\n✗ Failed to register task:")
        print(f"  {result.stderr.strip()}")
        print("\n  Make sure you're running this script as Administrator.")
        print("  Right-click setup_scheduler.py → Run as administrator")


def remove_task():
    """Helper to remove the task if you want to stop automation."""
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"✓ Task '{TASK_NAME}' removed.")
    else:
        print(f"✗ Could not remove task: {result.stderr.strip()}")


def check_existing_task():
    """Check if the task is already registered."""
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True, text=True
    )
    return result.returncode == 0


if __name__ == "__main__":
    print("Newegg Price Tracker — Windows Task Scheduler Setup")
    print("=" * 52)

    # Check for existing task
    if check_existing_task():
        print(f"\n⚠ Task '{TASK_NAME}' already exists.")
        choice = input("  Overwrite it? (y/n): ").strip().lower()
        if choice != "y":
            print("Aborted.")
            sys.exit(0)

    python_path, project_dir, scrapy_path = get_paths()

    print(f"\nDetected paths:")
    print(f"  Python  : {python_path}")
    print(f"  Project : {project_dir}")
    print(f"  Scrapy  : {scrapy_path}")

    bat_path = create_runner_bat(project_dir, scrapy_path)
    register_task(bat_path)

    print(f"""
Next steps:
  1. Open Task Scheduler (press Win+R, type taskschd.msc)
  2. Find "{TASK_NAME}" under Task Scheduler Library
  3. Right-click → Run to test it immediately
  4. Check spider_log.txt in your project folder for output

To remove the schedule later:
  python setup_scheduler.py --remove
""")

    # Handle --remove flag
    if "--remove" in sys.argv:
        remove_task()
