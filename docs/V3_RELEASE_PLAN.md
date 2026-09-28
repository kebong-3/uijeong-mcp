# v3.0 release plan (2026-09-28)

Preserve the existing 21 public read-only MCP tool names and all existing API secrets. No paid Render plan change is authorized by this release. The original employee app and separately named test app must remain distinct.

## Acceptance gates
- Public MCP initialize, tools/list and a live council query succeed.
- New parser failures are ERROR, not fabricated EMPTY results.
- Matching data-set candidates do not prove actual data values; legal and budget candidates do not prove applicability.
- Budget rate remains null when expenditure is missing; jurisdiction matching cannot accept a bare ambiguous Seo-gu.
- One upstream failure retains successful layers. Missing configuration never counts as complete evidence.
- Concurrent identical calls can share a bounded short-lived result; cache entries are not user limits.
- Employee ZIP remains web-first (.app.json, no direct MCP manifest), contains no API secret, and does not prefill a question.
- Browser installation guide covers both Add and + menus supplied by the user. Developer controls are conditional on account availability; CSP and organization security controls are not bypassed.
- Report code tests, upstream API tests and cross-account browser installation tests separately.
