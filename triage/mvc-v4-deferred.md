# MVC judge.v4 triage — deferred findings

Scanned: 21 high-severity findings post-rerun (chain-rule + parametric).

## Acted on
- mvc-quadric-surfaces: regenerated (prompt now has one-sheet hyperboloid rule, line 102). Expected to clear 5 high findings (2 factual + 3 missing_plot).

## Deferred to admin editor or future judge run
### Compliance gap, not rule gap — log for cross-course comparison
- missing_plot cluster: 13 findings across 9 topics. Rules exist (prompt.py lines 90–96) and are explicit; agent3 underemits. Re-evaluate after numerical-computation run to determine if MVC-specific or general agent3 behavior.

### Real but isolated content bugs
- mvc-limits-continuity: algebraic manipulation error in absolute-value bound
- mvc-motion-3d: "upward acceleration" claim is physically wrong
- mvc-tangent-planes: c_0 notation collision with level-set constant c
- mvc-chain-rule (rerun): 2 high findings, descriptions self-refute on headline claim — likely judge FPs

### Judge.v5 candidate pattern (do NOT cut until num-comp confirms)
- Judge marks "factual_error / high" then states "is correct" in description. Seen in: arc-length, chain-rule ×2. Rule for v5: suppress or downgrade when description self-refutes.
