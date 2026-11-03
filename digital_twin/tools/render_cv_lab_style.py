"""Isaac Sim FillCam render with the SAME vialcv lab_capture station-state preview UI.

Renders each frame from the USD scene, feeds the live RGB camera result into the
team's SignalTracker + LiveVialReader, and draws the lab_capture status / vial
history panel. Inspection records are produced from those synthetic camera
pixels, not from a previously encoded movie.

The visual UI functions draw_preview/draw_panel are bundled in lab_capture_ui.py
from the team's user-supplied scripts/lab_capture.py. This adapter changes only
the input (Isaac Sim instead of a USB camera), and upscales the layout for a
Full HD presentation file. Outputs are synthetic, not factory defect truth.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from pathlib import Path

from lab_capture_ui import (PANEL_W, STATE_STEP, STATE_COLORS, draw_panel,
                            draw_preview)

SCRIPT = Path(__file__).resolve()
DEFAULT_TWIN_ROOT = SCRIPT.parent.parent
NATIVE_SIZE = (640, 480)
PRESENTATION_SIZE = (1920, 1080)


def absolute_under(root, value):
    p = Path(value).expanduser()
    return (p if p.is_absolute() else root / p).resolve()


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--twin-root', type=Path, default=DEFAULT_TWIN_ROOT)
    p.add_argument('--cv-root', type=Path, default=Path.home() / 'MAIC_CV')
    p.add_argument('--stage', default='stations/fill_station/fill_station.usda')
    p.add_argument('--camera', default='FillCam', choices=['FillCam'])
    p.add_argument('--out-dir', default='outputs/ProcessDNA_LabStyle_CV')
    p.add_argument('--start', type=int, default=1)
    p.add_argument('--end', type=int, default=686)
    p.add_argument('--fps', type=int, choices=[30, 60], default=30)
    p.add_argument('--subframes', type=int, default=8)
    p.add_argument('--render-width', type=int, default=1280)
    p.add_argument('--render-height', type=int, default=960)
    p.add_argument('--roi', type=int, nargs=4, metavar=('X','Y','W','H'),
                   help='Optional MANUAL measurement ROI in 640x480 coords. Does not enable auto detection.')
    p.add_argument('--run-plan', type=Path,
                   help='Optional synthetic CSV with vial_order,recipe_id, same as lab_capture.py. '
                        'Use only if its event count really matches the simulated fill order.')
    p.add_argument('--flag-de00', type=float,
                   help='Provisional first-vial threshold; default comes from vialcv.live')
    p.add_argument('--white-balance', choices=['none','white_patch','gray_world'], default='none')
    p.add_argument('--save-camera-frames', action='store_true')
    p.add_argument('--offline-frame', type=Path,
                   help='Preview lab-style layout / single-frame CV measurement without Isaac Sim')
    args = p.parse_args()
    if not (1 <= args.start <= args.end <= 686):
        p.error('Frame range must be within 1..686')
    if args.subframes < 1 or args.render_width < 640 or args.render_height < 480:
        p.error('Bad render resolution or subframes')
    if args.render_width * 3 != args.render_height * 4:
        p.error('Render dimensions must be 4:3 (e.g. 1280x960)')
    if args.roi:
        x,y,w,h = args.roi
        if min(x,y) < 0 or min(w,h) <= 0 or x+w > 640 or y+h > 480:
            p.error('Manual ROI must be inside 640x480 image')
    return args


def setup_cv(args):
    root = args.cv_root.expanduser().resolve()
    if not (root / 'vialcv' / 'live.py').is_file():
        raise RuntimeError(f'Missing {root}/vialcv/live.py; copy complete CV branch vialcv/')
    if not (root / 'vialcv' / 'detect.py').is_file():
        raise RuntimeError(f'Missing {root}/vialcv/detect.py')
    sys.path.insert(0, str(root))
    from vialcv.detect import detect_vial_color
    from vialcv.events import SignalTracker, load_run_plan
    from vialcv.live import DEFAULT_FLAG_DE00, LiveVialReader
    from vialcv.roi import load_camera_config
    config = load_camera_config('FillCam')
    if tuple(config.image_size_wh) != NATIVE_SIZE:
        raise RuntimeError(f'FillCam CV config size {config.image_size_wh}, expected {NATIVE_SIZE}')
    config.region('vial')  # fail early when required calibration data absent
    plan = load_run_plan(args.run_plan.expanduser()) if args.run_plan else None
    threshold = DEFAULT_FLAG_DE00 if args.flag_de00 is None else args.flag_de00
    return dict(root=root, detect=detect_vial_color, tracker=SignalTracker,
                reader=LiveVialReader, config=config, plan=plan, flag=threshold)


def measure_camera(native_bgr, deps, args, image_ref, reference=None, t=None):
    """Call real team CV, retaining its quality codes and provenance."""
    kwargs = dict(camera_id='FillCam',
                  roi=tuple(args.roi) if args.roi else None,
                  reference_bgr=reference,
                  white_balance_method=args.white_balance,
                  image_ref=image_ref,
                  source_data_origin='digital_twin')
    # The lab_capture measurement callback adds video time via metadata.
    if t is not None:
        kwargs['metadata'] = {'video_s': round(float(t), 3)}
    return deps['detect'](native_bgr, **kwargs)


def compose_lab_ui(bgr_highres, config, state, t, fps, vials, has_plan, manual_roi=None):
    """Same lab_capture styling; high-res camera pixels remain sharp in 1080p output."""
    import cv2
    import numpy as np

    h, w = bgr_highres.shape[:2]
    sx, sy = w/640.0, h/480.0
    preview = bgr_highres.copy()
    x,y,rw,rh = manual_roi or config.region('vial')
    x1,y1 = round(x*sx),round(y*sy)
    x2,y2 = round((x+rw-1)*sx),round((y+rh-1)*sy)
    color = STATE_COLORS.get(state,(255,255,255))
    thickness = max(2,round(2*sx))
    cv2.rectangle(preview,(x1,y1),(x2,y2),color,thickness)
    bar_h = round(28*sy)
    cv2.rectangle(preview,(0,0),(w-1,bar_h),(0,0,0),-1)
    # 'SIM' replaces 'REC', so the synthetic video is unmistakably labeled.
    text = f'SIM {t:6.1f}s  {fps:4.1f} fps  state: {state}'
    cv2.putText(preview,text,(round(6*sx),round(19*sy)),cv2.FONT_HERSHEY_SIMPLEX,
                0.55*min(sx,sy),color,max(1,round(2*min(sx,sy))),cv2.LINE_AA)
    if manual_roi:
        # Small but explicit provenance note; not labeled a detected vial.
        cv2.putText(preview,'MANUAL INSPECTION ROI',(round(6*sx),round(44*sy)),
                    cv2.FONT_HERSHEY_SIMPLEX,0.38*min(sx,sy),(0,220,255),
                    max(1,round(min(sx,sy))),cv2.LINE_AA)

    # This is the original draw_panel function from scripts/lab_capture.py.
    panel_native = draw_panel(vials,480,has_plan)
    panel = cv2.resize(panel_native,(round(PANEL_W*sx),h),interpolation=cv2.INTER_CUBIC)
    joined = np.hstack((preview,panel))
    dest_w,dest_h = PRESENTATION_SIZE
    scale = min(dest_w/joined.shape[1],dest_h/joined.shape[0])
    dw,dh = round(joined.shape[1]*scale),round(joined.shape[0]*scale)
    resized = cv2.resize(joined,(dw,dh),interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    out = np.full((dest_h,dest_w,3), (30,30,30), dtype=np.uint8)
    left,top = (dest_w-dw)//2,(dest_h-dh)//2
    out[top:top+dh,left:left+dw] = resized
    # Do not fabricate recipe IDs, defect flags, timestamps, or vial events.
    cv2.putText(out,'SYNTHETIC ISAAC SIM  |  PROVISIONAL CV RESULTS',
                (24,dest_h-20),cv2.FONT_HERSHEY_SIMPLEX,0.48,(194,194,194),1,cv2.LINE_AA)
    return out


def finished_json(reader):
    return [v.summary() for v in reader.vials if v.status in ('final','not_measured')]


def write_finished_if_new(reader, outdir):
    if reader.pop_finished():
        records = finished_json(reader)
        (outdir/'vials_live.jsonl').write_text(''.join(json.dumps(x, allow_nan=False)+'\n' for x in records))


def preview_offline(args, deps, outdir):
    import cv2
    path = absolute_under(args.twin_root,args.offline_frame)
    frame = cv2.imread(str(path))
    if frame is None:
        raise RuntimeError(f'Cannot open image: {path}')
    native = cv2.resize(frame,NATIVE_SIZE,interpolation=cv2.INTER_AREA)
    result = measure_camera(native,deps,args,path.name)
    # A single image is not a fill event; don't invent vial history.
    big = cv2.resize(frame,(args.render_width,args.render_height),interpolation=cv2.INTER_CUBIC)
    outdir.mkdir(parents=True,exist_ok=True)
    pic = compose_lab_ui(big,deps['config'],'offline preview',0,args.fps,[],False,args.roi)
    target = outdir/'lab_style_preview.png'
    if not cv2.imwrite(str(target),pic):
        raise RuntimeError(f'Unable to write {target}')
    (outdir/'offline_cv_result.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print('PREVIEW:',target,flush=True)
    print('CV QUALITY:',result.get('quality'),flush=True)
    print('ROI SOURCE:',result.get('roi_source'),flush=True)
    print('VIAL HISTORY: 0 (single frame has no temporal events)',flush=True)


def render(args, deps, outdir):
    root = args.twin_root.expanduser().resolve()
    stage_path = absolute_under(root,args.stage)
    cam = json.loads((root/'cameras'/f'{args.camera}.json').read_text())
    if not stage_path.is_file():
        raise RuntimeError(f'Missing USD scene: {stage_path}')
    if (outdir/'frames.jsonl').exists():
        raise RuntimeError(f'Refusing to overwrite {outdir}/frames.jsonl. Choose a fresh --out-dir.')
    outdir.mkdir(parents=True,exist_ok=True)
    frames_dir=outdir/'presentation_frames'
    frames_dir.mkdir(exist_ok=True)
    raw_dir=outdir/'camera_frames'
    if args.save_camera_frames:
        raw_dir.mkdir(exist_ok=True)
    (outdir/'vials_live.jsonl').write_text('')

    # Isaac Sim must initialize before importing omni.*, pxr, etc.
    from isaacsim import SimulationApp
    sim_app=SimulationApp({'headless':True,'renderer':'PathTracing',
                           'width':args.render_width,'height':args.render_height})
    writer=None
    reader=None
    last=0
    try:
        import cv2
        import numpy as np
        import omni.usd
        import omni.timeline
        from isaacsim.core.utils.extensions import enable_extension
        enable_extension('omni.replicator.core')
        import omni.replicator.core as rep
        from pxr import Gf,UsdGeom

        context=omni.usd.get_context()
        if not context.open_stage(str(stage_path)):
            raise RuntimeError(f'Cannot open stage {stage_path}')
        while context.get_stage_loading_status()[2]>0:
            sim_app.update()
        for _ in range(10):sim_app.update()
        stage=context.get_stage()
        camera_prim=next((x for x in (cam['prim_in_csi_line'],cam['prim_in_station_file'])
                          if stage.GetPrimAtPath(x).IsValid()),None)
        if camera_prim is None:
            raise RuntimeError('No FillCam camera in scene')
        rp=rep.create.render_product(camera_prim,(args.render_width,args.render_height))
        annotator=rep.AnnotatorRegistry.get_annotator('rgb')
        annotator.attach([rp])
        rep.orchestrator.set_capture_on_play(False)
        sim_app.update()
        clipping=UsdGeom.Camera(stage.GetPrimAtPath(camera_prim)).GetClippingRangeAttr()
        old=clipping.Get()
        stage.SetEditTarget(stage.GetSessionLayer())
        clipping.Set(Gf.Vec2f(old[0]*0.5,old[1]))
        sim_app.update()
        clipping.Set(old)
        sim_app.update()
        timeline=omni.timeline.get_timeline_interface()
        scene_rate=float(stage.GetTimeCodesPerSecond())
        total=round((args.end-args.start)*args.fps/scene_rate)+1
        timecodes=[min(float(args.end),args.start+i*scene_rate/args.fps) for i in range(total)]

        manifest={'source':'Isaac Sim FillCam USD', 'data_origin':'digital_twin',
                  'stage':str(stage_path),'cv_root':str(deps['root']),
                  'render_px':[args.render_width,args.render_height],
                  'cv_px':[640,480], 'video_px':list(PRESENTATION_SIZE),
                  'output_fps':args.fps, 'timecodes_per_sec':scene_rate,
                  'start_timecode':args.start,'end_timecode':args.end,'sample_count':len(timecodes),
                  'state_logic':'vialcv.events.SignalTracker',
                  'vial_history':'vialcv.live.LiveVialReader',
                  'ui_source':'lab_capture.py draw_panel / same colored status bar',
                  'manual_roi_xywh':args.roi,'run_plan':str(args.run_plan) if args.run_plan else None,
                  'limitations':'FillCam ROI/camera geometry needs calibration; no physically modeled carryover or validated defect labels.'}
        (outdir/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        writer=cv2.VideoWriter(str(outdir/'ProcessDNA_LabStyle_Preview.avi'),
                               cv2.VideoWriter_fourcc(*'MJPG'),args.fps,PRESENTATION_SIZE)
        if not writer.isOpened():
            raise RuntimeError('MJPG video encoder unavailable; no preview AVI')

        tracker=deps['tracker'](deps['config'],args.fps/STATE_STEP)
        def measure(frame,reference,t):
            return measure_camera(frame,deps,args,f'FillCam_t{t:.3f}.png',reference,t)
        reader=deps['reader'](measure,args.fps/STATE_STEP,deps['plan'],deps['flag'])
        state='starting'
        frame_path=outdir/'frames.jsonl'
        with frame_path.open('w',encoding='utf-8') as jf:
            for idx,tc in enumerate(timecodes):
                timeline.set_current_time(tc/scene_rate)
                sim_app.update()
                for _ in range(2):
                    rep.orchestrator.step(rt_subframes=args.subframes,delta_time=0.0)
                data=np.asarray(annotator.get_data())
                if data.ndim!=3 or data.shape[:2]!=(args.render_height,args.render_width) or data.shape[2]<3:
                    raise RuntimeError(f'Invalid RGB data shape: {data.shape}')
                bgr=data[...,:3][...,::-1].copy()
                native=cv2.resize(bgr,NATIVE_SIZE,interpolation=cv2.INTER_AREA)
                t=(tc-args.start)/scene_rate
                if idx%STATE_STEP==0:
                    # Identical state and vial-history logic to lab_capture.py.
                    state=reader.update(t,native,tracker.update(native))
                    write_finished_if_new(reader,outdir)
                composed=compose_lab_ui(bgr,deps['config'],state,t,args.fps,
                                        reader.vials,deps['plan'] is not None,args.roi)
                path=frames_dir/f'frame_{idx:05d}.png'
                if not cv2.imwrite(str(path),composed):
                    raise OSError(f'Cannot save {path}')
                if args.save_camera_frames:
                    if not cv2.imwrite(str(raw_dir/f'frame_{idx:05d}.png'),bgr):
                        raise OSError('Cannot write raw FillCam frame')
                writer.write(composed)
                row={'frame_index':idx,'simulation_timecode':round(tc,6),
                     'sim_elapsed_s':round(t,6), 'state':state,
                     'vials_filled':len(reader.vials),
                     'vials_flagged':sum(v.flag is not None for v in reader.vials),
                     'image_file':f'presentation_frames/frame_{idx:05d}.png',
                     'data_origin':'digital_twin','roi_source':'argument' if args.roi else 'config',
                     'recipe_ids_validated':False,'factory_defect_ground_truth':None}
                jf.write(json.dumps(row,allow_nan=False)+'\n')
                jf.flush()
                last=idx+1
                print(f'frame {last}/{len(timecodes)} | state: {state} | '
                      f'vials: {len(reader.vials)} | flags: {row["vials_flagged"]}',flush=True)
        reader.close((timecodes[-1]-args.start)/scene_rate)
        write_finished_if_new(reader,outdir)
        if deps['plan'] is not None and len(reader.vials)!=len(deps['plan']):
            print('WARNING: live vial count differs from run plan; recipe IDs may be wrong.',flush=True)
        print(f'DONE: {last} frames, {len(reader.vials)} tracked vial events',flush=True)
        print('VIDEO:',outdir/'ProcessDNA_LabStyle_Preview.avi',flush=True)
        print('LOSSLESS FRAMES:',frames_dir,flush=True)
    except BaseException:
        traceback.print_exc()
        raise
    finally:
        if writer is not None:
            writer.release()
        sim_app.close()


def main():
    args=parse_args()
    deps=setup_cv(args)
    outdir=absolute_under(args.twin_root,args.out_dir)
    if args.offline_frame:
        preview_offline(args,deps,outdir)
    else:
        render(args,deps,outdir)


if __name__=='__main__':
    main()
