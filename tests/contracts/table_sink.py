"""Shared contract suite: every table sink module must pass it."""

import copy

from app.contracts import ExportTable, TableSinkProvider


def sample_table() -> ExportTable:
    return ExportTable(
        name="attempts",
        columns=["run", "revision", "score"],
        headers=["Běh", "Revize", "Skóre"],
        rows=[{"run": "1", "revision": "2", "score": "3,5"}],
        numeric=frozenset({"score"}),
    )


class TableSinkSuite:
    def __init__(self, sink: object) -> None:
        self.sink = sink

    def run(self) -> None:
        self.satisfies_the_port()
        self.send_says_where_and_leaves_tables_alone()

    def satisfies_the_port(self) -> None:
        assert isinstance(self.sink, TableSinkProvider)
        assert isinstance(self.sink.id, str) and self.sink.id

    def send_says_where_and_leaves_tables_alone(self) -> None:
        assert isinstance(self.sink, TableSinkProvider)
        table = sample_table()
        before = copy.deepcopy(table)
        where = self.sink.send("t", [table])
        assert isinstance(where, str) and where
        assert table == before
