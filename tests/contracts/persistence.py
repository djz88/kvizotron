import pytest
from django.db import transaction

from app.contracts import PersistenceProvider
from app.kernel.models import AuditEvent


class PersistenceContract:
    """Subclasses set `provider`."""

    provider: PersistenceProvider

    def test_satisfies_protocol(self):
        assert isinstance(self.provider, PersistenceProvider)

    def test_settings_name_an_engine_and_database(self):
        database = self.provider.database_settings()
        assert database["ENGINE"]
        assert database["NAME"]

    def test_healthcheck_true_on_a_working_database(self, db):
        assert self.provider.healthcheck() is True

    def test_transaction_rolls_back(self, transactional_db):
        with pytest.raises(ZeroDivisionError), transaction.atomic():
            AuditEvent.objects.create(actor_type="test", action="x", entity_type="x", entity_id="x")
            raise ZeroDivisionError
        assert not AuditEvent.objects.exists()
