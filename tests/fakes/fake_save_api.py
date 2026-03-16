"""In-memory SaveApiProtocol implementation for service tests."""

from __future__ import annotations

from datetime import datetime, timezone


class FakeSaveApi:
    """In-memory fake that satisfies SaveApiProtocol without HTTP."""

    def __init__(self) -> None:
        self.saves: dict[int, dict] = {}  # save_id -> save dict
        self.roms: dict[int, dict] = {}  # rom_id -> rom detail dict
        self.notes: dict[int, list[dict]] = {}  # rom_id -> [note dicts]
        self.uploaded_files: dict[int, str] = {}  # save_id -> file_path
        self.downloaded_files: dict[int, str] = {}  # save_id -> dest_path
        self.call_log: list[tuple[str, tuple, dict]] = []
        self._next_save_id = 1000
        self._next_note_id = 2000
        self._fail_on_next: Exception | None = None

    def fail_on_next(self, exc: Exception) -> None:
        """Make the next call raise the given exception."""
        self._fail_on_next = exc

    def _check_fail(self) -> None:
        if self._fail_on_next is not None:
            exc = self._fail_on_next
            self._fail_on_next = None
            raise exc

    async def list_saves(self, rom_id: int) -> list[dict]:
        self.call_log.append(("list_saves", (rom_id,), {}))
        self._check_fail()
        return [s for s in self.saves.values() if s.get("rom_id") == rom_id]

    async def upload_save(
        self,
        rom_id: int,
        file_path: str,
        emulator: str,
        save_id: int | None = None,
    ) -> dict:
        self.call_log.append(("upload_save", (rom_id, file_path, emulator), {"save_id": save_id}))
        self._check_fail()

        import os

        filename = os.path.basename(file_path)
        now = datetime.now(timezone.utc).isoformat()
        size = os.path.getsize(file_path) if os.path.isfile(file_path) else 0

        if save_id and save_id in self.saves:
            entry = self.saves[save_id]
            entry["updated_at"] = now
            entry["file_size_bytes"] = size
            entry["emulator"] = emulator
        else:
            # Check for upsert by filename
            existing = None
            for s in self.saves.values():
                if s.get("rom_id") == rom_id and s.get("file_name") == filename:
                    existing = s
                    break
            if existing:
                save_id = existing["id"]
                existing["updated_at"] = now
                existing["file_size_bytes"] = size
                existing["emulator"] = emulator
                entry = existing
            else:
                save_id = self._next_save_id
                self._next_save_id += 1
                entry = {
                    "id": save_id,
                    "rom_id": rom_id,
                    "file_name": filename,
                    "updated_at": now,
                    "file_size_bytes": size,
                    "emulator": emulator,
                    "download_path": f"/saves/{filename}",
                }
                self.saves[save_id] = entry

        self.uploaded_files[save_id] = file_path
        return dict(entry)

    async def download_save(self, save_id: int, dest_path: str) -> None:
        self.call_log.append(("download_save", (save_id, dest_path), {}))
        self._check_fail()

        self.downloaded_files[save_id] = dest_path

        # If we have uploaded content for this save, copy it
        if save_id in self.uploaded_files:
            import shutil

            src = self.uploaded_files[save_id]
            import os

            if os.path.isfile(src):
                shutil.copy2(src, dest_path)
                return

        # Write default content so the file exists
        with open(dest_path, "wb") as f:
            f.write(b"\x00" * 1024)

    async def get_save_metadata(self, save_id: int) -> dict:
        self.call_log.append(("get_save_metadata", (save_id,), {}))
        self._check_fail()
        if save_id in self.saves:
            return dict(self.saves[save_id])
        return {"id": save_id, "download_path": f"/saves/unknown_{save_id}"}

    async def get_rom_detail(self, rom_id: int) -> dict:
        self.call_log.append(("get_rom_detail", (rom_id,), {}))
        self._check_fail()
        detail = self.roms.get(rom_id, {"id": rom_id})
        # Attach notes
        detail = dict(detail)
        detail["all_user_notes"] = self.notes.get(rom_id, [])
        return detail

    async def create_note(self, rom_id: int, data: dict) -> dict:
        self.call_log.append(("create_note", (rom_id, data), {}))
        self._check_fail()
        note_id = self._next_note_id
        self._next_note_id += 1
        note = {"id": note_id, "rom_id": rom_id, **data}
        self.notes.setdefault(rom_id, []).append(note)
        return dict(note)

    async def update_note(self, rom_id: int, note_id: int, data: dict) -> dict:
        self.call_log.append(("update_note", (rom_id, note_id, data), {}))
        self._check_fail()
        for notes in self.notes.values():
            for note in notes:
                if note.get("id") == note_id:
                    note.update(data)
                    return dict(note)
        return {"id": note_id, "rom_id": rom_id, **data}
