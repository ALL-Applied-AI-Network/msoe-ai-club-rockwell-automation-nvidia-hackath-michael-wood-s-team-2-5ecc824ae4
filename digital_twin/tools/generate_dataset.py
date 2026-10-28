"""Generate a small, labeled FillCam color-variation dataset in ONE Isaac Sim session.

Run on the GB10:
  cd ~/csi_digital_twin_v1
  ~/isaacsim/python.sh tools/generate_dataset.py

Requires the existing CSI twin, Isaac Sim 6.0, and camera JSON. These images
vary a USD material for CV integration testing; they do NOT simulate fluid
physics, physically modeled color mixing, or proven factory defects.
"""
import argparse
import csv
import json
import os
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--stage', default='stations/fill_station/fill_station.usda')
parser.add_argument('--camera', default='FillCam', choices=('FillCam',))
parser.add_argument('--frame', type=int, default=686, help='Fill-station time code: 1..686')
parser.add_argument('--out-dir', default='outputs/synthetic_dataset')
parser.add_argument('--subframes', type=int, default=8, help='Path tracing subframes per capture')
parser.add_argument('--warmup', type=int, default=4, help='Updates after material edit')
args = parser.parse_args()
if not (1 <= args.frame <= 686) or args.subframes < 1 or args.warmup < 1:
    parser.error('frame must be 1..686; subframes/warmup must be positive')

stage_path = Path(args.stage).expanduser()
if not stage_path.is_absolute():
    stage_path = ROOT / stage_path
stage_path = stage_path.resolve()
if not stage_path.is_file():
    parser.error(f'USD stage does not exist: {stage_path}')

out_dir = Path(args.out_dir).expanduser()
if not out_dir.is_absolute():
    out_dir = ROOT / out_dir
out_dir = out_dir.resolve()
image_dir = out_dir / 'images'
image_dir.mkdir(parents=True, exist_ok=True)

cam = json.loads((ROOT / 'cameras' / f'{args.camera}.json').read_text())
width, height = cam['render_px']

# All shader values are 0..1. Controlled synthetic appearance changes only.
# Blue matches the nominal blue shader seen in the CSI twin.
variants = [
    ('blue_baseline',       (0.006, 0.200, 0.300)),
    ('blue_darker',         (0.004, 0.090, 0.170)),
    ('blue_lighter',        (0.060, 0.300, 0.390)),
    ('teal_variant',        (0.008, 0.270, 0.240)),
    ('green_variant',       (0.020, 0.350, 0.050)),
    ('red_variant',         (0.350, 0.025, 0.020)),
    ('purple_variant',      (0.180, 0.025, 0.280)),
    ('yellow_variant',      (0.380, 0.320, 0.025)),
]

from isaacsim import SimulationApp
kit = SimulationApp({'headless': True, 'renderer': 'PathTracing', 'width': width, 'height': height})
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
    shader = UsdShade.Shader(shader_prim)
    color_input = shader.GetInput('diffuseColor')
    if not color_input:
        raise RuntimeError(f'Liquid shader has no inputs:diffuseColor: {shader_path}')
    original_color = color_input.Get()
    print(f'Original liquid diffuseColor: {original_color}', flush=True)

    timeline = omni.timeline.get_timeline_interface()
    timeline.set_current_time(args.frame / stage.GetTimeCodesPerSecond())
    kit.update()

    product = rep.create.render_product(camera_path, (width, height))
    annotator = rep.AnnotatorRegistry.get_annotator('rgb')
    annotator.attach([product])
    rep.orchestrator.set_capture_on_play(False)
    kit.update()

    # Match the camera clipping-range workaround in the known-working renderer.
    clip = UsdGeom.Camera(stage.GetPrimAtPath(camera_path)).GetClippingRangeAttr()
    old_range = clip.Get()
    stage.SetEditTarget(stage.GetSessionLayer())
    clip.Set(Gf.Vec2f(old_range[0] * 0.5, old_range[1]))
    kit.update()
    clip.Set(old_range)
    kit.update()

    records = []
    baseline_image = None
    for idx, (variant, rgb) in enumerate(variants):
        print(f'[{idx + 1}/{len(variants)}] Rendering {variant}: {rgb}', flush=True)
        # Apply only to the USD session layer; no source asset changes.
        color_input.Set(Gf.Vec3f(*rgb))
        timeline.set_current_time(args.frame / stage.GetTimeCodesPerSecond())
        for _ in range(args.warmup):
            kit.update()
        for _ in range(2):
            rep.orchestrator.step(rt_subframes=args.subframes, delta_time=0.0)
        pixels = np.asarray(annotator.get_data())
        if pixels.ndim != 3 or pixels.shape[:2] != (height, width) or pixels.shape[2] < 3:
            raise RuntimeError(f'Unexpected annotator image shape: {pixels.shape}')
        bgr = pixels[..., :3][..., ::-1].copy()
        name = f'vial_{idx:03d}_{variant}.png'
        path = image_dir / name
        if not cv2.imwrite(str(path), bgr):
            raise OSError(f'Could not save image: {path}')
        difference = 0.0 if baseline_image is None else float(np.mean(
            np.abs(bgr.astype(np.int16) - baseline_image.astype(np.int16))))
        if baseline_image is None:
            baseline_image = bgr.copy()
        records.append({
            'image_file': f'images/{name}',
            'variant': variant,
            'camera': args.camera,
            'usd_frame': args.frame,
            'shader_r': rgb[0],
            'shader_g': rgb[1],
            'shader_b': rgb[2],
            'pixel_mean_abs_difference_from_baseline': f'{difference:.3f}',
            'simulated_defect': 'not_modeled',
            'recipe_id': 'not_available',
            'expected_pass_fail': 'not_labeled',
        })
        print(f'  wrote {path.name}; full-image difference from blue baseline: {difference:.3f}', flush=True)

    csv_path = out_dir / 'metadata.csv'
    with csv_path.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print(f'DONE: {len(records)} images and metadata at {out_dir}', flush=True)
    print('NOTE: Shader colors are not recipe/mixing ground truth or factory defect labels.', flush=True)
except BaseException:
    traceback.print_exc()
    kit.close(exit_code=1)
    raise
kit.close()
