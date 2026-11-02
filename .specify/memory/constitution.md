# Sessions Manager Constitution

## Core Principles

### I. Clear Requirements and Traceability

Every feature MUST define its intended user outcome, scope, acceptance scenarios, and
measurable success criteria in a feature specification before implementation. Plans and
tasks MUST trace back to those requirements. Assumptions MUST be explicit; unresolved
questions that affect correctness, data safety, or public behavior MUST be resolved before
implementing the affected behavior. This keeps delivered work verifiable against user needs.

### II. Simple Design

Implementations MUST use the smallest design that satisfies the specified requirements.
New dependencies, services, and abstractions MUST have a documented purpose tied to a
current requirement. Added architectural complexity MUST include its justification and
the simpler alternative considered in the implementation plan. Speculative infrastructure
and unrelated refactoring MUST be excluded from feature changes to keep maintenance bounded.

### III. Test-Driven Development (NON-NEGOTIABLE)

New or changed application behavior MUST follow the red-green-refactor cycle: write a
test for the required behavior, run it and verify that it fails for the expected reason,
implement the minimum change that makes it pass, then refactor with relevant tests passing.
Bug fixes MUST begin with a failing regression test that reproduces the defect.

Tests MUST assert observable behavior and meaningful failure cases. Test depth MUST match
risk: changes spanning persistence, external integrations, or component contracts MUST
include tests at those boundaries. Feature specifications and task lists MUST explicitly
include the required test work, even when a template describes tests as optional.
Documentation-only changes require document validation; they do not require invented
application tests. TDD makes correctness evidence part of implementation from the start.

### IV. Protected Session Data

Features handling session data MUST define ownership, access boundaries, retention, and
destructive effects. Operations MUST respect the intended owner or execution context.
Secrets and sensitive session contents MUST be excluded from source control, logs, and
test fixtures. Diagnostics MUST expose enough context to identify a failure without
disclosing those contents.

Changes to persistence or session lifecycle behavior MUST specify failure handling and
recovery expectations, and tests MUST cover the identified risks of data loss, corruption,
or unintended access. Destructive operations MUST make their scope and consequences
explicit to the caller. These rules protect user work regardless of the eventual session model.

### V. Documented Changes and Compatibility

Changes to user-visible behavior, public interfaces, configuration, or stored data formats
MUST update the relevant documentation in the same change. Breaking changes MUST identify
affected users or consumers and provide migration and recovery instructions before release.
Each change MUST record its purpose, validation performed, and known limitations. Developer
setup and validation instructions MUST be reproducible from the documented prerequisites.
This makes changes reviewable and reduces surprises during upgrades.

## Project Constraints

- The project source and change history MUST use GitHub under the project owner's account,
  [YehudaItkin](https://github.com/YehudaItkin), as their canonical home. Feature specifications,
  plans, tasks, and this constitution MUST be versioned with the source.
- Before the first implementation, the feature specification MUST define what a session
  represents, its intended users, supported environment, and lifecycle boundaries.
- Language, framework, storage, and deployment choices MUST be justified in the implementation
  plan against the specified needs. This constitution does not prescribe an unselected stack.
- Performance or capacity requirements MUST state a measurable target and validation method
  when a feature introduces such requirements.

## Development Workflow

1. Specify the user outcomes and acceptance scenarios, then prepare an implementation plan
   and dependency-ordered tasks. Behavioral tasks MUST include tests before implementation.
2. Complete a Constitution Check in the plan before research and repeat it after design.
   Record evidence for each applicable principle and explain any item marked inapplicable.
3. Implement one testable increment at a time using TDD. Run the relevant regression checks
   and any configured formatting, linting, or static analysis checks for the change.
4. Submit changes through a GitHub branch and pull request. The pull request MUST link the
   relevant specification or task, describe the resulting behavior, and include validation
   commands and results. Behavioral changes MUST include evidence of the expected failing
   test and subsequent passing result.
5. Before merge, the maintainer or a designated reviewer MUST check constitutional compliance,
   acceptance evidence, data handling, compatibility, and documentation. Self-review is
   permitted for a sole maintainer but MUST be recorded. Required checks MUST pass before merge.

## Governance

This constitution takes precedence over conflicting project templates and development
guidance. Specifications, plans, tasks, and pull requests MUST be reviewed for compliance;
template examples do not waive these rules. A noncompliant change MUST be corrected or
covered by an explicit constitutional amendment before merge.

Amendments MUST describe the proposed rule changes, their rationale, affected artifacts,
and any transition or migration work. The project owner MUST approve an amendment before
adoption. Related feature artifacts MUST be reviewed for consistency when applying it;
the constitution workflow itself changes only this document.

Constitution versions MUST follow semantic versioning: MAJOR for incompatible principle
removals or redefinitions, MINOR for new principles, sections, or materially expanded
guidance, and PATCH for non-semantic clarifications or corrections. Every amendment MUST
record the version rationale, preserve the original ratification date, and update the
last-amended date. Dates MUST use ISO format YYYY-MM-DD.

**Version**: 1.0.0 | **Ratified**: 2026-11-02 | **Last Amended**: 2026-11-02
