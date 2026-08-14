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
