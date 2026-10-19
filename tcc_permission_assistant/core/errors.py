"""Domain errors that can be presented safely by the CLI or GUI."""


class TCCAssistantError(Exception):
    """Base class for expected application errors."""


class ScanError(TCCAssistantError):
    """The selected application could not be scanned."""


class InvalidAppBundle(ScanError):
    """The selected path is not a readable macOS application bundle."""


class InvalidBundleID(TCCAssistantError):
    """A bundle identifier is empty, malformed, or unsafe."""


class UnsupportedService(TCCAssistantError):
    """A requested TCC service is not in the fixed allowlist."""


class TCCDatabaseError(TCCAssistantError):
    """Base class for expected TCC database errors."""


class TCCDatabaseNotFound(TCCDatabaseError):
    """The selected TCC database does not exist."""


class TCCDatabaseAccessError(TCCDatabaseError):
    """The TCC database exists but cannot be opened read-only."""


class TCCDatabaseLocked(TCCDatabaseError):
    """The TCC database is busy or locked."""


class TCCDatabaseCorrupt(TCCDatabaseError):
    """SQLite reports a malformed or corrupt database."""


class TCCSchemaError(TCCDatabaseError):
    """The access table is missing or lacks required columns."""


class TCCQueryError(TCCDatabaseError):
    """A read-only TCC query failed."""


class BackupError(TCCAssistantError):
    """A TCC database backup could not be created."""


class InjectionError(TCCAssistantError):
    """A TCC injection plan or operation was rejected."""


class InjectionConfirmationRequired(InjectionError):
    """The user did not complete every required confirmation."""


class UnsupportedInjectionScope(InjectionError):
    """The selected database scope is not writable in this phase."""


class InjectionSchemaError(InjectionError):
    """The access schema cannot be safely inserted into."""


class InjectionDatabaseError(InjectionError):
    """The SQLite write transaction failed."""


class VerificationError(InjectionError):
    """A post-injection verification query failed."""


class RestoreError(TCCAssistantError):
    """A TCC database restore failed or was rejected."""


class RestoreConfirmationRequired(RestoreError):
    """The user did not complete the required restore confirmation."""


class RestoreSourceError(RestoreError):
    """A backup file is not a valid managed restore source."""


class RestoreVerificationError(RestoreError):
    """A restored database could not be verified."""


class DiagnosticsError(TCCAssistantError):
    """Diagnostic collection failed unexpectedly."""
