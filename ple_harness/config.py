"""Validated orchestration settings; each field maps to PLE_<UPPERCASE_NAME>."""

from dataclasses import dataclass, fields
import math
import os


@dataclass(frozen=True)
class Config:
    default_total_seconds: float = 3600
    recon_share: float = .12
    execute_share: float = .55
    verify_share: float = .15
    fix_share: float = .65
    min_phase_seconds: float = 120
    final_reserve_seconds: float = 90
    final_reserve_share: float = .03
    finalize_seconds: float = 90
    final_check_seconds: float = 30
    setup_seconds: float = 60
    max_fix_rounds: int = 2

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field.name} must be finite and nonnegative")
        if self.default_total_seconds <= 0 or self.min_phase_seconds <= 0 or self.finalize_seconds <= 0:
            raise ValueError("Total, minimum phase and finalization durations must be positive")
        for name in ("recon_share", "execute_share", "verify_share", "fix_share", "final_reserve_share"):
            if getattr(self, name) > 1:
                raise ValueError(f"{name} must be <=1")
        if self.recon_share > .12 or self.verify_share > .15:
            raise ValueError("Recon and verify shares cannot exceed .12 and .15")
        if not isinstance(self.max_fix_rounds, int):
            raise ValueError("max_fix_rounds must be an integer")

    @classmethod
    def from_env(cls, environ=None):
        environ = os.environ if environ is None else environ
        values = {}
        for field in fields(cls):
            key = "PLE_" + field.name.upper()
            if key in environ:
                values[field.name] = (int if field.name == "max_fix_rounds" else float)(environ[key])
        return cls(**values)
