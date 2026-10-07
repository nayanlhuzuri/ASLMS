"""`services/profile.py` (design `otp-and-profile`, decisions 11, 12): the confirmation's order and checks, the
preferences saved through the notifications service, read-only memberships, and edits audited only when
something changed."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.services import access, profile
from aslms.services.profile import ProfileError


def _audit(s, action: str) -> list:
    return list(
        s.execute(sa.text("select before, after from audit_log where action = :a"), {"a": action}).all()
    )


def test_confirm_order_and_checks(world):
    with world.Session() as s:
        user = world.user(s, "edu_off1")
        actor = access.actor_for(user)
        user.must_change_password, user.must_confirm_profile = True, True
        with pytest.raises(ProfileError) as e:
            profile.confirm(s, actor, user, full_name="Edu Off1", mobile="9864012345")
        assert e.value.code == "password_change_required" and e.value.http_status == 409
        user.must_change_password = False
        for name, mobile, code in (
            ("Edu Off1", None, "invalid_mobile"),
            ("Edu Off1", "1234567890", "invalid_mobile"),
            ("E", "9864012345", "invalid_name"),
        ):
            with pytest.raises(ProfileError) as e:
                profile.confirm(s, actor, user, full_name=name, mobile=mobile)
            assert e.value.code == code and e.value.http_status == 422
        with pytest.raises(ProfileError) as e:
            profile.confirm(
                s,
                actor,
                user,
                full_name="Edu Off1",
                mobile="9864012345",
                preferences={"sms": {"enabled": True}},
            )
        assert e.value.code == "channel_not_available"
        out = profile.confirm(
            s,
            actor,
            user,
            full_name="Edu Officer One",
            mobile="+919864012345",
            preferences={"email": {"critical_only": True}},
        )
        assert (
            out["mobile"] == "9864012345"
            and out["notification_preferences"]["email"]["critical_only"] is True
        )
        assert out["memberships"] == [
            {
                "office": {"code": "EDU", "name": "Education", "kind": "department"},
                "designation": None,
                "role": "dept_officer",
                "is_primary": True,
            }
        ]
        assert user.must_confirm_profile is False and user.profile_confirmed_at is not None
        [(before, after)] = _audit(s, "profile.confirmed")
        assert before["must_confirm_profile"] is True and after["mobile"] == "9864012345"
        assert len(_audit(s, "notification_preferences.changed")) == 1
        with pytest.raises(ProfileError) as e:
            profile.confirm(s, actor, user, full_name="Edu Officer One", mobile="9864012345")
        assert e.value.code == "already_confirmed"
        s.rollback()


def test_update_audits_only_a_change(world):
    with world.Session() as s:
        user = world.user(s, "edu_off1")
        actor = access.actor_for(user)
        user.mobile = "9864012345"
        s.flush()
        profile.update(s, actor, user, mobile="98640 12345")  # the same number, written differently
        assert _audit(s, "profile.updated") == []
        profile.update(s, actor, user, full_name="Edu Officer", mobile="7002012345")
        [(before, after)] = _audit(s, "profile.updated")
        assert before["mobile"] == "9864012345" and after == {
            **after,
            "mobile": "7002012345",
            "full_name": "Edu Officer",
        }
        with pytest.raises(ProfileError):
            profile.update(s, actor, user, mobile="")
        s.rollback()
