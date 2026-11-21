"""AC circuit relations from standard phasor theory (e.g. Grainger, Power Analysis).

Voltages are RMS line-to-line for three phase; lengths are one-way. Tables are
provided by the caller: no NEC ampacity or installation assumptions are embedded.
"""

import math


def current(voltage, kw=None, kva=None, pf=1, phases=3):
    """I=1000*kW/(k*V*PF) or 1000*kVA/(k*V), k=√3 or 1."""
    if voltage <= 0 or not 0 < pf <= 1 or phases not in (1, 3):
        raise ValueError("Invalid voltage, PF or phase count")
    if (kw is None) == (kva is None):
        raise ValueError("Supply exactly one of kw and kva")
    apparent = kw / pf if kw is not None else kva
    if apparent < 0:
        raise ValueError("Power cannot be negative")
    return 1000 * apparent / (voltage * (math.sqrt(3) if phases == 3 else 1))


def voltage_drop(amps, length, resistance, reactance=0, pf=1, voltage=480, phases=3):
    """Approximate VD=k I L(R cosθ+X sinθ); R/X per unit length, lagging PF."""
    if min(amps, length, resistance, reactance) < 0 or voltage <= 0 or not 0 < pf <= 1 or phases not in (1, 3):
        raise ValueError("Invalid voltage-drop inputs")
    drop = (math.sqrt(3) if phases == 3 else 2) * amps * length * (
        resistance * pf + reactance * math.sqrt(1 - pf ** 2))
    return {"volts": drop, "percent": 100 * drop / voltage}


def size_conductor(amps, table, derating=1):
    """First sufficient entry in an ascending caller table of {size, ampacity}."""
    if amps < 0 or not 0 < derating <= 1:
        raise ValueError("Invalid load or derating")
    for entry in table:
        if entry["ampacity"] * derating >= amps:
            return dict(entry)
    raise ValueError("No conductor in provided table meets required ampacity")


def transformer_current(kva, voltage, phases=3):
    """Transformer full-load RMS line current."""
    return current(voltage, kva=kva, phases=phases)


def short_circuit_current(kva, voltage, percent_z):
    """Infinite-bus 3φ bolted fault: I=1000*kVA*100/(√3*V*%Z), in amperes.

The factor 1000 converts kVA to VA. Ignores motor contribution and all upstream
and cable impedance; not a complete fault/coordination study.
"""
    if percent_z <= 0:
        raise ValueError("Impedance must be positive")
    return transformer_current(kva, voltage) * 100 / percent_z
