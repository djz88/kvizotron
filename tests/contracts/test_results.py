import pytest

from app.kernel import registry
from app.plugins.results.manifest import MANIFEST
from app.plugins.results.ranking import LocalResultView
from tests.contracts.result_view import ResultViewContract


class TestLocalResultView(ResultViewContract):
    view = LocalResultView()


@pytest.mark.django_db
def test_registered_under_the_port():
    assert isinstance(registry.get("result_view", "local"), LocalResultView)


def test_every_setting_is_run_wide_with_a_reason():
    from app.contracts import RESULT_KEYS, SCOREBOARD_RUNS

    found = {item["key"]: item for item in MANIFEST["settings"]}
    # The run copies all but the boards the quiz page offers, which is read live (AC-176).
    assert set(found) == {*RESULT_KEYS, SCOREBOARD_RUNS}
    assert SCOREBOARD_RUNS not in RESULT_KEYS
    for item in found.values():
        assert item["scopes"] == ["global", "quiz"]
        assert item["scope_reason"]
        assert item["default"] in item["choices"]
