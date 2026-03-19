"""SyncState enum — shared between LibraryService and consumers."""

from enum import Enum


class SyncState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
