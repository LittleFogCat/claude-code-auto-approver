"""Unit tests for rule.py utilities."""

from __future__ import annotations

from classifier.engine.rule import compile_pattern, glob_match, pattern_hits


def test_compile_and_match():
    # Matches rm -rf / style (R before F)
    p_rf = compile_pattern(r"rm\s+-[a-zA-Z]*[rR][a-zA-Z]*f")
    assert pattern_hits("rm -rf /", p_rf)
    assert pattern_hits("please rm -Rf /tmp", p_rf)
    assert not pattern_hits("rm -fr /", p_rf)  # FR order, not RF
    assert not pattern_hits("echo hi", p_rf)
    assert not pattern_hits(None, p_rf)

    # Matches rm -fr / style (F before R)
    p_fr = compile_pattern(r"rm\s+-[a-zA-Z]*[fF][a-zA-Z]*[rR]\b")
    assert pattern_hits("rm -fr /", p_fr)
    assert pattern_hits("rm -fr /tmp/test", p_fr)


def test_glob_match_simple():
    assert glob_match("/repo/.env", "**/.env")
    assert glob_match("/repo/.env", "/repo/.env")
    assert glob_match("/repo/.env.local", "**/.env.*")
    assert not glob_match("/repo/main.py", "**/.env")


def test_glob_match_windows():
    assert glob_match("C:\\repo\\app\\.env.local", "**/.env.*")
    assert glob_match("C:/repo/app/.env.local", "**/.env.*")
    assert glob_match("C:\\Users\\alice\\.ssh\\id_rsa", "C:/Users/*/.ssh/id_*")
    assert glob_match("C:/Users/alice/.ssh/id_rsa", "C:/Users/*/.ssh/id_*")


def test_glob_match_user_home():
    assert glob_match("~/.aws/credentials", "~/.aws/credentials")
    # After expansion it should also work
    import os
    home = os.path.expanduser("~")
    assert glob_match(f"{home}/.aws/credentials", "~/.aws/credentials")


def test_glob_match_double_star():
    # ** matches any depth
    assert glob_match("/a/b/c/.env", "**/.env")
    assert glob_match("/.env", "**/.env")
    assert glob_match("/repo/sub/sub/sub/x.pem", "**/*.pem")
    assert not glob_match("/repo/main.py", "**/*.pem")