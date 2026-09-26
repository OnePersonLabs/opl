# Auditing Repository Shape: Pressure Tests

## Test 1: Incoherent developer surface

Present a monorepo with many working package scripts using inconsistent verb order, overlapping terms such as check, validate, qualify, QA, and preflight, misleading names, aliases, and root-level pass-throughs.

Success requires the auditor to:

* treat the entire script set as one developer-facing interface;
* detect vocabulary and hierarchy incoherence;
* distinguish standard terms such as smoke testing from actual problems;
* identify broad-name/narrow-behavior mismatches;
* question excessive root forwarding;
* recommend a command ontology rather than whack-a-mole renames.

Failure modes:

* only review whether commands execute;
* declare every unusual name wrong;
* focus specifically on the word smoke;
* suggest individual renames without reconstructing the interface.

## Test 2: Workaround propagation

Present a change where a custom state wrapper caused adapters, synchronization flags, lifecycle hooks, and special tests across several packages.

Success requires the auditor to identify the originating wrapper as a possible false premise and trace its downstream complexity.

Failure mode: report each adapter and flag as an isolated code smell.

## Test 3: Justified novelty

Present an unusual audio asset pipeline required by proprietary SDK licensing, platform-specific binary formats, and offline CI constraints.

Success requires the auditor to investigate reference implementations, recognize the unusual constraints, and retain justified custom machinery while improving its explanation and boundaries.

Failure mode: recommend deletion merely because mature generic repositories do not contain it.

## Test 4: Implementation-shaped tests

Present a system with comprehensive passing tests that mock away resource ownership, concurrency, and failure behavior.

Success requires the auditor to distinguish mechanism coverage from requirement coverage.

Failure mode: classify the implementation as sound because all tests pass.

## Test 5: Baseline discrimination

Present a diff that touches legacy architectural oddities but introduces only a small unrelated feature.

Success requires the auditor to distinguish preexisting debt from newly introduced contamination while still noting material integration risks.

Failure mode: attribute all repository oddities to the current change.

## Test 6: Cross-domain transfer

Present one of the following:

* inconsistent API routes and request schemas;
* duplicated configuration layers;
* irregular directory and package ownership;
* CI workflows with overlapping semantics;
* event names with competing vocabularies.

Success requires the same expected-shape and surface-coherence reasoning without relying on package-script-specific language.

## Pass Criteria

The skill passes when an isolated reviewer consistently:

1. reconstructs expected shape before judging implementation;
2. detects systemic interface incoherence;
3. traces causal complexity to root premises;
4. uses external conventions as calibration rather than law;
5. preserves justified domain-specific novelty;
6. clusters symptoms instead of producing a whack-a-mole list;
7. remains read-only until the audit is complete.
