import asyncio
import io
import json
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from ple_harness.host_tools import CHUNK, HostTools
from ple_harness.install import install_engtools
from ple_harness.tools import ToolDispatcher
from test_core import FakeSession


def test_roundtrip(tmp_path):
    async def scenario():
        session = FakeSession(tmp_path)
        host = HostTools(session)
        dispatcher = ToolDispatcher(session)
        dispatcher.register_host(host)
        markdown = "# Report\nA **bold** and *italic* paragraph with $x$.\n- Item\n1. Step\n| Part | Value |\n| --- | --- |\n| Beam | 12 |\n```python\nprint(1)\n```"
        assert "Wrote" in await dispatcher("write_docx", {"path": "out.docx", "markdown": markdown})
        text = await host.extract_text("out.docx")
        for expected in ("Report", "bold", "italic", "$x$", "Beam | 12", "print(1)"):
            assert expected in text
        inspection = json.loads(await host.inspect_office("out.docx"))
        assert inspection["tables"] == 1
        assert inspection["paragraphs"] >= 5
        await host.write_xlsx("out.xlsx", [{"name": "Calc", "rows": [
            ["Name", "Value"], ["Load", 12], ["Total", "=B2*2"], ["Bad", "#REF!"]],
            "column_widths": [20, 15]}])
        text = await host.extract_text("out.xlsx")
        assert "Load,12" in text and "=B2*2 [cached: unavailable]" in text
        inspection = json.loads(await host.inspect_office("out.xlsx"))
        assert inspection["sheets"][0]["formulas"] == 1
        assert "#REF!" in inspection["errors"][0]
        assert "error:" in await dispatcher("extract_text", {"path": "absent.docx"})
        assert "error:" in await dispatcher("write_xlsx", {"path": "x", "sheets": []})
        await host.write_docx("empty.docx", "")
        assert await host.extract_text("empty.docx") == ""
        assert "error:" in await dispatcher("extract_text", {"path": "out.docx", "max_chars": 0})
    asyncio.run(scenario())


def test_other_formats_and_limits(tmp_path):
    async def scenario():
        session = FakeSession(tmp_path)
        host = HostTools(session)
        (tmp_path / "data.txt").write_text("hello world")
        assert await host.extract_text("data.txt", max_chars=5) == "hello\n[truncated]"
        (tmp_path / "unknown.bin").write_bytes(b"abc")
        assert "bash" in await host.extract_text("unknown.bin")
        (tmp_path / "broken.docx").write_bytes(b"invalid zip")
        dispatcher = ToolDispatcher(session)
        dispatcher.register_host(host)
        assert "error:" in await dispatcher("extract_text", {"path": "broken.docx"})
        with (tmp_path / "big.txt").open("wb") as stream:
            stream.truncate(10_000_001)
        with pytest.raises(ValueError, match="10000001 bytes"):
            await host.extract_text("big.txt")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("ppt/slides/slide1.xml",
                '<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>Slide text</a:t></a:p>')
        (tmp_path / "slides.pptx").write_bytes(stream.getvalue())
        assert "Slide text" in await host.extract_text("slides.pptx")
        assert "ppt/slides/slide1.xml" in await host.inspect_office("slides.pptx")
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with (tmp_path / "blank.pdf").open("wb") as stream:
            writer.write(stream)
        assert json.loads(await host.inspect_office("blank.pdf"))["pages"] == 1
        assert "[Page 1]" in await host.extract_text("blank.pdf", pages=[1])
        with pytest.raises(ValueError, match="1-based"):
            await host.extract_text("blank.pdf", pages=[2])
    asyncio.run(scenario())


def test_chunking_and_installer(tmp_path):
    class RecordingSession(FakeSession):
        def __init__(self, directory):
            super().__init__(directory)
            self.writes = []

        async def write_file(self, path, data, append=False):
            self.writes.append((path, len(data), append))
            if path.startswith("/tmp/ple_work/"):
                path = str(tmp_path / Path(path).name)
            return await super().write_file(path, data, append)

    async def scenario():
        session = RecordingSession(tmp_path)
        host = HostTools(session)
        await host._upload("large", b"x" * (CHUNK + 1))
        assert [w[1:] for w in session.writes] == [(CHUNK, False), (1, True)]
        assert (tmp_path / "large").stat().st_size == CHUNK + 1
        doc = await install_engtools(session)
        assert "PYTHONPATH=/tmp/ple_work" in doc
        assert (tmp_path / "mechanical.py").exists()
        assert len([w for w in session.writes if w[0].startswith("/tmp/ple_work/engtools/")]) == 8
    asyncio.run(scenario())
