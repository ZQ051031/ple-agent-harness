"""Calculation-package formatting; no numerical formulas or external dependencies."""


def markdown_table(headers, rows):
    """Escape pipes/newlines and render a rectangular GitHub-style Markdown table."""
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", "<br>")
    headers = list(headers)
    if not headers:
        raise ValueError("Supply headers")
    lines = [headers, ["---"] * len(headers)]
    for row in rows:
        row = list(row)
        if len(row) != len(headers):
            raise ValueError("Row width does not match headers")
        lines.append(row)
    return "\n".join("| " + " | ".join(cell(c) for c in row) + " |" for row in lines)


class CalcLog:
    """Record description, formula, inputs and result with units for audit."""
    def __init__(self, title="Calculation package"):
        self.title = title
        self.entries = []

    def record(self, description, formula, inputs, result, units=""):
        self.entries.append((description, formula, inputs, result, units))
        return result

    def render(self):
        return "# " + self.title + "\n\n" + markdown_table(
            ["Description", "Formula", "Inputs", "Result", "Units"], self.entries)
