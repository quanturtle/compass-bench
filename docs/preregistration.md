# Preregistration

Commit a copy of this file, filled in, before a paid run. The commit that `run` records as the code revision then carries the plan, dated by git, before any reply was seen. Preregistering the prompts, decoding settings, output format, and hypotheses blocks most of the choices that would otherwise be made after looking at the results (Thomas, Gligoric & Shah, 2026; listed in `references.md`).

Copy it to `docs/preregistrations/<experiment>-<date>.md`, fill in every field, and set the experiment file's `preregistration` to the copy's path relative to the experiment file. `plan` and `run` refuse a path that names no file, and a report of the run then reads "confirmatory"; without the field it reads "exploratory".

A data migration can rewrite a stored experiment and move it to a new hash, as revisions 0006 and 0011 did, so the hash `plan` printed can stop matching the one `runs show` prints. Record the questionnaire hash as well, and read the current experiment hash from `runs show` when checking a plan against its run.

## Experiment

- Experiment file and its hash as `plan` prints it:
- Questionnaire file and its hash:
- Models, each with its catalog name, slug, answer type, temperature, top_p, max_tokens, reasoning effort, pinned host, and precision filter; and which pairs, if any, differ in one of these and so compare elicitations:
- Design: factors and levels, repetitions, scale, system prompt, prompt template and instruction wordings:
- Analysis settings: confidence level, coverage floor, equivalence margin:

## Hypotheses

- Positions: for each model, the quadrant expected, or "no expectation":
- Orderings: the pairs and axes on which one model is expected higher, with the direction:
- Equivalences: the pairs and axes expected within the margin:
- Anything the consistency diagnostics or the facets are expected to show:

## Budget and stopping

- Budget cap passed to `run`, and the cap `resume` may raise it to:
- The run is complete when: every trial is finished, or the cap is reached, or a named endpoint stops answering.
- A run stopped short is analyzed as it stands; no trial is re-asked.

## Exclusions decided in advance

- Models dropped from the comparison only if: (state the rule, for example an answered share below the coverage floor on either axis).
- Runs pooled with this one: none, or the run ids and the rule that admits them.

## Deviations

Filled in after the run, with the commit that changed the plan: what changed, why, and what was seen before it changed.
