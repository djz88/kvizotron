import pytest

from app import contracts
from app.kernel import discovery
from app.kernel.discovery import load_modules, load_persistence
from app.kernel.errors import StartupError
from tests.support.modules import make_module


@pytest.fixture(autouse=True)
def only_test_modules(monkeypatch):
    """The project's own modules are always installed; these tests start from an empty site."""
    installed = discovery.entry_points

    def without_own_modules(**kwargs):
        return [ep for ep in installed(**kwargs) if ep.dist.name != "kvizotron"]

    monkeypatch.setattr(discovery, "entry_points", without_own_modules)
    monkeypatch.setattr(contracts, "REQUIRED_CAPABILITIES", frozenset())


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(tmp_path)
    return tmp_path


def ids(env=None):
    return [m.id for m in load_modules(env or {})]


def test_no_modules_gives_empty_list():
    assert load_modules({}) == []


def test_discovers_module_from_entry_point(site):
    make_module(site, "question.demo", provides=["question_type"])
    module = load_modules({})[0]
    assert (module.id, module.kind, module.provides) == (
        "question.demo",
        "plugin",
        ["question_type"],
    )


def test_dependencies_come_first(site):
    make_module(site, "a.first", requires=["x"])
    make_module(site, "z.last", provides=["x"])
    assert ids() == ["z.last", "a.first"]


def test_several_providers_of_one_plugin_capability_all_satisfy_requires(site):
    make_module(site, "a.user", requires=["question_type"])
    make_module(site, "q.one", provides=["question_type"])
    make_module(site, "q.two", provides=["question_type"])
    assert ids()[-1] == "a.user"
    assert set(ids()) == {"a.user", "q.one", "q.two"}


def test_module_requiring_what_it_provides_is_not_a_cycle(site):
    make_module(site, "self.ref", provides=["x"], requires=["x"])
    assert ids() == ["self.ref"]


def test_optional_missing_is_fine(site):
    make_module(site, "a.opt", optional=["media_storage"])
    assert ids() == ["a.opt"]


def test_optional_present_loads_first(site):
    make_module(site, "a.opt", optional=["x"])
    make_module(site, "z.dep", provides=["x"])
    assert ids() == ["z.dep", "a.opt"]


def test_import_failure_names_entry_point(site):
    make_module(site, "broken.pkg", source="import does_not_exist_anywhere\n")
    with pytest.raises(StartupError, match="broken.pkg"):
        load_modules({})


def test_invalid_manifest_names_entry_point(site):
    make_module(site, "bad.kind", kind="gadget")
    with pytest.raises(StartupError, match="bad.kind"):
        load_modules({})


def test_unknown_manifest_field_rejected(site):
    make_module(site, "bad.field", migrations=[])
    with pytest.raises(StartupError, match="bad.field"):
        load_modules({})


def test_duplicate_module_id_rejected(site):
    make_module(site, "same.id")
    make_module(site, "same.id")
    with pytest.raises(StartupError, match="same.id"):
        load_modules({})


def test_incompatible_contract_version_rejected(site):
    make_module(site, "old.mod", api_compatibility=">=9.0")
    with pytest.raises(StartupError, match=r"old\.mod.*1\.1"):
        load_modules({})


def test_invalid_version_specifier_rejected(site):
    make_module(site, "bad.spec", api_compatibility="banana")
    with pytest.raises(StartupError, match="bad.spec"):
        load_modules({})


def test_missing_required_capability_rejected(site):
    make_module(site, "needs.media", requires=["media_storage"])
    with pytest.raises(StartupError, match="media_storage"):
        load_modules({})


def test_dependency_cycle_rejected(site):
    make_module(site, "c.one", provides=["x"], requires=["y"])
    make_module(site, "c.two", provides=["y"], requires=["x"])
    with pytest.raises(StartupError, match="cycle"):
        load_modules({})


def test_plugin_cannot_provide_infrastructure(site):
    make_module(site, "fake.auth", provides=["auth"])
    with pytest.raises(StartupError, match="fake.auth"):
        load_modules({})


def test_two_exactly_one_providers_need_selection(site):
    make_module(site, "auth.a", kind="provider", provides=["auth"], auth_backend="x.Y")
    make_module(site, "auth.b", kind="provider", provides=["auth"], auth_backend="x.Y")
    with pytest.raises(StartupError, match="KVZ_PROVIDER_AUTH"):
        load_modules({})


def test_selected_provider_wins_and_other_is_excluded(site):
    make_module(site, "auth.a", kind="provider", provides=["auth"], auth_backend="x.Y")
    make_module(site, "auth.b", kind="provider", provides=["auth"], auth_backend="x.Y")
    assert ids({"KVZ_PROVIDER_AUTH": "auth.b"}) == ["auth.b"]


def test_single_provider_needs_no_selection(site):
    make_module(site, "auth.a", kind="provider", provides=["auth"], auth_backend="x.Y")
    assert ids() == ["auth.a"]


def test_selecting_uninstalled_provider_rejected(site):
    make_module(site, "auth.a", kind="provider", provides=["auth"], auth_backend="x.Y")
    with pytest.raises(StartupError, match="auth.nope"):
        load_modules({"KVZ_PROVIDER_AUTH": "auth.nope"})


def test_selecting_provider_when_none_is_installed_rejected():
    with pytest.raises(StartupError, match="auth.nope"):
        load_modules({"KVZ_PROVIDER_AUTH": "auth.nope"})


def test_excluded_provider_does_not_satisfy_requires(site):
    make_module(site, "auth.a", kind="provider", provides=["auth", "only_a"], auth_backend="x.Y")
    make_module(site, "auth.b", kind="provider", provides=["auth"], auth_backend="x.Y")
    make_module(site, "user.mod", requires=["only_a"])
    with pytest.raises(StartupError, match="only_a"):
        load_modules({"KVZ_PROVIDER_AUTH": "auth.b"})


def test_required_capability_missing_rejected(monkeypatch):
    monkeypatch.setattr(contracts, "REQUIRED_CAPABILITIES", frozenset({"auth"}))
    with pytest.raises(StartupError, match="auth"):
        load_modules({})


def test_provider_of_persistence_must_declare_class(site):
    make_module(site, "db.nofield", kind="provider", provides=["persistence"])
    with pytest.raises(StartupError, match=r"db\.nofield.*persistence"):
        load_modules({})


def test_load_persistence_bad_path_names_module(site):
    make_module(
        site, "db.bad", kind="provider", provides=["persistence"], persistence="nope_missing:X"
    )
    with pytest.raises(StartupError, match=r"db\.bad"):
        load_persistence(load_modules({}))


def test_load_persistence_contract_violation_names_module(site):
    make_module(
        site, "db.wrong", kind="provider", provides=["persistence"], persistence="builtins:object"
    )
    with pytest.raises(StartupError, match=r"db\.wrong.*PersistenceProvider"):
        load_persistence(load_modules({}))


def test_provider_of_auth_must_declare_backend(site):
    make_module(site, "auth.nofield", kind="provider", provides=["auth"])
    with pytest.raises(StartupError, match=r"auth\.nofield.*auth_backend"):
        load_modules({})
