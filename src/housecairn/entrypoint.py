"""Container entry point: prepare the data directory, then run HouseCairn.

Usage (the image's ENTRYPOINT is `python -m housecairn.entrypoint`):

- `run` (default): create the secret key if needed, apply the migrations, then
  start the web server (gunicorn) and the task worker (django-q2) and supervise
  them. If either stops, the other is stopped and the container exits;
  SIGTERM or SIGINT stops both cleanly.
- `healthcheck`: exit 0 if `/healthz` answers "ok", 1 otherwise (used by the
  image's HEALTHCHECK).
- `backup`: write a consistent copy of the SQLite database under
  `<data>/backups/`, while the application runs.
- `manage <command> [args]`: run a Django management command.

No account is created here: while there is no administrator, a one-time code is
written to the log and the first one is created on the web screen /setup/
(docs/adr/0055, docs/getting-started/first-start.md). See docs/adr/0015.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import NoReturn

SETTINGS_MODULE = "housecairn.settings"
DEFAULT_DATA_DIR = "/data"
SECRET_KEY_FILE = "secret_key"  # noqa: S105 - a file name, not a secret
DEFAULT_PORT = 8000
DEFAULT_WEB_WORKERS = 2
DEFAULT_STOP_TIMEOUT = 20.0
# Same default as HOUSECAIRN_FORWARDED_ALLOW_IPS in the settings.
DEFAULT_FORWARDED_ALLOW_IPS = ("127.0.0.1", "::1")


def log(message: str) -> None:
    sys.stderr.write(f"housecairn: {message}\n")
    sys.stderr.flush()


def data_dir() -> Path:
    return Path(os.environ.get("HOUSECAIRN_DATA_DIR", DEFAULT_DATA_DIR))


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"housecairn: {name} must be an integer, not {raw!r}.") from exc


def prepare_data_dir(path: Path) -> None:
    """Create the data directory tree and fail early if it is not writable."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        (path / "media").mkdir(exist_ok=True)
        probe = path / f".write-test-{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise SystemExit(
            f"housecairn: the data directory {path} is not writable by user "
            f"{os.getuid()}:{os.getgid()} ({exc.strerror}). Give that user ownership "
            "of the volume, for example: chown -R 10001:10001 <host directory>."
        ) from exc


def ensure_secret_key(path: Path) -> str:
    """Return SECRET_KEY: from the environment, else from `<data>/secret_key`.

    The file is created on first start with 50 random bytes, readable by the
    application user only (mode 600), and reused afterwards.
    """
    from_env = os.environ.get("SECRET_KEY", "").strip()
    if from_env:
        return from_env
    key_file = path / SECRET_KEY_FILE
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return read_secret_key(key_file)
    key = secrets.token_urlsafe(50)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(key + "\n")
    log(f"generated a new secret key in {key_file}")
    return key


def read_secret_key(key_file: Path) -> str:
    key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(f"housecairn: {key_file} is empty; delete it or set SECRET_KEY.")
    if key_file.stat().st_mode & 0o077:
        os.chmod(key_file, 0o600)
        log(f"restricted {key_file} to mode 600")
    return key


def django_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "django", *args]


def web_command() -> list[str]:
    port = env_int("HOUSECAIRN_PORT", DEFAULT_PORT)
    workers = env_int("HOUSECAIRN_WEB_WORKERS", DEFAULT_WEB_WORKERS)
    return [
        sys.executable,
        "-m",
        "gunicorn",
        "housecairn.wsgi:application",
        f"--bind=0.0.0.0:{port}",
        f"--workers={workers}",
        # Heartbeat files of the workers: in memory, the root file system is
        # read-only.
        "--worker-tmp-dir=/dev/shm",
        # No runtime control interface: it would need a writable socket path and
        # is not needed in a container.
        "--no-control-socket",
        "--access-logfile=-",
        "--error-logfile=-",
        # The address of a calendar feed is a secret: the access log masks it (docs/adr/0052).
        "--logger-class=housecairn.core.gunicorn_logging.Logger",
        # Proxy headers count from the reverse proxies of
        # HOUSECAIRN_FORWARDED_ALLOW_IPS only, in gunicorn as in Django
        # (docs/adr/0012). Without HOUSECAIRN_BEHIND_TLS_PROXY, no peer may mark
        # a request as HTTPS.
        f"--forwarded-allow-ips={forwarded_allow_ips()}",
    ]


def env_bool(name: str) -> bool:
    """A boolean variable read as the settings read it (django-environ)."""
    from environ import Env

    return bool(Env().bool(name, default=False))


def forwarded_allow_ips() -> str:
    """gunicorn's `--forwarded-allow-ips`: who may set X-Forwarded-Proto."""
    if not env_bool("HOUSECAIRN_BEHIND_TLS_PROXY"):
        return ""
    raw = os.environ.get("HOUSECAIRN_FORWARDED_ALLOW_IPS", "")
    entries = [entry.strip() for entry in raw.split(",") if entry.strip()]
    return ",".join(entries or DEFAULT_FORWARDED_ALLOW_IPS)


def worker_command() -> list[str]:
    return django_command("qcluster")


def prepare_environment() -> Path:
    """Data directory, secret key and settings module, for any command."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", SETTINGS_MODULE)
    # Files written in the data directory (database, uploads, backups) are
    # readable by the application user only.
    os.umask(0o077)
    path = data_dir()
    prepare_data_dir(path)
    os.environ["SECRET_KEY"] = ensure_secret_key(path)
    return path


def exit_status(returncode: int) -> int:
    """Exit status of the container when a supervised process stopped by itself.

    Never 0, since the container stops although nobody asked; a process killed
    by a signal gives 128 + the signal number, as in a shell.
    """
    if returncode < 0:
        return 128 - returncode
    return returncode or 1


@dataclass
class Supervisor:
    """Run named commands side by side; stop all of them as soon as one stops."""

    commands: Sequence[tuple[str, Sequence[str]]]
    stop_timeout: float = DEFAULT_STOP_TIMEOUT
    poll_interval: float = 0.2
    processes: dict[str, subprocess.Popen[bytes]] = field(default_factory=dict)
    stop_requested: bool = False

    def request_stop(self, signum: int, _frame: FrameType | None) -> None:
        if not self.stop_requested:
            log(f"received {signal.Signals(signum).name}, stopping")
        self.stop_requested = True

    def reap_orphans(self) -> None:
        """Collect exited processes that are not ours (re-parented to PID 1).

        Only looks without collecting (WNOWAIT) first, so the exit code of our
        own processes stays for `Popen.poll`.
        """
        own = {proc.pid for proc in self.processes.values()}
        while True:
            try:
                info = os.waitid(os.P_ALL, 0, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            except ChildProcessError:
                return
            if info is None or info.si_pid in own:
                return
            os.waitpid(info.si_pid, 0)

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        for name, command in self.commands:
            self.processes[name] = subprocess.Popen(list(command))  # noqa: S603
        exit_code = 0
        while not self.stop_requested:
            finished = [(n, p) for n, p in self.processes.items() if p.poll() is not None]
            if finished:
                name, proc = finished[0]
                log(f"{name} exited with code {proc.returncode}, stopping the others")
                exit_code = exit_status(proc.returncode)
                break
            self.reap_orphans()
            time.sleep(self.poll_interval)
        self.stop_all()
        return exit_code

    def stop_all(self) -> None:
        running = [(n, p) for n, p in self.processes.items() if p.poll() is None]
        for _name, proc in running:
            proc.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + self.stop_timeout
        for name, proc in running:
            try:
                proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                log(f"{name} did not stop within {self.stop_timeout:g} s, killing it")
                proc.kill()
                proc.wait()


def migrate() -> None:
    log("applying database migrations")
    result = subprocess.run(django_command("migrate", "--noinput"), check=False)  # noqa: S603
    if result.returncode != 0:
        raise SystemExit(f"housecairn: migrations failed (exit code {result.returncode}).")
    # The table of a database cache (HOUSECAIRN_CACHE_URL=dbcache://...); a no-op for any
    # other cache (docs/adr/0025).
    result = subprocess.run(django_command("createcachetable"), check=False)  # noqa: S603
    if result.returncode != 0:
        raise SystemExit(f"housecairn: cache table failed (exit code {result.returncode}).")


def write_setup_code() -> None:
    """Write the one-time code of the first-account screen in the log, if one is needed.

    Without an administrator only; a failure never stops the start (docs/adr/0055).
    """
    result = subprocess.run(django_command("setup_code"), check=False)  # noqa: S603
    if result.returncode != 0:
        log(f"could not issue the first-account code (exit code {result.returncode})")


def command_run() -> int:
    prepare_environment()
    migrate()
    write_setup_code()
    stop_timeout = float(env_int("HOUSECAIRN_STOP_TIMEOUT", int(DEFAULT_STOP_TIMEOUT)))
    supervisor = Supervisor(
        [("web server", web_command()), ("task worker", worker_command())],
        stop_timeout=stop_timeout,
    )
    log("starting the web server and the task worker")
    return supervisor.run()


def health_host(allowed_hosts: str) -> str:
    """A host name the instance accepts, for the Host header of the probe."""
    for entry in (h.strip() for h in allowed_hosts.split(",")):
        if not entry or entry == "*":
            continue
        return entry.lstrip(".")
    return "localhost"


def command_healthcheck(timeout: float = 4.0) -> int:
    port = env_int("HOUSECAIRN_PORT", DEFAULT_PORT)
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/healthz",
        headers={"Host": health_host(os.environ.get("ALLOWED_HOSTS", ""))},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log(f"unhealthy: {exc}")
        return 1
    if body != {"status": "ok"}:
        log(f"unhealthy: {body}")
        return 1
    return 0


def sqlite_path() -> Path | None:
    """The SQLite database file, or None if DATABASE_URL points elsewhere."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return data_dir() / "db.sqlite3"
    if url.startswith("sqlite:////"):
        return Path(url.removeprefix("sqlite:///"))
    return None


def command_backup() -> int:
    """Copy the SQLite database with SQLite's online backup API."""
    source = sqlite_path()
    if source is None:
        log(
            "DATABASE_URL is not SQLite; back up that database with its own tools "
            "(for PostgreSQL, pg_dump)."
        )
        return 2
    if not source.is_file():
        log(f"no database at {source}.")
        return 1
    target_dir = data_dir() / "backups"
    target_dir.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"db-{stamp}.sqlite3"
    # Created empty and readable by the application user only before SQLite
    # writes to it, whatever the umask: no moment where another user could
    # open it. SQLite gives its journal file the same mode.
    try:
        os.close(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        log(f"{target} already exists; wait a second and run the backup again.")
        return 1
    with (
        closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(target)) as dst,
    ):
        src.backup(dst)
    sys.stdout.write(f"{target}\n")
    return 0


def command_manage(args: Sequence[str]) -> NoReturn:
    prepare_environment()
    command = django_command(*args)
    os.execv(command[0], command)  # noqa: S606 - replaces this process, no shell


USAGE = "usage: python -m housecairn.entrypoint [run | healthcheck | backup | manage <command>]"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args.pop(0) if args else "run"
    if command == "run" and not args:
        return command_run()
    if command == "healthcheck" and not args:
        return command_healthcheck()
    if command == "backup" and not args:
        return command_backup()
    if command == "manage" and args:
        return command_manage(args)
    sys.stderr.write(USAGE + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
