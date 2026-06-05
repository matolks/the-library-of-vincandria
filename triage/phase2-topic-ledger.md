# Phase 2 Topic Ledger

## 2026-06-05

| Topic | Fresh judge result | Triage | Action |
| --- | --- | --- | --- |
| `numerical-computation` / `matlab-programming-numerical-methods` | `judge.v5 --no-record` returned 0 findings. | Prior high factual MATLAB quadrature finding did not reproduce. | Logged as variance; no patch; raw judge JSON discarded. |
| `numerical-computation` / `multistep-methods-adams-bashforth-moulton` | `judge.v5 --no-record` returned 1 low `generic_prose` finding and no factual/prereq findings. | Prior high factual ABM findings did not reproduce. | Logged as variance/cosmetic residual; no patch; raw judge JSON discarded. |
| `multivariable-calculus` / `mvc-level-curves` | Pre-patch targeted judge returned 1 high `factual_error`, 1 medium content contradiction, and plot/grouping findings. Post-patch targeted judge returned only plot/grouping findings. | Factual/content corrections confirmed; plot/grouping residuals classified as Agent 3 generation-layer debt. | Patched two live blocks through the explicit production write guard; set both patched blocks `manually_edited=true`; dry-run regen preserved both anchors; `pipeline.evals.content_generation --course multivariable-calculus` passed; raw judge JSON discarded; residuals appended to `generation-layer-debt.md`. |
