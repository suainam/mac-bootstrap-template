# Evaluation

Test one causal claim: after handbook cleanup, a fresh Agent finds the correct authority faster with fewer tokens.

Compare the same repository and task before and after the accepted handbook. Hold model, reasoning, permissions, and tools constant. Use fresh sessions.

Judge only:

1. correct target found;
2. total input/output tokens;
3. wall-clock time.

Accept only when treatment stays correct and improves both token and time. Record other observations without using them for acceptance. Do not claim general effectiveness from one case.

Start with one causal A/B; add cases only after it works. Add no metric unless it changes the decision. Next, repeat the same test on one real repository before generalizing.
