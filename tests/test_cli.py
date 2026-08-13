"""One command, three subcommands, and the preview as the default."""
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
