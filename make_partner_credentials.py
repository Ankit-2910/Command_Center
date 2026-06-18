"""
OBSIDIAN — Partner Credential Generator (Stage 6B admin helper)

Mints API keys and webhook signing secrets. Run from Render Shell or locally
with DATABASE_URL set:

    python make_partner_credentials.py apikey  "Acme Corp"
    python make_partner_credentials.py webhook "Acme Corp" https://acme.com/obsidian-hook 70

The raw API key is printed ONCE. Only its SHA-256 hash is stored. If the partner
loses the key, you mint a new one — you cannot recover the original.
"""
import sys
import secrets
import hashlib
from sqlalchemy import text
from db import get_session


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_api_key(partner_name: str):
    raw = "obsk_" + secrets.token_urlsafe(32)  # ~43 url-safe chars
    key_hash = _hash_key(raw)
    key_prefix = raw[:12]

    with get_session() as s:
        s.execute(text("""
            INSERT INTO obs_api_keys (partner_name, key_hash, key_prefix, scopes, active)
            VALUES (:pn, :kh, :kp, 'read', TRUE)
        """), {"pn": partner_name, "kh": key_hash, "kp": key_prefix})

    print("\n  API KEY CREATED")
    print(f"  Partner   : {partner_name}")
    print(f"  Key prefix: {key_prefix}")
    print(f"  RAW KEY   : {raw}")
    print("  ^ Give this to the partner ONCE. It is not stored and cannot be recovered.\n")


def make_webhook(partner_name: str, target_url: str, min_severity: int = 70):
    secret = "whsec_" + secrets.token_urlsafe(32)

    with get_session() as s:
        s.execute(text("""
            INSERT INTO obs_webhooks
            (partner_name, target_url, signing_secret, min_severity, active)
            VALUES (:pn, :url, :sec, :ms, TRUE)
        """), {"pn": partner_name, "url": target_url, "sec": secret, "ms": min_severity})

    print("\n  WEBHOOK REGISTERED")
    print(f"  Partner       : {partner_name}")
    print(f"  Target URL    : {target_url}")
    print(f"  Min severity  : {min_severity}")
    print(f"  SIGNING SECRET: {secret}")
    print("  ^ Give this to the partner to verify the X-OBSIDIAN-Signature header.\n")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "apikey":
        make_api_key(sys.argv[2])
    elif cmd == "webhook":
        url = sys.argv[3]
        sev = int(sys.argv[4]) if len(sys.argv) > 4 else 70
        make_webhook(sys.argv[2], url, sev)
    else:
        print(__doc__)
        sys.exit(1)
