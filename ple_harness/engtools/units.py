"""Unit conversion using exact SI definitions (NIST SP 811); US mechanical hp."""

UNITS = {
    "m": ("length", 1), "mm": ("length", .001), "cm": ("length", .01),
    "ft": ("length", .3048), "in": ("length", .0254),
    "N": ("force", 1), "kN": ("force", 1000),
    "lbf": ("force", 4.4482216152605), "kip": ("force", 4448.2216152605),
    "Pa": ("pressure", 1), "kPa": ("pressure", 1000), "MPa": ("pressure", 1e6),
    "psi": ("pressure", 6894.757293168), "ksi": ("pressure", 6894757.293168),
    "psf": ("pressure", 47.88025898034), "bar": ("pressure", 1e5),
    "N*m": ("moment", 1), "kN*m": ("moment", 1000),
    "lb*ft": ("moment", 1.3558179483314), "kip*ft": ("moment", 1355.8179483314),
    "W": ("power", 1), "kW": ("power", 1000), "hp": ("power", 745.699871582),
    "BTU/h": ("power", .293071070172), "tons": ("power", 3516.852842064),
    "m3/s": ("flow", 1), "L/s": ("flow", .001), "m3/h": ("flow", 1 / 3600),
    "gpm": ("flow", .003785411784 / 60), "cfm": ("flow", .028316846592 / 60),
    "J": ("energy", 1), "kJ": ("energy", 1000), "MJ": ("energy", 1e6),
    "kWh": ("energy", 3.6e6), "BTU": ("energy", 1055.05585262),
}


def convert(value, from_unit, to_unit):
    """Convert compatible units; temperature C/F/K is absolute, not a difference."""
    if from_unit in ("C", "F", "K") and to_unit in ("C", "F", "K"):
        c = value if from_unit == "C" else (value - 32) * 5 / 9 if from_unit == "F" else value - 273.15
        if c < -273.15:
            raise ValueError("Temperature below absolute zero")
        return c if to_unit == "C" else c * 9 / 5 + 32 if to_unit == "F" else c + 273.15
    source, target = UNITS[from_unit], UNITS[to_unit]
    if source[0] != target[0]:
        raise ValueError("Incompatible unit dimensions")
    return value * source[1] / target[1]


def temperature_difference(value, from_unit, to_unit):
    """NIST SP 811: one kelvin/Celsius interval equals 1.8 Fahrenheit intervals."""
    if from_unit not in ("C", "F", "K") or to_unit not in ("C", "F", "K"):
        raise ValueError("Use C, F or K")
    return value * (5 / 9 if from_unit == "F" else 1) * (9 / 5 if to_unit == "F" else 1)
