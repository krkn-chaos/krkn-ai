# Krkn-AI Contribution Policy

## Overview

This policy establishes guidelines for contributions to the Krkn-AI project
that involve Artificial Intelligence (AI) tools, including but not limited to
Large Language Models (LLMs), code generation tools, AI-assisted development
environments, and AI coding agents. This is a living document that will evolve
as AI technology, community practices, and legal frameworks mature.

## Motivation

AI tools are powerful assistants that can help developers become more productive
when configured and used correctly. This policy encourages their use within the
Krkn-AI project to boost both productivity and innovation while ensuring
transparency and safety.

Krkn-AI is an intelligent chaos engineering framework that uses genetic
algorithms to evolve and discover the most effective chaos experiments for
testing Kubernetes and OpenShift application resilience. It orchestrates
destructive chaos scenarios against live clusters, automatically evolves them
through mutation, crossover, and composition, and evaluates their impact via
Prometheus metrics. The consequences of incorrect or poorly-understood code can
be severe — unintended destructive operations, runaway scenario evolution,
miscalculated fitness scores that drive the algorithm toward excessively
harmful experiments, or silent failures that mask real resilience issues. This
context demands a higher standard of human oversight for all contributions, and
especially those involving AI-generated content.

Transparency about AI usage allows the community to learn and refine our
policies and practices to maximize the value of these tools while maintaining
the trust and safety our users depend on.

### Contributor Accountability

AI tools can produce verbose, over-engineered, or superficially-correct code
that places a disproportionate review burden on maintainers. Disclosure creates
accountability and helps ensure contributors take ownership of AI-assisted work.
Contributors are expected to:

- Thoroughly review and understand every line of AI-generated code before
  submission
- Refine and groom AI output to meet project quality standards
- Take full ownership of all submitted content regardless of its origin
- Be able to explain and justify any line of code when asked during review

Low-effort submissions that appear to be unreviewed AI output may be rejected
without detailed feedback until properly refined. This applies to all
contributions, but is particularly relevant for AI-assisted work.

### Legal and Copyright Rationale

Disclosure also serves important legal purposes. Copyright law in this area
continues to evolve, and as of current legal guidance, computer-generated work
may not be considered an original work eligible for copyright protection in many
jurisdictions. Additionally:

- AI training data may originate from materials with unclear or incompatible
  licenses
- Some AI tool vendors may retain rights to generated output, which could
  conflict with open source licensing
- Proper attribution helps maintain the integrity of the project's licensing
  under Apache 2.0

For further reading on these legal considerations, see the
[Linux Foundation Generative AI Guidelines](https://www.linuxfoundation.org/legal/generative-ai)
and [AI-Assisted Development and Open Source: Navigating Legal Issues](https://www.redhat.com/en/blog/ai-assisted-development-and-open-source-navigating-legal-issues).

## AI Tool Disclosure Requirements

### Disclosure

All contributors **SHOULD** disclose AI tool use when submitting code,
documentation, tests, scenario configurations, or other content to the Krkn-AI
project.

Disclosure **SHOULD** take the form of a trailer line within the commit
attributing the AI tool used. Acceptable formats include:

- `Assisted-by: GitHub Copilot <noreply@github.com>`
- `Assisted-by: Claude <noreply@anthropic.com>`
- `Co-authored-by: Claude <noreply@anthropic.com>`
- `Generated-by: ChatGPT <noreply@openai.com>`

Many AI coding tools automatically add `Co-authored-by` trailers — this is
acceptable and need not be changed to `Assisted-by`.

### Scope of Disclosure

Disclosure is expected when AI tools have materially contributed to the
submitted content.

**Requires disclosure:**

- AI wrote a function, class, scenario definition, or significant code block
  that you included
- AI suggested an algorithm, architecture, or chaos engineering approach you
  adopted
- AI generated tests, documentation, configuration templates, or commit
  messages you used
- AI-suggested solutions, refactoring, or significant debugging help that
  shaped the final implementation
- AI generated genetic algorithm operators (mutation, crossover, composition
  logic) or fitness calculation code

**Does not require disclosure:**

- General Q&A or learning (even if it informed your approach)
- IDE autocomplete (Copilot line completions, IntelliSense)
- Using AI to explain existing code or understand the codebase
- Asking AI to review your human-written code
- Spell checking or minor syntax corrections
- Content that has been substantially rewritten such that the original AI
  output is no longer recognizable

When in doubt, err on the side of disclosure — transparency benefits the
community.

## Acceptable Uses of AI Tools

AI tools are **accepted** as development assistants for:

- **Code scaffolding**: Generating boilerplate code, initial scenario
  implementations, and parameter definitions
- **Refactoring**: Suggesting code improvements and modernization
- **Testing**: Creating unit test cases and test data (subject to quality
  standards below)
- **Documentation**: Drafting technical documentation, docstrings, and usage
  examples
- **Debugging**: Identifying potential issues and suggesting fixes
- **Research**: Exploring architectural approaches, chaos engineering patterns,
  genetic algorithm strategies, and best practices
- **Learning**: Understanding the krkn-ai codebase, Kubernetes concepts, and
  Prometheus query language

## Chaos Engineering Safety Requirements

Given that Krkn-AI orchestrates destructive chaos scenarios against live
Kubernetes and OpenShift clusters and automatically evolves them, AI-generated
contributions carry unique safety risks that require additional scrutiny.

### Mandatory Human Verification

The following areas **MUST** receive thorough human review regardless of whether
AI tools were used, but contributors should be especially diligent when AI has
generated code in these areas:

- **Genetic algorithm operators**: Code that implements mutation, crossover, or
  composition of chaos scenarios (`krkn_ai/algorithm/`). Incorrect operators
  can cause uncontrolled escalation of destructive experiments across
  generations.
- **Scenario composition**: Code that combines multiple chaos scenarios into
  composite experiments (`krkn_ai/chaos_engines/composite.py`). Composite
  scenarios amplify destructive impact and require careful validation.
- **Fitness calculation**: Code that queries Prometheus and scores chaos impact
  (`krkn_ai/chaos_engines/fitness.py`). Miscalculated fitness can drive the
  genetic algorithm toward excessively destructive or ineffective scenarios.
- **Scenario command construction**: Code that builds shell commands for chaos
  execution (`krkn_ai/chaos_engines/commands.py`). Parameters are injected via
  string formatting and executed via subprocess — errors here can cause
  unintended cluster operations.
- **Scenario parameter ranges**: Parameter bounds defined in scenario models
  (`krkn_ai/models/scenario/`). AI may set overly broad ranges that allow
  the genetic algorithm to explore dangerously extreme configurations.
- **Cluster discovery and interaction**: Code that queries the Kubernetes API
  for cluster topology (`krkn_ai/cluster/cluster_manager.py`), especially
  network interface targeting and node selection logic.
- **Shell execution**: Code that runs subprocess commands
  (`krkn_ai/utils/run_shell`). This is the execution boundary where chaos
  scenarios become real cluster operations.
- **Health check monitoring**: Code that monitors application health during
  chaos runs (`krkn_ai/chaos_engines/health_check_watcher.py`). Failures in
  this system could allow experiments to continue when the target system is
  already critically impaired.
- **Stopping criteria**: Code that determines when the genetic algorithm should
  halt (`krkn_ai/algorithm/genetic/stopping.py`). Incorrect stopping logic
  can cause the algorithm to run indefinitely or terminate prematurely.

### Dependency Safety

AI tools may suggest dependency versions that conflict with Krkn-AI's
requirements. Contributors **MUST** verify:

- New dependencies are compatible with the existing dependency tree
- Dependencies are checked for known security vulnerabilities
- Changes to `pyproject.toml` do not introduce conflicting version constraints

## Code Quality Standards

AI-generated code must meet the same quality standards as human-written code.
Common AI-generated patterns that do **not** meet Krkn-AI's standards include:

- **Excessive comments**: Avoid narrating what the code does (e.g.,
  "# Import the module", "# Define the function"). Comments should only explain
  non-obvious intent, trade-offs, or constraints.
- **Over-engineering**: AI often generates unnecessarily complex solutions.
  Prefer simplicity and consistency with existing patterns in the codebase.
- **Hallucinated APIs**: AI may generate calls to Kubernetes client methods,
  Prometheus query functions, or internal utilities that do not exist. All API
  calls must be verified.
- **Generic variable names**: AI tends toward `result`, `data`, `item` etc.
  Use descriptive names consistent with the existing codebase.

## Testing Requirements

AI-generated code must meet Krkn-AI's existing testing requirements. Additional
considerations for AI-assisted contributions:

- All code must pass the project's pre-commit checks (`ruff` linting and
  formatting, `mypy` type checking)
- Unit tests must contain **meaningful assertions** that validate behavior, not
  just verify that code runs without exceptions
- AI-generated tests that mock everything and test only the mock interactions
  will be rejected
- Tests must pass when run as part of the full test suite (`pytest tests/unit/`)
  — not just in isolation
- Test output should be included in the PR description

## Contributor Ladder and AI

The Krkn project uses a
[contributor ladder](https://github.com/krkn-chaos/krkn/blob/main/MAINTAINERS.md)
model (Contributor → Member → Maintainer → Owner). AI tool usage intersects
with this model in the following ways:

- **AI tools are tools, not contributors.** AI cannot be listed as a
  contributor, member, or maintainer.
- **Contribution quality over quantity**: Bulk AI-generated PRs that do not
  demonstrate genuine understanding of the project will not count toward
  advancement on the contributor ladder.
- **Review credibility**: PR reviews must reflect genuine human understanding.
  AI-assisted reviews that parrot generic feedback without engaging with the
  actual code changes may not count toward the review requirements for becoming
  a maintainer.
- **Demonstrated understanding**: Maintainers may ask contributors to explain
  their AI-assisted contributions during review. Inability to explain the code
  is grounds for requesting rework.

## Prohibited Uses

The following uses of AI tools are **not permitted** within the Krkn-AI project:

- **Substituting AI for required human review**: Maintainer and member reviews
  must reflect genuine human evaluation
- **AI participation in governance**: AI-generated content must not be used in
  governance votes, Code of Conduct proceedings, or security response
  activities
- **Bulk low-quality contributions**: Using AI to generate high volumes of
  trivial PRs, issues, or comments to inflate contribution metrics
- **Unverified security reports**: AI-generated vulnerability reports submitted
  without human verification and analysis
- **Circumventing disclosure**: Deliberately concealing material AI involvement
  in a contribution

## Legal and Licensing Considerations

### Copyright Compliance

Contributors must ensure that:

- AI tool terms of service do not conflict with Apache 2.0 licensing
- No copyrighted material is inadvertently included in AI-generated output
- All third-party content is properly attributed and licensed

### Employer Policies

Contributors should verify that their use of AI tools complies with their
employer's policies regarding AI-generated code in open source contributions.

## Review Process

### Review Criteria

Consistent with [Krkn's contribution guidelines](https://github.com/krkn-chaos/krkn/blob/main/CONTRIBUTING.md),
reviewers should evaluate all contributions — AI-assisted or otherwise — for:

- Code quality and adherence to project standards
- Appropriate test coverage and meaningful assertions
- Security implications, especially for cluster-facing operations
- Correct implementation of genetic algorithm operators and fitness logic
- Long-term maintainability and consistency with existing patterns

### Reviewer Guidance for AI-Assisted Contributions

Reviewers should be attentive to common AI-generated issues:

- Plausible-but-incorrect logic, especially in scenario evolution and fitness
  calculation paths
- Hallucinated API calls to Kubernetes client, Prometheus, or internal
  utilities
- Incorrect parameter ranges that could cause excessive cluster disruption
- Over-commented or over-engineered code
- Tests that achieve coverage without meaningful validation

Reviewers may request that contributors demonstrate understanding of AI-assisted
code before approving.

## Policy Evolution

This policy will be regularly reviewed and updated to reflect:

- Changes in AI technology capabilities
- Legal and regulatory developments
- Community feedback and experience
- Industry best practices within the CNCF ecosystem

## Questions and Clarifications

For questions about this policy, please:

1. Open an issue in the [krkn-ai repository](https://github.com/krkn-chaos/krkn-ai)
2. Discuss in the [#krkn channel](https://kubernetes.slack.com/archives/C05SFMHRWK1)
   on Kubernetes Slack
3. Bring up during monthly
   [office hours](https://zoom-lfx.platform.linuxfoundation.org/meetings/krkn?view=month)
4. Email the maintainers at krkn.maintainers@gmail.com

## References

- [Krkn AI Contribution Policy](https://github.com/krkn-chaos/krkn/blob/main/AI_CONTRIBUTION_POLICY.md)
- [Linux Foundation Generative AI Guidelines](https://www.linuxfoundation.org/legal/generative-ai)
- [KubeVirt AI Contribution Policy](https://github.com/kubevirt/community/blob/main/ai-contribution-policy.md)
- [Avocado Framework AI Policy](https://avocado-framework.readthedocs.io/en/latest/guides/contributor/chapters/ai_policy.html)
- [QEMU Code Provenance Policy](https://www.qemu.org/docs/master/devel/code-provenance.html#use-of-ai-content-generators)
- [AI-Assisted Development and Open Source: Navigating Legal Issues](https://www.redhat.com/en/blog/ai-assisted-development-and-open-source-navigating-legal-issues)
- [Krkn Contributing Guidelines](https://github.com/krkn-chaos/krkn/blob/main/CONTRIBUTING.md)
- [Krkn Governance](https://github.com/krkn-chaos/krkn/blob/main/GOVERNANCE.md)
- [Krkn Code of Conduct](https://github.com/krkn-chaos/krkn/blob/main/CODE_OF_CONDUCT.md)
