from typing import TypedDict, Dict, List, Optional, Literal, Any

# Hybrid Policy:
# - Top-level envelopes are Total (strict).
# - Nested metadata is total=False to allow for version drift.

# --- Enums ---

ScanChange = Literal["New", "Different", "Removed", "Same", "Unknown"]
OperationStepDecision = Literal["Processed", "Cancelled", "Ignored"]
Os = Literal["windows", "linux", "mac", "other"]

# --- Common Structures ---


class ScanChangeCount(TypedDict):
    different: int
    new: int
    same: int


class OperationStatus(TypedDict):
    changedGames: ScanChangeCount
    processedBytes: int
    processedGames: int
    totalBytes: int
    totalGames: int


class ApiErrorDetails(TypedDict, total=False):
    cloudConflict: Optional[Dict]
    cloudSyncFailed: Optional[Dict]
    someGamesFailed: Optional[bool]
    unknownGames: Optional[List[str]]


# --- Game Level Structures ---


class ApiFile(TypedDict, total=False):
    bytes: int
    change: ScanChange
    duplicatedBy: List[str]
    failed: bool
    ignored: bool
    originalPath: Optional[str]
    redirectedPath: Optional[str]
    error: Optional[Dict[str, str]]


class ApiRegistryValue(TypedDict, total=False):
    change: ScanChange
    duplicatedBy: List[str]
    ignored: bool


class ApiRegistry(TypedDict, total=False):
    change: ScanChange
    duplicatedBy: List[str]
    failed: bool
    ignored: bool
    values: Dict[str, ApiRegistryValue]
    error: Optional[Dict[str, str]]


class ApiBackup(TypedDict):
    name: str
    when: str  # ISO date-time
    locked: bool
    os: Optional[Os]
    comment: Optional[str]


class ApiGame(TypedDict, total=False):
    # Used by backup/restore
    change: ScanChange
    decision: OperationStepDecision
    files: Dict[str, ApiFile]
    registry: Dict[str, ApiRegistry]

    # Used by backups command
    backupPath: str
    backups: List[ApiBackup]

    # Used by find command
    score: Optional[float]


# --- Top Level Response ---


class LudusaviApiOutput(TypedDict):
    games: Dict[str, ApiGame]
    errors: Optional[ApiErrorDetails]
    overall: Optional[OperationStatus]
    cloud: Optional[Dict[str, Dict]]


# --- Configuration ---


class ApiConfig(TypedDict, total=False):
    language: str
    theme: str
    customGames: List[Dict[str, Any]]
    roots: List[Dict[str, Any]]
    redirects: List[Dict[str, Any]]
    backup: Dict[str, Any]
    restore: Dict[str, Any]
    scan: Dict[str, Any]
    cloud: Dict[str, Any]
    gui: Dict[str, Any]


# --- Manifest ---


class ApiManifestGame(TypedDict, total=False):
    files: Optional[Dict[str, Any]]
    registry: Optional[Dict[str, Any]]
    steam: Optional[int]
    gog: Optional[int]
    lutris: Optional[str]


class ApiManifest(TypedDict):
    games: Dict[str, ApiManifestGame]
