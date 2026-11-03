"""Run full FillCam T01-T20 dataset generation and inspection in ONE Isaac Sim session.
 
Run on GB10:
  cd ~/csi_digital_twin_v1
  ~/isaacsim/python.sh tools/run_all_tests.py
"""
import argparse
import csv
import json
import traceback
from pathlib import Path
import cv2
import numpy as np
 
ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--stage', default='stations/fill_station/fill_station.usda')
parser.add_argument('--camera', default='FillCam', choices=('FillCam',))
parser.add_argument('--frame', type=int, default=686, help='Fill-station time code: 1..686')
parser.add_argument('--out-dir', default='outputs/synthetic_dataset')
parser.add_argument('--subframes', type=int, default=8)
parser.add_argument('--warmup', type=int, default=4)
args = parser.parse_args()
 
stage_path = (ROOT / args.stage).resolve()
out_dir = (ROOT / args.out_dir).resolve()
image_dir = out_dir / 'images'
image_dir.mkdir(parents=True, exist_ok=True)
 
cam = json.loads((ROOT / 'cameras' / f'{args.camera}.json').read_text())
width, height = cam['render_px']
 
TEST_CASES = [
    ("T01", "correct_recipe_blue_baseline", (0.006, 0.200, 0.300), "GENERATED", "Correct Recipe", "Nominal blue liquid"),
    ("T02", "correct_recipe_teal_variant", (0.008, 0.270, 0.240), "GENERATED", "Correct Recipe", "Nominal teal formulation"),
    ("T03", "carryover_darker_blue", (0.004, 0.090, 0.170), "GENERATED", "Carryover", "Residual dark blue contamination"),
    ("T04", "carryover_lighter_blue", (0.060, 0.300, 0.390), "GENERATED", "Carryover", "Diluted prior batch contamination"),
    ("T05", "mixing_error_green", (0.020, 0.350, 0.050), "GENERATED", "Mixing Error", "Off-target green ratio"),
    ("T06", "mixing_error_red", (0.350, 0.025, 0.020), "GENERATED", "Mixing Error", "Incorrect red active dye component"),
    ("T07", "mixing_error_purple", (0.180, 0.025, 0.280), "GENERATED", "Mixing Error", "High purple active concentrate"),
    ("T08", "mixing_error_yellow", (0.380, 0.320, 0.025), "GENERATED", "Mixing Error", "Yellow precursor overflow"),
    ("T09", "cam_lighting_glare_reflection", (0.006, 0.200, 0.300), "BLOCKED", "Camera/Lighting", "Requires specular HDR light mesh in USD"),
    ("T10", "cam_lighting_dim_exposure", (0.003, 0.100, 0.150), "GENERATED", "Camera/Lighting", "Dim lighting simulation via shader attenuation"),
    ("T11", "fill_level_overfill", (0.006, 0.200, 0.300), "BLOCKED", "Fill Level", "Requires geometry mesh scale modification"),
    ("T12", "fill_level_underfill", (0.006, 0.200, 0.300), "BLOCKED", "Fill Level", "Requires geometry mesh scale modification"),
    ("T13", "fill_level_empty_vial", (0.000, 0.000, 0.000), "NOT YET GENERATED", "Fill Level", "Requires clearing fluid geometry entirely"),
    ("T14", "obstruction_nozzle_in_frame", (0.006, 0.200, 0.300), "BLOCKED", "Obstruction", "Requires mechanical arm CAD prim inserted"),
    ("T15", "obstruction_condensation_droplets", (0.006, 0.200, 0.300), "BLOCKED", "Obstruction", "Requires surface normal map modification"),
    ("T16", "missing_vial_off_station", (0.000, 0.000, 0.000), "NOT YET GENERATED", "Missing Vial", "Requires toggling vial visibility prim"),
    ("T17", "low_contrast_translucent", (0.001, 0.010, 0.015), "GENERATED", "Low Contrast", "Near-transparent low attenuation shader"),
    ("T18", "low_contrast_milky_opaque", (0.200, 0.200, 0.200), "GENERATED", "Low Contrast", "Low delta RGB against vial background"),
    ("T19", "fluid_physics_sloshing", (0.006, 0.200, 0.300), "BLOCKED", "Fluid Physics", "Not modeled in USD material editor"),
    ("T20", "proven_factory_defect_bubble", (0.006, 0.200, 0.300), "BLOCKED", "Factory Defect", "Requires volumetric defect mesh modeling")
]
 
from isaacsim import SimulationApp
kit = SimulationApp({'headless': True, 'renderer': 'PathTracing', 'width': width, 'height': height})
 
try:
    from isaacsim.core.utils.extensions import enable_extension
    enable_extension('omni.replicator.core')
    import omni.usd
    import omni.timeline
    import omni.replicator.core as rep
    from pxr import Gf, UsdGeom, UsdShade
 
    ctx = omni.usd.get_context()
    if not ctx.open_stage(str(stage_path)):
        raise RuntimeError(f'Could not open {stage_path}')
    while ctx.get_stage_loading_status()[2] > 0:
        kit.update()
 
    stage = ctx.get_stage()
    camera_path = next((p for p in (cam['prim_in_csi_line'], cam['prim_in_station_file'])
                        if stage.GetPrimAtPath(p).IsValid()), None)
    if camera_path is None:
        raise RuntimeError('FillCam camera prim not found in stage')
 
    shader_path = '/FillStation/_materials/USD_blue_liquid_approximation/Principled_BSDF'
    shader_prim = stage.GetPrimAtPath(shader_path)
    shader = UsdShade.Shader(shader_prim)
    color_input = shader.GetInput('diffuseColor')
 
    timeline = omni.timeline.get_timeline_interface()
    timeline.set_current_time(args.frame / stage.GetTimeCodesPerSecond())
    kit.update()
 
    product = rep.create.render_product(camera_path, (width, height))
    annotator = rep.AnnotatorRegistry.get_annotator('rgb')
    annotator.attach([product])
    rep.orchestrator.set_capture_on_play(False)
    kit.update()
 
    records = []
    baseline_image = None
 
    print("=== STARTING RENDER PASS ===", flush=True)
    for case_id, variant, rgb, status, category, notes in TEST_CASES:
        if status != "GENERATED":
            print(f"[{case_id}] SKIPPED ({status}): {notes}", flush=True)
            records.append({
                'test_case': case_id,
                'image_file': 'N/A',
                'variant': variant,
                'status': status,
                'category': category,
                'shader_r': rgb[0], 'shader_g': rgb[1], 'shader_b': rgb[2],
                'pixel_mean_abs_difference_from_baseline': 'N/A',
                'notes': notes
            })
            continue
 
        print(f'[{case_id}] Rendering {variant}: {rgb}', flush=True)
        color_input.Set(Gf.Vec3f(*rgb))
        timeline.set_current_time(args.frame / stage.GetTimeCodesPerSecond())
        for _ in range(args.warmup):
            kit.update()
        for _ in range(2):
            rep.orchestrator.step(rt_subframes=args.subframes, delta_time=0.0)
 
        pixels = np.asarray(annotator.get_data())
        bgr = pixels[..., :3][..., ::-1].copy()
        filename = f'vial_{case_id}_{variant}.png'
        path = image_dir / filename
        cv2.imwrite(str(path), bgr)
 
        diff = 0.0 if baseline_image is None else float(np.mean(np.abs(bgr.astype(np.int16) - baseline_image.astype(np.int16))))
        if baseline_image is None:
            baseline_image = bgr.copy()
 
        records.append({
            'test_case': case_id,
            'image_file': f'images/{filename}',
            'variant': variant,
            'status': status,
            'category': category,
            'shader_r': rgb[0], 'shader_g': rgb[1], 'shader_b': rgb[2],
            'pixel_mean_abs_difference_from_baseline': f'{diff:.3f}',
            'notes': notes
        })
 
    metadata_path = out_dir / 'metadata.csv'
    with metadata_path.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
 
    print("=== STARTING OPENCV INSPECTION PASS ===", flush=True)
    inspection_results = []
    with metadata_path.open('r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            case_id = row['test_case']
            status = row['status']
            image_file = row['image_file']
 
            result_row = {
                'test_case': case_id,
                'variant': row['variant'],
                'status': status,
                'image_quality_outcome': 'PASS' if status == 'GENERATED' else 'BLOCKED_OR_SKIPPED',
                'low_contrast_flag': False,
                'vial_off_station_flag': False,
                'mean_r': 'N/A', 'mean_g': 'N/A', 'mean_b': 'N/A',
                'mean_l': 'N/A', 'mean_a': 'N/A', 'mean_b_lab': 'N/A',
                'color_measurement_valid': False,
                'notes': row['notes']
            }
 
            if status != 'GENERATED' or image_file == 'N/A':
                inspection_results.append(result_row)
                continue
 
            img_path = ROOT / image_file
            if not img_path.is_file():
                result_row['image_quality_outcome'] = 'FILE_MISSING'
                inspection_results.append(result_row)
                continue
 
            bgr_img = cv2.imread(str(img_path))
            if bgr_img is None:
                result_row['image_quality_outcome'] = 'READ_ERROR'
                inspection_results.append(result_row)
                continue
 
            gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
            contrast = gray.std()
            is_low_contrast = contrast < 15.0
            result_row['low_contrast_flag'] = is_low_contrast
            if is_low_contrast:
                result_row['image_quality_outcome'] = 'FLAG_LOW_CONTRAST'
 
            lab = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2Lab)
            mean_bgr = bgr_img.mean(axis=(0, 1))
            mean_lab = lab.mean(axis=(0, 1))
 
            result_row['mean_r'] = f"{mean_bgr[2]:.2f}"
            result_row['mean_g'] = f"{mean_bgr[1]:.2f}"
            result_row['mean_b'] = f"{mean_bgr[0]:.2f}"
            result_row['mean_l'] = f"{mean_lab[0]:.2f}"
            result_row['mean_a'] = f"{mean_lab[1]:.2f}"
            result_row['mean_b_lab'] = f"{mean_lab[2]:.2f}"
            result_row['color_measurement_valid'] = not is_low_contrast
 
            inspection_results.append(result_row)
            print(f"Inspected {case_id}: Contrast={contrast:.2f}, Valid={result_row['color_measurement_valid']}", flush=True)
 
    results_path = out_dir / 'inspection_results.csv'
    with results_path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(inspection_results[0].keys()))
        writer.writeheader()
        writer.writerows(inspection_results)
 
    print(f'DONE: All renders and inspection results saved to {out_dir}', flush=True)
 
except BaseException:
    traceback.print_exc()
    kit.close(exit_code=1)
    raise
kit.close()