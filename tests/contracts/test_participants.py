from app.plugins.participants.policy import BasicParticipantPolicy
from tests.contracts.participant_policy import ParticipantPolicyContract


class TestBasicParticipantPolicy(ParticipantPolicyContract):
    policy = BasicParticipantPolicy()


def test_nickname_help_names_the_public_scoreboard():
    # A visible scoreboard shows nicknames (ADR-0051, docs/privacy.md); the help must say so.
    from app.plugins.participants.manifest import MANIFEST

    help_text = next(s for s in MANIFEST["settings"] if s["key"] == "ask_name")["help"]
    assert "scoreboard" in str(help_text).lower()


def test_name_key_of_a_longest_name_fits_its_column():
    # casefold() can lengthen a name: "ß" becomes "ss".
    from app.domain.models import Participant

    policy = BasicParticipantPolicy()
    key = policy.name_key(policy.clean_name("ß" * 40))
    assert len(key) <= Participant._meta.get_field("name_key").max_length
