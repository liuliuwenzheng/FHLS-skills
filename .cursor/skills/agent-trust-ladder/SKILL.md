---
name: agent-trust-ladder
description: >-
  use this when correcting an agent’s repeated mistakes, deciding whether to
  spawn many agents/PRs, hardening a repo for agent work, or designing
  verification so quality rises without babysitting
---
# Agent trust ladder

Goal: raise trust in agent work so you can parallelize safely. Do not scale agents until the environment earns trust.

Analogy: a Michelin kitchen, not a factory line — you still own the plate; cooks only work well if mise en place, tools, and standards are solid.

## When you correct an agent

Ask: *where is the cheapest permanent fix?* Invest in this order (hardest / most reliable first):

1. **Make the bad pattern impossible** — architecture, types, data structures, APIs, invariants. Prefer designs where the mistake cannot compile or cannot be expressed.
2. **Static analysis** — linters, typechecks, CI gates, curated deny-lists. If the same mistake recurs, encode it as a failing check.
3. **Rules / review bots / skills** — last layer. Useful, but easiest to skip or ignore. Keep them short and specific; do not rely on them alone.

Never stop at a one-off chat correction if the same class of error will happen again.

## Verification before volume

Correctness = does it do the intended thing. Build **verification** (control) skills that:

- run the app or critical path the way a user would
- collect evidence (traces, screenshots, test output, metrics)
- map coverage of features so gaps are visible
- fail closed when evidence is missing

Pair verification with **quality** playbooks (how a careful engineer would design, review, refactor). Verification alone is not craft; craft alone is not proof.

Do not spawn large batches of sub-agents or cloud agents when trust is low — you will only multiply babysitting.

## Codebase as agent memory

Agents extend patterns they see.

- Good conventions spread — invest in clear, boring, consistent code.
- Workarounds and “temporary” hacks also spread like a virus. Delete or encapsulate them; do not leave copy-pasteable excuses in-tree.
- Prefer a codebase that feels locked-down for humans but **safe by default** for low-context pilots (designers, PMs, busy owners).

### Comments caution

Agents often treat nearby comments as licenses to bypass rules. Prefer types, tests, and lints over narrative comments that explain how to cheat. If a comment is the only guardrail, move the rule into an enforceable check.

## Compounding stack

Keep these aligned so they reinforce each other:

- codebase shape (impossible states)
- static gates (CI / lint / types)
- rules and review bots
- skills (verification + quality playbooks)
- outer-loop automations (events → agents → PRs) that **reuse** the same gates

When all layers agree, agents can run with less supervision; when they conflict, fix the lower layer first.

## Checklist (end of a correction)

- [ ] Named the failure mode in one sentence
- [ ] Chose the lowest layer that permanently prevents it (1 → 2 → 3)
- [ ] Added or tightened a check that fails without human memory
- [ ] Removed or isolated any copy-pasteable anti-pattern
- [ ] Only then consider more parallelism
