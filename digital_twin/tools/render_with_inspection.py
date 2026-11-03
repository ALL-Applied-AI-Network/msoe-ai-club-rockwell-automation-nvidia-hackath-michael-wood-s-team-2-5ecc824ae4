"""Synchronized Isaac Sim FillCam inspection, not video post-processing.

GB10 examples:
  ~/isaacsim/python.sh tools/render_with_inspection.py --start 350 --end 360 --mode roi
  ~/isaacsim/python.sh tools/render_with_inspection.py --start 350 --end 360 --mode team-cv --cv-root ~/MAIC-color-measurement --roi 290 290 35 55
  ~/isaacsim/python.sh tools/render_with_inspection.py --start 350 --end 360 --mode team-cv --cv-root ~/MAIC-color-measurement  # auto ROI, only if FillCam config works

Synthetic scene shader is NOT per-vial physical mixing ground truth.
Output contains raw frames, per-frame JSONL, CSV, and a run manifest.
"""
import argparse
import csv
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHADER_PATH = '/FillStation/_materials/USD_blue_liquid_approximation/Principled_BSDF'


def file_path(value):
    p = Path(value).expanduser()
    return p if p.is_absolute() else ROOT / p


def as_rgb(value):
    if value is None:
        return None
    try:
        return [round(float(v), 6) for v in value]
    except (ValueError, TypeError):
        return None


def basic_roi_measure(bgr, roi):
    """Measured patch color, NOT automatic vial detection or fill estimation."""
    import cv2
    import numpy as np
    x, y, w, h = roi
    height, width = bgr.shape[:2]
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        return {
            'mode': 'fixed_roi_measurement', 'quality': {'ok': False, 'code': 'invalid_roi'},
            'roi_xywh': list(roi), 'rgb_mean': None, 'lab_of_mean_rgb': None,
            'pixel_count': 0,
        }
    crop = bgr[y:y+h, x:x+w, :3]
    mean_rgb = crop[..., ::-1].mean(axis=(0, 1)).astype(float)
    lab = cv2.cvtColor(np.float32([[mean_rgb / 255.0]]), cv2.COLOR_RGB2Lab)[0, 0]
    return {
        'mode': 'fixed_roi_measurement',
        'vial_detected': None,
        'liquid_present': None,
        'quality': {'ok': True, 'code': None, 'meaning': 'ROI pixels are readable; NOT a vial/liquid detection result'},
        'roi_xywh': list(roi),
        'pixel_count': int(w * h),
        'rgb_mean': [round(float(a), 3) for a in mean_rgb],
        'lab_of_mean_rgb': [round(float(a), 3) for a in lab],
        'limitations': 'Patch measurement only; no vial detection, liquid segmentation, or validated fill level.',
    }


def team_cv_measure(bgr, roi, image_name):
    from vialcv.detect import detect_vial_color
    return detect_vial_color(
        bgr,
        camera_id='FillCam',
        roi=tuple(roi) if roi else None,
        white_balance_method='none',
        reference_bgr=None,
        image_ref=image_name,
        source_data_origin='digital_twin',
    )


def report_fields(record):
    """Flatten a small subset of the detailed CV/ROI record for CSV."""
    result = record.get('inspection', {})
    quality = result.get('quality') or {}
    rgb, lab = None, None
    if result.get('mode') == 'fixed_roi_measurement':
        rgb = result.get('rgb_mean')
        lab = result.get('lab_of_mean_rgb')
    else:
        primary = (result.get('color') or {}).get('primary') or {}
        if primary:
            rgb = (primary.get('rgb_0_255') or {}).get('median')
            lab_dict = (primary.get('lab') or {}).get('median') or {}
            if all(k in lab_dict for k in ('L', 'a', 'b')):
                lab = [lab_dict['L'], lab_dict['a'], lab_dict['b']]
    shader = record.get('scene_shader_rgb')
    row = {
        'frame': record['frame'], 'sim_time_s': record['sim_time_s'],
        'image_file': record['image_file'], 'data_origin': 'digital_twin',
        'inspection_mode': record['inspection_mode'],
        'roi_xywh': json.dumps(result.get('roi_xywh')),
        'quality_ok': quality.get('ok', False),
        'quality_code': quality.get('code') or '',
        'rgb_r': None, 'rgb_g': None, 'rgb_b': None,
        'lab_L': None, 'lab_a': None, 'lab_b': None,
        'shader_r': None, 'shader_g': None, 'shader_b': None,
        'vial_id': '', 'recipe_id': '', 'defect_label': '',
    }
    if isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
        for k, v in zip(('rgb_r', 'rgb_g', 'rgb_b'), rgb):
            row[k] = v
    if isinstance(lab, (list, tuple)) and len(lab) >= 3:
        for k, v in zip(('lab_L', 'lab_a', 'lab_b'), lab):
            row[k] = v
    if shader is not None:
        for k, v in zip(('shader_r', 'shader_g', 'shader_b'), shader):
            row[k] = v
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--camera', default='FillCam', choices=('FillCam',))
    parser.add_argument('--stage', default='stations/fill_station/fill_station.usda')
    parser.add_argument('--out-dir', default='outputs/live_inspection')
    parser.add_argument('--start', type=int, default=350)
    parser.add_argument('--end', type=int, default=360)
    parser.add_argument('--step', type=int, default=1)
    parser.add_argument('--subframes', type=int, default=8)
    parser.add_argument('--mode', choices=('roi', 'team-cv'), default='roi')
    parser.add_argument('--roi', nargs=4, type=int, metavar=('X', 'Y', 'W', 'H'),
                        default=(290, 290, 35, 55),
                        help='Manual patch; for team-cv, pass --auto-roi to use its locator')
    parser.add_argument('--auto-roi', action='store_true',
                        help='Only with --mode team-cv; let the CV pipeline locate the vial')
    parser.add_argument('--cv-root', help='Path containing the vialcv package, for --mode team-cv')
    parser.add_argument('--shader-rgb', nargs=3, type=float, metavar=('R', 'G', 'B'),
                        help='Optional temporary session-layer shader appearance override (0..1)')
    parser.add_argument('--offline-test', type=Path,
                        help='Test basic_roi_measure on an image; do not launch Isaac Sim')
    args = parser.parse_args()
    if args.offline_test:
        import cv2
        image = cv2.imread(str(args.offline_test))
        if image is None:
            parser.error('offline image cannot be opened')
        print(json.dumps(basic_roi_measure(image, args.roi), indent=2))
        return
    if not (1 <= args.start <= args.end <= 686) or args.step < 1 or args.subframes < 1:
        parser.error('Invalid animation range, step, or subframes')
    if args.auto_roi and args.mode != 'team-cv':
        parser.error('--auto-roi requires --mode team-cv')
    if args.shader_rgb is not None and any(v < 0 or v > 1 for v in args.shader_rgb):
        parser.error('Shader RGB components must be between 0 and 1')
    if args.mode == 'team-cv':
        if not args.cv_root:
            parser.error('--mode team-cv requires --cv-root pointing to the folder containing vialcv/')
        cv_root = Path(args.cv_root).expanduser().resolve()
        if not (cv_root / 'vialcv' / 'detect.py').is_file():
            parser.error(f'Could not find vialcv/detect.py under {cv_root}')
        sys.path.insert(0, str(cv_root))
    stage_file = file_path(args.stage).resolve()
    if not stage_file.is_file():
        parser.error(f'USD stage not found: {stage_file}')
    output = file_path(args.out_dir).resolve()
    if (output / 'inspection.csv').exists() or (output / 'inspection.jsonl').exists():
        parser.error(f'Inspection results already exist in {output}; choose a new --out-dir')
    output.mkdir(parents=True, exist_ok=True)
    images = output / 'images'
    images.mkdir(exist_ok=True)
    cam = json.loads((ROOT / 'cameras' / (args.camera + '.json')).read_text())
    width, height = cam['render_px']
    if not args.auto_roi:
        x, y, w, h = args.roi
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            parser.error(f'ROI {args.roi} is outside {width}x{height}')

    from isaacsim import SimulationApp
    kit = SimulationApp({'headless': True, 'renderer': 'PathTracing', 'width': width, 'height': height})
    try:
        import cv2
        import numpy as np
        import omni.usd
        import omni.timeline
        from isaacsim.core.utils.extensions import enable_extension
        enable_extension('omni.replicator.core')
        import omni.replicator.core as rep
        from pxr import Gf, UsdGeom, UsdShade

        # Check the optional team CV imports before starting a lengthy capture.
        if args.mode == 'team-cv':
            from vialcv.detect import detect_vial_color  # noqa: F401

        ctx = omni.usd.get_context()
        if not ctx.open_stage(str(stage_file)):
            raise RuntimeError(f'Could not open stage: {stage_file}')
        while ctx.get_stage_loading_status()[2] > 0:
            kit.update()
        for _ in range(10):
            kit.update()
        stage = ctx.get_stage()

        camera_path = next((p for p in (cam['prim_in_csi_line'], cam['prim_in_station_file'])
                            if stage.GetPrimAtPath(p).IsValid()), None)
        if camera_path is None:
            raise RuntimeError('FillCam prim missing in selected scene')
        shader_prim = stage.GetPrimAtPath(SHADER_PATH)
        color_input = (UsdShade.Shader(shader_prim).GetInput('diffuseColor')
                       if shader_prim.IsValid() else None)
        if color_input is None:
            print('WARN: Shared liquid shader not found; recording null shader values', flush=True)

        stage.SetEditTarget(stage.GetSessionLayer())
        if args.shader_rgb and color_input is not None:
            color_input.Set(Gf.Vec3f(*args.shader_rgb))
        timeline = omni.timeline.get_timeline_interface()
        product = rep.create.render_product(camera_path, (width, height))
        annotator = rep.AnnotatorRegistry.get_annotator('rgb')
        annotator.attach([product])
        rep.orchestrator.set_capture_on_play(False)
        kit.update()

        clip = UsdGeom.Camera(stage.GetPrimAtPath(camera_path)).GetClippingRangeAttr()
        old = clip.Get()
        clip.Set(Gf.Vec2f(old[0] * 0.5, old[1]))
        kit.update()
        clip.Set(old)
        kit.update()

        fps = float(stage.GetTimeCodesPerSecond())
        settings = {
            'generator': 'tools/render_with_inspection.py',
            'camera_id': args.camera,
            'camera_prim': camera_path,
            'image_px': [width, height],
            'stage_path': str(stage_file),
            'time_codes_per_second': fps,
            'frame_range': [args.start, args.end, args.step],
            'inspection_mode': args.mode,
            'roi_method': ('cv_auto' if args.auto_roi else 'manual_fixed_roi'),
            'roi_xywh': None if args.auto_roi else list(args.roi),
            'shader_prim': SHADER_PATH if color_input is not None else None,
            'programmed_shader_rgb': args.shader_rgb,
            'scene_shader_scope': 'shared liquid shader, not individual vial ground truth',
            'data_origin': 'digital_twin',
            'physical_mixing_validated': False,
            'factory_defect_labels_available': False,
            'vial_identity_ground_truth_available': False,
        }
        (output / 'run_manifest.json').write_text(json.dumps(settings, indent=2) + '\n')

        csv_file = output / 'inspection.csv'
        jsonl_file = output / 'inspection.jsonl'
        expected = list(range(args.start, args.end + 1, args.step))
        # Fail closed on existing results to avoid mixing runs/deduplicating incorrectly.
        if csv_file.exists() or jsonl_file.exists():
            raise RuntimeError(f'Inspection results already exist in {output}; choose a fresh --out-dir')
        with csv_file.open('w', newline='') as csv_out, jsonl_file.open('w') as json_out:
            writer = None
            for i, frame in enumerate(expected, 1):
                print(f'Inspecting frame {frame} ({i}/{len(expected)})...', flush=True)
                timeline.set_current_time(frame / fps)
                kit.update()
                for _ in range(2):
                    rep.orchestrator.step(rt_subframes=args.subframes, delta_time=0.0)
                pixels = np.asarray(annotator.get_data())
                if pixels.ndim != 3 or pixels.shape[:2] != (height, width) or pixels.shape[2] < 3:
                    raise RuntimeError(f'Unexpected camera data shape {pixels.shape}')
                bgr = pixels[..., :3][..., ::-1].copy()
                filename = f'frame_{frame:04d}.png'
                if not cv2.imwrite(str(images / filename), bgr):
                    raise RuntimeError(f'Could not write {filename}')

                try:
                    if args.mode == 'roi':
                        inspection = basic_roi_measure(bgr, args.roi)
                    else:
                        inspection = team_cv_measure(bgr,
                                                     None if args.auto_roi else args.roi,
                                                     f'images/{filename}')
                except Exception as e:
                    inspection = {'mode': args.mode,
                                  'roi_xywh': None if args.auto_roi else list(args.roi),
                                  'quality': {'ok': False, 'code': 'inspection_exception',
                                              'detail': str(e)}}
                    print(f'WARN: CV inspection failed at frame {frame}: {e}', flush=True)

                record = {
                    'schema': 'processdna.sim_inspection.v0',
                    'frame': frame,
                    'sim_time_s': round(frame / fps, 6),
                    'image_file': f'images/{filename}',
                    'camera_id': args.camera,
                    'data_origin': 'digital_twin',
                    'inspection_mode': args.mode,
                    'scene_shader_rgb': as_rgb(color_input.Get()) if color_input is not None else None,
                    'scene_shader_path': SHADER_PATH if color_input is not None else None,
                    'scene_shader_is_per_vial': False,
                    'vial_id': None,
                    'recipe_id': None,
                    'physical_carryover_fraction': None,
                    'factory_defect_label': None,
                    'inspection': inspection,
                }
                json_out.write(json.dumps(record, allow_nan=False) + '\n')
                json_out.flush()
                row = report_fields(record)
                if writer is None:
                    writer = csv.DictWriter(csv_out, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)
                csv_out.flush()
                print(f"  saved {filename}; inspection quality={inspection.get('quality', {}).get('ok')}",
                      flush=True)
        print(f'DONE: {len(expected)} captured/inspected frames: {output}', flush=True)
        print('NOTE: This measures simulated pixels. No physical carryover or factory PASS/FAIL labels.', flush=True)
    except BaseException:
        traceback.print_exc()
        kit.close(exit_code=1)
        raise
    kit.close()


if __name__ == '__main__':
    main()
