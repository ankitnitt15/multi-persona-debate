import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Noisy at INFO (a line or two per single Gemini call) and not useful for
# this app's own request/response logging -- keep only warnings+.
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="Multi-Persona Debate API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(router, prefix="/api")
