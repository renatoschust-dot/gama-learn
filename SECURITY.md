# Security

- Do not commit `.env`, tokens, API keys, chat IDs or client secrets.
- Runtime state (`state/`) is local and untracked.
- Report vulnerabilities privately to the repository owner; do not open a public issue with exploit details.
- Mutating actions (mail/WhatsApp/public posting/database writes) require explicit approval.
- The Sentinel is read-only by default; skill fixes require approve + apply and create a backup.
