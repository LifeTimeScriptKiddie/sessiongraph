# Security

SessionGraph treats every session as untrusted data. It parses JSON but never executes recorded commands, code, or tool arguments. Imports are capped at 100,000 events, 2 MiB per JSONL line, and 64 MiB in total. Outputs use caller-selected paths and standard file permissions.

Report vulnerabilities privately via GitHub Security Advisories on the repository (**Security → Report a vulnerability**), addressed to the maintainer (@LifeTimeScriptKiddie). Do not open a public issue for a suspected vulnerability, and do not attach a real transcript; provide the smallest synthetic reproducer. Particularly important issues include secret-redaction bypasses, unexpected network access, command execution from session data, and output path manipulation.

Supported version: the latest `0.1.x` release on the default branch.
