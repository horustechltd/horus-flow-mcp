# Contributing to Horus Flow MCP

Thank you for your interest in contributing to Horus Flow MCP — the open-source MCP server interface to the Horus Flow Intelligence API.

This document describes how to contribute effectively and what to expect from the maintainers.

## Table of Contents

- [Project Scope](#project-scope)
- [Ways to Contribute](#ways-to-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Commit Message Convention](#commit-message-convention)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)
- [Security Issues](#security-issues)
- [Licensing](#licensing)

## Project Scope

**Horus Flow MCP** is a thin, audited Model Context Protocol (MCP) wrapper around the Horus Flow Intelligence API. Its role is:

1. Expose Horus tools to MCP-compatible hosts (Claude Desktop, Cursor, Cline, Continue, LangChain MCP adapters, etc.).
2. Translate MCP tool calls into authenticated HTTPS requests to the Horus Flow API.
3. Shape responses for AI-agent consumption.

**In scope** for contributions:
- MCP server bug fixes
- New MCP tools that wrap existing Horus Flow API endpoints
- Transport improvements (stdio, SSE, HTTP)
- Documentation, examples, integration guides
- Developer experience (installers, error messages, telemetry controls)

**Out of scope** for this repository:
- Changes to the proprietary prediction engine (lives in a private Horus Tech Ltd repo)
- API endpoint definitions (managed upstream at `api.horustek.pro`)
- Trading strategies or financial advice

## Ways to Contribute

| Type | Starting Point |
|---|---|
| Bug report | Open an issue using the **Bug report** template |
| Feature request | Open an issue using the **Feature request** template |
| Documentation improvement | Open a PR directly — small doc PRs are accepted quickly |
| Code fix | Open an issue first, then PR |
| New MCP tool | Open an issue with proposed tool name + schema first |
| Integration example | PR a new file in `examples/<host>/` |

## Development Setup

### Requirements

- Python 3.10 or newer
- A Horus Flow API key (free tier available at https://flow.horustek.pro/register.html)

### Local clone

```bash
git clone https://github.com/horustechltd/horus-flow-mcp.git
cd horus-flow-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run the MCP server locally

```bash
export HORUS_API_KEY=your_key_here
python horus_mcp_public.py
```

### Test against Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "horus-flow-dev": {
      "command": "python",
      "args": ["/absolute/path/to/horus-flow-mcp/horus_mcp_public.py"],
      "env": { "HORUS_API_KEY": "your_key_here" }
    }
  }
}
```

## Pull Request Process

1. **Open an issue first** for anything larger than a typo fix. This avoids duplicated effort.
2. **Fork** the repository and create a topic branch from `main`:
   `git checkout -b fix/my-fix` or `feat/my-feature`.
3. **Keep PRs focused.** One logical change per PR. Large PRs will be asked to split.
4. **Write a clear PR description** using the provided template. Link the related issue.
5. **Pass CI.** All checks must be green before review.
6. **Respond to review feedback** within a reasonable window. PRs with no activity for 30 days may be closed.
7. **Squash merges** are the default. Your individual commits do not need to be perfect; the squashed commit will follow the Conventional Commits format.

## Coding Standards

- **Python style:** follow [PEP 8](https://peps.python.org/pep-0008/) with line length ≤ 100.
- **Type hints:** use type hints for all public functions.
- **Docstrings:** public functions and MCP tools must have docstrings describing purpose, inputs, and outputs.
- **Logging:** use `logging` module, not `print()`, except in CLI entry points.
- **No secrets in code:** all secrets come from environment variables.
- **Dependencies:** prefer the standard library. New dependencies must be justified in the PR description.

## Commit Message Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<optional scope>): <short summary>

<optional body>

<optional footer>
```

Common types used in this repository:

- `feat` — new functionality visible to users
- `fix` — bug fix
- `docs` — documentation only
- `chore` — tooling, CI, or infrastructure changes
- `refactor` — code change that is neither a feature nor a bug fix
- `ci` — continuous-integration changes
- `test` — adding or updating tests
- `perf` — performance improvements
- `revert` — reverts a previous commit

Example:

```
feat(mcp): add get_composite_intelligence tool

Wraps /v1/intelligence/composite and returns a structured
verdict object ready for agent consumption.

Closes #42
```

## Reporting Bugs

Please use the **Bug report** issue template. Include:

- Your operating system and Python version
- The version of `horus-flow-mcp` (`pip show horus-flow-mcp`)
- The MCP host (Claude Desktop / Cursor / Cline / …)
- Full reproduction steps
- Expected vs. actual behavior
- Relevant log output (with any keys redacted)

## Requesting Features

Use the **Feature request** template. Include:

- The problem you are trying to solve (not just the proposed solution)
- Which MCP host you are using
- Whether the requested capability already exists in the Horus Flow REST API

Note: MCP tools in this repository wrap existing API endpoints. If the underlying endpoint does not exist, the feature request should be directed to the Horus Flow API team via `support@horustek.pro`.

## Security Issues

**Do not open public issues for security vulnerabilities.** Email `security@horustek.pro` with details. See [`SECURITY.md`](./SECURITY.md) for our full policy.

## Licensing

By contributing, you agree that your contributions will be licensed under the same license as the project (see [`LICENSE`](./LICENSE)).

---

Thank you for helping make Horus Flow MCP better.

**Horus Tech Ltd** — Maintainers.
