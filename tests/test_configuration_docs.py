"""docs/configuration.md is the one list of environment variables, and compose delivers them."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIGURATION = ROOT / "docs" / "configuration.md"
VARIABLE = re.compile(r"KVZ_[A-Z][A-Z_]*")
# Python names in settings and the registry, not variables, and the prefix of a variable
# that is built at run time: `KVZ_PROVIDER_<CAPABILITY>` has its own row.
NOT_VARIABLES = {"KVZ_MODULES", "KVZ_PERSISTENCE", "KVZ_PROVIDER_"}


def sources() -> list[Path]:
    deploy = ROOT / "deploy"
    return [
        *(ROOT / "app").rglob("*.py"),
        deploy / "compose.yaml",
        deploy / "Caddyfile",
        deploy / "load.sh",
        deploy / "smoke.sh",
        ROOT / "Dockerfile",
    ]


def variables_in_use() -> dict[str, set[str]]:
    used: dict[str, set[str]] = {}
    for path in sources():
        for name in VARIABLE.findall(path.read_text()):
            if name not in NOT_VARIABLES:
                used.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return used


def table_rows() -> dict[str, list[str]]:
    """Rows of the variable table by the first variable named in the first cell."""
    rows: dict[str, list[str]] = {}
    for line in CONFIGURATION.read_text().splitlines():
        if not line.startswith("| `KVZ_"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        for name in re.findall(r"`(KVZ_[A-Z][A-Z_<>]*)`", cells[0]):
            rows[name] = cells
    return rows


def compose_environment() -> set[str]:
    """Names set in the `environment` of the `x-app` block, which every app container shares."""
    text = (ROOT / "deploy" / "compose.yaml").read_text()
    block = text.split("x-app:", 1)[1].split("\nservices:", 1)[0]
    environment = block.split("environment:", 1)[1].split("\n  volumes:", 1)[0]
    return set(re.findall(r"^    ([A-Z][A-Z_]*):", environment, re.M))


def test_every_kvz_variable_is_documented():
    """AC-138: every KVZ variable read in code or compose has a row in the reference."""
    documented = table_rows()
    missing = {
        name: sorted(where) for name, where in variables_in_use().items() if name not in documented
    }
    assert not missing


def test_the_table_names_no_variable_that_nothing_reads():
    used = set(variables_in_use()) | {"KVZ_PROVIDER_<CAPABILITY>"}
    assert not {name for name in table_rows() if name not in used}


def test_deployment_does_not_repeat_the_table():
    text = (ROOT / "docs" / "deployment.md").read_text()
    assert "| `KVZ_" not in text
    assert "configuration.md" in text


def test_compose_passes_the_documented_operator_variables():
    passed = compose_environment()
    claimed = {name for name, cells in table_rows().items() if re.search(r"\bapp\b", cells[-1])}
    assert claimed
    assert claimed <= passed, sorted(claimed - passed)


def test_compose_passes_every_limit_and_the_backup_retention():
    """AC-138: compose passes the limit variables and the backup retention to the containers."""
    settings = (ROOT / "app" / "settings.py").read_text()
    read_as_numbers = set(re.findall(r'_positive_int\(\s*"(KVZ_[A-Z_]+)"', settings))
    assert read_as_numbers >= {"KVZ_LOGIN_ATTEMPTS_PER_MINUTE", "KVZ_BACKUP_RETENTION_DAYS"}
    assert read_as_numbers <= compose_environment(), sorted(read_as_numbers - compose_environment())


def test_an_empty_pass_through_means_the_default():
    """Compose hands over an empty string when `deploy/.env` leaves a limit out."""
    text = (ROOT / "deploy" / "compose.yaml").read_text()
    for name in ("KVZ_CODE_ATTEMPTS_PER_MINUTE", "KVZ_BACKUP_RETENTION_DAYS"):
        assert f"{name}: ${{{name}:-}}" in text


def test_the_test_stacks_do_not_inherit_what_compose_passes_through():
    """An exported limit or retention would reach `make smoke` and `make load` through compose."""
    passed = re.findall(
        r"^\s+(KVZ_\w+): \$\{\1:-\}\s*$", (ROOT / "deploy/compose.yaml").read_text(), re.M
    )
    assert "KVZ_STARTS_PER_MINUTE" in passed
    for script in ("smoke.sh", "load.sh"):
        text = (ROOT / "deploy" / script).read_text()
        unset = re.search(r"^unset((?: |\\\n)+[\w ]+?(?:\\\n[\w ]+)*)$", text, re.M)
        assert unset, script
        assert set(unset.group(1).replace("\\", " ").split()) >= set(passed), script
