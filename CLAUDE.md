# CLAUDE.md

## Project Overview

Read `docs/hsa-architecture.md` (HSA receipts app), `docs/budget-architecture.md` (family budget app), and `docs/user_guide.md` to understand the project structure, AWS architecture, and common workflows.

## Repository Structure

- `infra/` — AWS CDK infrastructure (TypeScript 5.x, Node.js)
- `lambda/` — Lambda function code (Python 3.13)
- `docs/` — Project documentation

## Coding Standards

### Python (`lambda/`)
- Package manager: **uv**
- Linter/formatter: **ruff** (120 char line width, 4-space indent, double quotes)
- Type checker: **ty**
- Tests: **pytest** (run from `lambda/` directory)
- Typing is required everywhere
- Run tests: `uv run pytest`
- Run linter: `uv run ruff check .`
- Run formatter: `uv run ruff format .`

### TypeScript (`infra/`)
- Package manager: **npm**
- Linter: **eslint** (flat config with `defineConfig()`)
- Formatter: **prettier** (120 char print width, 4-space indent, double quotes)
- Compiler: **tsc** (strict mode)
- Always run TS tooling from the `infra/` directory

## Running Commands

- **Do not run test suites, builds, or lint commands** (`npm test`, `npm run build`, `uv run pytest`, `uv run ruff`, `npx tsc`, etc.) unless explicitly asked. These produce verbose output that consumes tokens quickly.
- Instead, tell the user which commands to run and what to look for. The user will run them and paste back any errors or relevant output.

## Rules

- **Commit messages must be a single line.** No multi-line commit messages.
- **Never include Co-Authored-By in commit messages.**
- **Never use deprecated features or packages.** Always use the latest stable APIs, options, and versions from our dependencies. If you notice deprecated usage in existing code, flag it or fix it.
- All module-level private constants use ALL_CAPS with a single leading underscore (e.g., `_SNS_CLIENT`).
- Required environment variables must use `get_env_var()` from `util.py`, which raises on missing or blank values.
- **Every CDK stack class must have a JSDoc comment listing all AWS resources it creates.** When adding, removing, or modifying resources in a stack, update the class docstring to match.
