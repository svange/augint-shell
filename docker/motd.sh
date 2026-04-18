#!/bin/bash
# MOTD (Message of the Day) for augint-shell dev containers
# Displays environment status, tools, integrations, and network info at launch.
# Called from docker-entrypoint.sh; also runnable standalone.
set -o pipefail

# ─── Colors (amber/mauve palette matching tmux theme) ────────────────────────
AMBER='\e[38;5;172m'
AMBER_BOLD='\e[1;38;5;172m'
MAUVE='\e[38;5;95m'
GRAY='\e[38;5;248m'
DIM='\e[2m'
DIM_MAUVE='\e[2;38;5;95m'
DIM_ITALIC='\e[2;3m'
GREEN='\e[32m'
RED='\e[31m'
CYAN='\e[36m'
BOLD='\e[1m'
RESET='\e[0m'

# ─── Temp dir for parallel results ───────────────────────────────────────────
MOTD_TMP=$(mktemp -d /tmp/motd.XXXXXX)
trap 'rm -rf "$MOTD_TMP"' EXIT

# ─── Utilities ────────────────────────────────────────────────────────────────

mask_secret() {
    local val="$1"
    if [ -z "$val" ]; then
        echo ""
        return
    fi
    local len=${#val}
    if [ "$len" -le 8 ]; then
        echo "****${val: -4}"
    else
        # Show prefix (up to first dash or underscore boundary, max 8 chars) + **** + last 4
        local prefix="${val:0:8}"
        # Find a natural break point (dash, underscore) in the prefix
        if [[ "$prefix" =~ ^([a-zA-Z_-]+[-_]) ]]; then
            prefix="${BASH_REMATCH[1]}"
        else
            prefix="${val:0:4}"
        fi
        echo "${prefix}****${val: -4}"
    fi
}

get_version() {
    local name="$1" cmd="$2"
    local ver
    ver=$(timeout 3 bash -c "$cmd" 2>/dev/null | head -1 | grep -oP '[\d]+\.[\d]+[\d.]*' | head -1)
    if [ -n "$ver" ]; then
        echo "$ver" > "$MOTD_TMP/tool_${name}"
    fi
}

check_llm_service() {
    local name="$1" port="$2"
    if nc -z -w 1 host.docker.internal "$port" 2>/dev/null; then
        echo "UP" > "$MOTD_TMP/llm_${name}"
    elif nc -z -w 1 "augint-shell-${name}" "$port" 2>/dev/null; then
        echo "UP" > "$MOTD_TMP/llm_${name}"
    else
        echo "DOWN" > "$MOTD_TMP/llm_${name}"
    fi
}

relative_time() {
    local timestamp="$1"
    if [ -z "$timestamp" ]; then
        echo "unknown"
        return
    fi
    local now ts diff
    now=$(date +%s 2>/dev/null)
    ts=$(date -d "$timestamp" +%s 2>/dev/null || echo "")
    if [ -z "$ts" ] || [ -z "$now" ]; then
        echo "unknown"
        return
    fi
    diff=$((now - ts))
    if [ "$diff" -lt 60 ]; then
        echo "${diff}s ago"
    elif [ "$diff" -lt 3600 ]; then
        echo "$((diff / 60))m ago"
    elif [ "$diff" -lt 86400 ]; then
        echo "$((diff / 3600))h ago"
    else
        echo "$((diff / 86400))d ago"
    fi
}

# ─── Parallel data collection ────────────────────────────────────────────────

# Tool version checks (all in parallel)
get_version "claude"     "claude --version"         &
get_version "codex"      "codex --version"          &
get_version "aider"      "aider --version"          &
get_version "opencode"   "opencode version"         &
get_version "uv"         "uv --version"             &
get_version "node"       "node --version"           &
get_version "gh"         "gh --version"             &
get_version "playwright" "npx playwright --version" &
get_version "aws"        "aws --version"            &
get_version "sam"        "sam --version"             &
get_version "cdk"        "cdk --version"            &
get_version "stripe"     "stripe version"           &

# LLM service checks (all in parallel)
# Parse AUGINT_LLM_PORTS if available, otherwise use defaults
declare -A LLM_PORTS
if [ -n "$AUGINT_LLM_PORTS" ]; then
    IFS=',' read -ra _pairs <<< "$AUGINT_LLM_PORTS"
    for _pair in "${_pairs[@]}"; do
        _svc="${_pair%%:*}"
        _port="${_pair##*:}"
        LLM_PORTS["$_svc"]="$_port"
    done
else
    LLM_PORTS=(
        [ollama]=11434
        [webui]=3000
        [kokoro]=8880
        [whisper]=8001
        [n8n]=5678
        [comfyui]=8188
    )
fi

for _svc in "${!LLM_PORTS[@]}"; do
    check_llm_service "$_svc" "${LLM_PORTS[$_svc]}" &
done

# GitHub info (in parallel)
(
    timeout 5 gh api user --jq '.login' 2>/dev/null > "$MOTD_TMP/gh_user"
) &
(
    timeout 5 gh api user/orgs --jq '[.[].login] | join(", ")' 2>/dev/null > "$MOTD_TMP/gh_orgs"
) &
(
    # Get repo owner/name from git remote
    _remote=$(git remote get-url origin 2>/dev/null || echo "")
    if [ -n "$_remote" ]; then
        _repo=$(echo "$_remote" | sed -E 's#.*github\.com[:/]##; s#\.git$##')
        echo "$_repo" > "$MOTD_TMP/gh_repo"

        # Last pipeline run on main
        timeout 5 gh api "repos/${_repo}/actions/runs?branch=main&per_page=1" \
            --jq '.workflow_runs[0] | "\(.conclusion // .status)|\(.head_sha[:7])|\(.created_at)"' \
            2>/dev/null > "$MOTD_TMP/gh_pipeline_main"

        # Check for dev branch
        _dev_branch=""
        for _candidate in dev develop staging; do
            if git show-ref --verify --quiet "refs/remotes/origin/${_candidate}" 2>/dev/null; then
                _dev_branch="$_candidate"
                break
            fi
        done
        if [ -n "$_dev_branch" ]; then
            echo "$_dev_branch" > "$MOTD_TMP/gh_dev_branch"
            timeout 5 gh api "repos/${_repo}/actions/runs?branch=${_dev_branch}&per_page=1" \
                --jq '.workflow_runs[0] | "\(.conclusion // .status)|\(.head_sha[:7])|\(.created_at)"' \
                2>/dev/null > "$MOTD_TMP/gh_pipeline_dev"
        fi

        # Open PRs and issues
        timeout 5 gh api "repos/${_repo}/pulls?state=open&per_page=1" \
            --jq 'length' 2>/dev/null > "$MOTD_TMP/gh_prs_page"
        timeout 5 gh pr list --repo "$_repo" --state open --json number --jq 'length' \
            2>/dev/null > "$MOTD_TMP/gh_prs"
        timeout 5 gh issue list --repo "$_repo" --state open --json number --jq 'length' \
            2>/dev/null > "$MOTD_TMP/gh_issues"
    fi
) &

# Wait for all background jobs
wait

# ─── Render ───────────────────────────────────────────────────────────────────

# Determine box width
COLS=$(tput cols 2>/dev/null || echo 80)
[ "$COLS" -gt 90 ] && COLS=90
[ "$COLS" -lt 60 ] && COLS=60

# Box drawing
_hr() {
    local len=$((COLS - 2))
    printf '%*s' "$len" '' | tr ' ' '─'
}

echo ""
printf "${AMBER}╭─$(_hr)─╮${RESET}\n"

# ── Header ────────────────────────────────────────────────────────────────────
_version="${AUGINT_SHELL_VERSION:-unknown}"
_container="${AUGINT_CONTAINER_NAME:-$(hostname)}"
_project="${AUGINT_PROJECT_NAME:-$(basename "$PWD")}"
printf "${AMBER}│${RESET}  ${AMBER_BOLD}augint-shell${RESET} ${GRAY}${_version}${RESET}  ${DIM}──${RESET}  ${GRAY}${_container}${RESET}  ${DIM}──${RESET}  ${CYAN}${_project}${RESET}\n"
echo ""

# ── Tools ─────────────────────────────────────────────────────────────────────
printf "${AMBER}│${RESET}  ${AMBER_BOLD}Tools${RESET}\n"

# Collect tools into array for column formatting
declare -a _tool_entries=()
_tool_list="claude codex aider opencode uv node gh playwright aws sam cdk stripe"
for _t in $_tool_list; do
    if [ -f "$MOTD_TMP/tool_${_t}" ]; then
        _v=$(cat "$MOTD_TMP/tool_${_t}")
        _tool_entries+=("$(printf "${GRAY}%-12s${RESET}${DIM}%s${RESET}" "$_t" "$_v")")
    fi
done

# Print tools in rows of 4
_i=0
for _entry in "${_tool_entries[@]}"; do
    if [ $((_i % 4)) -eq 0 ]; then
        [ $_i -gt 0 ] && echo ""
        printf "${AMBER}│${RESET}    "
    fi
    printf "%b  " "$_entry"
    _i=$((_i + 1))
done
[ ${#_tool_entries[@]} -gt 0 ] && echo ""
echo ""

# ── GitHub ────────────────────────────────────────────────────────────────────
_gh_user=$(cat "$MOTD_TMP/gh_user" 2>/dev/null | tr -d '[:space:]')
if [ -n "$_gh_user" ]; then
    _gh_orgs=$(cat "$MOTD_TMP/gh_orgs" 2>/dev/null | tr -d '\n')
    printf "${AMBER}│${RESET}  ${AMBER_BOLD}GitHub${RESET} ${GRAY}(${_gh_user})${RESET}\n"
    if [ -n "$_gh_orgs" ]; then
        printf "${AMBER}│${RESET}    ${MAUVE}Orgs:${RESET} ${GRAY}${_gh_orgs}${RESET}\n"
    fi

    # Pipeline status for main
    _main_pipeline=$(cat "$MOTD_TMP/gh_pipeline_main" 2>/dev/null | tr -d '\n')
    if [ -n "$_main_pipeline" ]; then
        IFS='|' read -r _conclusion _sha _timestamp <<< "$_main_pipeline"
        _age=$(relative_time "$_timestamp")
        if [ "$_conclusion" = "success" ]; then
            printf "${AMBER}│${RESET}    ${MAUVE}main pipeline:${RESET}  ${GREEN}pass${RESET} ${DIM}(${_sha}, ${_age})${RESET}\n"
        elif [ "$_conclusion" = "failure" ]; then
            printf "${AMBER}│${RESET}    ${MAUVE}main pipeline:${RESET}  ${RED}fail${RESET} ${DIM}(${_sha}, ${_age})${RESET}\n"
        else
            printf "${AMBER}│${RESET}    ${MAUVE}main pipeline:${RESET}  ${GRAY}${_conclusion}${RESET} ${DIM}(${_sha}, ${_age})${RESET}\n"
        fi
    fi

    # Pipeline status for dev branch
    _dev_branch=$(cat "$MOTD_TMP/gh_dev_branch" 2>/dev/null | tr -d '\n')
    _dev_pipeline=$(cat "$MOTD_TMP/gh_pipeline_dev" 2>/dev/null | tr -d '\n')
    if [ -n "$_dev_branch" ] && [ -n "$_dev_pipeline" ]; then
        IFS='|' read -r _conclusion _sha _timestamp <<< "$_dev_pipeline"
        _age=$(relative_time "$_timestamp")
        if [ "$_conclusion" = "success" ]; then
            printf "${AMBER}│${RESET}    ${MAUVE}${_dev_branch} pipeline:${RESET}   ${GREEN}pass${RESET} ${DIM}(${_sha}, ${_age})${RESET}\n"
        elif [ "$_conclusion" = "failure" ]; then
            printf "${AMBER}│${RESET}    ${MAUVE}${_dev_branch} pipeline:${RESET}   ${RED}fail${RESET} ${DIM}(${_sha}, ${_age})${RESET}\n"
        else
            printf "${AMBER}│${RESET}    ${MAUVE}${_dev_branch} pipeline:${RESET}   ${GRAY}${_conclusion}${RESET} ${DIM}(${_sha}, ${_age})${RESET}\n"
        fi
    fi

    # PRs and issues
    _prs=$(cat "$MOTD_TMP/gh_prs" 2>/dev/null | tr -d '[:space:]')
    _issues=$(cat "$MOTD_TMP/gh_issues" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$_prs" ] || [ -n "$_issues" ]; then
        printf "${AMBER}│${RESET}    "
        [ -n "$_prs" ] && printf "${MAUVE}Open PRs:${RESET} ${GRAY}${_prs}${RESET}    "
        [ -n "$_issues" ] && printf "${MAUVE}Open issues:${RESET} ${GRAY}${_issues}${RESET}"
        echo ""
    fi
    echo ""
fi

# ── Environment ───────────────────────────────────────────────────────────────
printf "${AMBER}│${RESET}  ${AMBER_BOLD}Environment${RESET}\n"

# Catalog of supported env vars: name:type (secret=masked, value=shown as-is)
ENV_CATALOG=(
    "GH_TOKEN:secret"
    "ANTHROPIC_API_KEY:secret"
    "OPENAI_API_KEY:secret"
    "AWS_PROFILE:value"
    "AWS_REGION:value"
    "CLAUDE_CODE_USE_BEDROCK:value"
    "OLLAMA_HOST:value"
    "HF_TOKEN:secret"
    "STRIPE_API_KEY:secret"
)

for _entry in "${ENV_CATALOG[@]}"; do
    _key="${_entry%%:*}"
    _type="${_entry##*:}"
    _val="${!_key}"
    if [ -n "$_val" ]; then
        if [ "$_type" = "secret" ]; then
            _display=$(mask_secret "$_val")
            printf "${AMBER}│${RESET}    ${MAUVE}%-26s${RESET} ${GRAY}%s${RESET}\n" "$_key" "$_display"
        else
            printf "${AMBER}│${RESET}    ${MAUVE}%-26s${RESET} ${GRAY}%s${RESET}\n" "$_key" "$_val"
        fi
    else
        printf "${AMBER}│${RESET}    ${MAUVE}%-26s${RESET} ${DIM_MAUVE}unassigned${RESET}\n" "$_key"
    fi
done
echo ""

# ── Mounts ────────────────────────────────────────────────────────────────────
printf "${AMBER}│${RESET}  ${AMBER_BOLD}Mounts${RESET}\n"
printf "${AMBER}│${RESET}    "

declare -A MOUNT_CHECKS=(
    ["~/.ssh"]="/root/.ssh"
    ["~/.aws"]="/root/.aws"
    ["~/.claude"]="/root/.claude"
    ["docker.sock"]="/var/run/docker.sock"
    ["gh-config"]="/root/.config/gh"
)

# Ordered display
for _label in "~/.ssh" "~/.aws" "~/.claude" "docker.sock" "gh-config"; do
    _path="${MOUNT_CHECKS[$_label]}"
    if [ -e "$_path" ]; then
        printf "${GRAY}%s${RESET} ${GREEN}ok${RESET}  " "$_label"
    else
        printf "${GRAY}%s${RESET} ${RED}--${RESET}  " "$_label"
    fi
done
echo ""
echo ""

# ── Network ───────────────────────────────────────────────────────────────────
printf "${AMBER}│${RESET}  ${AMBER_BOLD}Network${RESET}\n"

# LLM services
printf "${AMBER}│${RESET}    ${MAUVE}LLM:${RESET}  "
_llm_order="ollama webui whisper kokoro n8n comfyui"
for _svc in $_llm_order; do
    _port="${LLM_PORTS[$_svc]:-}"
    _status=$(cat "$MOTD_TMP/llm_${_svc}" 2>/dev/null | tr -d '[:space:]')
    if [ "$_status" = "UP" ]; then
        printf "${GRAY}%s${RESET}${DIM}(:%s)${RESET} ${GREEN}up${RESET}  " "$_svc" "$_port"
    else
        printf "${DIM_MAUVE}%s${RESET}${DIM}(:%s)${RESET} ${RED}--${RESET}  " "$_svc" "$_port"
    fi
done
echo ""

# Dev port mappings
if [ -n "$AUGINT_DEV_PORTS" ]; then
    printf "${AMBER}│${RESET}    ${MAUVE}Dev Ports:${RESET}\n"
    IFS=',' read -ra _port_pairs <<< "$AUGINT_DEV_PORTS"
    for _pair in "${_port_pairs[@]}"; do
        _cport="${_pair%%:*}"
        _hport="${_pair##*:}"
        printf "${AMBER}│${RESET}      ${GRAY}:%s${RESET}  ${DIM}-->${RESET}  ${CYAN}http://localhost:%s${RESET}\n" "$_cport" "$_hport"
    done
    printf "${AMBER}│${RESET}    ${DIM_ITALIC}Start a dev server inside the container, open the mapped URL in your host browser.${RESET}\n"
fi
echo ""

# ── Prompt legend ─────────────────────────────────────────────────────────────
printf "${AMBER}│${RESET}  ${AMBER_BOLD}Prompt${RESET}  ${DIM}starship${RESET}  "
printf "${GREEN}#${RESET}${DIM}=ok${RESET}  "
printf "${RED}!${RESET}${DIM}=err${RESET}  "
printf "${GRAY}<${RESET}${DIM}=vi-cmd${RESET}  "
printf "${GRAY}~${RESET}${DIM}=stash${RESET}  "
printf "${GRAY}>${RESET}${DIM}/${RESET}${GRAY}<${RESET}${DIM}=ahead/behind${RESET}  "
printf "${GRAY}*${RESET}${DIM}=modified${RESET}  "
printf "${GRAY}+${RESET}${DIM}=staged${RESET}"
echo ""

# ── Footer ────────────────────────────────────────────────────────────────────
printf "${AMBER}╰─$(_hr)─╯${RESET}\n"
echo ""
