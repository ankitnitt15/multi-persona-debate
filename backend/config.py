import os

DAILY_USER_CAP = int(os.getenv("DAILY_USER_CAP", "3"))
GLOBAL_DAILY_CALL_CAP = int(os.getenv("GLOBAL_DAILY_CALL_CAP", "300"))

MAX_TOPIC_CHARS = int(os.getenv("MAX_TOPIC_CHARS", "300"))
MIN_PERSONAS = 2
MAX_PERSONAS = 4

# The optional display name a user gives so persona statements read as
# "The Pragmatist Tom" instead of just "The Pragmatist" -- capped short
# since it's only ever used as a label suffix, never free-form content.
MAX_NAME_CHARS = int(os.getenv("MAX_NAME_CHARS", "40"))

# Comma-separated list -- the hosted frontend's origin(s).
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5500").split(",")
    if origin.strip()
]

# Cross-site cookies (frontend and backend on different domains) need
# SameSite=None + Secure, which in turn requires HTTPS. For local dev over
# plain http://localhost, leave these at their defaults.
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# Shared secret for GET /admin/stats -- unset by default so the endpoint is
# effectively disabled (returns 404) until you deliberately turn it on.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
