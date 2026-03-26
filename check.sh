#!/usr/bin/env bash
# Run every static check in the monorepo: tests, linters, type checkers,
# formatters, and CDK synth. Each check runs independently; the script does NOT
# fail-fast, so you see the full picture in one pass. Exit code is non-zero iff
# any check failed.

set -o pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

RUN_PYTHON=false
RUN_TS=false
RUN_SYNTH=false
COPY=false
FIX=true

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Run static checks across the monorepo (pytest, ruff, ty, tsc, eslint, prettier).

By default, ruff/eslint/prettier autofix in place. Pass --no-fix for a
read-only run (CI-style).

Options:
  -p, --python       Only run Python checks (lambda/)
  -t, --typescript   Only run TypeScript/JS checks (infra/, budget/)
  -s, --synth        Also run \`cdk synth\` (opt-in; slow, skipped by default)
  -n, --no-fix       Don't autofix — just report. pytest, ty, tsc, cdk synth
                     are always read-only and unaffected by this flag.
  -c, --copy         Also copy combined output to the clipboard (macOS pbcopy)
  -h, --help         Show this help

With no -p/-t flag, both sides run. Flags combine: \`-t -s -c\` runs TS checks
plus cdk synth and copies output. \`cdk synth\` is opt-in so quick runs don't
pay the synth cost.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--python) RUN_PYTHON=true ;;
        -t|--typescript) RUN_TS=true ;;
        -s|--synth) RUN_SYNTH=true ;;
        -n|--no-fix) FIX=false ;;
        -c|--copy) COPY=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown flag: $1" >&2; usage; exit 1 ;;
    esac
    shift
done

# Default: run everything if neither side was named explicitly.
if ! $RUN_PYTHON && ! $RUN_TS; then
    RUN_PYTHON=true
    RUN_TS=true
fi

FAILURES=()

run() {
    local label="$1"
    shift
    echo
    echo "==> $label"
    if "$@"; then
        echo "    PASS"
    else
        local code=$?
        echo "    FAIL (exit $code)"
        FAILURES+=("$label")
    fi
}

main() {
    # In --fix mode, swap `--check` flags for the equivalent in-place writes.
    # Only "safe" autofixes are applied (ruff's default policy, eslint's default
    # --fix scope, prettier's --write). pytest/ty/tsc/synth have no fix mode.
    if $FIX; then
        local RUFF_CHECK_ARGS=(--fix)
        local RUFF_FORMAT_ARGS=()
        local ESLINT_ARGS=(--fix)
        local PRETTIER_ARGS=(--write)
    else
        local RUFF_CHECK_ARGS=()
        local RUFF_FORMAT_ARGS=(--check)
        local ESLINT_ARGS=()
        local PRETTIER_ARGS=(--check)
    fi

    if $RUN_PYTHON; then
        cd "$ROOT/lambda"
        run "lambda: pytest"        uv run python -m pytest
        run "lambda: ruff check"    uv run ruff check "${RUFF_CHECK_ARGS[@]}" .
        run "lambda: ruff format"   uv run ruff format "${RUFF_FORMAT_ARGS[@]}" .
        run "lambda: ty"            uv run ty check
    fi

    if $RUN_TS; then
        cd "$ROOT/infra"
        run "infra: tsc"            npx tsc --noEmit
        run "infra: eslint"         npx eslint "${ESLINT_ARGS[@]}" .
        run "infra: prettier"       npx prettier "${PRETTIER_ARGS[@]}" .

        cd "$ROOT/budget"
        run "budget: tsc"           npx tsc --noEmit
        run "budget: eslint"        npx eslint "${ESLINT_ARGS[@]}" .
        run "budget: prettier"      npx prettier "${PRETTIER_ARGS[@]}" .
    fi

    if $RUN_SYNTH; then
        cd "$ROOT/infra"
        run "infra: cdk synth"      npx cdk synth --quiet
    fi

    echo
    echo "================================================================"
    if [ ${#FAILURES[@]} -eq 0 ]; then
        echo "All checks passed."
        return 0
    fi
    echo "${#FAILURES[@]} check(s) failed:"
    for f in "${FAILURES[@]}"; do
        echo "  - $f"
    done
    return 1
}

if $COPY; then
    if ! command -v pbcopy >/dev/null 2>&1; then
        echo "Error: --copy requires pbcopy (macOS) but it was not found." >&2
        exit 1
    fi
    OUTPUT_FILE=$(mktemp)
    # Capture combined stdout+stderr; PIPESTATUS[0] preserves main's exit code.
    main 2>&1 | tee "$OUTPUT_FILE"
    RC=${PIPESTATUS[0]}
    pbcopy < "$OUTPUT_FILE"
    rm -f "$OUTPUT_FILE"
    echo
    echo "(Output copied to clipboard.)"
    exit "$RC"
else
    main
fi
