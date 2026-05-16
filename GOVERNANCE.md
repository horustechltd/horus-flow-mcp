# Project Governance

**Horus Flow MCP** is an open-source MCP server published by **Horus Tech Ltd** (United Kingdom). This document describes how decisions are made, who can make them, and how the project stays aligned with its stated mission.

## Mission

To provide AI agents and autonomous systems with a clean, audited, MCP-native interface into the Horus Flow Intelligence API — with zero lock-in, open source code, and clearly documented authority boundaries.

## Maintainer Structure

| Role | Responsibility | Who |
|---|---|---|
| **Steward** | Owns strategic direction, release approval, and final arbitration | Horus Tech Ltd |
| **Maintainer** | Reviews PRs, triages issues, manages releases | Named in `MAINTAINERS.md` (upon first external maintainer) |
| **Contributor** | Anyone who has a merged PR | Tracked via GitHub |

At present the maintainer team is small. As the project grows, additional maintainers will be nominated by existing maintainers based on contribution history and will be added by PR to `MAINTAINERS.md`.

## Decision Making

Decisions follow a tiered model based on impact:

### Tier 1 — Day-to-day changes
Typos, minor bug fixes, documentation improvements, dependency patches, and small refactors.
- Any maintainer may merge after a single approving review.

### Tier 2 — Feature additions
New MCP tools, new transports, new integration examples, new CI checks.
- Requires one approving review and no blocking objections after 72 hours.
- Must include tests and documentation updates.

### Tier 3 — Breaking changes
Tool renames, parameter removals, response-schema changes, transport protocol changes.
- Requires explicit approval from the Steward.
- Must be announced in the previous release as *deprecated* whenever possible.
- Must be published via a MAJOR version bump per SemVer.

### Tier 4 — Security fixes
- Handled via the private disclosure process in `SECURITY.md`.
- May bypass the normal review timeline to ship a patch release quickly.

## Relationship to the Horus Flow API

This MCP server is a **thin client** to the proprietary Horus Flow Intelligence API, which is operated and maintained separately by Horus Tech Ltd at `api.horustek.pro`. The MCP server repository governs:

- MCP tool names, schemas, and transport behavior
- Client-side configuration
- Packaging and distribution (PyPI, Docker, Homebrew where applicable)

The MCP server repository does **not** govern:

- The underlying prediction engine (proprietary, closed source)
- REST endpoint definitions at `api.horustek.pro`
- API SLA, pricing, or tier definitions (see `https://flow.horustek.pro/`)

Proposed changes that would require new API endpoints should be escalated to the Horus Flow API team via `support@horustek.pro` before a PR is opened against this repository.

## Release Process

1. All changes for a release accumulate under `## [Unreleased]` in `CHANGELOG.md`.
2. When a release is cut, a maintainer renames the `Unreleased` section to the new version with the release date.
3. A signed git tag `vX.Y.Z` is created.
4. GitHub Actions build the distribution artifacts and publish to PyPI.
5. A GitHub Release is created containing the CHANGELOG excerpt.
6. The Smithery, Glama, and PulseMCP registry metadata is updated if version-dependent fields changed.

Releases are targeted approximately monthly; there is no fixed cadence.

## Conflict Resolution

If two or more maintainers disagree on a decision:

1. Technical discussion on the PR or issue, with evidence.
2. If unresolved after 7 days, the Steward makes the final call and documents the reasoning in the PR.
3. Steward decisions can be revisited by a new issue at any time.

## Code of Conduct

All participants in project spaces are bound by our [Code of Conduct](./CODE_OF_CONDUCT.md). The Steward is the final authority on enforcement actions.

## Changes to Governance

Changes to this document require a PR, 14-day comment window, and Steward approval.

## Contact

- General: `support@horustek.pro`
- Security: `security@horustek.pro`
- Conduct: `conduct@horustek.pro`
- Commercial: `sales@horustek.pro`

---

_Last reviewed: 2026-05-12_
