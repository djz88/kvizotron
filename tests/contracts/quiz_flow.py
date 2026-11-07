"""Shared contract suite: every navigation module must pass it."""

from app.contracts import QuizFlowPlugin

MOMENTS = ("never", "at_end", "after_each")


class QuizFlowContract:
    plugin: QuizFlowPlugin

    def test_satisfies_protocol(self):
        assert isinstance(self.plugin, QuizFlowPlugin)

    def test_every_mode_has_options(self):
        for mode in self.plugin.modes():
            for moment in MOMENTS:
                assert set(self.plugin.client_options(mode, moment)) == {"step", "back", "check"}

    def test_all_at_once_is_not_step(self):
        options = self.plugin.client_options("all_at_once", "never")
        assert options == {"step": False, "back": False, "check": False}

    def test_check_only_with_step_and_after_each(self):
        assert self.plugin.client_options("step_back", "after_each")["check"]
        assert not self.plugin.client_options("step_back", "at_end")["check"]
        assert not self.plugin.client_options("all_at_once", "after_each")["check"]

    def test_no_back_only_in_step_no_back(self):
        assert self.plugin.client_options("step_back", "never")["back"]
        assert not self.plugin.client_options("step_no_back", "never")["back"]
