"""환경변수 로딩.

외부 패키지(python-dotenv)를 쓰지 않는다 — 최소 의존성 원칙 (SPEC N4).
CI에서는 GitHub Secrets가 환경변수로 먼저 주입되므로 **이미 설정된 값을 덮어쓰지 않는다.**
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> None:
    """`.env`를 읽어 환경변수에 채운다.

    Args:
        path: `.env` 경로. None이면 프로젝트 루트의 `.env`를 쓴다.

    Note:
        이미 설정된 환경변수는 건드리지 않는다. 로컬 `.env`가 CI Secrets를
        덮어쓰면 원인을 찾기 매우 어려운 사고가 난다. 파일이 없으면 조용히 넘어간다 — CI에는 없다.
    """
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("\"'")


def require(key: str) -> str:
    """필수 환경변수를 읽는다. 없으면 즉시 실패한다 (SPEC N5).

    Args:
        key: 환경변수 이름.

    Returns:
        환경변수 값 (양끝 공백 제거).

    Raises:
        RuntimeError: 값이 없거나 비어 있을 때. 조용히 None으로 흘려보내지 않는다.
    """
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"환경변수 {key}가 없다. .env 또는 GitHub Secrets를 확인하라.")
    return value


def optional(key: str, default: str = "") -> str:
    """선택 환경변수를 읽는다. 없으면 기본값."""
    return os.environ.get(key, default).strip()
