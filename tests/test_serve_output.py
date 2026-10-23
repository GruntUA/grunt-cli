"""grunt serve reformats the dev processes' output: no banner repeats, no startup noise."""

from grunt_cli.commands.serve import _format_line


def test_noise_is_dropped():
    for line in (
        "",
        "   ",
        "> grunt-frontend@0.1.0 dev",
        "> vite",
        "INFO:     Will watch for changes in these directories: ['/a', '/b']",
        "INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)",
        "INFO:     Waiting for application startup.",
        "WARNING:root:Reload on change enabled. Number of worker processes set to 1.",
        "  \x1b[32m➜\x1b[39m  \x1b[1mLocal\x1b[22m:   \x1b[36mhttp://localhost:\x1b[1m5173\x1b[22m/\x1b[39m",
    ):
        assert _format_line(line) is None, line


def test_uvicorn_and_stdlib_levels_are_compacted():
    assert (
        _format_line("INFO:     Started server process [526]\n") == "Started server process [526]"
    )
    assert (
        _format_line("INFO:taskiq.process-manager:Started process worker-0 with pid 557 ")
        == "Started process worker-0 with pid 557"
    )
    assert _format_line("WARNING:  slow request") == "\x1b[33mWARNING\x1b[0m slow request"


def test_timestamps_are_replaced_by_ours():
    line = "\x1b[2m2026-10-07T07:25:03.158593Z\x1b[0m [info     ] grunt.startup"
    assert _format_line(line) == "[info     ] grunt.startup"
    assert _format_line("10:25:02 AM [vite] hmr update") == "[vite] hmr update"


def test_traceback_indentation_is_kept():
    line = "  grunt/grunt/middleware/rate_limit.py:203 in dispatch"
    assert _format_line(line) == line


def test_vite_banner_is_unindented():
    assert _format_line("  VITE v8.3.5  ready in 282 ms") == "VITE v8.3.5  ready in 282 ms"
