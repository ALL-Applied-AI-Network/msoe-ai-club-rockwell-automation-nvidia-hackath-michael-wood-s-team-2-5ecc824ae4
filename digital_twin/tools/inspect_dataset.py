"""Inspect rendered FillCam dataset images using OpenCV and compute color/quality metrics.

Run on GB10:
  cd ~/csi_digital_twin_v1
  ~/isaacsim/python.sh tools/inspect_dataset.py
"""
import csv
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
out_dir = ROOT / 'outputs' / 'synthetic_dataset'
image_dir = out_dir / 'images'
metadata_path = out_dir / 'metadata.csv'
results_path = out_dir / 'inspection_results.csv'

if not metadata_path.is_file():
    raise FileNotFoundError(f"Metadata file not found: {metadata_path}")

results = []

print(f"Reading metadata from {metadata_path}...", flush=True)
with metadata_path.open('r', newline='') as f:
    reader = csv.DictReader(f)
    for row in reader:
        case_id = row['test_case']
        status = row['status']
        image_file = row['image_file']

        # Default metrics for skipped/blocked cases
        result_row = {
            'test_case': case_id,
            'variant': row['variant'],
            'status': status,
            'image_quality_outcome': 'PASS' if status == 'GENERATED' else 'BLOCKED_OR_SKIPPED',
            'low_contrast_flag': False,
            'vial_off_station_flag': False,
            'mean_r': 'N/A',
            'mean_g': 'N/A',
            'mean_b': 'N/A',
            'mean_l': 'N/A',
            'mean_a': 'N/A',
            'mean_b_lab': 'N/A',
            'color_measurement_valid': False,
            'notes': row['notes']
        }

        if status != 'GENERATED' or image_file == 'N/A':
            results.append(result_row)
            continue

        img_path = ROOT / image_file
        if not img_path.is_file():
            result_row['image_quality_outcome'] = 'FILE_MISSING'
            results.append(result_row)
            continue

        # Load image with OpenCV (BGR format)
        bgr = cv2.imread(str(img_path))
        if bgr is None:
            result_row['image_quality_outcome'] = 'READ_ERROR'
            results.append(result_row)
            continue

        # Basic image checks
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        contrast = gray.std()
        
        # Track low contrast separately from valid color mismatch decisions
        is_low_contrast = contrast < 15.0
        result_row['low_contrast_flag'] = is_low_contrast

        if is_low_contrast:
            result_row['image_quality_outcome'] = 'FLAG_LOW_CONTRAST'

        # Convert to Lab for color measurement
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab)
        mean_bgr = bgr.mean(axis=(0, 1))
        mean_lab = lab.mean(axis=(0, 1))

        result_row['mean_r'] = f"{mean_bgr[2]:.2f}"
        result_row['mean_g'] = f"{mean_bgr[1]:.2f}"
        result_row['mean_b'] = f"{mean_bgr[0]:.2f}"
        result_row['mean_l'] = f"{mean_lab[0]:.2f}"
        result_row['mean_a'] = f"{mean_lab[1]:.2f}"
        result_row['mean_b_lab'] = f"{mean_lab[2]:.2f}"
        result_row['color_measurement_valid'] = not is_low_contrast

        results.append(result_row)
        print(f"Inspected {case_id} ({row['variant']}): Contrast={contrast:.2f}, Valid={result_row['color_measurement_valid']}", flush=True)

# Write out inspection results
with results_path.open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
    writer.writeheader()
    writer.writerows(results)

print(f"\nDONE: Inspection results saved to {results_path}", flush=True)
