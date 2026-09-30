# Security and privacy

Viraasat is a small, approved-tester family-archive demo. It can contain personal stories, relationships, and private media; do not enter real sensitive family or medical information unless you understand the current limits and have permission from the people involved. This repository does not claim a security certification, clinical-grade protection, uninterrupted hosting, or a recovery guarantee.

## Report a vulnerability privately

For a security issue, use the repository's **Security → Report a vulnerability** flow on [GitHub](https://github.com/npai96/family_tree) if it is available. If private vulnerability reporting is unavailable, use the owner's contact information on their GitHub profile. If that also has no private contact route, open a public issue titled “Request private security contact” **without vulnerability details** so the maintainer can arrange a private channel. Do not put an exploit, real family records, tokens, keys, or private media in a public issue, pull request, or screenshot. A useful private report contains the affected route or feature, reproduction steps with fictional accounts/data, impact, and the minimum evidence needed to reproduce it. Do not send live credentials.

This is an independently maintained portfolio project; there is no promised response or remediation time. The maintainer will assess reports, coordinate a fix, and credit the reporter if they request attribution and disclosure is safe. Please do not test against other families, exfiltrate data, or run load tests against the hosted free-tier service.

## Deployment expectations

- V3 code uses Google sign-in through Supabase with a server-enforced `APPROVED_TESTER_EMAILS` cohort. An unlisted Google account receives no V3 app session. This control is not live until the V3 Render release is deployed and checked. Review-mode identity selection must remain disabled on any public deployment.
- FastAPI checks circle membership and owner/editor/viewer permissions. A visible or disabled UI control is not a security boundary.
- Supabase Storage is private, and database/storage credentials belong only in server-side environment settings. Never put `DATABASE_URL`, `SUPABASE_SECRET_KEY`, session tokens, or live media tickets in source control, browser assets, issues, logs, or portfolio screenshots.
- Postgres RLS is enabled and browser roles lack table grants in the current hosted design. The backend runtime role is privileged, so **per-circle RLS does not currently protect backend queries**. See [V3 security decisions](docs/security-decisions.md) and [threat model](docs/security-threat-model.md).
- V3 code issues `Secure`, `HttpOnly` hosted app cookies with CSRF checks; sessions can be revoked and expire. A compromised same-origin browser can still make requests while signed in. A permitted member can retain copies of information they view. Free hosting and storage are not backups.

For operational setup and safe rollback, see [the hosted deployment guide](docs/DEPLOY_FREE_DEMO.md). For the exact controls and tests included in a given V3 release, consult [the implementation report](docs/security-implementation-report.md); documentation of a planned control is not proof it is live.
