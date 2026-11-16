"""The table sink contract, through the fake the export tests use."""

from tests.contracts.table_sink import TableSinkSuite, sample_table
from tests.support.sheets_fake import SheetsFake


def test_fake_passes_suite():
    """AC-109."""
    fake = SheetsFake()
    TableSinkSuite(fake).run()
    assert fake.sent == [("t", [sample_table()])]
