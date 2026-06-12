# Security policy

darwin-memo has zero runtime dependencies, so the attack surface is the
library itself plus whatever optional extras you install.

The full threat model lives in
[docs/threat-model.md](docs/threat-model.md): the settle trust
boundary, adversarial deltas, poisoned imports and probation,
cold-start damage and admission gating, prompt injection through
lesson text, and the explicit non-goals (single writer, no
cryptographic provenance).

Two things worth knowing when threat-modeling a deployment:

- `TestSuiteEnv` executes generated Python source in-process by design
  (it is a sandbox for its own generated micro-projects). Do not point
  it at untrusted code.
- Memory content is data, not instructions, but anything an LLM client
  encodes becomes retrievable context. Treat poisoned corpora as the
  benchmarks do: an expected input, not an impossibility.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting on this repository
(Security tab, "Report a vulnerability"). Please do not open public
issues for security reports. The latest minor version is supported.
