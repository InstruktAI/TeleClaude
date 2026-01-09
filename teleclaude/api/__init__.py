"""REST API for telec and other local clients."""

from fastapi import FastAPI

from teleclaude.api.routes import router

app = FastAPI(title="TeleClaude API", version="1.0.0")
app.include_router(router)
