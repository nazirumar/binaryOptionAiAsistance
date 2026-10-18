# Chart Analysis Prompt v1

Explain the structured analysis produced by the engines for this screenshot.

Structure your response using only the fields supplied in the structured
context:

1. Direction: repeat the engine direction exactly (UP, DOWN, or NO TRADE).
2. Market context: describe the recorded market context state.
3. Strategy: name the detected strategy family, or state that none qualified.
4. Supporting evidence: list the supplied supporting evidence items.
5. Contradictory evidence: list the supplied contradictory evidence items.
6. Invalidation conditions: list the supplied invalidation conditions.
7. Timing: state the target candle interval and timing validity.
8. Probability: show the probability value only when calibration status is
   "calibrated"; otherwise show
   "Probability unavailable — model not calibrated."
9. Warnings: surface every supplied warning, including OTC feed
   incompatibility and expired opportunities.

Do not add observations that are not present in the supplied context.
