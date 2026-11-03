"""UI code sourced from the team's lab_capture.py, with drawing functions unchanged.

This draws the same ROI/status bar and the same eight-row vial-history panel.
It is used in the Isaac Sim video, not for real lab acquisition.
"""
import cv2
import numpy as np

STATE_COLORS = {"no carrier": (160, 160, 160), "moving": (0, 165, 255), "pouring": (255, 120, 0),
                "parked, waiting": (0, 200, 200), "settling": (255, 200, 0),
                "settled, measured": (0, 200, 0), "settled, no color": (0, 0, 220)}
# The live state is computed on every Nth frame, matching extract_vials' default step.
STATE_STEP = 2
PANEL_W, ROW_H, PANEL_ROWS = 330, 54, 8
FONT = cv2.FONT_HERSHEY_SIMPLEX


def draw_preview(frame: np.ndarray, config, state: str, elapsed_s: float, fps: float) -> np.ndarray:
    preview = frame.copy()
    x, y, w, h = config.region("vial")
    color = STATE_COLORS.get(state, (255, 255, 255))
    cv2.rectangle(preview, (x, y), (x + w - 1, y + h - 1), color, 2)
    cv2.rectangle(preview, (0, 0), (640, 28), (0, 0, 0), -1)
    cv2.putText(preview, f"REC {elapsed_s:6.1f}s  {fps:4.1f} fps  state: {state}", (6, 19),
                FONT, 0.55, color, 2)
    return preview


def draw_panel(vials, height: int, has_plan: bool) -> np.ndarray:
    """Per-vial readout, newest at the bottom: swatch, recipe, zone, fill, comparison, flag."""
    panel = np.full((height, PANEL_W, 3), 30, dtype=np.uint8)
    n_flags = sum(v.flag is not None for v in vials)
    cv2.putText(panel, f"vials filled: {len(vials)}   flagged: {n_flags}", (8, 20), FONT, 0.5, (255, 255, 255), 1)
    if has_plan:
        cv2.putText(panel, "recipes by live fill order (provisional)", (8, 38), FONT, 0.4, (180, 180, 180), 1)
    for row, vial in enumerate(vials[-PANEL_ROWS:]):
        top = 46 + row * ROW_H
        if vial.flag:
            cv2.rectangle(panel, (2, top - 2), (PANEL_W - 3, top + ROW_H - 6), (0, 0, 255), 2)
        swatch = (60, 60, 60)
        if vial.ok:
            rgb = vial.record["color"]["primary"]["rgb_0_255"]["median"]
            swatch = tuple(int(round(c)) for c in rgb[::-1])
        cv2.rectangle(panel, (8, top + 2), (48, top + 42), swatch, -1)
        cv2.rectangle(panel, (8, top + 2), (48, top + 42), (200, 200, 200), 1)

        title = f"#{vial.number}"
        if vial.recipe_id is not None:
            title += f"  recipe {vial.recipe_id} (vial {vial.position_in_recipe})"
        cv2.putText(panel, f"{title}  {vial.status}", (56, top + 14), FONT, 0.45, (255, 255, 255), 1)
        if vial.ok:
            fill = vial.record["fill"]["state"].replace("at_or_above_view_top", "above view").replace("_", " ")
            detail = f"{vial.record['color']['primary_zone']}, fill {fill}"
        elif vial.record is not None:
            detail = f"no color: {vial.record['quality']['code']}"
        else:
            detail = "pouring..."
        cv2.putText(panel, detail, (56, top + 29), FONT, 0.4, (200, 200, 200), 1)
        if vial.flag:
            # The flag comes from the next vial's comparison with this one.
            de00 = vials[vial.number].compare["de00"]
            cv2.putText(panel, f"FLAG: dE00 {de00:.1f} from next vial", (56, top + 44), FONT, 0.42, (0, 0, 255), 1)
        elif vial.compare and vial.compare["de00"] is not None:
            cv2.putText(panel, f"dE00 {vial.compare['de00']:.1f} vs #{vial.compare['to_live_vial']} "
                        f"({vial.compare['zone']})", (56, top + 44), FONT, 0.4, (200, 200, 200), 1)
    return panel

