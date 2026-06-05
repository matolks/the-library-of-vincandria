# Agent 3 Generation-Layer Debt Backlog

## Phase 1 classification — 2026-06-05

Scope: DSA deferred plot/grouping findings only. Evidence came from two targeted `judge.v5 --no-record` passes over the DSA topics that had deferred generation-layer plot/grouping findings in the current triage reports. No content, renderer code, or database writes were changed.

Reports:
- `reports/judge_dsa_renderer_phase1_pass1_*_20260605.json`
- `reports/judge_dsa_renderer_phase1_pass2_*_20260605.json`

### Systematic findings

These reproduced in both targeted passes with the same topic, category, and block ID.

| Topic ID | Finding category | Layer classification | Evidence |
| --- | --- | --- | --- |
| `dsa-linear-programming` | math/plot grouping: missing plot for feasible-region geometry | Generation-layer: Agent 3 describes a concrete 2D feasible region without emitting a companion `function2d` plot. | `missing_plot` on block `e474be61-0cbe-46d6-95d8-d0b02ac1a935` in both passes. |
| `dsa-binary-search` | generation grouping: missing group for equation interpretation | Generation-layer: adjacent math/explanation blocks are not grouped, so the renderer cannot present them as a coupled unit. | `missing_group` on block `9efbb7fb-b3f8-4469-bef5-1e15bdb5d6d6` in both passes. |
| `dsa-binary-search` | generation grouping: missing group for worked rotated-array example | Generation-layer: adjacent worked-example math/explanation blocks are not grouped, so the renderer cannot present them as a coupled unit. | `missing_group` on block `2da0bc4c-9b6b-448d-8407-f00041cb6536` in both passes. |

### Dropped as non-reproducible variance

These appeared in only one of the two targeted passes, or were present in an earlier triage report but did not reproduce across both Phase 1 passes. They are logged here and are not backlog items.

| Topic ID | Finding category | Phase 1 result |
| --- | --- | --- |
| `dsa-strassen` | generation plot spec: `broken_plot_spec` for multi-expression `function2d` array | Non-reproducible; appeared in pass 1 only. |
| `dsa-horn-formulas` | generation grouping: `missing_group` around Horn formula / worked trace | Non-reproducible as the same finding; pass 1 and pass 2 pointed at different block IDs. |
| `dsa-topological-sort` | generation grouping: `missing_group` around complexity equation | Non-reproducible; appeared in pass 2 only. |
| `dsa-knapsack` | generation grouping: `missing_group` around worked-example paragraphs | Non-reproducible; appeared in pass 2 only. |
| `dsa-mst-theory` | generation grouping: `missing_group` around cut notation | Non-reproducible; appeared in pass 2 only. |
| `dsa-quicksort` | generation grouping: previous `missing_group` findings | Non-reproducible; did not appear in either Phase 1 targeted pass. |
| `dsa-heaps` | generation grouping: previous `missing_group` findings | Non-reproducible; did not appear as plot/grouping findings in either Phase 1 targeted pass. |
| `dsa-scc` | generation grouping: previous grouping/polish findings | Non-reproducible; did not appear as plot/grouping findings in either Phase 1 targeted pass. |

### Phase 1 readout

The Phase 1 plot/grouping debt signal is mostly variance: only three exact findings reproduced across both passes, and those are concentrated in two topics. A dedicated pass is therefore smaller than previously assumed and should target generation-layer grouping/plot-emission rules narrowly rather than becoming a renderer-code batch.

## Phase 2 probe — 2026-06-05

Scope: topic-level factual/prereq remediation loop. Plot/grouping findings were observed only as side-channel evidence while validating `mvc-level-curves`; no renderer code, generator prompt, or non-factual block edits were made for these items.

### Promoted generation-layer signals

These findings recurred on a new plot/grouping-heavy topic after the DSA Phase 1 backlog, so they should be treated as evidence for a future generation-layer plot/grouping fix rather than topic-local one-offs.

| Topic ID | Finding category | Layer classification | Evidence |
| --- | --- | --- | --- |
| `mvc-level-curves` | math/plot grouping: missing contour-map plot for circular level curves | Generation-layer: Agent 3 describes a 2D contour map but emits only a `surface3d` plot of the paraboloid. | `missing_plot` on block `72f6260f-c438-4d5b-99c0-b5dfaafb0c3d` in the post-patch targeted `judge.v5 --no-record` pass. |
| `mvc-level-curves` | generation grouping: missing group for surface plot and interpretation paragraph | Generation-layer: adjacent plot/explanation blocks are not grouped, so the renderer cannot present them as a coupled unit. | `missing_group` on block `bb795f16-f552-4308-b8b8-941a105175f2` in the post-patch targeted `judge.v5 --no-record` pass. |
| `mvc-level-curves` | generation grouping: missing group for equation and interpretation paragraph | Generation-layer: adjacent math/explanation blocks are not grouped, so the renderer cannot present them as a coupled unit. | `missing_group` on block `ba749ec7-c90a-4977-ab60-02fd5619a423` in the post-patch targeted `judge.v5 --no-record` pass. |

### Phase 2 readout

This probe promotes plot emission and math/plot grouping from isolated DSA one-offs to plausible generation-layer behavior worth fixing in a dedicated pass. It does not justify inline remediation during factual/prereq cleanup, and no cosmetic judge-count-chasing was done here.
