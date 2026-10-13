"""grunt serve starts the TaskIQ worker only when the site uses a Redis broker."""

from grunt_cli.commands.serve import _redis_configured


def test_redis_from_environment():
    assert _redis_configured({"REDIS_URL": "redis://localhost:6379/0"})


def test_redis_from_site_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEBUG=true\nREDIS_URL=redis://localhost:6379/0\n")
    assert _redis_configured({"DOTENV_PATH": str(env_file)})


def test_no_redis(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEBUG=true\nREDIS_URL=\n")
    assert not _redis_configured({"DOTENV_PATH": str(env_file)})
    assert not _redis_configured({})


def test_stopped_old_supervisor_is_taken_over(tmp_path):
    """A `grunt serve` left stopped by Ctrl+Z ignores SIGTERM - the next one
    must resume and end it, not just kill its children."""
    import signal
    import subprocess
    import sys
    import time

    from grunt_cli.commands.serve import _find_old_supervisors, _stop_old_supervisors

    bench = tmp_path / "bench"
    (bench / "sites" / "a").mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    fake = tmp_path / "bin" / "grunt"
    fake.parent.mkdir()
    fake.write_text("import time\ntime.sleep(60)\n")
    old = subprocess.Popen([sys.executable, str(fake), "serve"], cwd=bench / "sites" / "a")
    foreign = subprocess.Popen([sys.executable, str(fake), "serve"], cwd=other)
    try:
        time.sleep(0.3)
        old.send_signal(signal.SIGSTOP)
        assert _find_old_supervisors(bench) == [old.pid]

        _stop_old_supervisors(bench)
        assert old.wait(timeout=5) == -signal.SIGTERM
        assert foreign.poll() is None  # інший bench не чіпаємо
    finally:
        for p in (old, foreign):
            p.kill()
            p.wait()
