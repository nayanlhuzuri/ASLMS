# Hotfix: Current Status timeout (5 Nov 2026)

**Change.** Commit 245dbeb on `main`: the High Court Current Status API waits up to `NAPIX_STATUS_TIMEOUT_SECONDS`
(default 90 s, 40 to 300); every other NAPIX API keeps `NAPIX_TIMEOUT_SECONDS` (40 s). Fault pause, retries and
batch size unchanged. Owner's decision ("just increasing the time limit"); decisions log entry of 5 Nov 2026.
No migration.

**Why.** With the host off at 20:00 on 3 and 4 Nov, the daily status check ran as a catch-up at about 10:00, when the
gateway answered a 250-CNR call in 26–40 s and more. On 5 Nov all 103 calls from 10:00 to 12:10 timed out at 40 s,
and the runner's fault pause cut the collection to about 50 calls an hour. Other APIs answered in 1–2 s.

**Checks.** `ruff check` and `ruff format --check` clean; backend unit tests 1,405 passed (two new); CI run
41984348003 green (changes, policy, backend, frontend, compose, ci-ok).

## Deployed
5 Nov 2026 at 12:58 IST. Images built from clean `main` at 245dbeb; `up -d --wait` with the court-data switch on,
then `api`, `worker`, `scheduler` and `web` recreated with `--no-deps --force-recreate`. Switch on in `api` and
`worker` (the scheduler carries none by design); `napix_status_timeout_seconds` reads 90.0 in the worker; web build
ID matches the image (`JkkizOvNgcn-jEaZQPbwG`); portal smoke passed. First calls after the deploy: Current Status
ok in 18–43 s, one at 42.9 s that the old limit would have failed. The same deploy carried ccbd532 (Designations:
Hierarchy Order) and 453b1c2 (the LIMBS overview document).
