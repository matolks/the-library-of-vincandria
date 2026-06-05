# Renderer Debt Backlog

## Phase 1 classification — 2026-06-05

Scope: DSA deferred plot/renderer/layout findings only. Evidence came from two targeted `judge.v5 --no-record` passes over the DSA topics that had deferred renderer-style findings in the current triage reports. No content, renderer code, or database writes were changed.

Reports:
- `reports/judge_dsa_renderer_phase1_pass1_*_20260605.json`
- `reports/judge_dsa_renderer_phase1_pass2_*_20260605.json`

### Systematic findings

These reproduced in both targeted passes with the same topic, category, and block ID.

| Topic ID | Finding category | Layer classification | Evidence |
| --- | --- | --- | --- |
| `dsa-linear-programming` | math/plot grouping: missing plot for feasible-region geometry | Generation-layer: Agent 3 describes a concrete 2D feasible region without emitting a companion `function2d` plot. | `missing_plot` on block `e474be61-0cbe-46d6-95d8-d0b02ac1a935` in both passes. |
| `dsa-binary-search` | renderer layout: missing group for equation interpretation | Generation-layer: adjacent math/explanation blocks are not grouped, so the renderer cannot present them as a coupled unit. | `missing_group` on block `9efbb7fb-b3f8-4469-bef5-1e15bdb5d6d6` in both passes. |
| `dsa-binary-search` | renderer layout: missing group for worked rotated-array example | Generation-layer: adjacent worked-example math/explanation blocks are not grouped, so the renderer cannot present them as a coupled unit. | `missing_group` on block `2da0bc4c-9b6b-448d-8407-f00041cb6536` in both passes. |

### Dropped as non-reproducible variance

These appeared in only one of the two targeted passes, or were present in an earlier triage report but did not reproduce across both Phase 1 passes. They are logged here and are not backlog items.

| Topic ID | Finding category | Phase 1 result |
| --- | --- | --- |
| `dsa-strassen` | renderer layout: `broken_plot_spec` for multi-expression `function2d` array | Non-reproducible; appeared in pass 1 only. |
| `dsa-horn-formulas` | renderer layout: `missing_group` around Horn formula / worked trace | Non-reproducible as the same finding; pass 1 and pass 2 pointed at different block IDs. |
| `dsa-topological-sort` | renderer layout: `missing_group` around complexity equation | Non-reproducible; appeared in pass 2 only. |
| `dsa-knapsack` | renderer layout: `missing_group` around worked-example paragraphs | Non-reproducible; appeared in pass 2 only. |
| `dsa-mst-theory` | renderer layout: `missing_group` around cut notation | Non-reproducible; appeared in pass 2 only. |
| `dsa-quicksort` | renderer layout: previous `missing_group` findings | Non-reproducible; did not appear in either Phase 1 targeted pass. |
| `dsa-heaps` | renderer layout: previous `missing_group` findings | Non-reproducible; did not appear as renderer/layout findings in either Phase 1 targeted pass. |
| `dsa-scc` | renderer layout: previous grouping/polish findings | Non-reproducible; did not appear as renderer/layout findings in either Phase 1 targeted pass. |

### Phase 1 readout

The Phase 1 renderer/layout debt signal is mostly variance: only three exact renderer/layout findings reproduced across both passes, and those are concentrated in two topics. A dedicated renderer pass is therefore smaller than previously assumed and should probably target generation-layer grouping/plot-emission rules narrowly rather than becoming a broad renderer-code batch.
