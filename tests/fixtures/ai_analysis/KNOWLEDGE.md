# tests/fixtures/ai_analysis/

Fourteen synthetic SQL/SAS scripts for offline validation and explicit live evaluation.
No imported source executes and normal tests make no provider calls.

- `expected.json` — Versioned case manifest, language/split and expected facts/abstentions.
- `evaluation_gold.json` — Independent scorer labels by operation/scope/version/role;
  not injected into prompts. Development tuning smoke is not holdout qualification.
- `join_alias.sql`, `unused_cte.sql`, `ambiguous.sql`, `wildcard.sql` — Ownership,
  reachability and unknown-schema negatives.
- `constant.sql`, `union.sql`, `same_line.sql`, `unknown_udf.sql` — Values, branches,
  exact coordinates and unsupported functions.
- `update.sql`, `merge.sql` — Bounded DML assignments beyond baseline derivations.
- `assignments.sas`, `proc.sas`, `runtime_macro.sas`, `temporary_jobs.sas` — Ordered
  variable versions, PROC SQL, dynamic abstention and job-local WORK identities.
