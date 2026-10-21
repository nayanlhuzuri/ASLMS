"""The ASLMS service checks that need no database (design `api-health-checker`, decision 10): each card's ok, warn
and down at the Prometheus rules' thresholds, the direct database probe's protocol, and a raising check."""

from __future__ import annotations

import socket
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from aslms.core.config import Settings
from aslms.services import service_checks as sc

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
GB = 1024**3
SETTINGS = Settings(_env_file=None, app_env="test", redis_url=None)


def _clam(at: datetime) -> str:
    return f"ClamAV 1.5.4/27795/{at.strftime('%a %b %d %H:%M:%S %Y')}"


def test_redis_ok_warn_down():
    ok = sc.check_redis({"ping_ms": 2, "version": "7.4", "used": 50, "max": 100}, None, 3)
    assert (ok.status, ok.headline) == ("ok", "Answered in 2 ms")
    assert sc.check_redis({"ping_ms": 2, "version": "7.4", "used": 91, "max": 100}, None, 3).status == "warn"
    assert sc.check_redis({"ping_ms": 2, "version": "7.4", "used": 10**9, "max": 0}, None, 3).status == "ok"
    down = sc.check_redis(None, "ConnectionError", 5000)
    assert down.status == "down" and down.facts == [{"label": "Error", "value": "ConnectionError"}]


def test_clamav_ok_old_down():
    assert sc.check_clamav(_clam(NOW - timedelta(days=1)), None, NOW, 4).status == "ok"
    old = sc.check_clamav(_clam(NOW - timedelta(days=3, minutes=1)), None, NOW, 4)
    assert old.status == "warn" and "old" in old.headline
    assert sc.check_clamav("ClamAV 1.5.4", None, NOW, 4).status == "warn"  # signatures not loaded yet
    down = sc.check_clamav(None, "ScannerUnavailable", NOW, 4)
    assert down.status == "down" and "uploads are refused" in down.headline


def test_store_ok_low_unwritable():
    roomy = SimpleNamespace(free=200 * GB, total=400 * GB)
    assert sc.check_store(None, roomy, 1).status == "ok"
    assert sc.check_store(None, SimpleNamespace(free=50 * GB, total=400 * GB), 1).status == "warn"  # < 15 %
    assert sc.check_store(None, SimpleNamespace(free=9 * GB, total=40 * GB), 1).status == "warn"  # < 10 GB
    down = sc.check_store("PermissionError", None, 1)
    assert down.status == "down" and down.headline == "ASLMS cannot save documents"


def test_web_ok_slow_down():
    assert sc.check_web(True, 120).status == "ok"
    assert sc.check_web(True, 2500).status == "warn"
    assert sc.check_web(False, 30).status == "down"
    assert sc.check_web(None, 0).status == "unknown"


def test_direct_probe_states():
    assert sc.check_db_direct("S", None, True, SETTINGS, 2).status == "ok"
    n = sc.check_db_direct("N", None, False, SETTINGS, 2)
    assert n.status == "ok" and n.headline == "The database answers; the pool (PgBouncer) does not"
    mismatch = sc.check_db_direct(None, "ConnectionRefusedError", True, SETTINGS, 2)
    assert mismatch.status == "warn" and "configuration mismatch" in mismatch.headline
    assert sc.check_db_direct(None, "ConnectionRefusedError", False, SETTINGS, 2).status == "down"


def _server(answer: bytes):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got: list[bytes] = []

    def serve():
        conn, _ = srv.accept()
        with conn:
            got.append(conn.recv(8))
            conn.sendall(answer)
        srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1], got


def test_pg_direct_probe_speaks_the_ssl_request():
    port, got = _server(b"N")
    assert sc.pg_direct_probe("127.0.0.1", port, 2) == "N"
    assert got == [sc.SSL_REQUEST] and len(sc.SSL_REQUEST) == 8
    port, _ = _server(b"S")
    assert sc.pg_direct_probe("127.0.0.1", port, 2) == "S"
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    closed = free.getsockname()[1]
    free.close()
    try:
        sc.pg_direct_probe("127.0.0.1", closed, 1)
        raise AssertionError("a refused connection must raise")
    except OSError:
        pass


def test_a_raising_check_is_unknown_with_the_class_name_only():
    def boom():
        raise ValueError("postgresql://user:secret@host/db")

    out = sc._safe("worker", boom).to_dict()
    assert out["status"] == "unknown" and out["facts"] == [{"label": "Error", "value": "ValueError"}]
    assert "secret" not in str(out)
    value, err, _ms = sc._timed(boom)
    assert value is None and err == "ValueError"
