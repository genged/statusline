"""Contract tests. Run with: python3 -B -m unittest discover -s <this directory> -v.

Only the statusline subprocess runs Bash. Git is always replaced by a mock;
these tests never initialize a repository or write Git metadata.
"""


import json
import locale
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("statusline.sh")
BASH = "/bin/bash"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
GIT_MOCK = r'''#!/bin/sh
printf '%s\n' "$*" >> "$MOCK_GIT_LOG"
[ "$MOCK_GIT_MODE" = none ] && exit 1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-pager|--no-optional-locks) shift ;;
    -C) [ "$#" -ge 2 ] || exit 1; shift 2 ;;
    *) break ;;
  esac
done
case "$*" in
  'symbolic-ref --quiet --short HEAD')
    [ "$MOCK_GIT_MODE" = detached ] && exit 1
    printf 'feature/test\n' ;;
  'rev-parse --short HEAD') printf 'abc1234\n' ;;
  'rev-parse --is-inside-work-tree') printf 'true\n' ;;
  'rev-list --left-right --count HEAD...@{upstream}') printf '%s\t%s\n' "$MOCK_GIT_AHEAD" "$MOCK_GIT_BEHIND" ;;
  'status --porcelain --untracked-files=normal')
    [ "$MOCK_GIT_DIRTY" = 1 ] && printf ' M tracked.py\n?? untracked.py\n'
    exit 0 ;;
  *) exit 1 ;;
esac
'''


def payload():
    return {
        "workspace": {"current_dir": "/synthetic/project"},
        "model": {"display_name": "Test Model"},
        "cost": {"total_cost_usd": 1.25},
        "context_window": {
            "total_input_tokens": 987654,
            "context_window_size": 200000,
            "used_percentage": 25,
            "current_usage": {
                "input_tokens": 10000,
                "cache_creation_input_tokens": 15000,
                "cache_read_input_tokens": 25000,
            },
        },
    }


class StatuslineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="statusline-tests-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "git.log"
        git = self.bin / "git"
        git.write_text(GIT_MOCK)
        git.chmod(0o755)
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("STATUSLINE_", "MOCK_GIT_", "GIT_"))
            and key not in ("NO_COLOR", "CLAUDE_CODE_EFFORT_LEVEL", "BASH_ENV", "ENV", "CDPATH")
        }
        self.env.update({
            "PATH": str(self.bin) + os.pathsep + os.defpath,
            "NO_COLOR": "1",
            "LC_ALL": "C",
            "MOCK_GIT_LOG": str(self.log),
            "MOCK_GIT_MODE": "none",
            "MOCK_GIT_AHEAD": "0",
            "MOCK_GIT_BEHIND": "0",
            "MOCK_GIT_DIRTY": "0",
        })
        # jq is commonly installed outside os.defpath on macOS.
        jq = shutil.which("jq")
        if jq:
            (self.bin / "jq").symlink_to(jq)
        self.has_jq = jq is not None

    def run_line(self, data=None, *, raw=None, env=None, needs_jq=True):
        if needs_jq and not self.has_jq:
            self.skipTest("jq is not installed")
        process_env = self.env.copy()
        for key, value in (env or {}).items():
            if value is None:
                process_env.pop(key, None)
            else:
                process_env[key] = str(value)
        result = subprocess.run(
            [BASH, str(SCRIPT)],
            input=raw if raw is not None else json.dumps(payload() if data is None else data),
            text=True, capture_output=True, env=process_env, cwd=self.root, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        line = result.stdout.removesuffix("\n")
        self.assertTrue(line, "expected at least the directory")
        self.assertNotRegex(line, r"[\r\n]", "status must fit on one line")
        if process_env.get("NO_COLOR"):
            self.assertNotIn("\x1b", line)
        return line

    def assert_identity_only(self, line):
        self.assertRegex(line, r"[^\s|]+@[^\s|]+:")
        self.assertNotRegex(line, r"Context|session|effort|style|Test Model|[|]")

    def test_full_defaults(self):
        line = self.run_line()
        self.assertRegex(line, r"^[^\s|]+@[^\s|]+:project")
        self.assertRegex(line, r"Context:50k \[[█░]+ 25%/200k\]")
        self.assertIn("Test Model", line)
        self.assertIn("session $1.25", line)
        self.assertNotIn("effort", line)
        colored = self.run_line(env={"NO_COLOR": None})
        self.assertIn("\x1b[", colored)
        self.assertEqual(ANSI.sub("", colored), line)

    def test_missing_and_malformed_payload(self):
        for raw in ("", "{broken", "null", "[]", "42", '"text"', "{}"):
            with self.subTest(raw=raw):
                self.assert_identity_only(self.run_line(raw=raw))

    def test_missing_jq(self):
        isolated = self.root / "without-jq"
        isolated.mkdir()
        (isolated / "git").symlink_to(self.bin / "git")
        for command in ("cat", "whoami", "hostname", "basename", "dirname", "tr", "sed",
                        "awk", "cut", "printf", "wc", "uname", "head", "tail", "id",
                        "pwd", "env", "grep", "sort", "readlink", "date", "tput"):
            executable = shutil.which(command, path=os.defpath)
            if executable:
                (isolated / command).symlink_to(executable)
        line = self.run_line(env={"PATH": str(isolated)}, needs_jq=False)
        self.assert_identity_only(line)

    def test_current_usage_not_cumulative_and_compaction_drop(self):
        data = payload()
        data["context_window"].pop("used_percentage")
        self.assertIn("25%/200k", self.run_line(data))
        data["context_window"]["current_usage"] = dict.fromkeys(
            data["context_window"]["current_usage"], 2000)
        data["context_window"]["total_input_tokens"] += 100000
        line = self.run_line(data)
        self.assertIn("Context:6k", line)
        self.assertIn("3%/200k", line)

    def test_missing_current_usage_omits_context(self):
        for value in (None, {}, [], "50000"):
            data = payload()
            data["context_window"]["current_usage"] = value
            with self.subTest(value=value):
                self.assertNotIn("Context", self.run_line(data))
        data["context_window"].pop("current_usage")
        self.assertNotIn("Context", self.run_line(data))

    def test_all_current_token_fields_must_be_nonnegative_integers(self):
        for field in payload()["context_window"]["current_usage"]:
            for value in (-1, 0.5, "10000", True, None, [], {}):
                data = payload()
                data["context_window"]["current_usage"][field] = value
                with self.subTest(field=field, value=value):
                    self.assertNotIn("Context", self.run_line(data))
            data = payload()
            del data["context_window"]["current_usage"][field]
            with self.subTest(missing=field):
                self.assertNotIn("Context", self.run_line(data))
        data = payload()
        data["context_window"]["current_usage"] = dict.fromkeys(
            data["context_window"]["current_usage"], 0)
        data["context_window"].pop("used_percentage")
        self.assertIn("Context:0 ", self.run_line(data))
        data["context_window"]["current_usage"]["input_tokens"] = 999
        self.assertIn("Context:999 ", self.run_line(data))

    def test_unsafe_and_exponent_token_values(self):
        for field in payload()["context_window"]["current_usage"]:
            for literal in ("1e100", "1e309", "1e-1", "9007199254740992", "9223372036854775808"):
                data = payload()
                data["context_window"]["current_usage"][field] = "TOKEN_LITERAL"
                raw = json.dumps(data).replace('"TOKEN_LITERAL"', literal)
                with self.subTest(field=field, literal=literal):
                    self.assertNotIn("Context", self.run_line(raw=raw))
        data = payload()
        data["context_window"]["current_usage"] = {
            "input_tokens": 9007199254740991,
            "cache_creation_input_tokens": 1,
            "cache_read_input_tokens": 0,
        }
        self.assertNotIn("Context", self.run_line(data))

    def test_percentage_clamped_and_floored(self):
        for percentage, expected in ((-12, 0), (0, 0), (25.99, 25), (99.99, 99), (120, 100)):
            data = payload()
            data["context_window"]["used_percentage"] = percentage
            with self.subTest(percentage=percentage):
                self.assertIn(f" {expected}%/200k", self.run_line(data))

    def test_invalid_percentage_falls_back_to_current_tokens(self):
        for value in (None, "80", True, [], {}, "NaN", "Infinity", float("inf"), float("-inf")):
            data = payload()
            data["context_window"]["used_percentage"] = value
            with self.subTest(value=value):
                self.assertIn(" 25%/200k", self.run_line(data))

    def test_invalid_context_size_cannot_compute_percentage(self):
        for size in (None, 0, -200000, 200000.5, "200000", True, [], {}):
            data = payload()
            data["context_window"].pop("used_percentage")
            data["context_window"]["context_window_size"] = size
            with self.subTest(size=size):
                self.assertNotIn("Context", self.run_line(data))

    def test_cost_validation_and_format(self):
        for value, expected in ((0, "0.00"), (1.256, "1.26"), (12, "12.00")):
            data = payload()
            data["cost"]["total_cost_usd"] = value
            with self.subTest(value=value):
                self.assertIn(f"session ${expected}", self.run_line(data))
        for value in (None, -0.01, "1.25", True, [], {}, "NaN", float("inf")):
            data = payload()
            data["cost"]["total_cost_usd"] = value
            with self.subTest(value=value):
                self.assertNotIn("session", self.run_line(data))
        data.pop("cost")
        self.assertNotIn("session", self.run_line(data))

    def test_cost_with_non_c_numeric_locale(self):
        previous = locale.setlocale(locale.LC_NUMERIC)
        try:
            try:
                locale.setlocale(locale.LC_NUMERIC, "de_DE.UTF-8")
            except locale.Error:
                self.skipTest("de_DE.UTF-8 locale is not available")
        finally:
            locale.setlocale(locale.LC_NUMERIC, previous)
        self.assertIn("session $1.25", self.run_line(env={"LC_ALL": "de_DE.UTF-8"}))

    def test_compact_and_identity_overrides(self):
        line = self.run_line(env={"STATUSLINE_COMPACT": "1"})
        self.assertTrue(line.startswith("project"), line)
        self.assertNotRegex(line, r"@|[█░]")
        self.assertIn("Context 25% · 50k/200k", line)
        self.assertRegex(self.run_line(env={"STATUSLINE_COMPACT": "1", "STATUSLINE_SHOW_IDENTITY": "1"}),
                         r"^[^\s|]+@[^\s|]+:project")
        line = self.run_line(env={"STATUSLINE_SHOW_IDENTITY": "0"})
        self.assertTrue(line.startswith("project"), line)
        self.assertNotIn("@", line)
        self.assertIn("Context:50k", line)

    def test_style_is_opt_in_and_independent_of_effort(self):
        data = payload()
        data["output_style"] = {"name": "concise"}
        self.assertNotIn("style", self.run_line(data))
        self.assertIn("style concise", self.run_line(data, env={"STATUSLINE_SHOW_STYLE": "1"}))
        data["effort"] = {"level": "high"}
        line = self.run_line(data, env={"STATUSLINE_SHOW_STYLE": "1"})
        self.assertIn("style concise", line)
        self.assertIn("effort high", line)
        data["output_style"]["name"] = "default"
        self.assertNotIn("style", self.run_line(data, env={"STATUSLINE_SHOW_STYLE": "1"}))

    def test_effort_payload_and_configured_fallback(self):
        data = payload()
        data["effort"] = {"level": "custom"}
        line = self.run_line(data, env={"CLAUDE_CODE_EFFORT_LEVEL": "low"})
        self.assertIn("effort custom", line)
        self.assertNotIn("configured", line)
        for level in ("low", "medium", "high", "xhigh", "max"):
            with self.subTest(level=level):
                self.assertIn(f"effort {level} (configured)",
                              self.run_line(env={"CLAUDE_CODE_EFFORT_LEVEL": level}))
        for invalid in (None, "", 1, True, [], {}):
            data["effort"]["level"] = invalid
            with self.subTest(payload=invalid):
                self.assertIn("effort high (configured)",
                              self.run_line(data, env={"CLAUDE_CODE_EFFORT_LEVEL": "high"}))
                self.assertNotIn("effort", self.run_line(data))
        for invalid in ("", "turbo", "HIGH", " high "):
            with self.subTest(config=invalid):
                self.assertNotIn("effort", self.run_line(env={"CLAUDE_CODE_EFFORT_LEVEL": invalid}))

    def test_compaction_configuration(self):
        for compact in ("0", "1"):
            line = self.run_line(env={"STATUSLINE_COMPACT_AT": "400000", "STATUSLINE_COMPACT": compact})
            self.assertIn("compact@400k (configured)", line)
        for invalid in ("", "0", "-1", "1.5", "abc"):
            with self.subTest(value=invalid):
                self.assertNotIn("compact@", self.run_line(env={"STATUSLINE_COMPACT_AT": invalid}))
        data = payload()
        data.pop("context_window")
        self.assertNotIn("compact@", self.run_line(data, env={"STATUSLINE_COMPACT_AT": "400000"}))

    def test_configuration_is_data_not_shell_code(self):
        marker = self.root / "injection-marker"
        for key in ("STATUSLINE_WARN_PCT", "STATUSLINE_CRITICAL_PCT", "STATUSLINE_COMPACT_AT",
                    "STATUSLINE_COMPACT", "STATUSLINE_SHOW_IDENTITY", "STATUSLINE_GIT_DIRTY",
                    "STATUSLINE_SHOW_STYLE", "CLAUDE_CODE_EFFORT_LEVEL"):
            for hostile in ("$(touch injection-marker)", "a[$(touch injection-marker)]"):
                with self.subTest(key=key, value=hostile):
                    try:
                        line = self.run_line(env={key: hostile})
                        self.assertIn("Context:50k", line)
                        self.assertNotIn("compact@", line)
                        self.assertNotIn("effort", line)
                        self.assertNotIn(hostile, line)
                    finally:
                        self.assertFalse(marker.exists(), "configuration executed a shell command")

    def context_colors(self, percentage, env=None):
        data = payload()
        data["context_window"]["used_percentage"] = percentage
        line = self.run_line(data, env={"NO_COLOR": None, **(env or {})})
        segments = [part for part in line.split("|") if "Context:" in part]
        self.assertEqual(len(segments), 1, "expected one full context segment: " + repr(line))
        return set(ANSI.findall(segments[0]))

    def test_default_and_custom_threshold_colors(self):
        normal = self.context_colors(69)
        warning = self.context_colors(70)
        critical = self.context_colors(90)
        self.assertNotEqual(normal, warning)
        self.assertEqual(warning, self.context_colors(89))
        self.assertNotEqual(warning, critical)
        custom = {"STATUSLINE_WARN_PCT": "30", "STATUSLINE_CRITICAL_PCT": "60"}
        self.assertEqual(normal, self.context_colors(29, custom))
        self.assertEqual(warning, self.context_colors(30, custom))
        self.assertEqual(critical, self.context_colors(60, custom))

    def test_invalid_thresholds_fall_back(self):
        for value in ("", "abc", "-1", "101", "70.5"):
            for key in ("STATUSLINE_WARN_PCT", "STATUSLINE_CRITICAL_PCT"):
                for percentage in (69, 70, 89, 90):
                    with self.subTest(key=key, value=value, percentage=percentage):
                        self.assertEqual(self.context_colors(percentage),
                                         self.context_colors(percentage, {key: value}))

    def test_control_character_sanitization(self):
        data = payload()
        hostile = "safe\x1b[31mRED\x1b[0m\n\r\t\x00\x07\x7fend"
        data["workspace"]["current_dir"] = "/synthetic/" + hostile
        data["model"]["display_name"] = hostile
        data["output_style"] = {"name": hostile}
        data["effort"] = {"level": hostile}
        for no_color in ("1", None):
            with self.subTest(no_color=no_color):
                line = self.run_line(data, env={"NO_COLOR": no_color, "STATUSLINE_SHOW_STYLE": "1"})
                self.assertNotRegex(ANSI.sub("", line), r"[\x00-\x1f\x7f]")
                self.assertNotIn("\x1b[31m", line, "payload ANSI must not reach the terminal")
                self.assertIn("safe", line)

    def test_unicode_control_character_sanitization(self):
        controls = "".join(chr(code) for code in range(0x80, 0xA0)) + "\u2028\u2029"
        for path in (("workspace", "current_dir"), ("model", "display_name"),
                     ("output_style", "name"), ("effort", "level")):
            for no_color in ("1", None):
                with self.subTest(field=path, no_color=no_color):
                    data = payload()
                    hostile = "safe" + controls + "end"
                    if path[0] == "workspace":
                        hostile = "/synthetic/" + hostile
                    data.setdefault(path[0], {})[path[1]] = hostile
                    line = self.run_line(data, env={"NO_COLOR": no_color, "STATUSLINE_SHOW_STYLE": "1"})
                    self.assertNotRegex(ANSI.sub("", line), r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
                    self.assertIn("safe", line)

    def test_no_color_any_nonempty_value(self):
        for value in ("1", "0", "false"):
            with self.subTest(value=value):
                self.assertNotIn("\x1b", self.run_line(env={"NO_COLOR": value}))

    def test_git_branch_ahead_behind(self):
        line = self.run_line(env={"MOCK_GIT_MODE": "branch", "MOCK_GIT_AHEAD": "2", "MOCK_GIT_BEHIND": "3"})
        self.assertIn("feature/test", line)
        self.assertIn("↑2", line)
        self.assertIn("↓3", line)
        line = self.run_line(env={"MOCK_GIT_MODE": "branch"})
        self.assertNotRegex(line, r"[↑↓]0")

    def test_git_detached(self):
        line = self.run_line(env={"MOCK_GIT_MODE": "detached"})
        self.assertIn("abc1234", line)
        self.assertNotIn("feature/test", line)

    def test_git_dirty_is_opt_in(self):
        env = {"MOCK_GIT_MODE": "branch", "MOCK_GIT_DIRTY": "1"}
        self.assertNotIn("*", self.run_line(env=env))
        self.assertNotIn("status --porcelain", self.log.read_text())
        self.assertIn("*", self.run_line(env={**env, "STATUSLINE_GIT_DIRTY": "1"}))
        self.assertNotIn("*", self.run_line(env={**env, "MOCK_GIT_DIRTY": "0", "STATUSLINE_GIT_DIRTY": "1"}))


if __name__ == "__main__":
    unittest.main()
