# Security policy

darwin-memo has zero runtime dependencies, so the attack surface is the
library itself plus whatever optional extras you install.

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
