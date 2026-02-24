# Phase 1 Invariants (Pipeline-Generic)

These invariants define the **universal correctness rules** for Seedpipe Phase 1.
They are the non-negotiables that every agent, stage, and tool must preserve.

---

## Determinism & Reproducibility

1. **Deterministic builds**  
   Same `(inputs, manifest/config, code_version)` ⇒ same **artifact hashes**.

2. **Explicit precedence is deterministic**  
   Configuration resolution order is fixed and testable (e.g., `CLI override > manifest > defaults`), and invalid overrides fail closed (e.g., empty/whitespace override is an error).

3. **Stable identifiers**  
   `item_id`, `stage_id`, `run_id`, and schema versions are stable and never repurposed.

4. **No hidden ambient inputs**  
   Outputs must not depend on machine-local state (cwd, locale, timezone, hostnames), nondeterministic iteration order, or unpinned external resources—unless explicitly declared as an input.

---

## Immutability & Content Addressing

5. **Write-once stage outputs**  
   Stage outputs are immutable: once published, they are never modified in-place.

6. **Content-addressed artifacts**  
   Every artifact has a verifiable integrity identity (hash/etag) and may be safely cached/deduped.

7. **Append-only state logs**  
   Mutable “state” is expressed as append-only events (or versioned snapshots), never silent mutation of historical records.

---

## Resume Safety & Idempotency

8. **Resume is safe**  
   A restart cannot corrupt prior valid artifacts; at worst, it recomputes or advances safely.

9. **Idempotent stage execution**  
   Each stage is idempotent under a stable key, e.g.  
   `(run_id, stage_id, item_id, attempt)` ⇒ either (a) reuses prior result or (b) produces an equivalent result without duplication/corruption.

10. **Crash consistency**  
   Partial writes cannot masquerade as completed work. Completion must be atomic (e.g., temp + rename, commit marker).

11. **Exactly-one “commit point” per stage/item**  
   For a given stage+item execution, there is a single authoritative commit marker; multiple conflicting commits are invalid and must be detected.

---

## State Machines & Valid Transitions

12. **State transitions are validated**  
   Item state changes must be valid per an explicit state machine (no illegal jumps, no implicit transitions).

13. **No out-of-order mutation**  
   A stage may only mutate state after required prerequisites are proven satisfied (e.g., “candidate set validated” before “review_in_progress”).

14. **Canonical sources of truth are explicit**  
   For each decision domain (e.g., “which items are reviewable”), there is exactly one declared canonical artifact, and all downstream stages derive from it.

---

## Contracts, Schemas, and Validation

15. **Every artifact validates against a contract schema**  
   Each artifact has a declared schema/version; producers must emit valid artifacts; consumers must validate before use.

16. **Schema evolution is versioned and compatible by policy**  
   Breaking changes require a version bump and explicit migration strategy (no silent shape drift).

17. **Error handling is contract-preserving**  
   Failures must not produce “valid-looking” but semantically broken artifacts; invalid outputs must be unambiguously invalid.

---

## Isolation, Concurrency, and Locking

18. **Isolation of runs**  
   Two runs cannot overwrite each other’s artifacts. Shared caches are read-only or content-addressed and safe under concurrency.

19. **Locks are advisory + verifiable**  
   If locks exist, they must be (a) attributable (include run_id/owner), (b) refreshable/heartbeated if needed, and (c) safely reclaimable via a stale policy—without risking double-commit.

---

## Observability & Auditability

20. **Every execution is auditable**  
   For each stage+item, the system records: inputs’ hashes, config hash, code_version, start/end timestamps (always in UTC), status, and produced artifact hashes—sufficient to reproduce and debug. Any time-step markers, if present, are also recorded in UTC.
