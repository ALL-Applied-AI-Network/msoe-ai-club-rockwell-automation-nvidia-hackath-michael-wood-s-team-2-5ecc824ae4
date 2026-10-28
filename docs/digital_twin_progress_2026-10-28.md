# Digital Twin Progress Report

**Project:** ProcessDNA for Fluid Mixing  
**Date:** October 28, 2026  
**Workstream:** Digital Twin and Synthetic Data Generation  
**Platform:** NVIDIA GB10 / Isaac Sim 6.0

## 1. Project Objective

Develop a digital twin of the CSI vial-filling line to generate synthetic camera images for testing ProcessDNA's computer-vision and anomaly-detection systems.

The main factory problem is potential liquid carryover when switching between recipes, which may affect the first vial of a new batch.

## 2. Completed Work

### Isaac Sim Setup
- Installed and configured Isaac Sim 6.0 on the MSOE GB10.
- Successfully operated Isaac Sim headlessly through SSH.
- Loaded the CSI filling-station USD scene.
- Configured FillCam rendering using the supplied camera configuration.
- Generated PNG images and an MP4 animation of the filling station.

### Synthetic Color Dataset
- Developed `generate_dataset.py`.
- Generated 8 liquid-color variations:
  - Blue baseline
  - Dark blue
  - Light blue
  - Teal
  - Green
  - Red
  - Purple
  - Yellow
- Recorded shader values and image metadata in CSV format.
- Used one Isaac Sim session to render multiple images.

### Computer Vision Integration
- Tested all 8 synthetic color images with the team's `measure_color.py` script.
- All 8 produced numeric RGB measurements using a manually selected ROI.
- Confirmed that the measured colors vary as expected.

This verifies basic color-measurement integration, not automatic defect detection.

### Carryover Dataset
- Developed `generate_carryover_dataset.py`.
- Generated 15 images representing three recipe transitions:
  - Blue to Green
  - Green to Red
  - Red to Blue
- Tested visual carryover fractions of 0%, 1%, 5%, 10%, and 20%.
- Verified that all 15 PNG files were created.
- Generated `metadata.csv` with simulated material parameters.

## 3. Important Limitations

The carryover dataset currently uses linear interpolation of material shader colors.

It does not yet represent physically validated fluid mixing or actual residue concentrations.

The shared liquid material may affect multiple vials rather than only the first vial following a recipe change.

Factory PASS/FAIL labels and automatic root-cause diagnosis have not yet been validated.

## 4. Files Added to GitHub

### Python Scripts
- `digital_twin/tools/generate_dataset.py`
- `digital_twin/tools/generate_carryover_dataset.py`
- `digital_twin/tools/render_video.py`

### Example Images
- `digital_twin/examples/fillcam_686.png`
- `digital_twin/examples/green_vial.png`

### Dataset Metadata
- `digital_twin/data/synthetic_metadata.csv`
- `digital_twin/data/carryover_metadata.csv`

## 5. Next Steps

1. Connect the digital twin to the team's actual recipe and optical mixing model.
2. Simulate carryover affecting the first vial after a recipe change.
3. Expand synthetic data to additional lighting, fill levels, and recipes.
4. Deliver the datasets and metadata to the validation teammate.
5. Support integration with the CV and ProcessDNA detection pipeline.
6. Document reproduction instructions and approved CSI assets.

## 6. Current Status

**Completed:** Headless rendering, video generation, 8 color variations, 15 carryover-proxy images, metadata generation, initial RGB measurement integration.

**Remaining:** Physically validated mixing, first-vial-specific contamination, automated defect detection, and end-to-end factory-error validation.
