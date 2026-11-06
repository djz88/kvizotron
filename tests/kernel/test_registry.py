import pytest
from django.test import override_settings

from app.contracts import ScoreBreakdown
from app.kernel import registry
from app.kernel.errors import StartupError
from app.kernel.manifest import Manifest


class GoodQuestion:
    id = "good"
    version = "1.0.0"

    def config_schema(self):
        return {}

    def answer_schema(self):
        return {}

    def available_scoring_strategies(self):
        return []

    def validate_definition(self, config, locale):
        return None

    def validate_submission(self, config, answer):
        return None

    def parse_admin(self, form, locales):
        return {}

    def render_admin(self, config, locales):
        return ""

    def render_public(self, public_config, locale):
        return ""

    def public_payload(self, config, locale):
        return {}


class GoodScoring:
    id = "basic"
    version = "1.0.0"

    def supports(self, question_type_id):
        return True

    def max_score(self, definition, settings):
        return 1.0

    def evaluate(self, definition, answer, settings):
        return ScoreBreakdown(1.0, 1.0, 1, {})


MODULE = Manifest(
    id="mod.a",
    kind="plugin",
    version="1.0.0",
    app="x.y",
    api_compatibility=">=1.0",
    provides=["question_type"],
)


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setattr(registry, "_ports", {})


@pytest.fixture
def module():
    with override_settings(KVZ_MODULES=[MODULE]):
        yield MODULE


def test_registered_port_is_returned(module, db):
    plugin = GoodQuestion()
    registry.register("question_type", "good", plugin, owner="mod.a")
    assert registry.get("question_type", "good") is plugin
    assert registry.keys("question_type") == ["good"]
    assert registry.owned_by("mod.a") == {("question_type", "good")}


def test_port_breaking_contract_rejected(module):
    with pytest.raises(StartupError, match=r"mod\.a.*question_type"):
        registry.register("question_type", "bad", object(), owner="mod.a")


def test_duplicate_key_rejected(module):
    registry.register("question_type", "good", GoodQuestion(), owner="mod.a")
    with pytest.raises(StartupError, match=r"good.*mod\.a"):
        registry.register("question_type", "good", GoodQuestion(), owner="mod.a")


def test_unknown_capability_rejected(module):
    with pytest.raises(StartupError, match="mystery"):
        registry.register("mystery", "x", GoodQuestion(), owner="mod.a")


def test_owner_must_declare_capability(module):
    with pytest.raises(StartupError, match="scoring_strategy"):
        registry.register("scoring_strategy", "basic", GoodScoring(), owner="mod.a")


def test_owner_must_be_an_active_module(module):
    with pytest.raises(StartupError, match="mod.other"):
        registry.register("question_type", "good", GoodQuestion(), owner="mod.other")


def test_unknown_key_raises_unknown_port(module):
    with pytest.raises(registry.UnknownPort):
        registry.get("question_type", "nope")
