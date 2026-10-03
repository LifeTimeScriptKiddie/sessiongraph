# Plan: self-restoring and self-modifying SessionGraph

Status: plan, not built. Written 2026-10-03 from repository research by agentctl lanes (codex GPT Luna and cursor Composer), web research (agy Gemini), and local checks of every cited file and line.

## Goal

| Capability | Meaning here |
| --- | --- |
| **Self-restoring** | When a SessionGraph run, or a change it applied, goes wrong, it detects that from recorded facts and returns to the last known-good state without a person debugging it. |
| **Self-modifying** | SessionGraph proposes changes to its own detector parameters (later, its code) and to the harness settings it recommends. It tests each change and keeps it or rolls it back on evidence it computes itself. |

Both follow the project rule in [VERIFY.md](VERIFY.md): code computes the verdict, heuristics are verified before they act, and nothing reaches `main` or a remote without the human.

## Lessons from prior art

| Source | What it shows | What SessionGraph copies |
| --- | --- | --- |
| Darwin Gödel Machine ([arXiv:2505.22954](https://arxiv.org/abs/2505.22954)) | Keeps an archive of agent versions and validates each change on benchmarks, sandboxed with human oversight. The paper body (not re-checked here) reports a candidate that removed the markers its hallucination check relied on, faking a perfect score. | The judge and its inputs sit outside what a candidate can edit. Every generation is archived. |
| SICA ([arXiv:2504.15228](https://arxiv.org/abs/2504.15228)), STOP ([arXiv:2310.02304](https://arxiv.org/abs/2310.02304)) | Self-edits are scored on fixed tasks, with unseen instances to resist overfitting. | Tune on one slice of sessions and judge on a held-out slice. |
| AlphaEvolve ([DeepMind](https://deepmind.google/discover/blog/alphaevolve-a-coding-agent-for-scientific-and-algorithmic-discovery/)) | Correctness gates run before any score is compared. | Two-stage gate: invariants first, metrics second. |
| Argo Rollouts ([docs](https://argoproj.github.io/argo-rollouts/features/analysis/)), Flagger ([docs](https://docs.flagger.app/usage/metrics)), Kayenta ([repo](https://github.com/spinnaker/kayenta)) | A metric gate with a declared success condition and failure limit triggers rollback automatically. | A verdict must be acted on, not just printed. |
| A/B slots ([AOSP](https://source.android.com/docs/core/ota/ab)), symlink swap ([Deployer](https://deployer.org/docs/7.x/avoid-downtime-deploy)), Nix generations ([manual](https://nixos.org/manual/nixos/stable/#sec-rolling-back)) | Each state is an immutable generation; activation and rollback only move a pointer. | Generations plus an atomic `current` pointer and a last-known-good one. |
| Wilson intervals ([Brown, Cai, DasGupta 2001](https://projecteuclid.org/journals/statistical-science/volume-16/issue-2/Interval-Estimation-for-a-Binomial-Proportion/10.1214/ss/1009213286.full)); always-valid tests ([Johari et al.](https://arxiv.org/abs/1510.07600)) | Point comparisons on small samples keep bad changes. Intervals and replication control that risk. | A three-way verdict: keep, roll back, or insufficient. |

The agy summaries add mechanisms beyond these primary claims. Treat them as design ideas, not facts about those systems. Cursor's statistics URLs were cited from memory, because its web access was blocked.

## Where things stand (checked 2026-10-03)

| Fact | Evidence |
| --- | --- |
| Verdicts are computed but never acted on | `~/.agentctl/bin/graph-weekly.sh:25-26` runs `workflows-compare … \|\| true` |
| The nightly job never compares | `agentctl/dev/src/memory/sessiongraphNightly.ts` exports, analyzes and suggests only; it is absent on `current` |
| agentctl's keep test is the weak one | `current/src/graph/improve.ts:290-293` uses mean health and finding counts, not `check_delta` |
| Keep decisions are point comparisons with 5 requests per side | `worth_it.py` `compare()`; `THRESHOLDS["min_requests"] = 5` |
| A protected-files list exists | `current/src/graph/command.ts:62` `PROTECTED_PATHS`, enforced by `protectedTouched()` |
| Code proposals are written by an LLM on a branch | `current/src/graph/command.ts:189` `startJob({ kind: 'orchestrate' … })` |
| Wilson interval code exists | `current/src/graph/harness.ts:281` `wilson95()` |
| Settings rollback exists only for routing preferences | `agentctl tune --rollback` |
| Detector parameters are hard-coded | `analyze.py:80` `_repeated(minimum=3, window=8)`; `verify.py:243` `_same_tool_failing(minimum=3)` |
| Real example of a noisy verdict | 2026-10-03, `lookups-low-effort`: median tokens 627 → 1,044 on 62 → 17 requests; "roll back or collect more runs" |

## Phases

Each phase ends with a yes/no exit check. Do them in order; a later phase relies on the earlier ones.

### Phase 0. Seal the judge

The judge is the code that decides keep or roll back. If a candidate can edit the judge, every later gate is worthless (the DGM lesson).

1. Write a sealed manifest, `sessiongraph/sealed.json`, with the SHA-256 of each sealed file:
   - `verify.py`: thresholds, label rules, outcome rule
   - `scorecard.py`: gates
   - `worth_it.py` compare logic
   - `analyze.py`: the `CHECKS` table and its basis
   - `suggest.py`: `trusted()` and `VERIFIED_HEURISTICS`
   - `pipeline.py`
   - the parameter bounds module (Phase 3)
2. Every command that judges or activates checks the manifest first, and fails closed on a mismatch.
3. Add the agentctl graph files that judge (`improve.ts`, `harness.ts`, `sessiongraphBridge.ts`, `workflows.ts`, the new policy file) to `PROTECTED_PATHS`.
4. Only a human-reviewed commit may change the manifest.

**Exit check:** editing any sealed file without updating the manifest makes `analyze`, `verify-*`, `scorecard` and `workflows-compare` exit non-zero. A `graph apply` proposal that touches a sealed path is rejected.

### Phase 1. Self-restoring

1. **Generations.** Each active state is an immutable directory under `~/.agentctl/sessiongraph/generations/<id>/`. It holds detector parameters, recommended settings, the manifest hash and an evaluation record. `current` and `last-good` are pointers, moved with an atomic rename. Old generations are never overwritten.
2. **Atomic runs.** A run writes to a staging directory. It is published (the `latest` pointer moves) only after the schema, every declared output file and every output hash check out. A failed run leaves the previous published run in place.
3. **Act on the verdict.**
   - Replace `|| true` in `graph-weekly.sh` with exit-code handling: 0 = keep, 1 = roll back, 2 = insufficient, other = error.
   - Roll back means moving `current` back to `last-good`, then checking that the restored hash matches.
   - Only reversible states are rolled back automatically: generations and settings recorded at activation. Branches are discarded only if unmerged. `main` and remotes are never touched.
   - A rollback the system can't perform, such as a settings change made outside a generation, emits `rollback_required` for the human.
4. **Nightly closes the loop.** `sessiongraphNightly.ts` runs compare after analyze and records the verdict and any rollback.
5. **Don't move the baseline after a failure.** A rolled-back or failed comparison never becomes the new baseline.

**Exit checks:**
- A forced bad generation is rolled back by the next weekly run with no human step.
- A crash in the middle of a run leaves `latest` on the previous run.
- A tampered `current` file is detected by its hash and restored.

### Phase 2. Honest verdicts on small samples

This phase is needed before anything self-modifies. On today's data volumes, point comparisons flip-flop.

1. **Proportions** (error rates, guards):
   - Use a Wilson non-inferiority test with δ = 3 percentage points and at least 20 requests per window.
   - Keep: the metric moved the right way, and the upper Wilson bound after the change is at most the upper bound before it, plus δ.
   - Roll back: the lower bound after the change is above the upper bound before it.
2. **Medians** (token counts): keep only if the metric holds in 2 separate windows, each with at least 20 requests. A single window can't keep a change.
3. **Three-way exit code:** 0 keep, 1 roll back, 2 insufficient.
   - Insufficient means hold: the change stays active and is re-checked next week.
   - A metric that improves while its guard is undecided is insufficient. It is never kept.
4. **One keep test everywhere.** `workflows-compare`, `scorecard` and agentctl `graph compare` use the same rules. `compareAnalyses` adopts `check_delta` and `no_worse_checks`.
5. **Don't judge a change on data it influenced.** Each change records its activation time, and the evaluation window starts after it. Missing provenance means no keep.

**Exit checks:**
- Replaying the 2026-10-03 `lookups-low-effort` data returns insufficient (exit 2), not roll back.
- A synthetic clear regression returns roll back.
- No keep is possible with fewer than 20 requests per window.

### Phase 3. Self-modifying, numbers only

The first self-modification tunes numbers within sealed bounds, not code.

1. **Tunable parameters:** `repeated_action.minimum` (3-5), `repeated_action.window` (6-12), `same_tool_failing.minimum` (3-5).
   - The bounds are hard-coded in the sealed module. The parameter file can't widen them.
   - Everything in the Phase 0 manifest is not tunable.
2. **Search:** a deterministic grid within bounds, at most 63 candidates.
3. **Split:** group by transcript and sort by time. The earliest 70% is for tuning and the latest 30% is held out. Require at least 4 groups, or stop.
4. **Accept a candidate only if all of these hold:**
   - It strictly beats the active parameters on the tuning slice.
   - On the held-out slice, every detector it changes passes the sealed verifier: `verify-outcomes` predictive, or `verify-detectors` verified.
   - `no_worse_checks` passes on identical held-out traces.
   - The Phase 2 verdict is keep.
5. **Activation:** the candidate becomes a new generation (Phase 1). The next real window re-checks it, and a roll-back verdict restores `last-good` automatically.
6. **New command:** `sessiongraph tune-detectors [--apply]`, run weekly after compare. Exit 1 (candidate rejected) is a normal outcome, not a job failure.

**Exit checks:**
- The tuner can't change a sealed value.
- A candidate that only does well on the tuning slice is rejected.
- Every activation has a complete evaluation record.
- Rollback restores the exact previous hash.

### Phase 4. Self-modifying code (later, optional)

1. `graph apply` keeps its current role: an LLM writes a proposed change on a branch. It proposes; it never judges.
2. **Gate, in order:** sealed-manifest unchanged → tests pass → invariant replays pass (stage one) → Phase 2 keep on held-out data (stage two).
3. The human merges. Self-modification never merges or pushes.
4. **Start condition:** Phase 3 has kept at least one change that survived a later re-check. Without that, there is no evidence that the gates can tell good from bad.

## Failure modes and guards

| Failure | Guard |
| --- | --- |
| The candidate weakens the judge or its inputs | Phase 0 manifest and `PROTECTED_PATHS`; judge files sealed |
| Goodhart: hiding findings to score better | `no_worse_checks` on recorded checks; held-out verification; finding counts are never the metric |
| A lucky small sample keeps a bad change | Wilson non-inferiority, n ≥ 20, two windows, insufficient = hold |
| A change is judged on data it influenced | Activation timestamp; evaluation only after it; time-ordered holdout |
| A crash or partial run is published | Staging, hash check, then an atomic pointer move |
| A rollback damages the known-good state | Immutable generations; rollback moves pointers only |
| Agent-written ground truth | Unchanged rule: only human labels for intent; outcomes for behavior |
| Self-modification spreads beyond reversible state | Auto-rollback covers generations and recorded settings only; anything else emits `rollback_required` |

## What to expect

With about 400 requests per two weeks and about 5% going badly, most weekly verdicts will be **insufficient**. That's correct behavior, not a defect. A healthy self-modifying system mostly rejects its own proposals. A run of keeps is a signal to audit the gates, not a success.

## Decisions for the human

1. Where generations live. Proposed: `~/.agentctl/sessiongraph/` (outside any repo).
2. Whether the weekly job may roll back recommended settings automatically, or only report `rollback_required`.
3. Whether δ = 3 points and n ≥ 20 are acceptable, knowing they make keeps rare at current volumes.
