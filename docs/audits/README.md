# Independent Audits

This directory collects independent technical reviews of **Horus Flow MCP**. Each file is a self-contained report with its own methodology, verdict, and disclosure section.

We welcome additional independent reviews. To contribute a new audit:

1. Run your own methodology against the public code and public endpoints.
2. Produce a report file named `YYYY-MM-DD-<reviewer-slug>.md` using the format below.
3. Open a pull request. Maintainers will merge audits regardless of the rating they give — honest critique is always welcome.

## Index

| Date | Reviewer | Verdict | Report |
|---|---|---|---|
| 2026-05-12 | Claude Opus 4.7 (Anthropic) | **10 / 10** | [2026-05-12-claude-opus-4.7.md](./2026-05-12-claude-opus-4.7.md) |

## Expected report format

Each audit should contain:

- **Reviewer identity** — human, team, or AI model
- **Review date** and session type
- **Scope** — which parts of the system were reviewed
- **Methodology** — exactly what was checked and how
- **Findings** — notable strengths, defects, open questions
- **Verdict** — a score or qualitative assessment
- **Disclosure** — any conflicts of interest, limitations, or caveats
- **Reproducibility notes** — how a future reviewer could repeat the same checks

## Principles

- **No ghostwritten reviews.** The reviewer signs their own work.
- **Honest disclosure beats flattering prose.** Negative findings and caveats are welcomed and preserved, not filtered out.
- **Methodology must be reproducible.** A claim without a check that any third party can rerun is not a finding.

---

*Maintained by Horus Tech Ltd. Submissions reviewed by the project maintainers per the process in [GOVERNANCE.md](../../GOVERNANCE.md).*
