"""Pure save-sync display computation.

No I/O, no service/adapter imports. Stateless functions only.
"""

from __future__ import annotations

from datetime import UTC, datetime


def compute_save_sync_display(
    files: list[dict] | None,
    last_sync_check_at: str | None,
) -> dict:
    """Compute save sync display status and label.

    Returns dict with 'status' ('synced' | 'conflict' | 'none') and 'label' (str).
    """
    if not files:
        return {"status": "none", "label": "No saves"}

    has_conflict = any(f.get("status") == "conflict" for f in files)
    if has_conflict:
        return {"status": "conflict", "label": "Conflict"}

    has_local = any(f.get("local_path") or f.get("status") in ("synced", "upload") for f in files)
    if has_local:
        if last_sync_check_at:
            try:
                check_dt = datetime.fromisoformat(last_sync_check_at)
                now = datetime.now(UTC)
                if check_dt.tzinfo is None:
                    check_dt = check_dt.replace(tzinfo=UTC)
                diff_sec = (now - check_dt).total_seconds()
                diff_min = int(diff_sec // 60)
                if diff_min < 1:
                    label = "Just now"
                elif diff_min < 60:
                    label = f"{diff_min}m ago"
                elif diff_min < 1440:
                    label = f"{diff_min // 60}h ago"
                else:
                    label = f"{diff_min // 1440}d ago"
                return {"status": "synced", "label": label}
            except (ValueError, TypeError):
                pass
        return {"status": "synced", "label": "Not synced"}

    return {"status": "none", "label": "No local saves"}
