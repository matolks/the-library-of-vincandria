# Agent 3 v5 Pre-Rerun Audit

Date: 2026-06-02

## Provenance Gate

Current stored generated blocks for the three baseline courses are not `agent3.v2` or older. All generated blocks in the DB report `generation_metadata.prompt_version = agent3.v4` and `model = claude-sonnet-4-6`.

| Course | Generated blocks | Prompt version | Generated-at range |
| --- | ---: | --- | --- |
| multivariable-calculus | 1081 | agent3.v4 | 2026-05-31T22:52:00Z to 2026-06-02T12:42:34Z |
| numerical-computation | 1424 | agent3.v4 | 2026-06-01T00:19:43Z to 2026-06-01T01:41:40Z |
| data-structures-and-algorithms | 1691 | agent3.v4 | 2026-06-01T02:00:05Z to 2026-06-01T03:55:54Z |

Git history agrees with this: `agent3.v4` landed in `63a1d2e` and was then adjusted in `810fa45`; later generation-related changes landed in `07454a7` and `1ae27e9`.

Decision for steps 9 and 16: do not run an `agent3.v2`/older provenance refresh. The current v5 judge reports are already judging `agent3.v4` content, so the next generator pass should be a forward bump (`agent3.v5`), not the originally drafted `agent3.v3`.

## v5 Judge Baseline

| Course | Report | Findings | Main categories |
| --- | --- | ---: | --- |
| MVC | `reports/judge_multivariable-calculus_v5_20260602.json` | 45 | 21 missing_group, 9 confusing_transition, 8 missing_plot, 4 factual_error, 2 generic_prose, 1 broken_plot_spec |
| Numerical | `reports/judge_numerical-computation_v5_20260602.json` | 66 | 25 missing_group, 24 factual_error, 6 confusing_transition, 5 generic_prose, 3 missing_plot, 3 broken_plot_spec |
| DSA | `reports/judge_data-structures-and-algorithms_v5_20260602.json` | 47 | 21 factual_error, 18 missing_group, 4 confusing_transition, 2 generic_prose, 2 missing_plot |

## Noise Spot-Check

Missing group sample: 10 findings across MVC, numerical, and DSA. Result: 9 real or materially actionable, 1 lower-confidence but not judge-bogus (`mvc-quadric-surfaces` intro paragraph plus cylinder bullets). Noise rate is about 10%, below the 30% gate. No `missing_group` judge restraint is needed before Agent 3 tuning.

Generic prose sample: 6 findings. Result: mixed. Four are actionable boilerplate or generic motivation; two are harsher/borderline because the block also contains some concrete preview. Treat this as a prompt nudge, not a broad judge or generator overcorrection.

Confusing transition sample: 6 findings. Result: 6 real. Patterns include false-start derivations, unexplained variable/index changes, unrelated example transitions, and missing intermediate computation steps.

## Source-ID Hallucination Baseline

Validator scan against current stored blocks:

| Course | Bad blocks | Generated blocks | Notes |
| --- | ---: | ---: | --- |
| multivariable-calculus | 4 | 1081 | All in `mvc-quadric-surfaces`; invalid IDs include stale/non-course chunk IDs |
| numerical-computation | 0 | 1424 | Clean |
| data-structures-and-algorithms | 0 | 1691 | Clean |

The new `strip_invalid_source_ids` helper now drops invalid IDs immediately after LLM parse and logs each drop with topic/block context.

## Group Schema

`Block.group_id` is a nullable string with indexes on `group_id` and `(topicId, group_id)`. It is not a foreign key and there is no containment object/table. Rendering currently consumes a flat ordered block stream; grouping is a threaded label used by the pipeline/reconciler for cohort preservation rather than a structural container.

Decision: use generalized prompt criteria first. If `agent3.v5` still misses obvious cohorts after rejudge, escalate to a post-generation label pass. A containment schema is not justified yet because the app and persistence model are flat.

## Structured JSON Check

Local SDK: `anthropic==0.105.2`.

`messages.create` supports both `tools`/`tool_choice` and `output_config`. `OutputConfigParam` supports `format: { type: "json_schema", schema: ... }`, so `llm.py` can force structural JSON.

Applied follow-up: `output_config` was attempted first but Anthropic rejected the full BlockNote schema as too constrained/complex for response-grammar compilation. Agent 3 now uses forced tool use (`emit_blocks`) for routed structured topics instead. The setting is included in `agent3_generation_config`, persisted in generated block metadata as `structured_json`, and covered by the context fingerprint. CLI overrides: `--structured-json` and `--no-structured-json`.

## Agent 3 Change Draft Applied

Prompt version bumped from `agent3.v4` to `agent3.v5`.

Applied changes:

- Course-agnostic system prompt wording.
- Explicit valid source chunk ID list in the user prompt.
- Prompt instruction to use only exact listed chunk IDs.
- Generalized grouping criteria with per-domain anchors:
  - math: formula plus interpretation, plot plus explanation, worked-example computation chains
  - algorithms: pseudocode plus complexity, trace plus invariant, theorem/recurrence plus interpretation
  - numerical: algorithm/formula plus error analysis, code/tableau plus readout, worked-step computations
- Transition quality instruction for boilerplate openers, false-start derivations, and unrelated example jumps.

Next gate: dry-run smoke topics under `agent3.v5`, then eyeball grouping, source IDs, and JSON stability before scaling.

## Agent 3 v5 Dry-Run Smoke

All smoke runs were dry-run only; no blocks were persisted.

| Course | Topic | Status | Attempts | Blocks | Validation |
| --- | --- | ---: | ---: | ---: | --- |
| MVC | `mvc-dot-product` | ok | 1 | 46 | clean |
| Numerical | `matlab-programming-numerical-methods` | ok | 1 | 54 | clean |
| DSA | `dsa-binary-search` | ok | 1 | 45 | clean after stripping invalid source IDs |
| DSA preview | `dsa-binary-search` | ok | 1 | 50 | clean with generated block preview |

DSA source-ID backstop proof: `dsa-binary-search` dry-run emitted invalid `source_chunk_id='6c40f033-c388-4133-b1bd-e4e846da5ad4'` in eight generated blocks. `strip_invalid_source_ids` logged each drop and validation passed after removal.

Preview eyeball: `--include-preview` confirmed JSON held on a code/pseudocode-heavy topic and source IDs remained valid in the preview pass. The output used concrete binary-search variants and avoided false-start prose. Grouping improved for formula-plus-interpretation (`complexity-summary`) and one fixed-point derivation, but code/pseudocode blocks were not consistently grouped with their immediately following invariant/correctness explanations. The prompt was tightened again for this specific DSA grouping pattern before any broad regeneration.

Structured JSON follow-up smoke: forced tool mode passed on `dsa-binary-search` with `structured_json: true` in generated metadata, status `ok`, one attempt, 53 blocks, and no validation errors. Eyeball result: structural JSON is solved for code-heavy output, but codeBlock + explanation grouping is still the main thing to watch before broad DSA regeneration. The prompt now explicitly says not to insert a heading between algorithm code and its invariant/correctness/runtime explanation.

Post-nudge preview: rerunning `dsa-binary-search` after the explicit algorithm-code rule produced same-`group_id` code + explanation pairs for the main binary search (`g-bsearch-code`), peak search (`g-peak-code`), and rotation search (`g-rot-code`). One typo-like invalid source id (`6c40foszf-c388-4133-b1bd-e4e846da5ad4`) was dropped and logged by `strip_invalid_source_ids`; validation still passed. This is enough smoke evidence to scale the prompt/tooling, subject to the production-write gate below.

## Selective Regeneration Scope

Topics with at least one `missing_group`, `generic_prose`, or `confusing_transition` finding in the v5 reports:

| Course | Affected topics |
| --- | --- |
| MVC | `mvc-quadric-surfaces`, `mvc-dot-product`, `mvc-lines-planes-3d`, `mvc-parametric-curves`, `mvc-arc-length`, `mvc-motion-3d`, `mvc-level-curves`, `mvc-limits-continuity`, `mvc-partial-derivatives`, `mvc-tangent-planes`, `mvc-chain-rule`, `mvc-optimization`, `mvc-lagrange-multipliers`, `mvc-double-integrals` |
| Numerical | `number-base-conversion-floating-point`, `matlab-programming-numerical-methods`, `spline-interpolation`, `romberg-richardson-extrapolation`, `fixed-point-iteration`, `newtons-method`, `secant-method`, `tridiagonal-banded-systems`, `iterative-methods-linear-systems`, `multistep-methods-adams-bashforth-moulton`, `systems-odes-higher-order`, `two-point-bvp-shooting-methods`, `finite-difference-bvp-1d`, `finite-difference-elliptic-pde-2d`, `finite-difference-heat-equation` |
| DSA | `dsa-asymptotic-notation`, `dsa-divide-and-conquer-recurrences`, `dsa-strassen`, `dsa-bellman-ford`, `dsa-max-flow`, `dsa-rna-secondary-structure`, `dsa-greedy-interval-scheduling`, `dsa-horn-formulas`, `dsa-kruskal`, `dsa-mst-theory`, `dsa-union-find`, `dsa-linear-programming`, `dsa-graph-modeling` |

Production-write gate: `pipeline.db_guard` refuses writes because the active connection resolves to the known production ref `dkqlxidjhydrlddryjxw`. Even `PIPELINE_DB_TARGET=dev` is rejected. Persisted regeneration therefore requires an explicit production-write invocation such as `PIPELINE_DB_TARGET=prod PIPELINE_ALLOW_PROD_WRITES=1 ...`; until then, only dry runs and report-only judging should run.
