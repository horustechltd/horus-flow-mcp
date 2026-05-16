# Changelog

All notable changes to **Horus Flow MCP** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes live in the `Unreleased` section and are moved into a numbered release on publication.

---

## [Unreleased]

### Added
- Project governance documentation (`GOVERNANCE.md`)
- Contributor support policy (`SUPPORT.md`)
- Contributor Covenant 2.1 Code of Conduct
- Issue templates (bug report, feature request, documentation)
- Pull request template
- GitHub Actions CI workflow with matrix testing on Python 3.10 / 3.11 / 3.12
- Dependabot configuration for weekly dependency review
- `CONTRIBUTING.md` with full development and release workflow

### Changed
- README restructured with clearer install paths and MCP client integration snippets

---

## [1.0.1] — 2026-04-19

### Added
- `pyproject.toml` for modern Python packaging and PyPI publication
- `server.json` configuration for MCP registry compatibility
- AI Agent prompt guidelines (`AI_AGENT_PROMPT.md`) describing recommended
  agent behavior when invoking Horus Flow tools
- Installation instructions for the `uvx` one-shot runner

### Changed
- Version bumped from 1.0.0 to 1.0.1
- README clarified for MCP host installation (Claude Desktop, Cursor, Cline)
- `horus_mcp_public.py` updated with improved error surfaces for
  authentication failures
- `smithery.yaml` updated with config schema and command function so
  Smithery-based MCP hosts can install the server automatically

### Removed
- Legacy `.well-known/mcp/` directory (superseded by `server.json`)
- Obsolete `🦅_Horus_Flow_MCP_Server (2).md` draft

---

## [1.0.0] — 2026-04-17

### Added
- Initial public release of the Horus Flow MCP server
- Four MCP tools wrapping the Horus Flow Intelligence REST API:
  - `get_crypto_flow` — real-time orderflow for a crypto symbol
  - `get_equity_flow` — US equity orderflow via Alpaca IEX
  - `scan_crypto_flow` — multi-symbol sweep
  - `get_macro_blocks` — SPY macro climate and institutional block trades
- Stdio transport for Claude Desktop and Cursor
- `MCP_README.md` with MCP-host-specific install snippets
- `SKILL.md` summarizing agent behavior guidelines
- `Dockerfile` for containerized deployment
- `glama.json` manifest for Glama AI directory listing
- `SECURITY.md` with responsible disclosure policy
- `LICENSE` — MIT
- Postman collection for quick REST testing

---

## Versioning Policy

- **MAJOR** — incompatible changes to MCP tool names, required parameters, or response schemas
- **MINOR** — new MCP tools or backward-compatible additions to existing tools
- **PATCH** — bug fixes, documentation, internal refactors

The underlying Horus Flow REST API follows its own versioning at `api.horustek.pro` and is managed separately from this MCP wrapper. See `server.json` for the compatible API version range.

[Unreleased]: https://github.com/horustechltd/horus-flow-mcp/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/horustechltd/horus-flow-mcp/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/horustechltd/horus-flow-mcp/releases/tag/v1.0.0
