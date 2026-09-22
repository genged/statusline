#!/bin/bash
# Claude Code status line. Bash 3.2+, jq. Configuration: see README.md.
# Payload strings are data, never shell code. Git queries avoid optional locks.

export LC_NUMERIC=C
input=$(cat)

GREEN=$'\033[32m'
BLUE=$'\033[34m'
ORANGE=$'\033[38;5;208m'
RED=$'\033[31m'
DIM=$'\033[2m'
RESET=$'\033[0m'
if [ -n "${NO_COLOR:-}" ]; then
  GREEN='' BLUE='' ORANGE='' RED='' DIM='' RESET=''
fi

# Remove terminal escape sequences before removing remaining control bytes.
sanitize() {
  local text="$1" csi osc control code
  csi='('$'\033''\[|'$'\302\233'')[0-?]*[ -/]*[@-~]'
  osc='('$'\033'']|'$'\302\235'')'"[^"$'\007\033'"]*"'('$'\007''|'$'\033''\\|'$'\302\234'')'
  while [[ "$text" =~ $osc ]]; do text=${text/"${BASH_REMATCH[0]}"/}; done
  while [[ "$text" =~ $csi ]]; do text=${text/"${BASH_REMATCH[0]}"/}; done
  # Explicit UTF-8 sequences also work when the caller uses the C locale.
  for ((code = 128; code <= 159; code++)); do
    printf -v control '\\302\\%03o' "$code"
    printf -v control '%b' "$control"
    text=${text//"$control"/}
  done
  text=${text//$'\342\200\250'/}
  text=${text//$'\342\200\251'/}
  text=${text//[[:cntrl:]]/}
  printf '%s' "$text"
}

compact=0
[ "${STATUSLINE_COMPACT:-0}" = 1 ] && compact=1
show_identity=${STATUSLINE_SHOW_IDENTITY:-$((1 - compact))}
warn=70 critical=90
if [[ "${STATUSLINE_WARN_PCT:-70}" =~ ^[0-9]{1,3}$ ]] &&
   [[ "${STATUSLINE_CRITICAL_PCT:-90}" =~ ^[0-9]{1,3}$ ]]; then
  candidate_warn=$((10#${STATUSLINE_WARN_PCT:-70}))
  candidate_critical=$((10#${STATUSLINE_CRITICAL_PCT:-90}))
  if [ "$candidate_warn" -lt "$candidate_critical" ] && [ "$candidate_critical" -le 100 ]; then
    warn=$candidate_warn critical=$candidate_critical
  fi
fi

# One jq invocation, with NUL-delimited fields to preserve paths with whitespace.
# Construct the entire record before emitting it, so bad input cannot leak a
# partially parsed record. No eval, and no arithmetic on unvalidated JSON.
fields=()
if command -v jq >/dev/null 2>&1; then
  while IFS= read -r -d '' field; do fields+=("$field"); done < <(
    printf '%s' "$input" | jq -j -s '
      def at($path): try getpath($path) catch null;
      def text: if type == "string" then gsub("\u0000"; "") else "" end;
      def finite: if type == "number" then fabs < 1.7976931348623157e308 else false end;
      def uint: if finite then . >= 0 and . <= 9007199254740991 and floor == . else false end;
      if length == 1 and (.[0] | type) == "object" then .[0] else error("invalid payload") end
      | (at(["workspace", "current_dir"]) | text) as $workspace
      | (at(["cwd"]) | text) as $cwd
      | at(["context_window", "context_window_size"]) as $size
      | at(["context_window", "current_usage"]) as $usage
      | [$usage | at(["input_tokens"]), at(["cache_creation_input_tokens"]), at(["cache_read_input_tokens"])] as $tokens
      | at(["context_window", "used_percentage"]) as $percentage
      | (if ($size | uint) and $size > 0 and ($tokens | all(.[]; uint)) and ($tokens | add | uint)
         then ($tokens | add) as $used
         | {used: $used, size: $size,
            pct: ((if ($percentage | finite) then $percentage else $used / $size * 100 end) | [0, ., 100] | sort | .[1] | floor)}
         else {} end) as $context
      | at(["cost", "total_cost_usd"]) as $cost
      | [
          (if $workspace != "" then $workspace else $cwd end),
          ($context.used // ""), ($context.size // ""), ($context.pct // ""),
          (at(["model", "display_name"]) | text),
          (if ($cost | finite) and $cost >= 0 then $cost else "" end),
          (at(["effort", "level"]) | text),
          (at(["output_style", "name"]) | text)
        ] | .[] | tostring + "\u0000"
    ' 2>/dev/null
  )
fi
cwd=${fields[0]:-"$PWD"}
used_tokens=${fields[1]:-}
ctx_size=${fields[2]:-}
pct=${fields[3]:-}
model=$(sanitize "${fields[4]:-}")
cost=${fields[5]:-}
effort=$(sanitize "${fields[6]:-}")
style=$(sanitize "${fields[7]:-}")

# Compact mode limits long labels, without changing the directory Git queries.
label() {
  local value
  value=$(sanitize "$1")
  if [ "$compact" = 1 ] && [ "${#value}" -gt 24 ]; then value="${value:0:23}…"; fi
  printf '%s' "$value"
}
dir=$(label "$(basename -- "$cwd")")
identity="${BLUE}${dir}${RESET}"
if [ "$show_identity" = 1 ]; then
  user=$(sanitize "$(whoami 2>/dev/null)")
  host=$(sanitize "$(hostname -s 2>/dev/null || hostname 2>/dev/null)")
  identity="${GREEN}${user}@${host}${RESET}${DIM}:${RESET}${identity}"
fi

git_query() { git --no-pager --no-optional-locks -C "$cwd" "$@" 2>/dev/null; }
branch=$(git_query symbolic-ref --quiet --short HEAD)
if [ -z "$branch" ]; then branch=$(git_query rev-parse --short HEAD); fi
if [ -n "$branch" ]; then
  git_details=$(label "$branch")
  counts=$(git_query rev-list --left-right --count 'HEAD...@{upstream}')
  read -r ahead behind <<< "$counts"
  if [[ "$ahead" =~ ^[0-9]+$ ]] && [ "$ahead" -gt 0 ] 2>/dev/null; then git_details="${git_details} ↑${ahead}"; fi
  if [[ "$behind" =~ ^[0-9]+$ ]] && [ "$behind" -gt 0 ] 2>/dev/null; then git_details="${git_details} ↓${behind}"; fi
  if [ "${STATUSLINE_GIT_DIRTY:-0}" = 1 ] && [ -n "$(git_query status --porcelain --untracked-files=normal)" ]; then
    git_details="${git_details} *"
  fi
  identity="${identity} ${DIM}(${git_details})${RESET}"
fi

# Compact token labels keep 1M windows readable without rounding usage upward.
format_tokens() {
  if [ "$1" -ge 1000000 ]; then
    if [ "$(( $1 % 1000000 ))" -eq 0 ]; then printf '%sM' "$(( $1 / 1000000 ))";
    else printf '%sk' "$(( $1 / 1000 ))"; fi
  elif [ "$1" -ge 1000 ]; then printf '%sk' "$(( $1 / 1000 ))";
  else printf '%s' "$1"; fi
}
segments=("$identity")
if [ -n "$used_tokens" ] && [ -n "$ctx_size" ] && [ -n "$pct" ]; then
  used=$(format_tokens "$used_tokens")
  limit=$(format_tokens "$ctx_size")
  color=$GREEN
  [ "$pct" -ge "$warn" ] && color=$ORANGE
  [ "$pct" -ge "$critical" ] && color=$RED
  if [ "$compact" = 1 ]; then
    context="Context ${pct}% · ${used}/${limit}"
  else
    bar=''
    filled=$((pct / 10))
    for ((i = 0; i < 10; i++)); do
      if [ "$i" -lt "$filled" ]; then bar="${bar}█"; else bar="${bar}░"; fi
    done
    context="Context:${used} [${bar} ${pct}%/${limit}]"
  fi
  # This is a display-only reminder, not Claude Code compaction configuration.
  if [[ "${STATUSLINE_COMPACT_AT:-}" =~ ^[0-9]{1,15}$ ]]; then
    compact_at=$((10#$STATUSLINE_COMPACT_AT))
    if [ "$compact_at" -gt 0 ]; then
      context="${context} compact@$(format_tokens "$compact_at") (configured)"
    fi
  fi
  segments+=("${color}${context}${RESET}")
fi
[ -n "$model" ] && segments+=("${ORANGE}$(label "$model")${RESET}")
if [ -n "$cost" ] && cost_fmt=$(export LC_ALL=C; printf '%.2f' "$cost" 2>/dev/null); then
  if [ "$compact" = 1 ]; then segments+=("${BLUE}\$${cost_fmt}${RESET}");
  else segments+=("${DIM}session${RESET} ${BLUE}\$${cost_fmt}${RESET}"); fi
fi
if [ -z "$effort" ]; then
  case "${CLAUDE_CODE_EFFORT_LEVEL:-}" in
    low|medium|high|xhigh|max) effort="${CLAUDE_CODE_EFFORT_LEVEL} (configured)" ;;
  esac
fi
[ -n "$effort" ] && segments+=("${DIM}effort${RESET} ${BLUE}${effort}${RESET}")
if [ "${STATUSLINE_SHOW_STYLE:-0}" = 1 ] && [ -n "$style" ] && [ "$style" != default ]; then
  segments+=("${DIM}style${RESET} ${BLUE}$(label "$style")${RESET}")
fi
line=''
for segment in "${segments[@]}"; do
  [ -n "$line" ] && line="${line} ${DIM}|${RESET} "
  line="${line}${segment}"
done
printf '%s\n' "$line"
