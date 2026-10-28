# ProcessDNA — Digital Twin

This folder contains Python scripts and example outputs for synthetic
image generation using NVIDIA Isaac Sim 6.0.

## Project Goal

Generate synthetic images from the CSI vial-filling station to help
evaluate the ProcessDNA color-measurement and anomaly-detection pipeline.

## Completed Work

- Headless Isaac Sim rendering on NVIDIA GB10
- FillCam image and video generation
- Eight liquid-color variations
- Fifteen visual carryover-proxy images
- CSV metadata documenting simulated parameters
- Initial integration with the team's CV color-measurement script

## Files

### tools/
- `generate_dataset.py`: Generates eight liquid-color variations.
- `generate_carryover_dataset.py`: Generates fifteen visual
  carryover-proxy images.
- `render_video.py`: Renders an animation of the filling station.

### examples/
Contains representative FillCam images.

### data/
Contains metadata from the generated datasets.

The CSV files may reference images not included in this repository.

## Requirements

- NVIDIA Isaac Sim 6.0
- NVIDIA GPU compatible with Isaac Sim
- CSI digital twin assets, including the filling station USD scene
- FillCam camera configuration

The CSI source assets are not included in this folder.

## Running on the GB10

The scripts were developed and tested inside the original CSI
digital twin directory:

    ~/csi_digital_twin_v1/

Place the generator scripts inside that project's tools/ folder,
alongside its stations/ and cameras/ directories.

Then run:

    cd ~/csi_digital_twin_v1

    ~/isaacsim/python.sh tools/generate_dataset.py

    ~/isaacsim/python.sh tools/generate_carryover_dataset.py

The generators save PNG files and metadata CSVs under outputs/.

The repository copies are not standalone: the generators resolve
their source USD and camera files relative to their parent project.

## Important Limitations

The current carryover dataset is a visual approximation created
by interpolating liquid material shader colors.

It does not simulate physical fluid mixing or validated residue
concentrations.

The shared liquid material may affect multiple vials.

Factory PASS/FAIL decisions and root-cause diagnosis are not yet
validated by these datasets.

## Next Steps

1. Integrate real recipe and optical mixing information.
2. Model first-vial-specific carryover.
3. Expand lighting, fill-level, and camera variations.
4. Deliver generated datasets to the validation team.
5. Support end-to-end integration with ProcessDNA.

See docs/digital_twin_progress_2026-10-28.md in the repository
for the complete progress report.
