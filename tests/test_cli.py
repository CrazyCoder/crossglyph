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
    monkeypatch.setattr(cli.stamp, "_stamp", dict)
    monkeypatch.setattr(cli.install, "detect", lambda *a, **k: install.ZIP)
    assert "kept no record" in cli.version_report()


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
    monkeypatch.setattr(cli.updates, "available", lambda state, **kw: "0.2.0")
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
    monkeypatch.setattr(cli.updates, "available", lambda state, **kw: None)
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
    monkeypatch.setattr(cli.updates, "available", lambda state, **kw: "0.2.0")
    assert cli.main(["update", "--check"]) == 0
    assert "0.2.0" in capsys.readouterr().out


def test_update_check_names_the_release_a_rollback_turned_down(capsys,
                                                                monkeypatch):
    """Somebody asked, so they are answered, and told why nothing had
    mentioned it. The rejection stops the tool raising the subject; refusing
    to answer a question about it would only leave them unable to find what
    `crossglyph update` already does."""
    from crossglyph import updates

    state = updates.State(1.0, "0.2.0", None, rejected="0.2.0")
    monkeypatch.setattr(cli.updates, "check", lambda *a, **k: state)
    monkeypatch.setattr(cli.updates.version, "installed", lambda: "0.1.0")

    assert cli.main(["update", "--check"]) == 0
    said = capsys.readouterr().out
    assert "0.2.0 is available" in said
    assert "rolled back" in said


def test_the_note_after_a_build_still_says_nothing_about_it(capsys,
                                                            monkeypatch):
    """The other half of the rule. This one is the tool raising the subject,
    unasked, after work somebody ran for another reason."""
    from crossglyph import updates

    state = updates.State(1.0, "0.2.0", None, rejected="0.2.0")
    monkeypatch.setattr(cli.updates, "check", lambda *a, **k: state)
    monkeypatch.setattr(cli.updates.version, "installed", lambda: "0.1.0")

    assert cli.update_note() == ""


def test_an_argument_update_does_not_know_is_refused(capsys):
    assert cli.main(["update", "--yes-please"]) == 2
    assert "--check" in capsys.readouterr().err


# --- applying -------------------------------------------------------------


def steps(*given):
    """Stand in for the pipeline, which has its own tests."""
    return lambda root, *args, **kwargs: iter(given)


def test_a_bare_update_installs(capsys, monkeypatch):
    monkeypatch.setattr(cli.upgrade, "steps", steps(
        {"event": "plan", "version": "0.2.0", "bytes": 1600000,
         "notes_url": "https://example.invalid/", "converting": False},
        {"event": "step", "got": 1600000, "bytes": 1600000},
        {"event": "done", "version": "0.2.0", "kept": [], "staged": [],
         "converting": False,
         "where": "versions/0.2.0"}))
    assert cli.main(["update"]) == 0
    said = capsys.readouterr().out
    assert "updating to 0.2.0" in said
    assert "Restart CrossGlyph" in said


def test_a_refusal_is_an_error_and_says_why(capsys, monkeypatch):
    monkeypatch.setattr(cli.upgrade, "steps", steps(
        {"event": "error", "error": "this install cannot update itself. "
                                    "Run git pull to update."}))
    assert cli.main(["update"]) == 1
    assert "git pull" in capsys.readouterr().err


def test_being_up_to_date_is_not_a_failure(capsys, monkeypatch):
    monkeypatch.setattr(cli.upgrade, "steps",
                        steps({"event": "current", "version": "0.2.0"}))
    assert cli.main(["update"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_a_file_that_was_kept_is_named(capsys, monkeypatch):
    """A .new sitting in the workspace that nobody was told about is a file
    nobody ever reads."""
    monkeypatch.setattr(cli.upgrade, "steps", steps(
        {"event": "done", "version": "0.2.0", "kept": ["conf/all.conf"],
         "staged": [],
         "converting": False, "where": "versions/0.2.0"}))
    cli.main(["update"])
    said = capsys.readouterr().out
    assert "fonts/conf/all.conf" in said and "all.conf.new" in said


def test_a_staged_launcher_is_named_and_so_is_when_it_lands(capsys,
                                                            monkeypatch):
    """A file appearing beside the launcher, and an update that only half
    took effect until the next run, both need saying."""
    monkeypatch.setattr(cli.upgrade, "steps", steps(
        {"event": "done", "version": "0.2.0", "kept": [],
         "staged": ["crossglyph.cmd"], "converting": False,
         "where": "versions/0.2.0"}))
    cli.main(["update"])
    said = capsys.readouterr().out
    assert "crossglyph.cmd" in said and "next launch" in said


def test_a_conversion_says_the_old_files_are_no_longer_read(capsys,
                                                            monkeypatch):
    monkeypatch.setattr(cli.upgrade, "steps", steps(
        {"event": "plan", "version": "0.2.0", "bytes": 1600000,
         "notes_url": "https://example.invalid/", "converting": True},
        {"event": "done", "version": "0.2.0", "kept": [], "staged": [],
         "converting": True,
         "where": "versions/0.2.0"}))
    cli.main(["update"])
    said = capsys.readouterr().out
    assert "converting this install" in said
    assert "no longer read" in said


def test_rollback_says_where_it_landed(capsys, monkeypatch):
    monkeypatch.setattr(cli.upgrade, "rollback", lambda root: "0.1.0")
    assert cli.main(["update", "--rollback"]) == 0
    assert "back on 0.1.0" in capsys.readouterr().out


def test_a_rollback_with_nowhere_to_go_says_so(capsys, monkeypatch):
    def refuse(root):
        raise cli.upgrade.Refused("there is no version older than 0.1.0 to "
                                  "go back to")

    monkeypatch.setattr(cli.upgrade, "rollback", refuse)
    assert cli.main(["update", "--rollback"]) == 1
    assert "no version older" in capsys.readouterr().err


@pytest.fixture
def tidied(monkeypatch):
    seen = []
    monkeypatch.setattr(cli.layout, "tidy",
                        lambda root, keep: seen.append(keep))
    return seen


def test_housekeeping_runs_whatever_the_check_flags_say(monkeypatch, tidied):
    """Retention is not a check. Skipping it with --no-update-check would
    leave every old version on disk for anybody who uses the flag."""
    monkeypatch.setattr(cli, "_build", lambda argv: 0)
    cli.main(["build", "--no-update-check"])
    assert tidied == [1]


def test_housekeeping_runs_before_the_work(monkeypatch, tidied):
    """A build that raises is still a launch, and the sweep it skipped would
    not happen until one succeeded."""
    def boom(argv):
        raise RuntimeError("the fallbacks are missing")

    monkeypatch.setattr(cli, "_build", boom)
    with pytest.raises(RuntimeError):
        cli.main(["build"])
    assert tidied == [1]


def test_a_question_deletes_nothing(tidied):
    """--version is what somebody runs to find out what they have. Removing a
    directory as a side effect of asking is a surprise."""
    cli.main(["--version"])
    cli.main(["--help"])
    assert tidied == []
