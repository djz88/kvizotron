"""The retention provider through its contract."""

import pytest

from app.kernel import registry
from app.kernel.discovery import installed_modules
from tests.contracts.retention import RetentionSuite


@pytest.mark.django_db
def test_local_retention_passes_the_suite():
    RetentionSuite(registry.get("retention", "local")).run()


def test_manifest_states_no_settings_and_its_port():
    manifest = next(m for m in installed_modules() if m.id == "retention.local")
    assert manifest.settings == []
    assert list(manifest.provides) == ["retention"]


def test_the_triggers_the_domain_sends_are_the_ones_the_provider_takes():
    from app.domain import retention
    from app.providers.retention.models import RetentionJob

    sent = {retention.AUTOMATIC, retention.MANUAL, retention.ERASURE}
    assert sent == set(RetentionJob.Trigger.values)
