# Backend Architecture

Target architecture for the Python backend. Replaces the current mixin-based approach with composition, service layer, and adapter pattern.

## Why

The current codebase (6300+ lines, 10 mixins on a single Plugin class) mixes business logic with I/O in every module. This causes:

- **Tangled responsibilities**: `save_sync.py` (1309 lines) contains conflict detection logic, HTTP calls, file I/O, and state management all interleaved.
- **Shared mutable state**: All mixins access `self._state`, `self.settings`, `self._save_sync_state` directly. No boundaries, no contracts.
- **Hard to test**: Every test needs `unittest.mock.patch` on internal methods because there are no seams for dependency injection.
- **Doesn't scale**: Adding RomM version-specific code paths (4.6.x vs 4.7.0+), multi-emulator support (Phase 9), and new features means more code in already-large files with more branching.

No other Decky plugin uses mixins. The ecosystem standard is composition (Unifideck, PlayTime) or direct delegation (MoonDeck, SimpleDeckyTDP).

## Principles

Selectively inspired by "Cosmic Python" (cosmicpython.com), taking only what fits a Decky plugin:

1. **Composition over inheritance**: Plugin class instantiates services, delegates to them. No mixins. This is the Decky ecosystem standard.
2. **Separate I/O from logic**: HTTP calls and disk I/O live in adapters. Services contain business logic and receive adapters via `__init__`. Services *may* do local I/O (hashing a file, reading a config) when it's integral to their logic — the boundary is "no HTTP in business logic", not "no I/O at all".
3. **Explicit dependencies**: Each service declares what it needs in `__init__`. No global state, no `self._state` dict shared across 10 classes.
4. **Protocols where needed**: Use `typing.Protocol` for adapter interfaces that have multiple implementations (e.g. versioned Save API). Don't create protocols for one-implementation adapters — that's ceremony for ceremony's sake.
5. **No DI framework**: Manual wiring in a bootstrap function. Python doesn't need Spring.

**Not adopted** from Cosmic Python: Domain Events, Message Bus, Repository Pattern, Unit of Work. These are for server applications with databases and message queues — overkill for a Decky plugin.

## Target Structure

```
main.py                              # Entrypoint: thin Plugin class
                                     # _main() calls bootstrap(), stores services
                                     # Each callable = 1-3 lines delegating to a service
                                     # Target: ~150 lines

bootstrap.py                         # Composition root
                                     # Instantiates all adapters, services, wires dependencies
                                     # Called once from _main()
                                     # Only place that knows about all concrete classes

py_modules/
├── models/                          # Pure data, no I/O, no dependencies
│   ├── models.py                    # @dataclass: Rom, Platform, SaveFile, BiosFile,
│   │                                #   Achievement, Device, SyncDelta, DownloadItem
│   ├── settings.py                  # @dataclass: PluginSettings, SaveSyncSettings
│   └── state.py                     # @dataclass: PluginState, SyncState, SaveSyncState
│                                    #   Typed containers replace raw dicts
│
├── services/                        # Business logic, no HTTP, no disk I/O
│   ├── connection.py                # ConnectionService: test, version detection
│   ├── sync.py                      # SyncService: delta calculation, shortcut planning
│   ├── save_sync.py                 # SaveSyncService: conflict detection, resolution
│   ├── downloads.py                 # DownloadService: queue management, prioritization
│   ├── firmware.py                  # FirmwareService: BIOS status, validation
│   ├── achievements.py              # AchievementService: cache logic, summaries
│   ├── metadata.py                  # MetadataService: TTL cache, enrichment
│   └── sgdb.py                      # SgdbService: artwork matching, cache
│                                    #
│                                    # Pattern:
│                                    #   class SaveSyncService:
│                                    #       def __init__(self, save_api: SaveApiProtocol,
│                                    #                    state: SaveSyncState,
│                                    #                    settings: SaveSyncSettings): ...
│                                    #
│                                    #       def detect_conflict(self, rom_id, filename) -> Conflict | None:
│                                    #           server_hash = self._api.get_hash(save_id)
│                                    #           local_hash = self._compute_local_hash(path)
│                                    #           ...  # pure logic, no HTTP
│
├── adapters/                        # I/O boundaries
│   ├── romm/                        # Everything that talks to RomM
│   │   ├── client.py                # RommHttpClient: auth, SSL context, retry,
│   │   │                            #   generic _request/_download methods
│   │   ├── rom_api.py               # Platforms, ROMs, metadata endpoints
│   │   ├── firmware_api.py          # BIOS/firmware endpoints
│   │   ├── achievement_api.py       # RA metadata, user progress endpoints
│   │   └── save_api/                # Versioned save sync endpoints
│   │       ├── protocol.py          # SaveApiProtocol (typing.Protocol)
│   │       │                        #   download_save, upload_save, get_hash,
│   │       │                        #   register_device, list_saves
│   │       ├── v46.py               # 4.6.x: download_path workaround,
│   │       │                        #   download-and-hash, local device UUID
│   │       └── v47.py               # 4.7.0+: /content endpoint, content_hash,
│   │                                #   POST /api/devices, server-side 409
│   │
│   ├── sgdb_client.py               # SteamGridDB HTTP (own API, own auth)
│   ├── steam_config.py              # VDF writes, artwork file management
│   ├── es_de_config.py              # ES-DE gamelist.xml / es_systems.xml parsing
│   ├── retrodeck_config.py          # RetroDECK path resolution
│   └── persistence.py               # Settings/state load/save (atomic writes, flock)
│
├── version_router.py                # Selects correct adapter based on RomM version
│                                    #   class VersionRouter:
│                                    #       def get_save_api(self) -> SaveApiProtocol:
│                                    #           if self._version >= "4.7.0": return self._v47
│                                    #           return self._v46
│                                    #       def set_version(self, version: str): ...
│
└── errors.py                        # Exception hierarchy (stays as-is)
```

## Data Flow

```
Frontend: callable("start_sync")
    │
    ▼
main.py: Plugin.start_sync()                  # 2 lines: await self._sync.start()
    │
    ▼
services/sync.py: SyncService.start()         # Business logic: fetch platforms,
    │                                          # compute delta, plan shortcuts
    │ calls self._rom_api.get_platforms()
    ▼
adapters/romm/rom_api.py: RomRomApi           # HTTP call to RomM
    │
    │ calls self._rom_api.get_roms(platform_id)
    ▼
adapters/romm/rom_api.py: RomRomApi           # HTTP call to RomM
    │
    │ returns SyncDelta to main.py
    ▼
main.py: emits sync_preview event to frontend
```

```
Frontend: callable("resolve_conflict", rom_id, resolution)
    │
    ▼
main.py: Plugin.resolve_conflict()
    │
    ▼
services/save_sync.py: SaveSyncService.resolve()
    │                                          # Pure logic: check resolution mode,
    │                                          # decide upload vs download
    │ calls self._api.upload_save() or self._api.download_save()
    ▼
adapters/romm/save_api/v47.py                 # POST /api/saves (4.7.0+)
   or
adapters/romm/save_api/v46.py                 # POST /api/saves (4.6.x workaround)
```

## Version Routing

RomM version is detected on connection test via `GET /api/heartbeat` → `SYSTEM.VERSION`.

The `VersionRouter` selects the correct adapter implementation:

| Version | Save API | Device Registration | Conflict Detection |
|---------|----------|--------------------|--------------------|
| < 4.6.1 | v46 (with warning) | Local UUID | Client-side only |
| 4.6.x | v46 | Local UUID | Client-side only |
| 4.7.0+ | v47 | POST /api/devices | Client-side + server-side 409 |
| "development" | v47 | POST /api/devices | Client-side + server-side 409 |

The router is updated after each successful connection test. Services never check versions directly — they call the protocol interface, the router handles the dispatch.

## Testing Strategy

| Layer | Test type | Speed | Dependencies |
|-------|-----------|-------|-------------|
| models/ | Unit | Instant | None |
| services/ | Unit | Fast | `unittest.mock.patch` or fakes for adapters |
| adapters/ | Integration | Slower | May need mocks for HTTP, real files for persistence |
| main.py | Smoke | Slow | Full bootstrap |

**Fakes vs Mocks**: Use fakes (in-memory Protocol implementations) where we have multiple real implementations — specifically `SaveApiProtocol` which has v46 and v47 backends. A `FakeSaveApi` is more readable and reusable than mocking internals. For everything else, `unittest.mock.patch` is fine and pragmatic. Don't rewrite 800 working tests to chase an ideal.

```
tests/
├── test_save_sync_service.py        # SaveSyncService + FakeSaveApi
├── test_sync_service.py             # SyncService + mocked adapters
├── test_romm_client.py              # HTTP mocking (existing)
├── test_persistence.py              # Real tmp files
├── fakes/
│   └── fake_save_api.py             # Implements SaveApiProtocol in-memory
└── ...
```

## Migration Plan

Incremental, one service at a time. No big-bang rewrite.

### Phase R1: Foundation

1. Create directory structure (`models/`, `services/`, `adapters/`)
2. Define domain dataclasses (`models.py`, `settings.py`, `state.py`)
3. Extract `persistence.py` from `StateMixin` (load/save settings, state, caches)
4. Extract `RommHttpClient` from `RommClientMixin` (generic HTTP, SSL, auth, retry)
5. Write `bootstrap.py` skeleton
6. `main.py` starts using bootstrap but still has mixins for unmigrated services

### Phase R2: Save Sync (aligns with Phase 8)

1. Define `SaveApiProtocol` in `adapters/romm/save_api/protocol.py`
2. Extract current save API calls from `save_sync.py` → `v46.py`
3. Implement `v47.py` with new RomM 4.7.0 endpoints
4. Extract business logic from `SaveSyncMixin` → `SaveSyncService`
5. Wire via `VersionRouter` in bootstrap
6. Remove `SaveSyncMixin`
7. Write `FakeSaveApi` + rewrite save sync tests against it

### Phase R3: Sync + Downloads

1. Extract ROM API calls → `adapters/romm/rom_api.py`
2. Extract `SyncMixin` → `SyncService`
3. Extract `DownloadMixin` → `DownloadService`
4. Remove both mixins

### Phase R4: Remaining Services

1. Extract `FirmwareMixin` → `FirmwareService` + `adapters/romm/firmware_api.py`
2. Extract `AchievementsMixin` → `AchievementService` + `adapters/romm/achievement_api.py`
3. Extract `MetadataMixin` → `MetadataService`
4. Extract `SgdbMixin` → `SgdbService` + `adapters/sgdb_client.py`
5. Extract `SteamConfigMixin` → `adapters/steam_config.py`
6. Remove all remaining mixins
7. `main.py` is now purely delegation, ~150 lines

### Rules During Migration

- **Never two architectures in the same service.** When migrating SaveSync, it goes fully to the new pattern. No half-mixin-half-service.
- **Tests migrate with the service.** Old mixin tests get rewritten against the service + fakes.
- **Unmigrated mixins keep working.** They coexist with services during transition. `Plugin` has both `self._save_sync` (new service) and `SyncMixin` (old mixin) until Sync is migrated.
- **Each phase is a mergeable PR.** No long-lived refactor branches.
