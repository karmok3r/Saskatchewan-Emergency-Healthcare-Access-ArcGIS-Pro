"""Run the full pipeline in order (about 20 minutes; ArcGIS Pro must be closed)."""
import runpy
from pathlib import Path

HERE = Path(__file__).parent
STEPS = ["01_download_data.py", "02_prepare_data.py", "03_build_network.py",
         "04_access_analysis.py", "05_hotspots_equity.py", "06_location_allocation.py",
         "07_make_maps.py"]

if __name__ == "__main__":
    for step in STEPS:
        print(f"\n=== {step} ===")
        runpy.run_path(str(HERE / step), run_name="__main__")
