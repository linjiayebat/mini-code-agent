# Security Policy

## Current Support

The project is pre-alpha. Only the latest commit on `main` is supported.

## Reporting

Do not open a public issue for a vulnerability. Use GitHub private vulnerability reporting
after the repository is published. Until then, contact the repository owner privately.

## Current Boundary

M0 does not execute model-generated tools. Future filesystem, shell, hooks, skills, and MCP
features are treated as untrusted inputs and must pass independent policy checks.

The project does not claim OS-level sandboxing unless an explicit sandbox backend is enabled
and documented.
