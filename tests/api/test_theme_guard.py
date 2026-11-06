import pytest

from app.kernel import lifecycle
from tests.domain.helpers import ADMIN_ID
from tests.support.modules import make_module
from tests.support.run import run_manage, run_python


@pytest.mark.django_db
def test_last_theme_cannot_be_disabled():
    with pytest.raises(lifecycle.ModuleInUse):
        lifecycle.set_enabled("theme.default", False, actor_type="admin", actor_id=ADMIN_ID)


def test_theme_template_overrides_page_of_same_name(tmp_path):
    site = tmp_path / "site"
    package = make_module(site, "theme.fixture", provides=["theme"])
    templates = site / package / "jinja2" / "public"
    templates.mkdir(parents=True)
    (templates / "landing.html").write_text("replaced by theme")
    db = tmp_path / "db.sqlite3"
    assert run_manage("migrate", "--noinput", db=db, sites=[site]).returncode == 0
    result = run_python("print(client.get('/').content.decode())", db=db, sites=[site])
    assert "replaced by theme" in result.stdout, result.stderr
