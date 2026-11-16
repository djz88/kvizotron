"""Messages of the settings forms."""

import pytest

from app.api.admin_forms import clash_message, conflict_messages
from app.domain import settings
from app.domain.setting_rules import (
    AFTER_CLOSE_PROFILE,
    AFTER_CLOSE_VISIBILITY,
    RUN_PROFILE,
    Clash,
)


def test_unknown_clash_reason_names_it():
    with pytest.raises(KeyError, match="no_such_reason"):
        clash_message(Clash("no_such_reason", "k", None))


def test_after_close_clashes_have_their_own_sentences():
    texts = {
        reason: clash_message(Clash(reason, "k", None))
        for reason in (AFTER_CLOSE_PROFILE, AFTER_CLOSE_VISIBILITY, RUN_PROFILE)
    }
    assert len(set(texts.values())) == 3
    assert "profil dat Odpovědi nebo Podrobně" in texts[AFTER_CLOSE_PROFILE]
    assert "účastník viděl své odpovědi" in texts[AFTER_CLOSE_VISIBILITY]
    assert "Naplánovaný nebo otevřený běh" in texts[RUN_PROFILE]


def test_a_refused_run_names_the_reveal_moment_in_words():
    [line] = conflict_messages([settings.REVEAL_MOMENT])
    assert line == clash_message(Clash(AFTER_CLOSE_PROFILE, "k", None))
