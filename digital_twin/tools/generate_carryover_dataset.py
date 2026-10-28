"""Generate labeled *visual proxy* carryover images from the CSI FillCam twin.

Run on GB10:
  cd ~/csi_digital_twin_v1
  ~/isaacsim/python.sh tools/generate_carryover_dataset.py

Optional:
  ~/isaacsim/python.sh tools/generate_carryover_dataset.py --subframes 8 --out-dir outputs/carryover_dataset

IMPORTANT: The previous/new recipe colors below are illustrative USD SHADER colors.
The interpolation is NOT an optical mixing model, fluid simulation, or validated
factory carryover percentage. Because this script changes a shared material, it
may recolor all meshes referencing it, not solely the first post-change vial.
Do not treat these images as factory-defect ground truth or PASS/FAIL labels.
"""
import argparse
import csv
import json
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--stage', default='stations/fill_station/fill_station.usda')
parser.add_argument('--frame', type=int, default=686, help='Fill-station USD time code, 1..686')
parser.add_argument('--out-dir', default='outputs/carryover_dataset')
parser.add_argument('--subframes', type=int, default=8)
parser.add_argument('--warmup', type=int, default=4)
args = parser.parse_args()
if not 1 <= args.frame <= 686 or args.subframes < 1 or args.warmup < 1:
    parser.error('frame must be 1..686 and subframes/warmup must be positive')

stage_path = Path(args.stage).expanduser()
if not stage_path.is_absolute():
    stage_path = ROOT / stage_path
stage_path = stage_path.resolve()
if not stage_path.is_file():
    parser.error(f'USD stage not found: {stage_path}')

out_dir = Path(args.out_dir).expanduser()
if not out_dir.is_absolute():
    out_dir = ROOT / out_dir
out_dir = out_dir.resolve()
image_dir = out_dir / 'images'
image_dir.mkdir(parents=True, exist_ok=True)

cam = json.loads((ROOT / 'cameras' / 'FillCam.json').read_text())
width, height = cam['render_px']

# Illustrative shader settings: these are not calibrated liquid colors.
recipe_shader_colors = {
    'blue': (0.006, 0.200, 0.300),  # original scene's approximate blue
    'green': (0.020, 0.350, 0.050),
    'red': (0.350, 0.025, 0.020),
}
transitions = [('blue', 'green'), ('green', 'red'), ('red', 'blue')]
residue_levels = (0.00, 0.01, 0.05, 0.10, 0.20)

from isaacsim import SimulationApp
kit = SimulationApp({'headless': True, 'renderer': 'PathTracing',
                     'width': width, 'height': height})
try:
    from isaacsim.core.utils.extensions import enable_extension
    enable_extension('omni.replicator.core')
    import cv2
    import numpy as np
    import omni.usd
    import omni.timeline
    import omni.replicator.core as rep
    from pxr import Gf, UsdGeom, UsdShade

    ctx = omni.usd.get_context()
    if not ctx.open_stage(str(stage_path)):
        raise RuntimeError(f'Could not open {stage_path}')
    while ctx.get_stage_loading_status()[2] > 0:
        kit.update()
    for _ in range(10):
        kit.update()
    stage = ctx.get_stage()

    camera_path = next((p for p in (cam['prim_in_csi_line'], cam['prim_in_station_file'])
                        if stage.GetPrimAtPath(p).IsValid()), None)
    if camera_path is None:
        raise RuntimeError('FillCam camera prim not found in stage')

    shader_path = '/FillStation/_materials/USD_blue_liquid_approximation/Principled_BSDF'
    shader_prim = stage.GetPrimAtPath(shader_path)
    if not shader_prim.IsValid():
        raise RuntimeError(f'Liquid shader not found: {shader_path}')
    color_input = UsdShade.Shader(shader_prim).GetInput('diffuseColor')
    if not color_input:
        raise RuntimeError('Liquid shader lacks diffuseColor input')

    stage.SetEditTarget(stage.GetSessionLayer())  # Does not modify source USD files
    timeline = omni.timeline.get_timeline_interface()
    timeline.set_current_time(args.frame / stage.GetTimeCodesPerSecond())
    kit.update()

    product = rep.create.render_product(camera_path, (width, height))
    annotator = rep.AnnotatorRegistry.get_annotator('rgb')
    annotator.attach([product])
    rep.orchestrator.set_capture_on_play(False)
    kit.update()

    # Same clippingRange workaround as the known-working renderer.
    clip = UsdGeom.Camera(stage.GetPrimAtPath(camera_path)).GetClippingRangeAttr()
    old_range = clip.Get()
    clip.Set(Gf.Vec2f(old_range[0] * 0.5, old_range[1]))
    kit.update()
    clip.Set(old_range)
    kit.update()

    rows = []
    count = len(transitions) * len(residue_levels)
    index = 0
    for previous_recipe, new_recipe in transitions:
        previous_rgb = recipe_shader_colors[previous_recipe]
        target_rgb = recipe_shader_colors[new_recipe]
        for fraction in residue_levels:
            # This is linear interpolation of USD shader inputs, NOT physical mixing.
            shader_rgb = tuple((1 - fraction) * new + fraction * old
                               for old, new in zip(previous_rgb, target_rgb))
            name = (f'vial_{index:03d}_{previous_recipe}_to_{new_recipe}'
                    f'_residue_{round(fraction * 100):02d}pct.png')
            print(f'[{index + 1}/{count}] {previous_recipe} -> {new_recipe}, '
                  f'visual-proxy residue {fraction:.0%}', flush=True)
            color_input.Set(Gf.Vec3f(*shader_rgb))
            timeline.set_current_time(args.frame / stage.GetTimeCodesPerSecond())
            for _ in range(args.warmup):
                kit.update()
            for _ in range(2):
                rep.orchestrator.step(rt_subframes=args.subframes, delta_time=0.0)
            pixels = np.asarray(annotator.get_data())
            if pixels.ndim != 3 or pixels.shape[:2] != (height, width) or pixels.shape[2] < 3:
                raise RuntimeError(f'Unexpected RGB capture shape {pixels.shape}')
            bgr = pixels[..., :3][..., ::-1].copy()
            path = image_dir / name
            if not cv2.imwrite(str(path), bgr):
                raise OSError(f'Could not save {path}')
            rows.append({
                'image_file': f'images/{name}',
                'previous_recipe_proxy': previous_recipe,
                'target_recipe_proxy': new_recipe,
                'residue_fraction_proxy': f'{fraction:.3f}',
                'residue_percent_proxy': f'{fraction * 100:.1f}',
                'target_shader_r': f'{target_rgb[0]:.6f}',
                'target_shader_g': f'{target_rgb[1]:.6f}',
                'target_shader_b': f'{target_rgb[2]:.6f}',
                'render_shader_r': f'{shader_rgb[0]:.6f}',
                'render_shader_g': f'{shader_rgb[1]:.6f}',
                'render_shader_b': f'{shader_rgb[2]:.6f}',
                'scenario': 'visual_reference' if fraction == 0 else 'carryover_visual_proxy',
                'camera': 'FillCam',
                'usd_frame': args.frame,
                'mixing_method': 'linear_interpolation_of_shader_diffuseColor',
                'physical_mixing_validated': 'false',
                'real_factory_defect_label': 'not_available',
                'expected_pass_fail': 'not_labeled',
                'note': 'Shared material may recolor multiple vials',
            })
            print(f'  wrote {path.name}', flush=True)
            index += 1

    csv_path = out_dir / 'metadata.csv'
    with csv_path.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f'DONE: {len(rows)} images; metadata at {csv_path}', flush=True)
    print('IMPORTANT: Residue percentages are appearance interpolation parameters, '
          'not physical fluid carryover ground truth.', flush=True)
except BaseException:
    traceback.print_exc()
    kit.close(exit_code=1)
    raise
kit.close()
