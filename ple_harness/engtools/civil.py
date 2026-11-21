"""Geotechnical/hydraulic relations: Das, Principles of Foundation Engineering;
Chow, Open-Channel Hydraulics. SI unless stated; homogeneous idealizations.
"""

import math


def consolidation(height, cc, e0, sigma0, delta_sigma, cr=None, preconsolidation=None):
    """1D primary settlement, NC/OC: H/(1+e0) ΣC log10(σ'final/σ'initial).

OC recompresses to preconsolidation stress using Cr, then virgin Cc.
All stresses must share units, and height determines settlement length units.
"""
    if min(height, cc, delta_sigma) < 0 or e0 < 0 or sigma0 <= 0:
        raise ValueError("Invalid consolidation inputs")
    final = sigma0 + delta_sigma
    if preconsolidation is None:
        return height * cc / (1 + e0) * math.log10(final / sigma0)
    if preconsolidation < sigma0 or cr is None or cr < 0:
        raise ValueError("OC requires preconsolidation>=sigma0 and nonnegative Cr")
    recompress = cr * math.log10(min(final, preconsolidation) / sigma0)
    virgin = cc * math.log10(final / preconsolidation) if final > preconsolidation else 0
    return height / (1 + e0) * (recompress + virgin)


def stress_2to1(load, width, length, depth):
    """2 vertical:1 horizontal spread: Δσ=Q/((B+z)(L+z))."""
    if min(width, length) <= 0 or min(load, depth) < 0:
        raise ValueError("Invalid load geometry")
    return load / ((width + depth) * (length + depth))


def boussinesq_point(load, radius, depth):
    """Elastic half-space σz=3Q/(2πz²)*(1+(r/z)²)^(-5/2)."""
    if depth <= 0 or min(load, radius) < 0:
        raise ValueError("Invalid point-load geometry")
    return 3 * load / (2 * math.pi * depth ** 2) * (1 + (radius / depth) ** 2) ** -2.5


def bearing_factors(phi_degrees, method="meyerhof"):
    """Return Nq,Nc,Ngamma; Meyerhof (1963) or Terzaghi (1943).

Terzaghi Ngamma uses linear interpolation of the conventional tabulated
values (Das): 0,5,...,45 deg -> 0,.5,1.2,2.5,5,9.7,19.7,42.4,100.4,297.5.
Factors alone omit shape, depth, inclination and groundwater corrections.
"""
    if not 0 <= phi_degrees <= 45 or method not in ("meyerhof", "terzaghi"):
        raise ValueError("Use phi 0..45 deg and meyerhof or terzaghi")
    p = math.radians(phi_degrees)
    if method == "meyerhof":
        nq = math.exp(math.pi * math.tan(p)) * math.tan(math.pi / 4 + p / 2) ** 2
        nc = (nq - 1) / math.tan(p) if p else math.pi + 2
        ng = (nq - 1) * math.tan(1.4 * p)
    else:
        nq = math.exp((1.5 * math.pi - p) * math.tan(p)) / (2 * math.cos(math.pi / 4 + p / 2) ** 2)
        nc = (nq - 1) / math.tan(p) if p else 1 + 1.5 * math.pi
        values = [0, .5, 1.2, 2.5, 5, 9.7, 19.7, 42.4, 100.4, 297.5]
        index = min(int(phi_degrees // 5), 8)
        ng = values[index] + (values[index + 1] - values[index]) * (phi_degrees / 5 - index)
    return {"Nq": nq, "Nc": nc, "Ngamma": ng}


def rational(c, intensity, area, units="si"):
    """Q=C i A: si uses m/s,m² -> m³/s; mm/h-ha -> m³/s; in/h-acre -> cfs."""
    if not 0 <= c <= 1 or min(intensity, area) < 0:
        raise ValueError("Invalid runoff inputs")
    factor = {"si": 1, "mm/h-ha": 1 / 360, "in/h-acre": 43560 / (12 * 3600)}[units]
    return factor * c * intensity * area


def manning(area, hydraulic_radius, slope, n, units="si"):
    """Manning Q=(1/n) A R^(2/3) S^0.5 SI, multiplier 1.486 for US ft/cfs."""
    if min(area, hydraulic_radius, slope) < 0 or n <= 0:
        raise ValueError("Invalid Manning inputs")
    if units not in ("si", "us"):
        raise ValueError("Use si or us")
    return (1 if units == "si" else 1.486) / n * area * hydraulic_radius ** (2 / 3) * math.sqrt(slope)


def broad_crested_weir(coefficient, length, head):
    """Q=C L H^1.5; caller provides dimensional C appropriate to chosen units."""
    if min(coefficient, length, head) < 0:
        raise ValueError("Invalid weir inputs")
    return coefficient * length * head ** 1.5
