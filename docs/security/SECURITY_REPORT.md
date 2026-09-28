# SECURITY_REPORT.md â€” V17.2

Plain-language summary of what changed and why, for someone deciding
whether this is ready to deploy. Not a penetration-test report â€” no
external security testing was performed; this describes what was
built and reasoned through during development.

## Risks this pass mitigates

1. **Credential stuffing / distributed brute force against one
   account.** Before V17.2, the only defense against repeated login
   attempts was the per-IP rate limiter â€” an attacker rotating
   IPs (a botnet, a proxy pool) could attempt unlimited passwords
   against one known email. Account lockout now stops this regardless
   of source IP.
2. **Unbounded OTP guessing.** Before V17.2, a verification or
   password-reset code accepted unlimited wrong guesses until it
   expired, bounded only by the per-IP rate limit (which an attacker
   distributing guesses across IPs wouldn't trip). Now capped at
   `otp_max_attempts`.
3. **Indefinitely-lived idle sessions.** Before V17.2, a refresh token
   was valid for its full lifetime (`refresh_token_days`/
   `_remember_me_days`) regardless of activity â€” a session on a lost
   or shared device stayed silently valid. Now subject to an idle
   timeout in addition to its expiry.
4. **No account-level lockout visibility or control for admins.**
   Admins previously had no way to see or act on repeated failed
   logins against a specific account, or to force-lock/unlock one, or
   to see/revoke a specific user's active sessions.
5. **Admin credentials sharing a rate-limit budget with ordinary
   logins.** Admin/super_admin accounts are a higher-value target;
   they now have their own, stricter, budget.

## Residual risks / known gaps (not addressed in this pass)

- **No breached-password check.** A user can still set a password
  that appears in a public breach corpus, as long as it meets the
  existing length/complexity rules.
- **No password expiration/age policy.** Passwords don't expire.
- **No dedicated "change password while logged in" flow** â€” see
  CHANGELOG_V17_2.md. A user who wants to change their password today
  must go through the forgot-password OTP flow.
- **Enumeration tradeoff, accepted deliberately**: a locked account
  returns a distinct `423` on login (vs. the generic `401` for a wrong
  password), which confirms the account exists to anyone who tries a
  login and gets `423`. This is the standard industry tradeoff
  (stopping further brute-force attempts against a known-targeted
  account outweighs the marginal enumeration risk, since an attacker
  who's already triggered a lockout has already demonstrated
  knowledge the account exists) â€” not an oversight.
- **In-memory rate limiting/lockout counters are per-process** unless
  `REDIS_URL` is configured â€” a multi-replica deployment without
  Redis has each replica enforcing its own budget, which is
  effectively a higher combined limit than the configured one. Account
  lockout itself is stored on the `User` row in the database, so it
  *is* consistent across replicas regardless of Redis â€” only the
  rate-limit and progressive-delay timing checks are per-process.
- **No SIEM/webhook forwarding is actually connected** â€” only the
  extension point (`security_events.register_handler`) exists. See
  SECURITY_ARCHITECTURE.md.
- **This report itself is not a substitute for external security
  review** â€” no dependency/CVE scan, no fuzzing, no penetration test
  was run as part of this pass (nor could dependencies be installed
  in the environment this was built in â€” see TEST_REPORT_V17_2.md).

## Design decisions worth a second opinion

- **Permanent lock reuses `User.active`** rather than a distinct
  field â€” see SECURITY_ARCHITECTURE.md for the reasoning and the one
  known nuance (a permanently-locked account can also accumulate
  temporary-lock counters on top, since the two mechanisms aren't
  mutually exclusive by construction).
- **Progressive delay rejects rather than sleeps** â€” a request that
  arrives too soon after a failure gets an immediate 429, not a
  delayed response. This avoids tying up a worker thread/process for
  the delay duration, but means a client that retries immediately
  after a 429 (rather than waiting) will just get another 429 â€” this
  is the intended behavior, not a bug, but worth knowing if writing a
  client-side retry loop against this API.

