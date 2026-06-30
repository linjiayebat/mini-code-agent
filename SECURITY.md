# Security Policy

## Current Support

The project is pre-alpha. Only the latest commit on `main` is supported.

## Reporting

Do not open a public issue for a vulnerability. Use GitHub private vulnerability reporting
after the repository is published. Until then, contact the repository owner privately.

## Current Boundary

Model output, repository content, project Skills, Tool arguments, test reports, and future MCP
servers are untrusted inputs. File, command, Git, test, and Repair actions pass typed validation,
Workspace boundaries, Policy, and approval where applicable.

M5a Skills are inert Markdown data. Discovery rejects links/reparse points, unsafe YAML, invalid
metadata, conflicts, drift, and resource-limit violations. Parsing or hashing a Skill does not
make its instructions safe, and source labels are not signatures.

M5a Hooks are executable in-process code supplied by the trusted application composition root.
The project does not load or execute Hook code from repository files, Skill metadata, model
output, or environment-selected modules. Pre-Hooks can deny but cannot grant Policy authority;
post-Hook failures cannot rewrite Tool results. A malicious host-registered Hook still has the
Agent process authority.

The project does not claim OS-level sandboxing unless an explicit sandbox backend is enabled and
documented. It also does not claim that Hook timeout stops work delegated to another thread or
process, or that SHA-256 establishes extension authorship.
