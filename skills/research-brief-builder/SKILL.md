---
description: Builds precise research briefs through adversarial user interviews
---

# Research Brief Builder

Last updated: 2026-03-05 14:58 CET

Knowledge pack for constructing high-quality research briefs for the Gemini Deep Research Agent.

## Brief Quality Checklist

- [ ] Question is falsifiable (can be proven wrong)
- [ ] Scope has explicit boundaries (time, domain, geography)
- [ ] At least 1 hypothesis to test
- [ ] Known context documented (avoid rediscovery)
- [ ] Output format specified (audience, structure)
- [ ] Exclusions listed
- [ ] Cost acknowledged ($2-5 per run)

## Anti-patterns

- "Research everything about X" -- Too broad, will get generic results
- No hypotheses -- Research has no direction, agent wanders
- No exclusions -- $5 spent rediscovering what user already knows
- No format spec -- Get a wall of text instead of actionable output
- Vague scope -- "recent" means different things to different people

## Challenge Templates

- "Your question assumes X -- is that actually true?"
- "This could mean A or B -- which one matters for your decision?"
- "You said you want 'comprehensive' but also 'quick' -- pick one."
- "What would make this research WORTHLESS to you?"
- "What's the actual decision this research needs to inform?"
- "What finding would CHANGE your mind about this?"

## Brief Template

```
RESEARCH BRIEF
==============
Question: <precise, falsifiable research question>
Scope: <time period, domains, geography, depth>
Hypotheses to test: <H1, H2, ...>
Known context: <what we already know>
Output format: <structure, audience, tone>
Exclusions: <what to skip>
Cost: $2-5 | Time: 10-20 min
==============
```

## Evidence Tier Reference

When reviewing results, label claims:
- **CONFIRMED** -- Multiple independent sources agree
- **STRONG INDICATOR** -- Credible evidence with minor gaps
- **INFERENCE** -- Reasonable conclusion from indirect evidence
- **SPECULATION** -- Plausible but unverified
- **UNKNOWN** -- Insufficient evidence
