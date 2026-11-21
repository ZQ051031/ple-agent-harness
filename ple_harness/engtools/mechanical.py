"""Fluid/thermal relations: Incropera heat transfer; Crane TP-410; SI by default."""

import math


def heat_rate(mass_flow, cp, delta_t):
    """Q=ṁ cp ΔT; kg/s, J/(kg K), K -> W (signed)."""
    if mass_flow < 0 or cp <= 0:
        raise ValueError("Invalid flow or heat capacity")
    return mass_flow * cp * delta_t


def water_gpm(btuh, delta_f):
    """HVAC water approximation BTU/h=500*gpm*Δ°F, near room temperature."""
    if delta_f <= 0:
        raise ValueError("Temperature difference must be positive")
    return btuh / (500 * delta_f)


def air_cfm(btuh, delta_f):
    """Sensible standard-air approximation BTU/h=1.08*cfm*Δ°F."""
    if delta_f <= 0:
        raise ValueError("Temperature difference must be positive")
    return btuh / (1.08 * delta_f)


def reynolds(density, velocity, diameter, viscosity):
    """Re=ρVD/μ, dynamic viscosity in Pa s."""
    if min(density, diameter, viscosity) <= 0:
        raise ValueError("Properties and diameter must be positive")
    return density * abs(velocity) * diameter / viscosity


def friction_factor(re, relative_roughness=0, method="swamee-jain"):
    """Darcy f: 64/Re laminar; Swamee-Jain (1976) or Colebrook (1939).

Reject transitional Re=2300..4000, for which no unique steady correlation exists.
"""
    if re <= 0 or not 0 <= relative_roughness < .1:
        raise ValueError("Invalid Reynolds number or relative roughness")
    if method not in ("swamee-jain", "colebrook"):
        raise ValueError("Unknown friction-factor method")
    if re < 2300:
        return 64 / re
    if re < 4000:
        raise ValueError("Transitional flow: correlation is uncertain")
    f = .25 / math.log10(relative_roughness / 3.7 + 5.74 / re ** .9) ** 2
    if method == "colebrook":
        for _ in range(100):
            new = 1 / (-2 * math.log10(relative_roughness / 3.7 + 2.51 / (re * math.sqrt(f)))) ** 2
            if abs(new - f) < 1e-12:
                return new
            f = new
        raise ValueError("Colebrook iteration did not converge")
    return f


def darcy_head_loss(f, length, diameter, velocity, gravity=9.80665):
    """Darcy-Weisbach h=f(L/D)V²/(2g), metres with SI inputs."""
    if min(f, length) < 0 or min(diameter, gravity) <= 0:
        raise ValueError("Invalid pipe inputs")
    return f * length / diameter * velocity ** 2 / (2 * gravity)


def hazen_williams(flow, length, diameter, c=130):
    """SI Hazen-Williams h=10.67 L Q^1.852/(C^1.852 D^4.87), water only."""
    if min(flow, length) < 0 or min(diameter, c) <= 0:
        raise ValueError("Invalid pipe inputs")
    return 10.67 * length * flow ** 1.852 / (c ** 1.852 * diameter ** 4.87)


def pump_power(flow, head, efficiency=1, density=1000, gravity=9.80665):
    """Hydraulic/brake W = ρgQH and ρgQH/η; Q m³/s, H m."""
    if min(flow, head) < 0 or min(density, gravity) <= 0 or not 0 < efficiency <= 1:
        raise ValueError("Invalid pump inputs")
    hydraulic = density * gravity * flow * head
    return {"hydraulic_w": hydraulic, "brake_w": hydraulic / efficiency}


def lmtd(delta_t1, delta_t2):
    """Log mean terminal ΔT=(ΔT1-ΔT2)/ln(ΔT1/ΔT2); positive differences."""
    if min(delta_t1, delta_t2) <= 0:
        raise ValueError("Terminal differences must be positive (no crossing)")
    if math.isclose(delta_t1, delta_t2, rel_tol=1e-10):
        return (delta_t1 + delta_t2) / 2
    return (delta_t1 - delta_t2) / math.log(delta_t1 / delta_t2)


def effectiveness_ntu(ntu, capacity_ratio, arrangement="counterflow"):
    """Incropera ε-NTU for counterflow/parallel flow, Cr=Cmin/Cmax."""
    if ntu < 0 or not 0 <= capacity_ratio <= 1:
        raise ValueError("Require NTU>=0 and 0<=Cr<=1")
    cr = capacity_ratio
    if arrangement == "parallel":
        return -math.expm1(-ntu * (1 + cr)) / (1 + cr)
    if arrangement != "counterflow":
        raise ValueError("Use counterflow or parallel")
    if cr == 1:
        return ntu / (1 + ntu)
    e = math.exp(-ntu * (1 - cr))
    return (1 - e) / (1 - cr * e)
