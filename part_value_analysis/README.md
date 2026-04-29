# Part Value Analysis (DB-Native)

This folder contains new scripts that:

- read part rows directly from the database,
- compute `value` and `deal_quality` (plus CPU status fields),
- write results back to the same database tables.

These scripts do **not** use CSV files.

## Scripts

- `cpu_value_analysis_db.py`
- `motherboard_value_analysis_db.py`
- `power_supply_value_analysis_db.py`
- `ram_value_analysis_db.py`
- `internal_hard_drive_analysis_db.py`
- `video_card_analysis_db.py`
- `run_all_value_analysis.py`

## Run from project root

```powershell
cd src/app
python ../../part_value_analysis/cpu_value_analysis_db.py
python ../../part_value_analysis/motherboard_value_analysis_db.py
python ../../part_value_analysis/power_supply_value_analysis_db.py
python ../../part_value_analysis/ram_value_analysis_db.py
python ../../part_value_analysis/internal_hard_drive_analysis_db.py
python ../../part_value_analysis/video_card_analysis_db.py
```

Or run all:

```powershell
cd src/app
python ../../part_value_analysis/run_all_value_analysis.py
```

## Notes

- Existing scripts in `part_memory_analysis` are unchanged.
- If analysis columns are missing, these scripts create them automatically.
