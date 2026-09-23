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
