# CLAUDE.md

## Project Overview

Read these three documents first. They show the project structure, the AWS architecture, and the
usual tasks.

- `docs/hsa-architecture.md` — the HSA receipts app
- `docs/personal-finance-architecture.md` — the personal finance app. It holds the family budget
  feature today, and more features will follow.
- `docs/user_guide.md` — setup, deploy steps, and daily use

## Repository Structure

- `infra/` — AWS CDK infrastructure (TypeScript 5.x, Node.js)
- `lambda/` — Lambda function code (Python 3.13)
- `web/` — All frontend source, one folder for each app
    - `web/hsa/` — Static frontend for the HSA app
    - `web/root/` — Static landing page for corderohq.com
    - `web/math/` — Static math quiz page
    - `web/personal-finance/` — React frontend for the personal finance app
    - `web/shared/` — Assets that every frontend uses, such as the favicon
- `docs/` — Project documentation

## Coding Standards

### Python (`lambda/`)
- Package manager: **uv**
- Linter and formatter: **ruff** (120 character line width, 4-space indent, double quotes)
- Type checker: **ty**
- Tests: **pytest**. Run them from the `lambda/` directory.
- Give a type to everything.
- Run the tests: `uv run pytest`
- Run the linter: `uv run ruff check .`
- Run the formatter: `uv run ruff format .`

### TypeScript (`infra/`)
- Package manager: **npm**
- Linter: **eslint** (flat config, with `defineConfig()`)
- Formatter: **prettier** (120 character print width, 4-space indent, double quotes)
- Compiler: **tsc** (strict mode)
- Always run the TypeScript tools from the `infra/` directory.

## Running Commands

- **Do not run a test suite, a build, or a lint command** — `npm test`, `npm run build`,
  `uv run pytest`, `uv run ruff`, `npx tsc`, and others — unless the user asks you to. They write
  many lines of output, and that output uses tokens quickly.
- Tell the user which command to run, and what to look for. The user runs it, and then sends you
  any error or other output that matters.

## Rules

- **Write a commit message of one line.** Do not write a message body.
- **Do not put a "Co-Authored-By" line in a commit message.**
- **Do not use a deprecated feature or package.** Always use the newest stable API, option, and
  version of each dependency. If you find deprecated code, tell the user about it or correct it.
- Give every private constant at module level a name in ALL_CAPS, with one underscore in front.
  For example, `_SNS_CLIENT`.
- Read every necessary environment variable with `get_env_var()` from `util.py`. That function
  raises an error if the value is absent or blank.
- **Give every CDK stack class a JSDoc comment that lists each AWS resource it makes.** When you
  add, remove, or change a resource in a stack, change the class docstring to match.
