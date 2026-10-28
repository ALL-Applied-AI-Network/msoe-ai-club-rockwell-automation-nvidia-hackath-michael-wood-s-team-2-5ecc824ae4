"""Color conversions and color-difference metrics (no external deps beyond numpy)."""
import numpy as np

D65_WHITE = np.array([0.95047, 1.0, 1.08883])
_SRGB_TO_XYZ = np.array([[0.4124, 0.3576, 0.1805],
                         [0.2126, 0.7152, 0.0722],
                         [0.0193, 0.1192, 0.9505]])


def srgb_to_linear(rgb):
    """sRGB 0-255 -> linear 0-1 (undo display gamma)."""
    c = np.asarray(rgb, float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(lin):
    """Linear 0-1 -> sRGB 0-255 ints."""
    lin = np.clip(np.asarray(lin, float), 0, 1)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.round(c * 255).astype(int)


def srgb_to_lab(rgb):
    """sRGB 0-255 -> CIELAB (D65)."""
    xyz = _SRGB_TO_XYZ @ srgb_to_linear(rgb) / D65_WHITE
    e = (6 / 29) ** 3
    f = np.where(xyz > e, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def delta_e76(lab1, lab2):
    """CIE76: straight-line distance in Lab."""
    return float(np.linalg.norm(np.asarray(lab1, float) - np.asarray(lab2, float)))


def delta_e2000(lab1, lab2):
    """CIEDE2000 (Sharma et al. 2005 reference implementation)."""
    L1, a1, b1 = map(float, lab1)
    L2, a2, b2 = map(float, lab2)
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2))
    Lbp = (L1 + L2) / 2
    Cbp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    T = (1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp))
         + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63)))
    dtheta = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    Sc = 1 + 0.045 * Cbp
    Sh = 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * dtheta)) * Rc
    return float(np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                         + Rt * (dCp / Sc) * (dHp / Sh)))


def color_distance(rgb1, rgb2, metric="de2000"):
    l1, l2 = srgb_to_lab(rgb1), srgb_to_lab(rgb2)
    return delta_e2000(l1, l2) if metric == "de2000" else delta_e76(l1, l2)
