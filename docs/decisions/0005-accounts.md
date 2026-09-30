# 0005 — Cornell email accounts replace the shared site password

**Date:** 2026-09-30

**Status:** Implemented on `feature/account-login`, tested on `deploy/staging` before
production.

## Context

The hosted Render deployment ([guide](../deploy/render.md)) sat behind
one shared site password. Everyone who knew it used the owner's provider and model
credentials, and nobody could be signed out alone. The owner decided on 2026-09-30:

- replace the shared site password with personal accounts;
- email and password sign-up, no Google or other identity provider;
- only `@cornell.edu` addresses;
- send account email through Resend;
- keep the bearer token for scripts and agents that call `/v1` without a browser.

## Decision

**Ownership of the address is proved before a password exists.** Sign-up asks only for
an email address. OpenEPW emails a one-time link, and the password is chosen on the page
that link opens. Accepting a password at sign-up would let anyone register someone
else's address with a password they know, then wait for the owner to click the
verification link. Password reset uses the same link-and-set-password page.

- **Domain rule.** The address must end in exactly `@cornell.edu` (configurable list,
  `OPENEPW_ALLOWED_EMAIL_DOMAINS`); subdomains are not included. Because the link
  proves the inbox, the rule does limit who gets in.
- **No account enumeration.** Sign-up and reset give the same answer whether or not the
  address has an account. A sign-up for an existing account emails a reset link instead.
- **Links.** Tokens are 32 random bytes, stored only as SHA-256, single use, 24 hours for
  set-up and 1 hour for reset. They travel in the URL fragment (`/password#t=…`), which
  browsers never send to the server, so they do not appear in access logs or referrers;
  a small script on the page moves the token into the form.
- **Passwords.** 12 to 256 characters, hashed with scrypt (Python standard library,
  N=2^14, r=8, p=1, 16-byte salt); a failed sign-in for an unknown address still runs a
  hash so timing does not reveal accounts. Setting a password signs out every other
  session of that account.
- **Sessions.** A random token in an HttpOnly, SameSite=Lax cookie (Secure over https),
  stored as SHA-256 in SQLite, valid 30 days; sign-out deletes it on the server.
- **Throttling.** Ten failed sign-ins per address and per client in 10 minutes are
  refused. At most three account emails per address per hour and 100 per hour overall,
  which also protects the Resend quota.
- **Storage.** `accounts/accounts.sqlite3` in the data root, next to the chat sessions.
- **Mail.** Resend's HTTPS API with `OPENEPW_RESEND_API_KEY` from an address on a domain
  verified in Resend (`OPENEPW_MAIL_FROM`). Links use `OPENEPW_PUBLIC_URL`, or Render's
  `RENDER_EXTERNAL_URL`, never the request's Host header. For local work,
  `OPENEPW_ACCOUNTS_DEV_MAIL=1` prints links to the console instead of sending; it is
  refused when the server listens beyond the local machine.
- **Scripts.** `OPENEPW_BEARER_TOKEN`, if set, still authorises `/v1` calls with an
  `Authorization: Bearer` header.
- **Administration.** `openepw accounts list|disable|enable` on the server's data root.

## Consequences

- The Resend account needs a domain the owner controls, verified with DNS records;
  `cornell.edu` cannot be used as the sender. Until then accounts can be exercised only
  with the development mailer.
- Everyone signed in still shares the owner's NLR, Copernicus and OpenAI credentials and
  the model spending stop. Chat sessions are not yet separated per user.
- `OPENEPW_SITE_PASSWORD` and `api/site_gate.py` are removed; a deployment that still
  sets only that variable no longer starts in remote mode.
