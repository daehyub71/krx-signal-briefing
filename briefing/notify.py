"""Gmail SMTP 발송 (F10) — 상위 프로젝트와 같은 방식·같은 자격증명.

표준 라이브러리만 쓴다 (`smtplib` + `email.message`). macOS 파이썬은 CA 번들이 없어
`certifi`를 명시적으로 준다. **예외를 밖으로 내지 않는 것은 노드의 몫**이고, 여기서는 올린다.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import certifi

from briefing import config

HOST, PORT = "smtp.gmail.com", 587
TIMEOUT = 30.0


def recipients() -> list[str]:
    """수신자 목록. 본인 1명이다 (SPEC R7 — 늘리면 유사투자자문업 경계)."""
    return [x.strip() for x in config.require("RECIPIENTS").split(",") if x.strip()]


def build_message(subject: str, text: str, html: str, sender: str, to: list[str]) -> EmailMessage:
    """평문 + HTML 대체본. 평문을 함께 보내야 스팸 점수가 낮다 (R9)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send(subject: str, text: str, html: str) -> int:
    """메일을 보낸다.

    Returns:
        수신자 수.

    Raises:
        smtplib.SMTPException · OSError: 인증·연결 실패. 호출 노드가 잡아 상태에 적는다.
    """
    sender = config.require("GMAIL_ADDRESS")
    to = recipients()
    msg = build_message(subject, text, html, sender, to)
    ctx = ssl.create_default_context(cafile=certifi.where())
    with smtplib.SMTP(HOST, PORT, timeout=TIMEOUT) as s:
        s.starttls(context=ctx)
        s.login(sender, config.require("GMAIL_APP_PASSWORD"))
        s.send_message(msg)
    return len(to)
