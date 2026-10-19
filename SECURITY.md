# Security Policy

月星BAS工具箱 can modify the user-level TCC database and system maintenance
settings. Treat permission-writing issues as security-sensitive.

## Reporting

Do not publish working exploit details, personal TCC databases, audit logs,
administrator credentials, or unredacted filesystem paths in a public issue.
Report them privately to the maintainer after a security contact is added to
the public repository.

## Scope

Please report:

- unintended writes outside the user-level `TCC.db`;
- command injection or unsafe subprocess invocation;
- bypasses of service or Bundle ID validation;
- backup or restore path traversal;
- privileged EFI operations without explicit confirmation;
- accidental exposure of local paths, tokens, or personal data.

## Operator Guidance

- Keep tool-generated backups until permission changes are verified.
- Do not run the application from an untrusted DMG.
- Review changes before enabling login startup.
- Use a recovery USB or OpenCore backup before modifying EFI resources.
