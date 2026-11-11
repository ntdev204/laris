# Proof and derivation template

```latex
\paragraph{Problem.} State what is derived or proven, in the stored notation.

\paragraph{Notation.} Symbols, frames, units (link to notation-and-conventions.md).

\paragraph{Assumptions.}
\begin{enumerate}[label=(A\arabic*)]
  \item ...  % e.g., no lateral tire slip; |\delta| < \delta_{\max} < \pi/2
\end{enumerate}

\paragraph{Derivation / Proof.}
Step 1: ...  \hfill (by definition / (A1) / Lemma 1 / algebra)
Step 2: ...  \hfill (justification)
...
\begin{equation}\boxed{ \text{result} } \label{eq:result}\end{equation}

\paragraph{Conditions of validity.} Where the result holds and where it breaks.

\paragraph{Checks.} Special cases, dimensions, symbolic/numeric verification and outcome.

\paragraph{Status.} Full proof | Sketch (missing: ...) | Unverified claim.
```

## Proof review checklist
- Is the statement precise (quantifiers, domains, norms)?
- Are all assumptions stated and actually used? Any used but not stated?
- Does each implication hold in the stated direction? Any circular use of the conclusion?
- Are cited results applied within their conditions (continuity, boundedness, uniform vs. pointwise)?
- Are constants and bounds independent of quantities they should not depend on?
- Discrete vs. continuous time mixed correctly? Sampling effects considered?
- Does the conclusion match the claim in the paper (e.g., asymptotic vs. exponential vs. practical stability)?

## Common pitfalls in vehicle modeling and control
- Reference point confusion (rear axle vs. CoG) changing the kinematic equations.
- Linearizing about a trajectory but treating the result as time-invariant.
- Forward Euler discretization presented as exact; stability of the discretized model not checked.
- Small-angle approximations used outside their stated range.
- Lyapunov function positive definite but derivative only negative semi-definite, with no invariance argument.
