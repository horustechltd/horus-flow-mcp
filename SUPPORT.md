# Support

Thank you for using **Horus Flow MCP**. This document describes how to get help and what response times to expect.

## Where to Ask

Choose the channel that matches your situation:

### 🐛 You think you found a bug
- **Channel:** [GitHub Issues](https://github.com/horustechltd/horus-flow-mcp/issues/new/choose) → *Bug report* template
- **Expected response:** Within 2 business days
- **What to include:** OS, Python version, `horus-flow-mcp` version, MCP host (Claude Desktop / Cursor / Cline / …), full reproduction steps, logs with keys redacted

### 💡 You have a feature idea
- **Channel:** [GitHub Issues](https://github.com/horustechltd/horus-flow-mcp/issues/new/choose) → *Feature request* template
- **Expected response:** Within 5 business days

### ❓ You have a usage question
- **Channel:** [GitHub Discussions](https://github.com/horustechltd/horus-flow-mcp/discussions) (Q&A category)
- **Expected response:** Community-powered; maintainers answer when possible

### 🔒 You found a security issue
- **Channel:** `security@horustek.pro` (private email)
- **Expected response:** Acknowledgement within 24 hours
- **Do not** open a public issue. See [`SECURITY.md`](./SECURITY.md) for details.

### 💳 You have a billing / API-key question
- **Channel:** `support@horustek.pro`
- **Scope:** Billing, plan upgrades, API key generation, quota adjustments
- **Expected response:** Within 1 business day
- **Note:** Billing is handled by our parent service at `flow.horustek.pro`, not this MCP repository.

### 🏢 You want to discuss enterprise or custom usage
- **Channel:** `sales@horustek.pro`
- **Scope:** SLA agreements, private deployments, dedicated infrastructure, custom symbol coverage, MCP white-labeling
- **Expected response:** Within 1 business day

### 📋 You need to report a Code of Conduct violation
- **Channel:** `conduct@horustek.pro`
- **Expected response:** Within 24 hours, confidential handling per policy

## What Is Not Supported Here

This repository is the **MCP client layer** only. The following are handled upstream:

| Topic | Correct channel |
|---|---|
| API endpoint behavior | `support@horustek.pro` |
| Prediction-model questions | Not publicly discussed (model is proprietary) |
| Trading advice | Not provided — Horus publishes data, not financial advice |
| RapidAPI gateway issues | RapidAPI support + `support@horustek.pro` |

## Response Time Philosophy

We aim to respond to every legitimate request. Response time ranges above are targets, not commitments. For contractual SLAs, see our enterprise plans at https://flow.horustek.pro/#pricing.

## Support Language

Primary support language is **English**. Arabic is available on request at `support@horustek.pro`.

## Helping Yourself First

Before opening an issue, please check:

1. The [README](./README.md) install and integration guide
2. The [CHANGELOG](./CHANGELOG.md) for recent breaking changes
3. Existing open and closed [issues](https://github.com/horustechltd/horus-flow-mcp/issues)
4. Your MCP host's logs and our `horus-flow-mcp` logs

Most reported bugs are actually misconfigured MCP host entries or missing `HORUS_API_KEY` env vars — please verify these first.

## Commercial Support

For organizations that need guaranteed response times, private Slack / Teams channels, or onboarding assistance, please inquire about our **Professional** and **Institutional** plans at https://flow.horustek.pro/#pricing or email `sales@horustek.pro`.

---

**Horus Tech Ltd** — Support Policy v1.0 — last reviewed 2026-05-12.
