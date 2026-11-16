"""A table sink that keeps what it got, in place of a spreadsheet service."""

from collections.abc import Sequence

from app.contracts import ExportTable


class SheetsFake:
    id = "sheets_fake"

    def __init__(self) -> None:
        self.sent: list[tuple[str, list[ExportTable]]] = []

    def send(self, title: str, tables: Sequence[ExportTable]) -> str:
        self.sent.append((title, list(tables)))
        return f"fake://sheets/{len(self.sent)}"
