"""Original synthetic checks; requires only the task's Python stdlib."""
import json
import math
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def check(root):
    answer = json.loads((root / "answer.json").read_text())
    assert math.isclose(answer["current_a"], 100000 / (math.sqrt(3) * 480 * 0.9), rel_tol=1e-5)
    assert answer["power_kw"] == 100
    assert answer["voltage_ll_v"] == 480
    assert answer["power_factor"] == 0.9
    with zipfile.ZipFile(root / "result.docx") as doc:
        xml = ElementTree.fromstring(doc.read("word/document.xml"))
    text = " ".join(xml.itertext())
    for value in ("100000", "480", "0.9", "133.646 A", "Assumptions", "balanced", "line-line"):
        assert value in text, value
    print("PASS: result.docx + answer.json present; current = 133.646 A; document content checked")


if __name__ == "__main__":
    check(Path(sys.argv[1] if len(sys.argv) > 1 else "/output"))
