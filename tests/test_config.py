"""config — .env 로더가 CI 환경변수를 덮어쓰지 않는지, 필수 키가 없으면 즉시 실패하는지."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from briefing import config


def write_env(tmp_path: Path, body: str) -> Path:
    """임시 .env 파일을 만든다."""
    p = tmp_path / ".env"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_env_sets_missing_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KSB_TEST_A", raising=False)
    config.load_env(write_env(tmp_path, "KSB_TEST_A=hello\n"))
    assert os.environ["KSB_TEST_A"] == "hello"


def test_load_env_does_not_overwrite_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI가 주입한 Secret을 로컬 .env가 덮어쓰면 원인을 찾기 어려운 사고가 난다."""
    monkeypatch.setenv("KSB_TEST_B", "from-ci")
    config.load_env(write_env(tmp_path, "KSB_TEST_B=from-dotenv\n"))
    assert os.environ["KSB_TEST_B"] == "from-ci"


def test_load_env_skips_comments_and_blanks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KSB_TEST_C", raising=False)
    config.load_env(write_env(tmp_path, "# 주석\n\n  \nKSB_TEST_C = \"quoted\" \n"))
    assert os.environ["KSB_TEST_C"] == "quoted"


def test_load_env_missing_file_is_noop(tmp_path: Path) -> None:
    """CI에는 .env가 없다. 없다고 죽으면 안 된다."""
    config.load_env(tmp_path / "nope.env")


def test_require_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """조용히 None으로 흘려보내지 않는다 (N5)."""
    monkeypatch.delenv("KSB_TEST_D", raising=False)
    with pytest.raises(RuntimeError, match="KSB_TEST_D"):
        config.require("KSB_TEST_D")


def test_require_treats_blank_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KSB_TEST_E", "   ")
    with pytest.raises(RuntimeError):
        config.require("KSB_TEST_E")


def test_optional_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KSB_TEST_F", raising=False)
    assert config.optional("KSB_TEST_F", "dflt") == "dflt"
    monkeypatch.setenv("KSB_TEST_F", " set ")
    assert config.optional("KSB_TEST_F", "dflt") == "set"
