import random

import pytest

from app.domain import selection


@pytest.fixture
def seeded(monkeypatch):
    monkeypatch.setattr(selection, "RNG", random.Random(7))  # noqa: S311  # repeatable on purpose


SNAPSHOT = {"questions": [{"id": f"q{number}"} for number in range(8)]}
IDS = [question["id"] for question in SNAPSHOT["questions"]]


def test_without_shuffling_the_order_is_the_revision_order():
    items = selection.choose(SNAPSHOT, shuffle=False)
    assert [item["id"] for item in items] == IDS
    assert all(item["draw"] is None for item in items)


def test_shuffling_changes_order_and_keeps_every_question(seeded):
    items = selection.choose(SNAPSHOT, shuffle=True)
    ids = [item["id"] for item in items]
    assert ids != IDS
    assert sorted(ids) == sorted(IDS)


def test_given_returns_questions_in_the_order_of_the_items():
    items = [{"id": "q2", "draw": None}, {"id": "q0", "draw": None}]
    assert [q["id"] for q in selection.given(SNAPSHOT, items)] == ["q2", "q0"]


def test_count_of_a_snapshot_without_rows():
    assert selection.count(SNAPSHOT) == 8


def _pool(*ids):
    return [{"id": question} for question in ids]


def _snapshot(own, *rows):
    return {"questions": [{"id": q} for q in own], "draws": list(rows)}


def _row(row_id, count, *ids, position=0):
    return {"id": row_id, "count": count, "position": position, "pool": _pool(*ids)}


def _ids(items):
    return [item["id"] for item in items]


def test_each_attempt_gets_count_distinct_questions():
    snapshot = _snapshot([], _row("r", 3, "a", "b", "c", "d", "e"))
    for _ in range(30):
        ids = _ids(selection.choose(snapshot, shuffle=False))
        assert len(ids) == len(set(ids)) == 3


def test_drawing_varies(seeded):
    snapshot = _snapshot([], _row("r", 2, "a", "b", "c", "d", "e"))
    drawn = {tuple(sorted(_ids(selection.choose(snapshot, False)))) for _ in range(40)}
    assert len(drawn) > 1


def test_overlapping_rows_never_repeat_a_question(seeded):
    snapshot = _snapshot([], _row("r1", 2, "a", "b", "c"), _row("r2", 2, "b", "c", "d"))
    for _ in range(200):
        ids = _ids(selection.choose(snapshot, False))
        assert len(ids) == len(set(ids)) == 4


def test_draw_takes_the_rows_position():
    snapshot = _snapshot(["o1", "o2"], _row("r", 3, "a", "b", "c", position=1))
    items = selection.choose(snapshot, False)
    assert items[0] == {"id": "o1", "draw": None}
    assert {item["draw"] for item in items[1:4]} == {"r"}
    assert items[4] == {"id": "o2", "draw": None}


def test_shuffle_mixes_the_whole_list(seeded):
    snapshot = _snapshot(["o1", "o2", "o3", "o4"], _row("r", 4, "a", "b", "c", "d", position=4))
    orders = {tuple(_ids(selection.choose(snapshot, True))) for _ in range(5)}
    assert any(order[:4] != ("o1", "o2", "o3", "o4") for order in orders)


def test_given_takes_a_drawn_question_from_its_rows_pool():
    first = {"id": "a", "settings": {"points": 1}}
    second = {"id": "a", "settings": {"points": 9}}
    snapshot = {
        "questions": [],
        "draws": [{"id": "r1", "pool": [first]}, {"id": "r2", "pool": [second]}],
    }
    assert selection.given(snapshot, [{"id": "a", "draw": "r2"}]) == [second]


def test_count_includes_draws():
    assert selection.count(_snapshot(["o"], _row("r", 3, "a", "b", "c"))) == 4


def test_carry_over_keeps_drawn_questions_still_in_the_pool():
    old = _snapshot([], _row("r", 2, "a", "b", "c"))
    items = [{"id": "a", "draw": "r"}, {"id": "b", "draw": "r"}]
    new = _snapshot([], _row("r", 2, "a", "b", "d"))
    assert sorted(_ids(selection.carry_over(old, items, new, False))) == ["a", "b"]


def test_carry_over_replaces_a_question_gone_from_the_pool():
    old = _snapshot([], _row("r", 2, "a", "b"))
    items = [{"id": "a", "draw": "r"}, {"id": "b", "draw": "r"}]
    new = _snapshot([], _row("r", 2, "a", "c"))
    assert sorted(_ids(selection.carry_over(old, items, new, False))) == ["a", "c"]


def test_carry_over_draws_more_when_a_row_grew():
    old = _snapshot([], _row("r", 1, "a", "b", "c"))
    new = _snapshot([], _row("r", 3, "a", "b", "c"))
    ids = _ids(selection.carry_over(old, [{"id": "a", "draw": "r"}], new, False))
    assert "a" in ids
    assert len(set(ids)) == 3


def test_carry_over_drops_surplus_when_a_row_shrank():
    old = _snapshot([], _row("r", 3, "a", "b", "c"))
    items = [{"id": q, "draw": "r"} for q in "abc"]
    new = _snapshot([], _row("r", 1, "a", "b", "c"))
    ids = _ids(selection.carry_over(old, items, new, False))
    assert len(ids) == 1
    assert ids[0] in "abc"


def test_carry_over_removes_questions_of_a_removed_row():
    old = _snapshot(["o"], _row("r", 1, "a"))
    new = _snapshot(["o"])
    items = [{"id": "o", "draw": None}, {"id": "a", "draw": "r"}]
    assert _ids(selection.carry_over(old, items, new, False)) == ["o"]


def test_carry_over_fills_a_new_row():
    old = _snapshot(["o"])
    new = _snapshot(["o"], _row("r", 1, "a"))
    assert sorted(_ids(selection.carry_over(old, [{"id": "o", "draw": None}], new, False))) == [
        "a",
        "o",
    ]


def test_carry_over_without_a_row_in_the_old_attempt_still_works():
    new = _snapshot(["o"], _row("r", 1, "a"))
    assert len(selection.carry_over(_snapshot(["o"]), [], new, False)) == 2


def test_carry_over_moves_kept_questions_aside_when_they_block_a_row():
    """Keeping a question for a wide row must not leave a narrow row without one."""
    old = _snapshot([], _row("wide", 1, "a", "b"))
    new = _snapshot([], _row("wide", 1, "a", "b"), _row("narrow", 1, "a"))
    items = selection.carry_over(old, [{"id": "a", "draw": "wide"}], new, False)
    assert {item["draw"]: item["id"] for item in items} == {"wide": "b", "narrow": "a"}
