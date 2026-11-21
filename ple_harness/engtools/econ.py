"""Discrete end-of-period engineering economics (Blank & Tarquin).

Rates are fractions per period; cash inflows positive, costs positive for LCC.
"""


def sppw(rate, periods):
    """Single-payment present worth P/F=(1+i)^(-n)."""
    if rate <= -1 or periods < 0:
        raise ValueError("Require i>-1, n>=0")
    return (1 + rate) ** -periods


def upv(rate, periods):
    """Uniform-series present worth P/A=[1-(1+i)^(-n)]/i."""
    if rate <= -1 or periods < 0:
        raise ValueError("Require i>-1, n>=0")
    return periods if rate == 0 else (1 - sppw(rate, periods)) / rate


def uca(rate, periods):
    """Uniform capital recovery A/P, reciprocal of P/A."""
    if periods <= 0:
        raise ValueError("Require n>0")
    return 1 / upv(rate, periods)


def npv(rate, cashflows):
    """NPV=ΣCFt/(1+i)^t; first entry is at time zero."""
    if rate <= -1:
        raise ValueError("Require i>-1")
    return sum(value * sppw(rate, t) for t, value in enumerate(cashflows))


def life_cycle_cost(initial, annual_cost, years, discount, escalation=0, salvage=0):
    """LCC=initial+Σ annual_cost*(1+g)^(t-1)/(1+i)^t - salvage/(1+i)^n.

annual_cost is the first end-of-year payment, salvage is nominal final-year value.
"""
    if not isinstance(years, int) or years < 0 or escalation <= -1 or discount <= -1:
        raise ValueError("Invalid years or rates")
    return initial + sum(annual_cost * (1 + escalation) ** (t - 1) * sppw(discount, t)
                         for t in range(1, years + 1)) - salvage * sppw(discount, years)


def simple_payback(investment, annual_savings):
    """Undiscounted payback=investment/annual_savings, in periods."""
    if investment < 0 or annual_savings <= 0:
        raise ValueError("Require nonnegative investment and positive savings")
    return investment / annual_savings
