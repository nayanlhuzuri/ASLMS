"""The welcome mail's text (design `offices-import`, decision 18): the offices and user types by name and the steps
through Forgot password?; no password, no code and no link token."""

from __future__ import annotations

import re

from aslms.services.users import WELCOME_SUBJECT, welcome_text


def test_welcome_mail_has_no_password_code_or_token():
    body = welcome_text(
        "Asha Das",
        "asha@example.gov.in",
        [("Transport", "Head of Department"), ("Directorate of Transport", "Directorate Officer")],
        "http://localhost:3000/",
    )
    assert WELCOME_SUBJECT == "Your ASLMS Sign-In Is Ready"
    assert "Dear Asha Das," in body
    assert (
        "- Transport: Head of Department" in body
        and "- Directorate of Transport: Directorate Officer" in body
    )
    assert "http://localhost:3000/forgot" in body and "asha@example.gov.in" in body
    assert "6-digit code" in body and "confirm your profile" in body
    assert not re.search(r"\b\d{6}\b", body)  # no code
    assert "password:" not in body.lower()
    assert "token" not in body.lower() and "?" not in body.split("/forgot", 1)[1].split()[0]
    assert re.findall(r"https?://\S+", body) == ["http://localhost:3000/forgot"]
