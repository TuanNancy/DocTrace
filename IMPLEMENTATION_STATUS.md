# P0–P5 implementation status

Updated 2026-10-29. This records repository verification; cloud acceptance and rollout are tracked separately.

| Phase | Implemented | Remaining acceptance/work |
|---|---|---|
| P0 — DB/runtime foundation | Alembic control plane, dedicated runtime grants, separate migration env, strict readiness, sanitized API/worker/proxy logs, atomic request–job correlation | Bootstrap separate credentials on the shared Supabase project; authenticated Mac acceptance before VPS rollout |
| P1 — Workspace/RBAC | Workspace selection, owner-private catalogs, membership/archive/restore, workspace quota, locked upload/removal, concurrent-safe backfill (`edb5c8a`); existing-Auth-user validation via private hosted-compatible lookup; local two-user HTTP acceptance | Live two-account team acceptance |
| P2 — Quotas/cost | Atomic monthly admission, provider token/cost accounting, owner/member usage scope, USD display, uncertain-request recovery (`66e67e4`) | Reconcile attributed real OpenRouter charges; verify actual Auth/upload/chat/usage flow |
| P3 — Transcript | Owner-scoped persistence/reload, generation-aware sources, deletion/admission fence, worker retention recovery (`973778b`) | Install repository purge timer during rollout; resolve original soft-delete versus implemented physical “Chat mới” deletion contract |
| P4 — Admin/operations | Schema placeholders and readiness/logging foundation | Admin metadata-only APIs/UI, audit writers, durable failure summaries, lifecycle retry, workspace purge orchestration, Sentry, cost/latency/queue reports |
| P5 — Evaluation/optimization | Summary call cap and metering foundation | Golden set/evaluator/baseline, budgeted real-provider CI, exact cache/invalidation, routing, monetary request caps |

## Verified corrections

- P1: 348 backend cases and disposable Redis/Linux RQ checks.
- P3: 369 backend cases; Redis/Linux RQ; frontend typecheck/lint, 75 Vitest cases, 14 Playwright cases and production build.
- P2: 370 backend cases; frontend typecheck/lint, 99 Vitest cases and production build. 14 browser cases passed initially; the recovery case passed after its alert selector was scoped to the chat region.
- P0 (`fix/p0-runtime-boundaries`): 407 backend cases; real Redis rate-limit and Linux RQ checks (including retry correlation and persisted failure/log privacy); Docker build; production Compose validation; 15 Linux deployment/rollback and 6 certificate tests; Nginx TLS/upload/SSE/cancellation/rotation/recreation and privacy checks. Deployment fixtures use separate migration env and a disposable Postgres runtime role.
- P1 Auth follow-up (`fix/p1-auth-membership`): 455 backend cases passed on Mac, including 97 focused migration/workspace/readiness/team checks. Migration `0002` and no-op grants run as a non-superuser with Auth read/RLS bypass but no schema grant option. Tests cover upgrade from populated `0001`, private boolean lookup, missing/deleted users, duplicate/reactivation checks, authorization-before-lookup, denied direct Auth/Data API access, definer/grant fault detection and grant repair. Two-user HTTP tests use real Postgres/Redis/RQ and fixture Auth/PDF/vector/provider boundaries; synthetic costs and concurrent shared quotas are verified, not real provider billing.

## Release gates

1. Run local tests before touching VPS services. Real-provider acceptance uses attributable workspace/request/document/job IDs because Supabase/OpenRouter are shared.
2. Bootstrap the `doctrace_app` role, apply grants, and move DDL credentials into `.env.migrations` before enabling the new readiness gate. Follow `DEPLOYMENT.md`.
3. Backend `scope`/`costs`/nullable `remaining` support precedes the usage/recovery frontend. API and worker must share the transcript-deletion protocol.
4. Publish phase branches/PRs after GitHub CLI authentication. The correction stack is P1 → P3 → P2 → P0 → P1 Auth follow-up; these corrections have not yet been published.
5. Validate two real accounts, reload/new-chat behavior, recorded versus provider costs and purge scheduling before considering cloud acceptance complete.
