"""Textbook checks; isolated unittest-compatible runner also works without pytest."""

import ast
import importlib
import math
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1] / "ple_harness"
sys.path.insert(0, str(ROOT))
from engtools import civil, econ, electrical, mechanical, report, structural, units  # noqa: E402


class EngineeringTests(unittest.TestCase):
    def test_wind(self):
        kz = 2.01 * (30 / 900) ** (2 / 9.5)
        self.assertAlmostEqual(structural.kz(30), kz)
        self.assertAlmostEqual(structural.wind_qz(115), .00256 * kz * .85 * 115 ** 2)
        self.assertAlmostEqual(kz, .98, delta=.01)
        self.assertEqual(structural.kz(0), structural.kz(15))

    def test_structures(self):
        self.assertEqual(structural.design_spectra(1.5, .6, 1, 1.5), (1, .6))
        self.assertAlmostEqual(structural.seismic_cs(1, .6, 1, 5), .12)
        self.assertAlmostEqual(structural.seismic_cs(.1, .01, 20, 5, s1=.8), .08)
        self.assertEqual(structural.base_shear(.1, 1000), 100)
        self.assertEqual(structural.vertical_distribution(300, [1, 1], [1, 2], .5), [100, 200])
        beam = structural.simply_supported(10, 6, 200e9, 1e-4)
        self.assertEqual(beam["moment"], 45)
        self.assertEqual(beam["shear"], 30)
        self.assertAlmostEqual(beam["deflection"], 5 * 10 * 6 ** 4 / (384 * 200e9 * 1e-4))
        self.assertEqual(structural.simply_supported(10, 6, 1, 1, "point")["moment"], 15)
        self.assertEqual(structural.diaphragm_distribution(90, [1, 2]), [30, 60])
        self.assertEqual(structural.unit_shear(100, 10), 10)

    def test_electrical(self):
        self.assertAlmostEqual(electrical.current(480, kw=100, pf=.9), 133.6459, places=3)
        self.assertEqual(electrical.current(240, kva=24, phases=1), 100)
        self.assertAlmostEqual(electrical.short_circuit_current(1000, 480, 5.75), 20918.5, delta=1)
        self.assertAlmostEqual(electrical.transformer_current(100, 480), 120.2813, places=3)
        vd = electrical.voltage_drop(100, 100, .0002, phases=1, voltage=240)
        self.assertEqual(vd["volts"], 4)
        self.assertAlmostEqual(vd["percent"], 100 * 4 / 240)
        table = [{"size": "a", "ampacity": 100}, {"size": "b", "ampacity": 200}]
        self.assertEqual(electrical.size_conductor(110, table)["size"], "b")
        with self.assertRaises(ValueError):
            electrical.size_conductor(201, table)

    def test_mechanical(self):
        self.assertAlmostEqual(mechanical.friction_factor(1e5, .0002), .0190, delta=.0190 * .02)
        self.assertAlmostEqual(mechanical.friction_factor(1e5, .0002, "colebrook"), .0190, delta=.0001)
        self.assertAlmostEqual(mechanical.friction_factor(1000), .064)
        self.assertEqual(mechanical.heat_rate(2, 4180, 10), 83600)
        self.assertEqual(mechanical.water_gpm(100000, 20), 10)
        self.assertAlmostEqual(mechanical.air_cfm(10800, 10), 1000)
        self.assertEqual(mechanical.reynolds(1000, 1, .1, .001), 100000)
        self.assertAlmostEqual(mechanical.darcy_head_loss(.02, 100, .1, 2), 4.07886, places=4)
        self.assertAlmostEqual(mechanical.hazen_williams(.01, 100, .1, 130), 1.9017, places=4)
        self.assertAlmostEqual(mechanical.pump_power(.01, 10, .8)["brake_w"], 1225.83125)
        self.assertAlmostEqual(mechanical.lmtd(60, 30), 43.280851, places=5)
        self.assertEqual(mechanical.lmtd(30, 30), 30)
        self.assertEqual(mechanical.effectiveness_ntu(1, 1), .5)
        self.assertEqual(mechanical.effectiveness_ntu(0, .5), 0)

    def test_civil(self):
        self.assertAlmostEqual(civil.consolidation(4, .3, .8, 100, 100),
                               4 * .3 / 1.8 * math.log10(2))
        self.assertAlmostEqual(civil.consolidation(4, .3, .8, 100, 100, .05, 150),
                               4 / 1.8 * (.05 * math.log10(1.5) + .3 * math.log10(200 / 150)))
        self.assertEqual(civil.stress_2to1(1000, 2, 3, 2), 50)
        self.assertAlmostEqual(civil.boussinesq_point(100, 0, 2), 300 / (8 * math.pi))
        self.assertAlmostEqual(civil.bearing_factors(30)["Nq"], 18.4011, places=3)
        self.assertAlmostEqual(civil.bearing_factors(30, "terzaghi")["Ngamma"], 19.7)
        self.assertAlmostEqual(civil.bearing_factors(0)["Nc"], 5.14159, places=4)
        self.assertEqual(civil.rational(.9, 100, 4, "mm/h-ha"), 1)
        self.assertEqual(civil.manning(2, 1, .0001, .02), 1)
        self.assertEqual(civil.broad_crested_weir(1.7, 2, 1), 3.4)

    def test_econ_units_report(self):
        self.assertAlmostEqual(econ.sppw(.1, 2), 1 / 1.21)
        self.assertAlmostEqual(econ.upv(.1, 10) * econ.uca(.1, 10), 1)
        self.assertEqual(econ.upv(0, 10), 10)
        self.assertEqual(econ.npv(0, [-100, 60, 60]), 20)
        self.assertEqual(econ.life_cycle_cost(1000, 100, 2, 0, .1, 50), 1160)
        self.assertEqual(econ.simple_payback(1000, 100), 10)
        self.assertAlmostEqual(units.convert(1, "ksi", "MPa"), 6.894757293168)
        self.assertEqual(units.convert(32, "F", "C"), 0)
        self.assertEqual(units.temperature_difference(18, "F", "K"), 10)
        self.assertAlmostEqual(units.convert(1, "tons", "BTU/h"), 12000)
        log = report.CalcLog()
        self.assertEqual(log.record("Test", "a*b", {"a": 2}, 4, "N"), 4)
        self.assertIn("Calculation package", log.render())
        self.assertIn("N", log.render())
        self.assertIn("\\|", report.markdown_table(["a"], [["x|y"]]))

    def test_invalid_and_empty(self):
        for function, args in [
            (structural.kz, (-1,)), (structural.vertical_distribution, (1, [], [], 1)),
            (electrical.current, (0,)), (mechanical.lmtd, (0, 1)),
            (mechanical.friction_factor, (3000,)), (civil.consolidation, (1, .3, .5, 0, 1)),
            (econ.simple_payback, (1, 0)), (units.convert, (1, "m", "N")),
            (report.markdown_table, ([], [])),
        ]:
            with self.subTest(function=function.__name__), self.assertRaises(ValueError):
                function(*args)
        self.assertEqual(econ.npv(.1, []), 0)
        self.assertEqual(structural.wind_qz(0), 0)

    def test_isolated_stdlib_imports(self):
        for path in (ROOT / "engtools").glob("*.py"):
            ast.parse(path.read_text(), feature_version=(3, 8))
            name = "engtools" if path.stem == "__init__" else "engtools." + path.stem
            result = subprocess.run(
                ["/usr/bin/python3", "-I", "-S", "-c",
                 f"import sys; sys.path.insert(0, {str(ROOT)!r}); import {name}"],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            importlib.import_module(name)


if __name__ == "__main__":
    unittest.main()
