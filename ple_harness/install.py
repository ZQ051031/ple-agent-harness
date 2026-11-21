"""Upload the standalone stdlib engineering package to the task container."""

from pathlib import Path


async def install_engtools(session):
    for source in sorted((Path(__file__).parent / "engtools").glob("*.py")):
        await session.write_file("/tmp/ple_work/engtools/" + source.name, source.read_bytes())
    return (
        "Engineering helpers installed at /tmp/ple_work/engtools (Python 3.8+ stdlib only). "
        "Use PYTHONPATH=/tmp/ple_work python3 script.py, then "
        "from engtools import units, structural, electrical, mechanical, civil, econ, report. "
        "Use help(module) and help(function) for units, source formulas and assumptions. "
        "Defaults are SI except wind (mph/ft/psf) and explicit HVAC US-unit helpers. "
        "These are preliminary formulas, not complete code checks; verify applicability. "
        "report.CalcLog records description/formula/inputs/result/units and renders Markdown."
    )
