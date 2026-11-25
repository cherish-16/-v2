from daily_report.cli import main


def test_run_returns_zero(tmp_path, capsys):
    code = main(
        ["run", "--team", "t1", "--date", "2026-11-25", "--demo",
         "--db", str(tmp_path / "c.db")]
    )
    assert code == 0
    assert "success" in capsys.readouterr().out


def test_repeat_run_reports_skipped(tmp_path, capsys):
    args = ["run", "--team", "t1", "--date", "2026-11-25", "--demo",
         "--db", str(tmp_path / "c.db")]
    main(args)
    assert main(args) == 0
    assert "重复触发已忽略" in capsys.readouterr().out


def test_invalid_date_returns_2(tmp_path):
    code = main(
        ["run", "--team", "t1", "--date", "not-a-date", "--db", str(tmp_path / "c.db")]
    )
    assert code == 2


def test_missing_team_returns_2(tmp_path):
    assert main(["run", "--db", str(tmp_path / "c.db")]) == 2