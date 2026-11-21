"""ASCE 7-16/22 §§26.10, 12.8; Euler-Bernoulli beam theory.

Wind inputs are ft/mph and output psf. Seismic coefficients are dimensionless.
Beam inputs must use a consistent force/length unit system. Verify all code
exceptions and site-specific requirements separately.
"""


def kz(z_ft, exposure="C"):
    """ASCE Table 26.10-1: 2.01(z/zg)^(2/alpha), 15 ft minimum height."""
    alpha, zg = {"B": (7.0, 1200.0), "C": (9.5, 900.0), "D": (11.5, 700.0)}[exposure.upper()]
    if z_ft < 0 or z_ft > zg:
        raise ValueError("Height must be between 0 and gradient height")
    return 2.01 * (max(z_ft, 15) / zg) ** (2 / alpha)


def wind_qz(v_mph, z_ft=30, exposure="C", kzt=1, ke=1, kd=.85):
    """ASCE 7 velocity pressure: qz=0.00256 Kz Kzt Ke Kd V² (psf)."""
    if min(v_mph, kzt, ke, kd) < 0:
        raise ValueError("Wind inputs cannot be negative")
    return .00256 * kz(z_ft, exposure) * kzt * ke * kd * v_mph ** 2


def design_spectra(ss, s1, fa, fv):
    """ASCE 7 §11.4: SDS=(2/3)Fa Ss; SD1=(2/3)Fv S1."""
    if min(ss, s1, fa, fv) < 0:
        raise ValueError("Spectral inputs cannot be negative")
    return 2 / 3 * fa * ss, 2 / 3 * fv * s1


def seismic_cs(sds, sd1, period, r, importance=1, tl=8, s1=None):
    """ASCE 7 §12.8.1.1 ELF, including long-period cap and S1>=0.6 minimum.

Pass mapped S1 to apply the high-seismic minimum. Period must already satisfy
the applicable code upper limit; special exceptions are not implemented.
"""
    if min(period, r, importance, tl) <= 0 or min(sds, sd1) < 0:
        raise ValueError("Invalid ELF parameters")
    cap = sd1 * importance / (r * period)
    if period > tl:
        cap *= tl / period
    minimum = max(.044 * sds * importance, .01)
    if s1 is not None:
        if s1 < 0:
            raise ValueError("S1 cannot be negative")
        if s1 >= .6:
            minimum = max(minimum, .5 * s1 * importance / r)
    return max(min(sds * importance / r, cap), minimum)


def base_shear(cs, weight):
    """ASCE 7 Eq.12.8-1: V=Cs W."""
    if min(cs, weight) < 0:
        raise ValueError("Negative coefficient or weight")
    return cs * weight


def vertical_distribution(shear, weights, heights, period):
    """ASCE 7 §12.8.3: Fx=V wx hx^k / Σwi hi^k; k=1..2 by period."""
    if len(weights) != len(heights) or not weights or period < 0:
        raise ValueError("Supply matching nonempty levels and nonnegative period")
    if min(weights) < 0 or min(heights) < 0 or shear < 0:
        raise ValueError("Negative load or height")
    k = 1 if period <= .5 else 2 if period >= 2.5 else 1 + (period - .5) / 2
    terms = [w * h ** k for w, h in zip(weights, heights)]
    total = sum(terms)
    if total <= 0:
        raise ValueError("Distribution denominator must be positive")
    return [shear * term / total for term in terms]


def simply_supported(load, span, elastic_modulus, inertia, kind="udl"):
    """Roark beam formulas: UDL w or centered point P; return Mmax,Vmax,delta."""
    if min(span, elastic_modulus, inertia) <= 0 or load < 0:
        raise ValueError("Invalid beam inputs")
    if kind == "udl":
        return {"moment": load * span ** 2 / 8, "shear": load * span / 2,
                "deflection": 5 * load * span ** 4 / (384 * elastic_modulus * inertia)}
    if kind == "point":
        return {"moment": load * span / 4, "shear": load / 2,
                "deflection": load * span ** 3 / (48 * elastic_modulus * inertia)}
    raise ValueError("kind must be udl or point (at midspan)")


def diaphragm_distribution(shear, tributary_widths):
    """Flexible diaphragm: distribute uniform-area lateral load by tributary width."""
    if not tributary_widths or min(tributary_widths) < 0 or sum(tributary_widths) <= 0:
        raise ValueError("Widths must be nonnegative with a positive total")
    return [shear * w / sum(tributary_widths) for w in tributary_widths]


def unit_shear(shear, length):
    """Shear flow v=V/L in consistent force/length units."""
    if length <= 0:
        raise ValueError("Length must be positive")
    return shear / length
