"""Render a presentation-ready Isaac Sim FillCam video WITH live MAIC vialcv inspection.

This is NOT post-processing a pre-rendered video. The CV module runs on each
RGB frame returned by the Isaac Sim camera. The output is a 1920x1080 composed
frame (camera at left, CV results at right), high-quality PNGs, JSONL, and a
MJPEG AVI preview. Encode final H.264 MP4 from PNGs on Windows using FFmpeg.

Put this file in MAIC/digital_twin/tools/ for source control; copy to
GB10: ~/csi_digital_twin_v1/tools/render_cv_demo.py
Put the team's merged vialcv package (and configs, if used) on GB10 under ~/MAIC.
No fake detection or defect PASS/FAIL labels are generated.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

SCRIPT = Path(__file__).resolve()
DEFAULT_TWIN_ROOT = SCRIPT.parent.parent


def get_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--twin-root', type=Path, default=DEFAULT_TWIN_ROOT)
    p.add_argument('--cv-root', type=Path, default=Path.home() / 'MAIC',
                   help='MAIC repository root containing vialcv/ and its configs')
    p.add_argument('--stage', default='stations/fill_station/fill_station.usda')
    p.add_argument('--camera', default='FillCam')
    p.add_argument('--out-dir', default='outputs/presentation_cv')
    p.add_argument('--start', type=int, default=1)
    p.add_argument('--end', type=int, default=686)
    p.add_argument('--fps', type=int, choices=(30, 60), default=30)
    p.add_argument('--subframes', type=int, default=4)
    p.add_argument('--render-width', type=int, default=1280)
    p.add_argument('--render-height', type=int, default=960)
    p.add_argument('--roi', type=int, nargs=4, metavar=('X', 'Y', 'W', 'H'),
                   help='OPTIONAL manual inspection ROI in native 640x480 camera coordinates. '
                        'Without it, the team CV attempts automatic localization.')
    p.add_argument('--save-camera-frames', action='store_true',
                   help='Save unannotated full-res camera PNGs as well')
    p.add_argument('--offline-frame', type=Path,
                   help='Inspect a single existing frame to verify MAIC CV + panel; no Isaac Sim launch')
    args = p.parse_args()
    if not 1 <= args.start <= args.end <= 686:
        p.error('Frame range must be within 1..686')
    if args.subframes < 1 or args.render_width < 640 or args.render_height < 480:
        p.error('Invalid rendering settings')
    if args.render_width * 3 != args.render_height * 4:
        p.error('FillCam source render must remain 4:3, e.g. 1280x960 or 1440x1080')
    if args.roi is not None:
        x, y, w, h = args.roi
        if w < 1 or h < 1 or x < 0 or y < 0 or x+w > 640 or y+h > 480:
            p.error('ROI must be inside original 640x480 FillCam coordinates')
    return args


def setup_cv(cv_root):
    cv_root = cv_root.expanduser().resolve()
    if not (cv_root / 'vialcv' / 'detect.py').is_file():
        raise RuntimeError(
            f"Team vialcv missing at {cv_root}/vialcv/detect.py. "
            "Use the merged MAIC repo (not a separate CV worktree). "
            "Copy MAIC/vialcv and any MAIC/configs dependencies to the GB10."
        )
    sys.path.insert(0, str(cv_root))
    try:
        from vialcv.detect import detect_vial_color
    except Exception as exc:
        raise RuntimeError(f'Could not import MAIC vialcv from {cv_root}: {exc}') from exc
    return detect_vial_color, cv_root


def inspect(bgr, detect_vial_color, roi, image_ref):
    import cv2
    # Detector uses its original 640x480 FillCam config, while presentation RGB
    # is rendered at 1280x960. This keeps manual/automatic ROI coordinates valid.
    native = cv2.resize(bgr, (640, 480), interpolation=cv2.INTER_AREA)
    try:
        result = detect_vial_color(
            native,
            camera_id='FillCam',
            roi=tuple(roi) if roi else None,
            white_balance_method='none',
            reference_bgr=None,
            image_ref=image_ref,
            source_data_origin='digital_twin',
        )
        if not isinstance(result, dict):
            raise TypeError('CV detector returned non-dict result')
        return result
    except Exception as exc:
        return {
            'quality': {'ok': False, 'code': 'cv_exception', 'detail': str(exc)},
            'roi_xywh': list(roi) if roi else None,
            'roi_source': 'argument' if roi else 'unknown',
            'fill': None, 'color': None,
        }


def nested_color(result):
    primary = ((result.get('color') or {}).get('primary') or {})
    rgb = ((primary.get('rgb_0_255') or {}).get('median'))
    lab = ((primary.get('lab') or {}).get('median'))
    def three(a):
        if not isinstance(a, (list, tuple)) or len(a) < 3:
            return None
        try:
            return [round(float(v), 2) for v in a[:3]]
        except (TypeError, ValueError):
            return None
    return three(rgb), lab if isinstance(lab, dict) else None


def draw_demo(bgr, result, sim_frame, sim_time):
    """Compose FullHD slide-friendly frame: 1440x1080 camera + 480px dashboard."""
    import cv2
    import numpy as np
    W, H, MAIN_W = 1920, 1080, 1440
    canvas = np.full((H, W, 3), (23, 21, 17), dtype=np.uint8)
    image = cv2.resize(bgr, (MAIN_W, H), interpolation=cv2.INTER_LINEAR)
    canvas[:, :MAIN_W] = image

    rgb, lab = nested_color(result)
    quality = result.get('quality') or {}
    ok = bool(quality.get('ok'))
    roi = result.get('roi_xywh')
    roi_source = str(result.get('roi_source') or 'unknown')
    # Important: manual ROI is NOT an automatically detected vial.
    auto_located = roi_source == 'detected' and ok
    if auto_located:
        status = 'VIAL LOCATED'
        accent = (130, 231, 82)
    elif ok:
        status = 'ROI MEASURED'
        accent = (48, 205, 245)
    else:
        status = 'INSPECTION FAILED'
        accent = (62, 120, 238)

    if isinstance(roi, (list, tuple)) and len(roi) == 4:
        try:
            x, y, w, h = [float(v) for v in roi]
            # Detector/ROI coordinates always in its 640x480 input space.
            x1, y1 = int(round(x*MAIN_W/640)), int(round(y*H/480))
            x2, y2 = int(round((x+w)*MAIN_W/640)), int(round((y+h)*H/480))
            if w > 0 and h > 0:
                cv2.rectangle(canvas, (x1, y1), (x2, y2), accent, 4)
                tx = min(max(8, x1), MAIN_W-340)
                ty = max(34, y1-12)
                cv2.rectangle(canvas, (tx-6, ty-30), (tx+330, ty+10), (23, 21, 17), -1)
                cv2.putText(canvas, 'DETECTED VIAL' if auto_located else 'INSPECTION ROI',
                            (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.86, accent, 2, cv2.LINE_AA)
        except (TypeError, ValueError):
            pass

    X = 1475
    WHITE = (240, 241, 244)
    MUTED = (174, 179, 189)
    def line(t, y, size=.75, color=WHITE, bold=2):
        cv2.putText(canvas, str(t), (X, y), cv2.FONT_HERSHEY_SIMPLEX,
                    size, color, bold, cv2.LINE_AA)
    cv2.rectangle(canvas, (MAIN_W, 0), (W-1, H-1), (36, 33, 27), -1)
    line('PROCESSDNA', 75, 1.15, WHITE, 3)
    line('DIGITAL TWIN', 115, .70, MUTED, 2)
    cv2.line(canvas, (X, 150), (W-36, 150), (72, 74, 78), 2)
    line('LIVE CV INSPECTION', 215, .73, WHITE, 2)
    line(status, 270, .80, accent, 2)
    line(f'ROI: {roi_source[:22]}', 312, .57, MUTED, 1)

    if rgb:
        line('MEASURED RGB', 395, .64, MUTED)
        line(f'{rgb[0]:.0f}, {rgb[1]:.0f}, {rgb[2]:.0f}', 445, .92, WHITE, 2)
        patch = tuple(int(max(0, min(255, n))) for n in reversed(rgb))
        cv2.rectangle(canvas, (X, 465), (W-40, 530), patch, -1)
        cv2.rectangle(canvas, (X, 465), (W-40, 530), WHITE, 1)
    else:
        line('NO VALID COLOR READING', 435, .61, accent)

    if lab and all(k in lab for k in ('L', 'a', 'b')):
        line('CIELAB (MEDIAN)', 605, .64, MUTED)
        line('L* %.1f   a* %.1f' % (lab['L'], lab['a']), 651, .75, WHITE, 2)
        line('b* %.1f' % lab['b'], 692, .75, WHITE, 2)

    fill = result.get('fill') or {}
    fill_state = fill.get('state')
    line('FILL STATE', 768, .64, MUTED)
    line(fill_state if fill_state else 'not available', 808, .73, WHITE, 2)
    if not ok:
        error = str(quality.get('code') or 'unknown')[:32]
        line(f'CV: {error}', 860, .52, accent, 1)

    cv2.line(canvas, (X, 900), (W-36, 900), (72, 74, 78), 2)
    line(f'FRAME {sim_frame}', 956, .75, WHITE, 2)
    line('SIM TIME %.2f s' % sim_time, 1001, .67, MUTED, 2)
    line('SYNTHETIC / NOT DEFECT GT', 1043, .48, MUTED, 1)
    return canvas


def do_offline(args, detect):
    import cv2
    import numpy as np
    path = args.offline_frame.expanduser().resolve()
    img = cv2.imread(str(path))
    if img is None:
        raise RuntimeError(f'Could not read sample image {path}')
    result = inspect(img, detect, args.roi, path.name)
    canvas = draw_demo(img, result, 350, 350/30)
    out_dir = absolute_under(args.twin_root, args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / 'cv_preview.png'
    cv2.imwrite(str(out), canvas)
    print('PREVIEW:', out, flush=True)
    print('QUALITY:', result.get('quality'), flush=True)
    print('ROI_SOURCE:', result.get('roi_source'), flush=True)
    if not (result.get('quality') or {}).get('ok'):
        raise SystemExit('CV preview failed quality checks. Inspect the reason before rendering a full video.')


def absolute_under(root, path):
    path = Path(path).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def do_render(args, detect, cv_root):
    root = args.twin_root.expanduser().resolve()
    cam = json.loads((root / 'cameras' / f'{args.camera}.json').read_text())
    stage_path = absolute_under(root, args.stage)
    out = absolute_under(root, args.out_dir)
    if not stage_path.is_file():
        raise RuntimeError(f'USD file not found: {stage_path}')
    if (out / 'inspections.jsonl').exists():
        raise RuntimeError(f'{out}/inspections.jsonl already exists; use a fresh out-dir')
    frames_dir = out / 'presentation_frames'
    raw_dir = out / 'camera_frames'
    frames_dir.mkdir(parents=True, exist_ok=True)
    if args.save_camera_frames:
        raw_dir.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp
    sim_app = SimulationApp({'headless': True, 'renderer': 'PathTracing',
                             'width': args.render_width, 'height': args.render_height})
    try:
        import cv2
        import numpy as np
        import omni.usd
        import omni.timeline
        from isaacsim.core.utils.extensions import enable_extension
        enable_extension('omni.replicator.core')
        import omni.replicator.core as rep
        from pxr import Gf, UsdGeom

        ctx = omni.usd.get_context()
        if not ctx.open_stage(str(stage_path)):
            raise RuntimeError(f'Could not open stage {stage_path}')
        while ctx.get_stage_loading_status()[2] > 0:
            sim_app.update()
        for _ in range(10):
            sim_app.update()
        stage = ctx.get_stage()
        camera_prim = next((p for p in (cam['prim_in_csi_line'], cam['prim_in_station_file'])
                            if stage.GetPrimAtPath(p).IsValid()), None)
        if camera_prim is None:
            raise RuntimeError('FillCam USD camera prim not found')
        rp = rep.create.render_product(camera_prim, (args.render_width, args.render_height))
        annotator = rep.AnnotatorRegistry.get_annotator('rgb')
        annotator.attach([rp])
        rep.orchestrator.set_capture_on_play(False)
        sim_app.update()
        clip = UsdGeom.Camera(stage.GetPrimAtPath(camera_prim)).GetClippingRangeAttr()
        old = clip.Get()
        stage.SetEditTarget(stage.GetSessionLayer())
        clip.Set(Gf.Vec2f(old[0] * 0.5, old[1]))
        sim_app.update()
        clip.Set(old)
        sim_app.update()

        timeline = omni.timeline.get_timeline_interface()
        scene_rate = float(stage.GetTimeCodesPerSecond())
        # True time sampling, not doubling playback speed at 60fps.
        count = round((args.end - args.start) * args.fps / scene_rate) + 1
        count = max(count, 1)
        times = [args.start + i * scene_rate / args.fps for i in range(count)]
        times = [min(float(args.end), t) for t in times]
        manifest = {
            'stage': str(stage_path), 'camera': args.camera, 'cv_root': str(cv_root),
            'render_resolution_px': [args.render_width, args.render_height],
            'cv_resolution_px': [640, 480],
            'presentation_px': [1920, 1080],
            'fps': args.fps, 'source_timecodes_per_sec': scene_rate,
            'start_frame': args.start, 'end_frame': args.end,
            'samples': len(times), 'data_origin': 'digital_twin',
            'cv_module': 'vialcv.detect.detect_vial_color',
            'roi_mode': 'manual' if args.roi else 'auto',
            'roi_original_640x480': list(args.roi) if args.roi else None,
            'note': 'CV measured synthetic pixels, no physically validated carryover or defect GT',
        }
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

        # MJPG AVI is a higher-bitrate, high-quality working master than OpenCV's
        # very low-bitrate mp4v. Also save lossless PNGs for final H.264 encoding.
        video_file = out / 'ProcessDNA_CV_Preview.avi'
        writer = cv2.VideoWriter(str(video_file), cv2.VideoWriter_fourcc(*'MJPG'),
                                 args.fps, (1920, 1080))
        if not writer.isOpened():
            raise RuntimeError('Could not open MJPG preview writer; PNG frames remain primary')
        try:
            with (out / 'inspections.jsonl').open('w') as jf:
                for idx, scene_frame in enumerate(times):
                    timeline.set_current_time(scene_frame / scene_rate)
                    sim_app.update()
                    for _ in range(2):
                        rep.orchestrator.step(rt_subframes=args.subframes, delta_time=0.0)
                    data = np.asarray(annotator.get_data())
                    if data.ndim != 3 or data.shape[:2] != (args.render_height, args.render_width) or data.shape[2] < 3:
                        raise RuntimeError(f'Unexpected RGB data shape {data.shape}')
                    bgr = data[..., :3][..., ::-1].copy()
                    measured = inspect(bgr, detect, args.roi, f'camera_frames/frame_{idx:05d}.png')
                    if (measured.get('quality') or {}).get('code') == 'cv_exception':
                        raise RuntimeError('CV integration error at frame %s: %s' % (
                            scene_frame, (measured.get('quality') or {}).get('detail')))
                    preview = draw_demo(bgr, measured, f'{scene_frame:.1f}', scene_frame/scene_rate)
                    annotated_path = frames_dir / f'frame_{idx:05d}.png'
                    if not cv2.imwrite(str(annotated_path), preview):
                        raise RuntimeError(f'PNG write failed: {annotated_path}')
                    if args.save_camera_frames:
                        cv2.imwrite(str(raw_dir / f'frame_{idx:05d}.png'), bgr)
                    writer.write(preview)
                    record = {
                        'data_origin': 'digital_twin',
                        'scene_frame': round(scene_frame, 6),
                        'sim_time_s': round(scene_frame / scene_rate, 6),
                        'output_frame_index': idx,
                        'image_file': f'presentation_frames/frame_{idx:05d}.png',
                        'inspection': measured,
                        'factory_defect_label': None,
                        'physical_carryover_fraction': None,
                    }
                    jf.write(json.dumps(record, allow_nan=False) + '\n')
                    jf.flush()
                    print(f'CV render {idx+1}/{len(times)} scene={scene_frame:.2f} '
                          f"quality={measured.get('quality', {}).get('code') or 'ok'} ", flush=True)
        finally:
            writer.release()
        print('DONE:', len(times), 'frames;', video_file, flush=True)
        print('LOSSLESS FRAMES:', frames_dir, flush=True)
        print('DATA:', out / 'inspections.jsonl', flush=True)
    except BaseException:
        traceback.print_exc()
        sim_app.close(exit_code=1)
        raise
    sim_app.close()


def main():
    args = get_args()
    detect, cv_root = setup_cv(args.cv_root)
    if args.offline_frame:
        do_offline(args, detect)
    else:
        do_render(args, detect, cv_root)


if __name__ == '__main__':
    main()
