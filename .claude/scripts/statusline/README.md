# Claude Code status line

Shows the current directory, Git branch, context usage, model, and session cost. Effort appears when supplied in the payload or configured through the environment. Missing or invalid values are omitted.

Full display (default):

```text
user@host:repo (main ↑2 ↓1) | Context:261k [██░░░░░░░░ 26%/1M] | Opus | session $25.39 | effort high
```

Compact display:

```text
repo (main ↑2 ↓1) | Context 26% · 261k/1M | Opus | $25.39 | effort high
```

## Setup

Requires Bash 3.2 or newer, `jq` 1.6 or newer, and optionally Git. macOS's bundled Bash is supported. Install `jq` if it is not already available, for example with `brew install jq` on macOS.

From this directory:

```sh
mkdir -p ~/.claude
cp statusline.sh ~/.claude/statusline.sh
chmod +x ~/.claude/statusline.sh
```

Merge the `statusLine` entry from `settings.json` into `~/.claude/settings.json`. Keep your existing settings. The example file's spelling is intentional here to match its existing filename.

To enable compact mode and a dirty-worktree marker, use this command in the `statusLine` entry:

```json
{
  "statusLine": {
    "type": "command",
    "command": "STATUSLINE_COMPACT=1 STATUSLINE_GIT_DIRTY=1 ~/.claude/statusline.sh"
  }
}
```

## Configuration

Set these environment variables in the status-line command or in the environment that launches Claude Code. Boolean options are enabled only by `1`.

| Variable | Default | Behavior |
| --- | --- | --- |
| `STATUSLINE_COMPACT` | `0` | Removes the bar and session label, hides user/host by default, and shortens directory, branch, model, and style labels to 24 characters. |
| `STATUSLINE_SHOW_IDENTITY` | `1` full, `0` compact | Shows `user@host:`. Set to `0` for screenshots. Directory and branch names remain visible. |
| `STATUSLINE_WARN_PCT` | `70` | Context becomes amber at this percentage. |
| `STATUSLINE_CRITICAL_PCT` | `90` | Context becomes red at this percentage. |
| `STATUSLINE_COMPACT_AT` | unset | Adds a reminder such as `compact@400k (configured)`. Accepts a positive integer token count of up to 15 digits. **Does not configure or detect Claude Code's compaction threshold.** |
| `STATUSLINE_GIT_DIRTY` | `0` | Adds `*` for tracked changes or untracked files. This scans the worktree and can slow down large repositories. |
| `STATUSLINE_SHOW_STYLE` | `0` | Shows a non-default output style as a separate segment, independent of effort. |
| `NO_COLOR` | unset | Any nonempty value disables ANSI colors. |
| `CLAUDE_CODE_EFFORT_LEVEL` | unset | Used as a display fallback when payload effort is absent. Accepted values: `low`, `medium`, `high`, `xhigh`, `max`. Shown as `effort high (configured)`, not as detected runtime state. |

Warning thresholds must be integers satisfying `0 <= warn < critical <= 100`. Invalid threshold configurations reset both values to their defaults.

## What the numbers mean

- **Context tokens** are the sum of `context_window.current_usage.input_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens`. They describe current usage, not cumulative session input. All three fields must be nonnegative integers; the context limit must be a positive integer. Missing current usage hides the context segment.
- **Percentage** uses numeric `context_window.used_percentage` when available, otherwise the current token sum divided by `context_window_size`. It is floored and clamped to 0–100 for display. Claude Code's supplied percentage may differ slightly from the displayed token ratio.
- **Token labels** show exact values below 1,000, whole thousands above that, and `M` for exact multiples of one million. Labels truncate rather than round upward.
- **Cost** is `cost.total_cost_usd`, formatted to two decimals using a fixed decimal point. Only nonnegative numeric values are accepted.
- **Git counts** compare HEAD with the locally recorded upstream. They do not fetch. Detached HEAD shows a short commit hash. A branch without an upstream simply has no ahead/behind counts. Git reads avoid optional locks.

Numeric token values and their sum are restricted to JSON's safe-integer range. Invalid segments are omitted rather than interpreted as zero.

### Effort compatibility

The script accepts `.effort.level` if a producer supplies it. This field has **not been verified against the current Claude Code payload schema**; do not assume your version sends it. When neither payload effort nor the environment fallback is present, the segment is omitted. Output style is never treated as reasoning effort.

The environment fallback only reports the configured value. It does not read settings files or account for interactive effort overrides, model support, or runtime changes. Its accepted labels do not imply every Claude Code version or model supports them.

## Failure handling and privacy

The JSON is parsed once. Missing `jq` or malformed input falls back to the current directory, optional identity, and any available Git information, without parser errors on stderr. Invalid fields do not suppress unrelated valid segments.

Display strings are stripped of terminal escape sequences, control characters, and Unicode line separators. Paths used for Git queries are kept separate from display labels. Compact mode is shorter, not terminal-width-aware; it does not guarantee that every combination of segments fits a narrow terminal. UTF-8 labels should be used with a UTF-8 locale.

The script makes no network requests and writes no cache files. Check directory and branch names before sharing screenshots, even with identity hidden.
