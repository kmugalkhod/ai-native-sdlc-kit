---
name: api-security
description: Apply the API security standard. Use whenever creating or modifying an external-facing endpoint, reviewing API code, or generating an OpenAPI spec.
---

# API security standard
<!-- Example policy skill. Copy to .claude/skills/api-security/ and replace with your real standard.
     Owner: <security policy owner>. Changes need the owner's sign-off. Back any rule that must
     ALWAYS hold with a hook or a review check — a skill is an advisory control. -->

When you create or change an API endpoint:
1. **Authentication**: every endpoint requires the gateway JWT; no anonymous routes outside `/health`.
2. **Input validation**: validate request bodies against the OpenAPI schema and reject unknown fields.
3. **Audit**: every state-changing endpoint emits an audit event with actor, action, entity and timestamp.
4. **Data classification**: fields tagged `pii` in the schema never appear in logs or error messages.

In your summary, list each endpoint you touched and how it meets rules 1–4.
