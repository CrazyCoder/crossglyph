"""One command, its subcommands, and the preview as the default."""
import pytest

from crossglyph import cli


def test_no_arguments_runs_the_preview(monkeypatch):
    """The double-click case: a tester who unpacked the zip wants the page."""
    seen = []
    monkeypatch.setattr(cli, "_preview", lambda argv: seen.append(argv) or 0)
    assert cli.main([]) == 0
    assert seen == [[]]


def test_a_subcommand_passes_the_rest_along(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_build", lambda argv: seen.append(argv) or 0)
    assert cli.main(["build", "--force", "probe"]) == 0
    assert seen == [["--force", "probe"]]


def test_fetch_fallbacks_is_the_build_flag(monkeypatch):
    """Spelled as a command because that is how it reads, but there is one
    implementation of it rather than two that can disagree."""
    seen = []
    monkeypatch.setattr(cli, "_build", lambda argv: seen.append(argv) or 0)
    assert cli.main(["fetch-fallbacks", "--fonts", "x"]) == 0
    assert seen == [["--fetch-fallbacks", "--fonts", "x"]]


def test_an_unknown_command_names_the_ones_there_are(capsys):
    assert cli.main(["frobnicate"]) == 2
    error = capsys.readouterr().err
    assert "frobnicate" in error
    for command in ("preview", "build", "fetch-fallbacks"):
        assert command in error


def test_help_lists_the_commands(capsys):
    assert cli.main(["--help"]) == 0
    assert "fetch-fallbacks" in capsys.readouterr().out


def test_the_version_is_reported(capsys, monkeypatch):
    monkeypatch.setattr(cli, "version_report", lambda: "crossglyph 9.9.9")
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "crossglyph 9.9.9"


def test_the_report_names_the_version_and_the_render_core(monkeypatch):
    from crossglyph import install

    monkeypatch.setattr(cli.version, "installed", lambda: "1.2.3")
    monkeypatch.setattr(cli.stamp, "build_stamp", lambda: "45caec3e76c2472b")
    monkeypatch.setattr(cli.install, "detect", lambda *a, **k: install.ZIP)

    said = cli.version_report()
    assert said.startswith("crossglyph 1.2.3")
    assert "45caec3e76c2" in said
    assert "crosspoint-reader" in said


def test_a_core_with_no_stamp_says_so_rather_than_nothing(monkeypatch):
    from crossglyph import install

    monkeypatch.setattr(cli.version, "installed", lambda: "1.2.3")
    monkeypatch.setattr(cli.stamp, "build_stamp", lambda: None)
    monkeypatch.setattr(cli.install, "detect", lambda *a, **k: install.ZIP)
    assert "unknown commit" in cli.version_report()


def test_a_kind_that_cannot_update_itself_is_named(monkeypatch):
    """Somebody filing a report from a source download should not have to be
    asked how they installed it."""
    from crossglyph import install

    monkeypatch.setattr(cli.version, "installed", lambda: "1.2.3")
    monkeypatch.setattr(cli.stamp, "build_stamp", lambda: None)
    monkeypatch.setattr(cli.install, "detect", lambda *a, **k: install.SOURCE)
    assert "source download" in cli.version_report()


def test_a_release_says_nothing_about_its_kind(monkeypatch):
    """The ordinary case stays quiet: naming it would be noise on every run."""
    from crossglyph import install

    monkeypatch.setattr(cli.version, "installed", lambda: "1.2.3")
    monkeypatch.setattr(cli.stamp, "build_stamp", lambda: None)
    monkeypatch.setattr(cli.install, "detect", lambda *a, **k: install.ZIP)
    assert "(" not in cli.version_report().splitlines()[0]


def test_help_mentions_the_version_flag(capsys):
    assert cli.main(["--help"]) == 0
    assert "--version" in capsys.readouterr().out


# --- the update note ------------------------------------------------------


def test_the_flag_is_taken_off_before_the_subcommand_sees_it(monkeypatch):
    """build's parser would reject it, and it is not build's flag."""
    seen = []
    monkeypatch.setattr(cli, "_build", lambda argv: seen.append(argv) or 0)
    monkeypatch.setattr(cli, "update_note", lambda: "")
    assert cli.main(["build", "--no-update-check", "--force"]) == 0
    assert seen == [["--force"]]


def test_the_flag_skips_the_check_entirely(monkeypatch):
    """Not merely silences it: the point of the flag is to spend no time."""
    monkeypatch.setattr(cli, "_build", lambda argv: 0)
    monkeypatch.setattr(cli, "update_note",
                        lambda: pytest.fail("it checked anyway"))
    assert cli.main(["build", "--no-update-check"]) == 0


def test_a_newer_release_is_mentioned_after_the_work(capsys, monkeypatch):
    """After, not before: the note costs nothing anybody is waiting on."""
    order = []
    monkeypatch.setattr(cli, "_build", lambda argv: order.append("built") or 0)
    monkeypatch.setattr(cli, "update_note",
                        lambda: order.append("checked") or "note: 0.2.0 is here")
    assert cli.main(["build"]) == 0
    assert order == ["built", "checked"]
    assert "0.2.0" in capsys.readouterr().out


def test_nothing_is_said_when_there_is_nothing_to_say(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_build", lambda argv: 0)
    monkeypatch.setattr(cli, "update_note", lambda: "")
    cli.main(["build"])
    assert capsys.readouterr().out == ""


def test_the_work_s_exit_code_survives_the_note(monkeypatch):
    """A failed build stays failed, however cheerful the note is."""
    monkeypatch.setattr(cli, "_build", lambda argv: 3)
    monkeypatch.setattr(cli, "update_note", lambda: "note: 0.2.0 is here")
    assert cli.main(["build"]) == 3


def test_the_note_carries_the_kind_s_own_instruction(monkeypatch):
    from crossglyph import install, updates

    monkeypatch.setattr(cli.updates, "check",
                        lambda *a, **k: updates.State(1.0, "0.2.0", None))
    monkeypatch.setattr(cli.updates, "available", lambda state: "0.2.0")
    monkeypatch.setattr(cli.install, "detect", lambda *a, **k: install.CONTAINER)
    said = cli.update_note()
    assert "0.2.0" in said
    assert install.instruction(install.CONTAINER) in said


def test_update_check_reports_being_up_to_date(capsys, monkeypatch):
    """The state an automatic check never has to say out loud. Without it the
    button and the flag both look broken."""
    from crossglyph import updates

    monkeypatch.setattr(cli.updates, "check",
                        lambda *a, **k: updates.State(1.0, "0.1.0", None))
    monkeypatch.setattr(cli.updates, "available", lambda state: None)
    assert cli.main(["update", "--check"]) == 0
    assert "up to date" in capsys.readouterr().out.lower()


def test_update_check_reports_being_unable_to_ask(capsys, monkeypatch):
    from crossglyph import updates

    monkeypatch.setattr(cli.updates, "check",
                        lambda *a, **k: updates.State(1.0, None, "no route"))
    assert cli.main(["update", "--check"]) == 1
    assert "could not" in capsys.readouterr().err.lower()


def test_update_check_names_the_newer_release(capsys, monkeypatch):
    from crossglyph import updates

    monkeypatch.setattr(cli.updates, "check",
                        lambda *a, **k: updates.State(1.0, "0.2.0", None))
    monkeypatch.setattr(cli.updates, "available", lambda state: "0.2.0")
    assert cli.main(["update", "--check"]) == 0
    assert "0.2.0" in capsys.readouterr().out


def test_bare_update_says_what_this_version_can_do(capsys):
    """Applying lands in the next phase. Until then the command exists only to
    check, and saying so beats a command that half works."""
    assert cli.main(["update"]) == 2
    assert "--check" in capsys.readouterr().err
