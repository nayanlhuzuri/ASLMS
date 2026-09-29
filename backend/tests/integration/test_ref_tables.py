"""DB_STANDARD §7 / §12.2 step 3: every enum member has a `ref_*` row after seed, the second seed inserts
nothing, and a code outside the set is rejected by the database."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.db.seed import run_seed
from aslms.db.seed_ref import ref_row_counts
from aslms.domain.org import Office, OfficeKind, Role, User
from aslms.domain.workflow import Stage


def test_seed_fills_every_code_set_once(db: Session) -> None:
    db.execute(sa.text("TRUNCATE " + ", ".join(t for t in ref_row_counts(db)) + " CASCADE"))
    db.commit()
    first = run_seed(db)
    db.commit()
    assert first["ref_rows_inserted"] > 0
    counts = ref_row_counts(db)
    assert all(rows == size for rows, size in counts.values()), counts
    assert counts["ref_case_stage"] == (len(Stage), 17)
    second = run_seed(db)
    db.commit()
    assert second["ref_rows_inserted"] == 0
    assert second["designations_inserted"] == 0 and second["districts_inserted"] == 0


def test_a_code_outside_the_set_is_rejected(db: Session) -> None:
    run_seed(db)
    db.commit()
    office = db.scalar(sa.select(Office).where(Office.code == "STATE"))
    with pytest.raises(sa.exc.IntegrityError):
        db.execute(
            sa.text(
                "INSERT INTO users (email, password_hash, full_name, office_id, role) "
                "VALUES ('x@t.in', 'h', 'X', :office, 'sultan')"
            ),
            {"office": office.id},
        )
    db.rollback()
    # the enum members themselves are accepted
    db.add(
        User(
            email="ok@t.in",
            password_hash="h",
            full_name="OK",
            office_id=office.id,
            role=Role.AUDITOR,
        )
    )
    db.flush()
    assert db.scalar(sa.select(Office.kind).where(Office.code == "STATE")) == OfficeKind.STATE_OFFICE
