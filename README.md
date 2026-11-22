# statusline

A status line for [Claude Code](https://claude.com/claude-code) that keeps session cost and context usage visible while you work.

```text
user@host:repo (main ↑2 ↓1) | Context:261k [██░░░░░░░░ 26%/1M] | Opus | session $25.39 | effort high
```

Cost tells you what the session is spending; context tells you how much history it is carrying — both worth glancing at before you start an unrelated task. See [local/linkedin-post.md](local/linkedin-post.md) for the background.

## Contents

- `.claude/scripts/statusline/statusline.sh` — the script (Bash 3.2+, `jq`, optional Git)
- `.claude/scripts/statusline/README.md` — setup, configuration options, and what each number means
- `.claude/scripts/statusline/test_statusline.py` — test suite
- `.claude/settings.json` — example `statusLine` wiring

## Quick start

Ask Claude Code:

```text
install this status line https://github.com/genged/statusline
```

Manual setup and full options — compact mode, color thresholds, a compaction reminder — are in the [script README](.claude/scripts/statusline/README.md).

## Tests

```sh
python3 -B -m unittest discover -s .claude/scripts/statusline -v
```
