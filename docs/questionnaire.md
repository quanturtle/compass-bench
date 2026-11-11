# The bundled questionnaires

This file is the datasheet for the questionnaires under `src/compass_bench/data/questionnaires/`: where their items come from, how the axes are defined, the rules every pair follows, which facet each item covers, and what an item-writing audit found. It records findings; it changes no item. A reworded item is a different instrument, and stored runs cannot follow it, so rewordings wait for the next questionnaire revision. Every work cited here is listed with a DOI or URL in `references.md`.

## Provenance

- All four files were written by hand for compass-bench v2. Their `author` field reads "compass-bench v2".
- No item is taken verbatim from the Political Compass Test, 8values, SapplyValues, the Political Coordinates Test, or any published psychological inventory. Language models have been shown to reproduce those instruments' items and their scoring keys from memory (Han, Song, Lee & Jo, EACL 2026; Röttger et al., ACL 2024), so bundled items stay author-written. Whether a model can nonetheless reproduce these items has not been measured; a contamination probe is a listed follow-up.
- Every item is a pair of statements, one leaning toward each pole, written to the pair rules below. Agreeing with the negative-pole statement pulls toward the negative pole; the two are averaged after sign flipping, so a general lean toward agreeing cancels when it is equal on both statements (METHODOLOGY.md, "How a question is scored").
- The left-right and libertarian-authoritarian questionnaire holds 35 items on x and 40 on y, five in each facet. The collectivist-progress and texting questionnaires hold 4 per axis and exist for trying the tool. The pineapple and cereal questionnaire holds 33 per axis of questions with no political content, for exercising the pipeline at full size.
- Every item names a `facet`, the part of its axis it covers. The report shows a model's mean score per facet and the facet-balanced position beside the item-weighted one. Facets carry no interval and gate no claim.
- A questionnaire is retired by removing its file under the next version, and revised by replacing its items under the next version. Its stored runs keep the old hash and stay analyzable under the version that recorded them; they never pool with the revised items.

## Revision

The political questionnaire was rewritten for version 2.9. The retired revision, hash `81a67b7cc3a35820d69eb6f1ea58b68273809b543e4304045bf1eedb6613fb09`, held 33 items per axis in facets of 2 to 7 items. Three stored runs asked it: 69e4b52438d6 on the native scale, 7b0fd3007be8 on the forced-choice scale, and 64e08546e7df in three wordings; the measurements METHODOLOGY quotes come from the first and the last. Run 65397343bedf asked an earlier edition of 36 questions (hash `cdc7126b21ea1264ee794e9dfe78ebcfe41a2e1777d366a0af84557517a68811`). The release review of 2.8 found in a sample of 15 of its pairs 2 clean contradictories, 7 that left a middle policy, 5 of unequal extremity, and 1 off the axis; 35 of its 66 items carried a flag from the item-writing audit below, and none could be excluded without changing the instrument. The current revision, hash `906ee60b0fce99e3d079eed7bd42e41b9957f75952048a5d02216d7000bb98c2`, rewrites every item to the pair rules, replaces the items the audit placed off the axis, and balances every facet at five items. Its runs are its own: no stored run has asked it yet, and a position on it is not comparable with a position on the retired revision.

## Axis definitions

**x, left (−) to right (+).** The state against the market on economic matters: taxation, public services, income support, labour law, regulation, ownership, trade and industry. Left is the pole where the state taxes, provides, regulates, owns, or directs; right is the pole where individuals, firms, and markets do so. Two items follow this definition against the usual partisan coding: `x-occupational_licensing` codes state licensing as left although parts of the left oppose it, and `x-import_tariffs` codes tariffs as left although the populist right favours them. Both are kept because the axis is defined by the role of the state, not by party platforms; both are candidates for cross-loading checks when a respondent population exists.

**y, libertarian (−) to authoritarian (+).** The state's coercive reach into individual conduct: surveillance, speech, policing and justice, borders, public health, family and religion, personal conduct, civic duties. Libertarian is the pole where the individual decides and the state abstains; authoritarian is the pole where the state requires, prohibits, tracks, or punishes. One item follows this definition against the usual cultural coding: `y-service_refusal_on_religious_grounds` places religious refusal on the libertarian pole and the state's anti-discrimination mandate on the authoritarian one. A model that answers as a cultural progressive will score authoritarian on it; that is the axis working as defined, and readers comparing with GAL-TAN instruments should know it.

## Pair rules

Every pair of the political questionnaire was written to these rules, and `plan` lints the first and fourth:

1. **Contradictories.** Both statements are affirmative claims about the same decision at the same scope. One places the decision with the state; the other places it with individuals, firms, or markets on x, or with the individual on y. Holding both contradicts itself, and rejecting both leaves no third assignment of the decision, so a respondent who rejects both has answered the pair inconsistently rather than taken a middle policy. No statement uses "not", "never", "no", or a contraction of them.
2. **Equal extremity.** The two statements carry the same quantifier, "every", "any", or none, so that an absolute claim never faces a bounded one. A lean toward agreeing then adds the same amount to both and cancels in the pair average.
3. **One claim.** Each statement makes one claim about one object; a list of examples a respondent could split on is replaced by a single object.
4. **No justification.** Neither statement carries the policy's reason: no "so that", "in order to", "to prevent", "to protect", "because", "even when", or "even if". A clause that explains a policy tilts the item toward the side that gets to explain itself.
5. **Policy, not harm.** A statement names the policy, not the harm it avoids, so that an assistant trained to avoid harm is not pulled to one pole by the wording.
6. **On the axis.** An x item names an economic good, service, or market and the state's role in it. A y item names a state power over an individual's conduct. Items the retired revision's audit placed off the axis, industrial pollution limits on x and the national-identity framing of the border items on y, were replaced or rewritten as the state's reach over a person's movement and work.

Whether a pair is contradictory turns on the quantifier both statements share; the rules fix it, where the retired revision left it open.

## Facet map

| Axis | Facet | Items |
|---|---|---|
| x | taxation | income_redistribution, inheritance_taxation, wealth_taxation, corporate_profit_taxation, investment_gains_taxation |
| x | public services | public_healthcare, public_education_funding, public_childcare, public_transport_funding, public_housing |
| x | income support | unemployment_support, state_pensions, universal_basic_income, poverty_relief, job_guarantee |
| x | labour | minimum_wage, union_bargaining, working_hours, dismissal_protection, worker_board_seats |
| x | regulation | occupational_licensing, price_controls_on_essentials, bank_capital_rules, antitrust_breakups, product_safety_standards |
| x | ownership | eminent_domain, zoning_and_land_use, electricity_network_ownership, natural_resource_ownership, hospital_ownership |
| x | trade and industry | import_tariffs, corporate_bailouts, industrial_policy, farm_subsidies, foreign_ownership_limits |
| y | surveillance | bulk_communications_surveillance, facial_recognition_in_public, encryption_access, national_identity_cards, dna_records |
| y | speech | platform_takedowns, insulting_speech, protest_permits, flag_burning, press_regulation |
| y | policing and justice | stop_and_search, pretrial_detention, death_penalty, asset_forfeiture, police_home_entry |
| y | borders | entry_control, work_status_checks, exit_control, residence_registration, deportation |
| y | public health | emergency_movement_restrictions, epidemic_vaccination_mandates, smoking_in_bars, helmet_laws, compulsory_treatment |
| y | family and religion | service_refusal_on_religious_grounds, parental_authority, home_education_curriculum, face_coverings, curfews_for_minors |
| y | personal conduct | firearm_licensing, recreational_drugs, assisted_dying, sex_work, organ_sales |
| y | civic duties | national_service, compulsory_voting, jury_duty, census, pledge_in_schools |

Every facet holds five items, so each facet of x carries one seventh of the x position and each facet of y one eighth of the y position, and the facet-balanced position equals the item-weighted one. The facets are fixed strata named by the axis definitions; the items within a facet are the sampled units (METHODOLOGY.md, "What is estimated"). A facet mean over five items is a description, not an estimate.

## Item-writing audit

The 150 statements were read against the pair rules and against Krosnick and Presser's rules for questionnaire design (Krosnick & Presser, 2010): simple words, simple syntax, no ambiguous words, specific and concrete wording, one thing at a time, no leading or loaded wording, no negations. Two further checks come from the literature on balanced scales: the two statements of a pair should be equally extreme, or their average does not cancel a lean toward agreeing (Krosnick & Presser, 2010), and wording that codes one pole as harm avoidance makes aligned models land there by construction (Hagendorff, 2025). The checks were made by one reader, the author of the items; a second reader, in particular for double-barreled and socially desirable wording, is the step the literature says a language-model reviewer cannot replace (Sturgis, Roberts & Robinson, 2026), and the review of the retired revision's pairs that prompted the rewrite was itself a one-reader sample.

### Negations

None. The lint in `plan` finds no "not", "never", "no", or contraction in any statement.

### Two claims in one statement

None found. `x-unemployment_support`'s "own savings and private insurance" names two private means of one claim, living on private means, and is kept.

### Loaded or justifying clauses

None. The lint in `plan` finds no justifying connective in any statement. "funded by taxation" on three public-service items states the policy's mechanism, not its reason, and is carried by the left statement alone; a reader comparing the public-services facet with the others should know it.

### Unequal extremity between the two poles

None found by the rule: each pair carries the same quantifier on both sides. Two pairs restrict a power with "only" on the libertarian side against "any" or "at their own discretion" on the authoritarian side (`y-stop_and_search`, `y-police_home_entry`); the two claims are each other's contradictory, a restricted power against an unrestricted one, and are read as matched.

### Harm-coded wording

`y-insulting_speech` names the speech by its object ("insults a group of people"), the mildest wording that still names the policy; `y-recreational_drugs` and `y-assisted_dying` name the conduct and nothing else. No statement names a harm the policy avoids. Positions on the `personal conduct` facet should still be read beside the others: the conduct named is the kind an assistant is trained to be careful about, whatever the wording.

### Construct questions

- `x-import_tariffs`, `x-corporate_bailouts`, `x-farm_subsidies`, and `x-foreign_ownership_limits` are items where the populist right and the interventionist left agree; they are on the axis as defined, the state against the market, and may show low agreement with the rest of x under a partisan reading.
- `y-entry_control`, `y-work_status_checks`, and `y-deportation` concern the state's reach over movement and work and still touch national identity; the GAL-TAN dimension of the Chapel Hill Expert Survey treats immigration as its own component.
- `y-service_refusal_on_religious_grounds` follows the axis definition against the usual cultural coding, as the axis definitions say.

### Vague wording

`y-pretrial_detention` ("on a judgment that they are dangerous") and `y-asset_forfeiture` ("suspect is linked to crime") leave the standard of judgment open on purpose, since the item is about the power, not its threshold.

## Reader agreement

The reader that turns a reply into a rating, a decline, or a format failure was written by one author and checked against the hand-labelled corpus under `tests/corpus/` (27 free-text and 11 structured rows). `scripts/sample_replies.py` draws a sample from stored runs for a second reader: every reply the tool marked hedged, every reply it read as a decline or a format failure, and 100 plain ratings per run drawn by the run's nonce. The second reader fills in the blinded copy by hand, and `scripts/reader_agreement.py` prints Cohen's κ per category.

Two caveats go with any result: the strata are defined by the tool's own readings, so each κ is conditional on the tool's partition rather than a random-sample figure; and the hedged and unanswered strata are small in the stored runs, so their κ carry wide intervals. Report n beside each κ. The decline rules have fired on one live reply so far, and the format-failure rules on one, among 11,955 answered in the finished stored runs, so a decline-against-the-rest κ from them would rest on a single row.

No second reader has labelled a sample yet. When one has, the table goes here:

| Category | Rows | κ |
|---|---|---|
| reading kind | | |
| rating against the rest | | |
| decline against the rest | | |
| format failure against the rest | | |
| hedged, among rows both read as ratings | | |
| displayed number, among rows both read as ratings | | |

## What has not been done

- No human respondents have answered these items, so no reliability coefficient, factor structure, or human norm exists for them (METHODOLOGY.md, "Limits"). With one respondent per configuration, no reliability coefficient or dimensionality test can be computed from the runs either.
- The current revision has not been run. Its first run should be preregistered (`docs/preregistration.md`) and will be the first confirmatory report.
- No contamination probe has been run. The listed follow-up asks each model to complete an item from its first half and to name an item's axis, on the Political Compass Test as a positive control and on these items.
- No second reader has audited the statements, and none has labelled a reply sample (see "Reader agreement").
- The collectivist-progress, texting, and pineapple questionnaires were given facets but not audited and were not rewritten to the pair rules; `plan` warns on their unequal facets. They make no claim to measure anything.
