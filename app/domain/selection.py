"""Which questions an attempt gets, in what order (FR-18, FR-19). Stored on the attempt at start."""

import random
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from app.contracts import JSON

# Replaced in tests. Not a secret: nothing depends on the order being unguessable.
RNG: random.Random = random.SystemRandom()


class Item(TypedDict):
    id: str
    draw: str | None  # the draw row it came from; own questions have none


def all_questions(snapshot: JSON) -> list[dict[str, Any]]:
    """Everything an attempt on this revision could be given."""
    pools = [row.get("pool", []) for row in snapshot.get("draws", [])]
    return [*snapshot["questions"], *(question for pool in pools for question in pool)]


def layout(questions: Sequence[Any], draws: Sequence[Any]) -> list[tuple[str, Any]]:
    """Own questions and draw rows in their order. A row's `position` counts own questions."""
    placed: list[tuple[str, Any]] = []
    for index in range(len(questions) + 1):
        placed += [("draw", row) for row in draws if min(row["position"], len(questions)) == index]
        if index < len(questions):
            placed.append(("question", questions[index]))
    return placed


def assign(
    rows: Sequence[Mapping[str, Any]], fixed: Mapping[str, Sequence[str]] | None = None
) -> dict[str, list[str]] | None:
    """Fill each row's places with no question used twice, or None when that is impossible.

    Rows can overlap, so filling them one by one could fail where a solution exists. Places take
    questions in random order, and a taken question moves its holder on when the holder has another
    choice (augmenting paths). `fixed` are questions already decided for a row.
    """
    decided = {row["id"]: list((fixed or {}).get(row["id"], [])) for row in rows}
    used = {question for chosen in decided.values() for question in chosen}
    places: list[tuple[str, list[str]]] = []
    for row in rows:
        candidates = [q["id"] for q in row["pool"] if q["id"] not in used]
        for _ in range(row["count"] - len(decided[row["id"]])):
            options = list(candidates)
            RNG.shuffle(options)
            places.append((row["id"], options))
    holder: dict[str, int] = {}

    def seat(place: int, seen: set[str]) -> bool:
        for question in places[place][1]:
            if question in seen:
                continue
            seen.add(question)
            if question not in holder or seat(holder[question], seen):
                holder[question] = place
                return True
        return False

    for place in range(len(places)):
        if not seat(place, set()):
            return None
    for question, place in holder.items():
        decided[places[place][0]].append(question)
    return decided


def own_items(snapshot: JSON) -> list[Item]:
    return [{"id": question["id"], "draw": None} for question in snapshot["questions"]]


class CannotDraw(Exception):
    """A published revision's rows cannot be filled. Publication checks this, so it is a bug."""


def _placed(snapshot: JSON, assigned: Mapping[str, Sequence[str]], shuffle: bool) -> list[Item]:
    items: list[Item] = []
    for kind, entry in layout(snapshot["questions"], snapshot.get("draws", [])):
        if kind == "draw":
            items += [{"id": question, "draw": entry["id"]} for question in assigned[entry["id"]]]
        else:
            items.append({"id": entry["id"], "draw": None})
    if shuffle:
        RNG.shuffle(items)
    return items


def choose(snapshot: JSON, shuffle: bool) -> list[Item]:
    assigned = assign(snapshot.get("draws", []))
    if assigned is None:
        raise CannotDraw
    return _placed(snapshot, assigned, shuffle)


def carry_over(
    old_snapshot: JSON, old_items: Sequence[Item], new_snapshot: JSON, shuffle: bool
) -> list[Item]:
    """What an attempt gets on a new revision: as much of what it had as still fits."""
    had: dict[str, list[str]] = {}
    for item in old_items:
        if item["draw"] is not None:
            had.setdefault(item["draw"], []).append(item["id"])
    draws = new_snapshot.get("draws", [])
    kept = {}
    for row in draws:
        pool = {question["id"] for question in row["pool"]}
        still = [question for question in had.get(row["id"], []) if question in pool]
        RNG.shuffle(still)
        kept[row["id"]] = still[: row["count"]]
    assigned = assign(draws, kept) or assign(draws)  # a kept question may be another row's only one
    if assigned is None:
        raise CannotDraw
    return _placed(new_snapshot, assigned, shuffle)


def given(snapshot: JSON, items: Sequence[Item]) -> list[dict[str, Any]]:
    """A drawn question comes from its row's pool, so its points are that row's."""
    own = {question["id"]: question for question in snapshot["questions"]}
    pools = {
        row["id"]: {question["id"]: question for question in row["pool"]}
        for row in snapshot.get("draws", [])
    }
    return [pools[item["draw"]][item["id"]] if item["draw"] else own[item["id"]] for item in items]


def count(snapshot: JSON) -> int:
    """How many questions a participant gets."""
    drawn = sum(row["count"] for row in snapshot.get("draws", []))
    return len(snapshot.get("questions", [])) + drawn
