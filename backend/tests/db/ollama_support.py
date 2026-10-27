"""Helpers for the local-model Case Assistant tests (design `assistant-ollama`): a connector over `FakeOllama`, a scene
with planted words in court orders, saved notes, a draft, a custody remark and department documents, and the switch
and questions through the service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.documents import DocGroup, DocKind
from aslms.domain.reference import DocType
from aslms.services import assistant as svc
from aslms.services.assistant_ollama import OllamaConnector
from aslms.services.audit import Actor
from tests.db import assistant_support as sup
from tests.db import workflow_support as w
from tests.db.world import make_case
from tests.fakes.ollama import FakeOllama

CONFIG = svc.AssistantConfig(timeout_seconds=10.0, retry_delay=0.01)
WORDS = {
    "order": "quokka",  # A's court order
    "saved": "numbat",  # a saved case-scope note on A by the EDU admin
    "private": "bilby",  # a private-to-office note on A by the EDU admin
    "remark": "dingo",  # the custody remark of the send to the directorate
    "draft": "echidna",  # an unsent draft on A by the holder
    "internal": "wallaby",  # an internal upload on A
    "restricted": "platypus",  # a private-to-office internal upload on A
    "other": "koala",  # case B's note, remark and upload
}


def settings(**over) -> Settings:
    base = {
        "assistant_mode": "ollama",
        "assistant_timeout_seconds": 10.0,
        "assistant_ollama_timeout_seconds": 5.0,
        "assistant_ollama_url": "http://127.0.0.1:9",
    }
    base.update(over)
    return Settings(_env_file=None, **base)


def connector(world, fake: FakeOllama | None = None, **over) -> OllamaConnector:
    fake = fake or FakeOllama()
    conn = OllamaConnector(world.Session, settings(**over), client=fake.client())
    conn.fake = fake  # type: ignore[attr-defined]
    return conn


@dataclass
class Scene:
    a: object
    b: object
    a_cnr: str
    store: object
    order_doc: object
    internal_doc: object
    restricted_doc: object


def build(world, store) -> Scene:
    """Case A (EDU, allotted to edu_off1): a court order on the quokka scheme; the EDU admin's saved note (numbat) and
    private note (bilby); edu_off1 sends the file to dse_user with the dingo remark; dse_user (now the holder) keeps a
    draft (echidna); an internal upload (wallaby) and a private one (platypus). Case B: the same kinds with koala."""
    with world.Session() as s:
        a = w.claimed_case(s, world, officer="edu_off1", case_no="WP(C)/301/2026")
        b = w.claimed_case(s, world, officer="edu_off1", case_no="WP(C)/302/2026")
        edu = world.office(s, "EDU")
        _o, order_doc = sup.order(
            s,
            store,
            a,
            [
                "The petitioner seeks arrears under the quokka scheme.",
                "The respondents shall file an affidavit on the quokka scheme within four weeks. Returnable on 12 April 2026.",
            ],
            order_no="5",
        )
        w.note(
            s, world, "edu_admin", a, body=f"Our stand on the {WORDS['saved']} issue is to contest the claim."
        )
        w.note(
            s,
            world,
            "edu_admin",
            a,
            body=f"Office only: the {WORDS['private']} matter.",
            visibility_="private_to_office",
        )
        internal = sup.filing(
            s,
            store,
            a,
            edu,
            [f"Legal opinion on the {WORDS['internal']} point of the quokka scheme."],
            group=DocGroup.INTERNAL,
            doc_type=DocType.LEGAL_OPINION,
        )
        from aslms.domain.documents import Visibility

        restricted = sup.filing(
            s,
            store,
            a,
            edu,
            [f"Restricted note on the {WORDS['restricted']} point of the quokka scheme."],
            group=DocGroup.INTERNAL,
            doc_type=DocType.LEGAL_OPINION,
            visibility=Visibility.PRIVATE_TO_OFFICE,
        )
        w.send(
            s,
            world,
            "edu_off1",
            a,
            "dse_user",
            remark=f"see the {WORDS['remark']} papers",
            due_date=w.in_days(5),
        )
        w.note(s, world, "dse_user", a, body=f"draft about the {WORDS['draft']} question")
        # case B
        w.note(s, world, "edu_admin", b, body=f"the {WORDS['other']} note of case B")
        sup.filing(
            s,
            store,
            b,
            edu,
            [f"the {WORDS['other']} opinion of case B"],
            group=DocGroup.INTERNAL,
            doc_type=DocType.LEGAL_OPINION,
        )
        w.send(s, world, "edu_off1", b, "dse_user", remark=f"the {WORDS['other']} remark of case B")
        s.commit()
        return Scene(a.id, b.id, a.cnr, store, order_doc.id, internal.id, restricted.id)


def ask(world, key: str, question: str, scope: str, conn, *, case=None, **kw):
    with world.Session() as s:
        actor, user = world.actor(s, key)
    return asyncio.run(
        svc.ask(
            world.Session,
            actor,
            user,
            question=question,
            scope=scope,
            case=case,
            connector=conn,
            config=CONFIG,
            **kw,
        )
    )


def switch(world, key: str, case, conversation_id=None, mode: str = "ollama") -> dict:
    with world.Session() as s:
        actor, user = world.actor(s, key)
    return svc.include_internal(
        world.Session, actor, user, case=case, conversation_id=conversation_id, mode=mode
    )


def system_switch(world, key: str, case, conversation_id=None) -> dict:
    with world.Session() as s:
        user = world.user(s, key)
        s.expunge(user)
    return svc.include_internal(
        world.Session, Actor.system("cli"), user, case=case, conversation_id=conversation_id, mode="ollama"
    )


def other_case(world, key: str = "health_admin") -> object:
    """A case of another department (HEALTH)."""
    from tests.db import alerts_support as h

    with world.Session() as s:
        c = make_case(s, case_no="WP(C)/909/2026")
        h.claim(s, world, key, c)
        s.commit()
        return c.id


def get_case(world, case_id) -> Case:
    with world.Session() as s:
        c = s.get(Case, case_id)
        s.expunge(c)
        return c


__all__ = ["DocKind"]
