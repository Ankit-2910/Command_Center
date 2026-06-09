"""
OBSIDIAN — Zero-state fallback
Caches last successful feed snapshot in Supabase.
Serves cached data when live feed returns empty.
"""
import json
from datetime import datetime, timezone
from sqlalchemy import text
from db import get_session

SNAPSHOT_KEY = "live_feed_latest"

def save_snapshot(payload: dict, is_demo: bool = False) -> None:
    """Call after every successful feed collection."""
    with get_session() as s:
        s.execute(text("""
            INSERT INTO obs_feed_cache (snapshot_key, payload, captured_at, is_demo)
            VALUES (:key, :payload, NOW(), :demo)
            ON CONFLICT (snapshot_key)
            DO UPDATE SET 
                payload = EXCLUDED.payload,
                captured_at = NOW(),
                is_demo = EXCLUDED.is_demo
        """), {
            "key": SNAPSHOT_KEY,
            "payload": json.dumps(payload),
            "demo": is_demo
        })

def load_snapshot() -> dict | None:
    """Returns cached snapshot dict with metadata, or None if cache empty."""
    with get_session() as s:
        row = s.execute(text("""
            SELECT payload, captured_at, is_demo
            FROM obs_feed_cache
            WHERE snapshot_key = :key
        """), {"key": SNAPSHOT_KEY}).fetchone()
        
        if not row:
            return None
        
        captured = row.captured_at
        age_minutes = int((datetime.now(timezone.utc) - captured).total_seconds() / 60)
        
        return {
            "data": row.payload,
            "captured_at": captured.isoformat(),
            "age_minutes": age_minutes,
            "is_demo": row.is_demo
        }