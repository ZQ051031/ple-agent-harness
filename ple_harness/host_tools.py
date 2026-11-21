"""Serve-side document processing; task files move only through the session."""

import csv
import io
import json
import posixpath
import re
import shlex
import zipfile
from xml.etree import ElementTree as ET

from docx import Document
from docx.shared import Pt
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from pypdf import PdfReader

LIMIT = 10_000_000
CHUNK = 5_000_000
ROW_CAP = 1000
EXPANDED_LIMIT = 100_000_000


class HostTools:
    def __init__(self, session):
        self.session = session

    def path(self, path):
        return path if posixpath.isabs(path) else posixpath.join(self.session.workdir, path)

    async def _read(self, path):
        path = self.path(path)
        command = "python3 -c " + shlex.quote(
            "import os; print(os.path.getsize(" + repr(path) + "))"
        )
        result = await self.session.exec(command, timeout_sec=30)
        if result["exit_code"]:
            raise ValueError("Cannot stat file: " + result["output"])
        size = int(result["output"].strip())
        if size > LIMIT:
            raise ValueError(f"File is {size} bytes (>10 MB); use container-side processing via bash.")
        data = await self.session.read_file(path)
        if len(data) > LIMIT:
            raise ValueError(f"File is {len(data)} bytes (>10 MB); use container-side processing via bash.")
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(i.file_size for i in archive.infolist()) > EXPANDED_LIMIT:
                    raise ValueError("Expanded ZIP exceeds 100 MB; use container-side processing via bash.")
        return data

    async def _upload(self, path, data):
        for start in range(0, max(1, len(data)), CHUNK):
            await self.session.write_file(self.path(path), data[start:start + CHUNK], append=start > 0)
        return f"Wrote {path} ({len(data)} bytes)"

    async def extract_text(self, path, pages=None, max_chars=30000):
        """PDF pages are optional 1-based page numbers; spreadsheet rows cap at 1000/sheet."""
        if not isinstance(max_chars, int) or not 1 <= max_chars <= 200000:
            raise ValueError("max_chars must be between 1 and 200000")
        data = await self._read(path)
        ext = posixpath.splitext(path)[1].lower()
        out = []
        if ext == ".pdf":
            pdf = PdfReader(io.BytesIO(data))
            selected = range(1, len(pdf.pages) + 1) if pages is None else pages
            for page in selected:
                if not isinstance(page, int) or not 1 <= page <= len(pdf.pages):
                    raise ValueError("pages must contain valid 1-based page numbers")
                out.append(f"[Page {page}]\n" + (pdf.pages[page - 1].extract_text() or ""))
        elif ext == ".docx":
            doc = Document(io.BytesIO(data))
            out.extend(p.text for p in doc.paragraphs)
            for table in doc.tables:
                out.extend(" | ".join(c.text for c in row.cells) for row in table.rows)
        elif ext in (".xlsx", ".xlsm"):
            formulas = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
            cached = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            try:
                for sheet in formulas:
                    stream = io.StringIO()
                    writer = csv.writer(stream)
                    out.append(f"[Sheet: {sheet.title}; first {ROW_CAP} rows maximum]")
                    values = cached[sheet.title].iter_rows(max_row=ROW_CAP, values_only=True)
                    for row, cache in zip(sheet.iter_rows(max_row=ROW_CAP), values):
                        writer.writerow([
                            f"{c.value} [cached: {v if v is not None else 'unavailable'}]"
                            if c.data_type == "f" else c.value
                            for c, v in zip(row, cache)
                        ])
                    out.append(stream.getvalue())
            finally:
                formulas.close()
                cached.close()
        elif ext == ".pptx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                slides = sorted(
                    (n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                    key=lambda n: int(re.search(r"slide(\d+)\.xml", n).group(1)),
                )
                for n in slides:
                    root = ET.fromstring(archive.read(n))
                    out.append(f"[{n}]\n" + "\n".join(
                        node.text or "" for node in root.iter()
                        if node.tag == "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
                    ))
        elif ext in (".csv", ".txt", ".md", ".json"):
            out.append(data.decode("utf-8-sig", errors="replace"))
        else:
            return "error: unsupported format; inspect with bash in the task container"
        text = "\n".join(out)
        return text[:max_chars] + ("\n[truncated]" if len(text) > max_chars else "")

    @staticmethod
    def _inline(paragraph, text):
        for token in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", text):
            bold = token.startswith("**") and token.endswith("**")
            italic = not bold and token.startswith("*") and token.endswith("*")
            run = paragraph.add_run(token[2:-2] if bold else token[1:-1] if italic else token)
            run.bold, run.italic = bold, italic

    async def write_docx(self, path, markdown):
        doc = Document()
        code = False
        table_lines = []

        def flush_table():
            if not table_lines:
                return
            rows = [[v.strip() for v in line.strip().strip("|").split("|")] for line in table_lines]
            rows = [row for row in rows if not all(re.fullmatch(r":?-+:?", c) for c in row)]
            if rows:
                table = doc.add_table(rows=0, cols=max(map(len, rows)))
                table.style = "Table Grid"
                for row in rows:
                    cells = table.add_row().cells
                    for cell, value in zip(cells, row):
                        self._inline(cell.paragraphs[0], value)
            table_lines.clear()

        for line in markdown.splitlines():
            if not code and "|" in line:
                table_lines.append(line)
                continue
            flush_table()
            if line.startswith("```"):
                code = not code
                continue
            if code:
                run = doc.add_paragraph().add_run(line)
                run.font.name, run.font.size = "Courier New", Pt(9)
            elif line.strip():
                heading = re.match(r"^(#{1,3})\s+(.+)", line)
                bullet = re.match(r"^\s*[-*+]\s+(.+)", line)
                numbered = re.match(r"^\s*\d+[.)]\s+(.+)", line)
                if heading:
                    p = doc.add_heading(level=len(heading[1]))
                    self._inline(p, heading[2])
                else:
                    p = doc.add_paragraph(style="List Bullet" if bullet else "List Number" if numbered else None)
                    self._inline(p, (bullet or numbered)[1] if bullet or numbered else line)
        flush_table()
        stream = io.BytesIO()
        doc.save(stream)
        return await self._upload(path, stream.getvalue())

    async def write_xlsx(self, path, sheets):
        if not sheets:
            raise ValueError("Provide at least one sheet")
        book = Workbook()
        book.remove(book.active)
        for spec in sheets:
            name = spec["name"]
            if not name or len(name) > 31 or re.search(r"[\\/*?:\[\]]", name):
                raise ValueError("Invalid sheet name")
            if name.casefold() in {s.casefold() for s in book.sheetnames}:
                raise ValueError("Duplicate sheet name")
            sheet = book.create_sheet(name)
            for row in spec["rows"]:
                if any(v is not None and not isinstance(v, (str, int, float)) for v in row):
                    raise ValueError("Cell values must be numbers, strings or null")
                sheet.append(row)
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            for index, width in enumerate(spec.get("column_widths", []), 1):
                if width <= 0:
                    raise ValueError("Column widths must be positive")
                sheet.column_dimensions[get_column_letter(index)].width = width
        stream = io.BytesIO()
        book.save(stream)
        return await self._upload(path, stream.getvalue())

    async def inspect_office(self, path):
        data = await self._read(path)
        ext = posixpath.splitext(path)[1].lower()
        if ext == ".docx":
            doc = Document(io.BytesIO(data))
            result = {"paragraphs": len(doc.paragraphs), "tables": len(doc.tables),
                      "first_lines": [p.text for p in doc.paragraphs[:10]]}
        elif ext in (".xlsx", ".xlsm"):
            book = load_workbook(io.BytesIO(data), data_only=False, read_only=True)
            cached = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
            result = {"sheets": [], "errors": []}
            try:
                for sheet in book:
                    count = 0
                    for row in sheet:
                        for cell in row:
                            count += cell.data_type == "f"
                            if cell.data_type == "e":
                                result["errors"].append(f"{sheet.title}!{cell.coordinate}: {cell.value}")
                    for row in cached[sheet.title]:
                        for cell in row:
                            if cell.data_type == "e":
                                item = f"{sheet.title}!{cell.coordinate}: {cell.value}"
                                if item not in result["errors"]:
                                    result["errors"].append(item)
                    result["sheets"].append({"name": sheet.title, "rows": sheet.max_row,
                                             "columns": sheet.max_column, "formulas": count})
            finally:
                book.close()
                cached.close()
        elif ext == ".pdf":
            result = {"pages": len(PdfReader(io.BytesIO(data)).pages)}
        elif zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                result = {"files": archive.namelist()}
        else:
            return "error: unsupported format; inspect with bash"
        return json.dumps(result, ensure_ascii=False)
