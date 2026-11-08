"""Container entry point (src/housecairn/entrypoint.py, docs/adr/0015)."""

import json
import os
import signal
import sqlite3
import stat
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, tzinfo
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from housecairn import entrypoint

REPO_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _keep_umask() -> Iterator[None]:
    # prepare_environment() sets the process umask; restore it for other tests.
    previous = os.umask(0o022)
    os.umask(previous)
    yield
    os.umask(previous)


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "data"
    monkeypatch.setenv("HOUSECAIRN_DATA_DIR", str(path))
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return path


class TestSecretKey:
    def test_generated_once_with_mode_600(self, data: Path) -> None:
        entrypoint.prepare_data_dir(data)
        first = entrypoint.ensure_secret_key(data)
        key_file = data / "secret_key"
        assert len(first) >= 50
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
        assert entrypoint.ensure_secret_key(data) == first

    def test_environment_wins_and_writes_nothing(
        self, data: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entrypoint.prepare_data_dir(data)
        monkeypatch.setenv("SECRET_KEY", "from-the-environment")
        assert entrypoint.ensure_secret_key(data) == "from-the-environment"
        assert not (data / "secret_key").exists()

    def test_loose_permissions_are_restricted(self, data: Path) -> None:
        entrypoint.prepare_data_dir(data)
        key_file = data / "secret_key"
        key_file.write_text("existing-key\n", encoding="utf-8")
        key_file.chmod(0o644)
        assert entrypoint.ensure_secret_key(data) == "existing-key"
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600

    def test_empty_file_is_an_error(self, data: Path) -> None:
        entrypoint.prepare_data_dir(data)
        (data / "secret_key").write_text("", encoding="utf-8")
        with pytest.raises(SystemExit, match="empty"):
            entrypoint.ensure_secret_key(data)


class TestDataDir:
    def test_creates_the_tree(self, data: Path) -> None:
        entrypoint.prepare_data_dir(data)
        assert (data / "media").is_dir()
        assert sorted(p.name for p in data.iterdir()) == ["media"]

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
    def test_not_writable_is_explained(self, tmp_path: Path) -> None:
        locked = tmp_path / "locked"
        locked.mkdir(mode=0o500)
        with pytest.raises(SystemExit, match="not writable"):
            entrypoint.prepare_data_dir(locked)

    def test_file_in_the_way_is_explained(self, tmp_path: Path) -> None:
        blocker = tmp_path / "data"
        blocker.write_text("", encoding="utf-8")
        with pytest.raises(SystemExit, match="not writable"):
            entrypoint.prepare_data_dir(blocker)

    def test_prepare_environment(self, data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "")
        previous = os.umask(0o022)
        try:
            assert entrypoint.prepare_environment() == data
            assert os.umask(0o022) == 0o077
        finally:
            os.umask(previous)
        assert os.environ["SECRET_KEY"] == (data / "secret_key").read_text().strip()


class TestCommands:
    def test_web_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOUSECAIRN_PORT", "9000")
        monkeypatch.setenv("HOUSECAIRN_WEB_WORKERS", "3")
        command = entrypoint.web_command()
        assert command[1:4] == ["-m", "gunicorn", "housecairn.wsgi:application"]
        assert "--bind=0.0.0.0:9000" in command
        assert "--workers=3" in command
        assert "--worker-tmp-dir=/dev/shm" in command
        assert "--no-control-socket" in command

    def test_no_proxy_may_claim_https_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOUSECAIRN_BEHIND_TLS_PROXY", raising=False)
        monkeypatch.setenv("HOUSECAIRN_FORWARDED_ALLOW_IPS", "192.0.2.10")
        command = entrypoint.web_command()
        assert "--forwarded-allow-ips=" in command
        assert not any(arg.startswith("--forwarded-allow-ips=*") for arg in command)

    def test_behind_tls_proxy_default_is_the_loopback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOUSECAIRN_BEHIND_TLS_PROXY", "true")
        monkeypatch.delenv("HOUSECAIRN_FORWARDED_ALLOW_IPS", raising=False)
        assert "--forwarded-allow-ips=127.0.0.1,::1" in entrypoint.web_command()

    def test_behind_tls_proxy_trusts_the_configured_proxies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOUSECAIRN_BEHIND_TLS_PROXY", "yes")
        monkeypatch.setenv("HOUSECAIRN_FORWARDED_ALLOW_IPS", " 192.0.2.10, 2001:db8::/32 ,")
        assert "--forwarded-allow-ips=192.0.2.10,2001:db8::/32" in entrypoint.web_command()

    def test_worker(self) -> None:
        assert entrypoint.worker_command()[1:] == ["-m", "django", "qcluster"]

    def test_bad_integer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOUSECAIRN_PORT", "eighty")
        with pytest.raises(SystemExit, match="HOUSECAIRN_PORT"):
            entrypoint.web_command()

    def test_run_migrates_before_starting(
        self, data: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[object] = []

        def fake_run(command: list[str], check: bool) -> subprocess.CompletedProcess[bytes]:
            calls.append(command[1:])
            return subprocess.CompletedProcess(command, 0)

        def fake_supervise(self: entrypoint.Supervisor) -> int:
            calls.append([name for name, _ in self.commands])
            return 0

        monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)
        monkeypatch.setattr(entrypoint.Supervisor, "run", fake_supervise)
        assert entrypoint.main(["run"]) == 0
        assert calls == [
            ["-m", "django", "migrate", "--noinput"],
            ["-m", "django", "createcachetable"],
            ["web server", "task worker"],
        ]
        assert (data / "secret_key").is_file()

    def test_failed_migrations_stop_the_start(
        self, data: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            entrypoint.subprocess,
            "run",
            lambda command, check: subprocess.CompletedProcess(command, 3),
        )
        with pytest.raises(SystemExit, match="migrations failed"):
            entrypoint.main([])

    def test_manage_replaces_the_process(self, data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []

        def fake_execv(path: str, args: list[str]) -> None:
            seen.append(args[1:])

        monkeypatch.setattr(entrypoint.os, "execv", fake_execv)
        entrypoint.main(["manage", "changepassword", "admin@example.com"])
        assert seen == [["-m", "django", "changepassword", "admin@example.com"]]

    @pytest.mark.parametrize("argv", [["unknown"], ["manage"], ["run", "extra"]])
    def test_usage(self, argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
        assert entrypoint.main(argv) == 2
        assert "usage:" in capsys.readouterr().err


SUPERVISED = textwrap.dedent(
    """
    import sys
    from housecairn.entrypoint import Supervisor
    py = sys.executable
    commands = [(name, [py, "-c", code]) for name, code in {spec}]
    sys.exit(Supervisor(commands, stop_timeout={timeout}, poll_interval=0.05).run())
    """
)
SLEEPER = "import time; time.sleep(60)"
STUBBORN = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"


def start_supervisor(spec: list[tuple[str, str]], timeout: float = 5.0) -> subprocess.Popen[str]:
    code = SUPERVISED.format(spec=repr(spec), timeout=timeout)
    return subprocess.Popen(  # noqa: S603 - fixed test code
        [sys.executable, "-c", code],
        cwd=REPO_DIR,
        env={**os.environ, "PYTHONPATH": str(REPO_DIR / "src")},
        stderr=subprocess.PIPE,
        text=True,
    )


class TestSupervisor:
    def test_one_process_exits_so_all_stop(self) -> None:
        proc = start_supervisor([("web", SLEEPER), ("worker", "raise SystemExit(4)")])
        _, err = proc.communicate(timeout=30)
        assert proc.returncode == 4
        assert "worker exited with code 4, stopping the others" in err

    def test_killed_process_gives_128_plus_signal(self) -> None:
        kill_self = "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"
        proc = start_supervisor([("web", SLEEPER), ("worker", kill_self)])
        proc.communicate(timeout=30)
        assert proc.returncode == 128 + signal.SIGKILL

    def test_clean_exit_still_stops_the_container(self) -> None:
        proc = start_supervisor([("web", SLEEPER), ("worker", "pass")])
        proc.communicate(timeout=30)
        assert proc.returncode == 1

    def test_sigterm_stops_everything_cleanly(self) -> None:
        proc = start_supervisor([("web", SLEEPER), ("worker", SLEEPER)])
        time.sleep(1.0)
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        _, err = proc.communicate(timeout=30)
        assert proc.returncode == 0
        assert "received SIGTERM, stopping" in err
        assert time.monotonic() - started < 5

    def test_process_ignoring_sigterm_is_killed(self) -> None:
        proc = start_supervisor([("web", STUBBORN), ("worker", SLEEPER)], timeout=1.0)
        time.sleep(1.0)
        proc.send_signal(signal.SIGTERM)
        _, err = proc.communicate(timeout=30)
        assert proc.returncode == 0
        assert "web did not stop within 1 s, killing it" in err

    def test_orphans_are_collected(self) -> None:
        # A finished child that is not supervised is collected; the supervised
        # one, still running, is left alone.
        supervisor = entrypoint.Supervisor([])
        own = subprocess.Popen([sys.executable, "-c", SLEEPER])  # noqa: S603
        supervisor.processes["own"] = own
        stray = subprocess.Popen([sys.executable, "-c", "pass"])
        stray_pid = stray.pid
        time.sleep(1.0)
        supervisor.reap_orphans()
        with pytest.raises(ChildProcessError):
            os.waitpid(stray_pid, os.WNOHANG)
        assert own.poll() is None
        own.kill()
        own.wait(timeout=5)
        supervisor.reap_orphans()  # nothing left to collect


class _Health(BaseHTTPRequestHandler):
    status = 200
    body = b'{"status": "ok"}'
    seen_hosts: list[str] = []

    def do_GET(self) -> None:
        type(self).seen_hosts.append(self.headers["Host"])
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture
def health_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_Health]]:
    server = HTTPServer(("127.0.0.1", 0), _Health)
    monkeypatch.setenv("HOUSECAIRN_PORT", str(server.server_address[1]))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Health.seen_hosts = []
    _Health.status = 200
    _Health.body = b'{"status": "ok"}'
    yield _Health
    server.shutdown()
    server.server_close()


class TestHealthcheck:
    @pytest.mark.parametrize(
        ("allowed", "host"),
        [
            ("housecairn.example.com,localhost", "housecairn.example.com"),
            (" *, .example.com", "example.com"),
            ("", "localhost"),
            ("*", "localhost"),
        ],
    )
    def test_host_header(self, allowed: str, host: str) -> None:
        assert entrypoint.health_host(allowed) == host

    def test_healthy(self, health_server: type[_Health], monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALLOWED_HOSTS", "housecairn.example.com")
        assert entrypoint.main(["healthcheck"]) == 0
        assert health_server.seen_hosts == ["housecairn.example.com"]

    def test_unhealthy_answer(
        self, health_server: type[_Health], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        health_server.status = 503
        health_server.body = json.dumps({"status": "unavailable"}).encode()
        assert entrypoint.command_healthcheck() == 1

    def test_unexpected_body(self, health_server: type[_Health]) -> None:
        # Status 503 would fail earlier: this one answers 200 with another body.
        health_server.body = b"[]"
        assert entrypoint.command_healthcheck() == 1

    def test_nothing_listening(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with closing(__import__("socket").socket()) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        monkeypatch.setenv("HOUSECAIRN_PORT", str(port))
        assert entrypoint.command_healthcheck(timeout=1.0) == 1


class TestBackup:
    def test_online_copy(self, data: Path, capsys: pytest.CaptureFixture[str]) -> None:
        entrypoint.prepare_data_dir(data)
        with closing(sqlite3.connect(data / "db.sqlite3")) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE t (v TEXT)")
            db.execute("INSERT INTO t VALUES ('kept')")
            db.commit()
            # The database stays open, as with the application running.
            assert entrypoint.main(["backup"]) == 0
        target = Path(capsys.readouterr().out.strip())
        assert target.parent == data / "backups"
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        with closing(sqlite3.connect(target)) as copy:
            assert copy.execute("SELECT v FROM t").fetchall() == [("kept",)]

    def test_created_private_without_chmod(
        self, data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The copy is mode 600 from its creation, not restricted afterwards."""
        entrypoint.prepare_data_dir(data)
        with closing(sqlite3.connect(data / "db.sqlite3")) as db:
            db.execute("CREATE TABLE t (v TEXT)")
            db.commit()
        chmods: list[object] = []
        monkeypatch.setattr(entrypoint.os, "chmod", lambda *args, **kw: chmods.append(args))
        modes_when_opened: list[int] = []
        real_connect = sqlite3.connect

        def connect(database: str | Path, **kwargs: Any) -> sqlite3.Connection:
            path = Path(database)
            if path.parent == data / "backups":
                # SQLite is about to write the copy: it must already be private.
                modes_when_opened.append(stat.S_IMODE(path.stat().st_mode))
            connection: sqlite3.Connection = real_connect(database, **kwargs)
            return connection

        monkeypatch.setattr(sqlite3, "connect", connect)
        # A permissive umask, as with `docker exec`.
        previous = os.umask(0o022)
        try:
            assert entrypoint.command_backup() == 0
        finally:
            os.umask(previous)
        target = Path(capsys.readouterr().out.strip())
        assert modes_when_opened == [0o600]
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert chmods == []

    def test_existing_target_is_not_overwritten(
        self, data: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entrypoint.prepare_data_dir(data)
        sqlite3.connect(data / "db.sqlite3").close()
        (data / "backups").mkdir()

        class Fixed(datetime):
            @classmethod
            def now(cls, tz: tzinfo | None = None) -> "Fixed":
                return cls(2026, 1, 2, 3, 4, 5, tzinfo=tz)

        monkeypatch.setattr(entrypoint, "datetime", Fixed)
        existing = data / "backups" / "db-20260102T030405Z.sqlite3"
        existing.write_bytes(b"older copy")
        assert entrypoint.command_backup() == 1
        assert existing.read_bytes() == b"older copy"

    def test_explicit_sqlite_url(self, data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{data}/other.sqlite3")
        assert entrypoint.sqlite_path() == data / "other.sqlite3"

    def test_no_database_yet(self, data: Path) -> None:
        assert entrypoint.command_backup() == 1

    def test_postgresql_is_refused(
        self, data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgres://housecairn@db.example.com/housecairn")
        assert entrypoint.command_backup() == 2
        assert "pg_dump" in capsys.readouterr().err
