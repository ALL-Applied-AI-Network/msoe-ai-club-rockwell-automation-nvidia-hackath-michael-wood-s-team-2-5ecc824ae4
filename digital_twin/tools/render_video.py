"""Render a FillCam animation to sequential PNG files with one Isaac Sim launch."""
import argparse
import json
import os
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--camera', choices=('FillCam',), default='FillCam')
parser.add_argument('--stage', default='stations/fill_station/fill_station.usda')
parser.add_argument('--out-dir', default='outputs/video_frames')
parser.add_argument('--start', type=int, default=1)
parser.add_argument('--end', type=int, default=686)
parser.add_argument('--step', type=int, default=25)
parser.add_argument('--subframes', type=int, default=4)
parser.add_argument('--fps', type=float, default=8.0)
parser.add_argument('--video', default='outputs/fill_station_demo.mp4')
args = parser.parse_args()

if args.step < 1 or args.start < 1 or args.end < args.start or args.subframes < 1 or args.fps <= 0:
    parser.error('invalid frame range, step, or subframes')
if args.camera == 'FillCam' and args.end > 686:
    parser.error('FillCam animation ends at frame 686')

stage_path = Path(args.stage).expanduser()
if not stage_path.is_absolute():
    stage_path = ROOT / stage_path
stage_path = stage_path.resolve()
if not stage_path.is_file():
    parser.error(f'Stage not found: {stage_path}')

out_dir = Path(args.out_dir).expanduser()
if not out_dir.is_absolute():
    out_dir = ROOT / out_dir
out_dir.mkdir(parents=True, exist_ok=True)

video_path = Path(args.video).expanduser()
if not video_path.is_absolute():
    video_path = ROOT / video_path
video_path.parent.mkdir(parents=True, exist_ok=True)

cam = json.loads((ROOT / 'cameras' / (args.camera + '.json')).read_text())
rw, rh = cam['render_px']

from isaacsim import SimulationApp
kit = SimulationApp({'headless': True, 'renderer': 'PathTracing', 'width': rw, 'height': rh})

try:
    from isaacsim.core.utils.extensions import enable_extension
    enable_extension('omni.replicator.core')
    import cv2
    import numpy as np
    import omni.usd
    import omni.timeline
    import omni.replicator.core as rep
    from pxr import Gf, UsdGeom

    ctx = omni.usd.get_context()
    if not ctx.open_stage(str(stage_path)):
        raise RuntimeError(f'Unable to open {stage_path}')
    while ctx.get_stage_loading_status()[2] > 0:
        kit.update()
    for _ in range(10):
        kit.update()
    stage = ctx.get_stage()

    camera_path = next((path for path in
        (cam['prim_in_csi_line'], cam['prim_in_station_file'])
        if stage.GetPrimAtPath(path).IsValid()), None)
    if camera_path is None:
        raise RuntimeError('Camera prim not found')

    timeline = omni.timeline.get_timeline_interface()
    rp = rep.create.render_product(camera_path, (rw, rh))
    annotator = rep.AnnotatorRegistry.get_annotator('rgb')
    annotator.attach([rp])
    rep.orchestrator.set_capture_on_play(False)
    kit.update()

    # Same camera clipping-range refresh as the working one-image renderer.
    clip = UsdGeom.Camera(stage.GetPrimAtPath(camera_path)).GetClippingRangeAttr()
    near_far = clip.Get()
    stage.SetEditTarget(stage.GetSessionLayer())
    clip.Set(Gf.Vec2f(near_far[0] * 0.5, near_far[1]))
    kit.update()
    clip.Set(near_far)
    kit.update()

    frames = list(range(args.start, args.end + 1, args.step))
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*'mp4v'), args.fps, (rw, rh))
    video_enabled = writer.isOpened()
    if not video_enabled:
        print('MP4 encoder unavailable; saving PNG frames only', flush=True)
    for image_no, frame in enumerate(frames):
        print(f'Rendering frame {frame} ({image_no + 1}/{len(frames)})...', flush=True)
        timeline.set_current_time(frame / stage.GetTimeCodesPerSecond())
        kit.update()
        for _ in range(2):
            rep.orchestrator.step(rt_subframes=args.subframes, delta_time=0.0)
        data = np.asarray(annotator.get_data())
        if data.ndim != 3 or data.shape[:2] != (rh, rw) or data.shape[2] < 3:
            raise RuntimeError(f'Unexpected RGB data shape {data.shape}')
        output = out_dir / f'frame_{image_no:04d}.png'
        bgr = data[..., :3][..., ::-1].copy()
        if not cv2.imwrite(str(output), bgr):
            raise OSError(f'Could not save {output}')
        if video_enabled:
            writer.write(bgr)
        print(f'Wrote {output}', flush=True)
    writer.release()
    print(f'DONE: {len(frames)} PNG frames in {out_dir}', flush=True)
    if video_enabled:
        print(f'VIDEO: {video_path}', flush=True)
except BaseException:
    traceback.print_exc()
    kit.close(exit_code=1)
    raise
kit.close()
