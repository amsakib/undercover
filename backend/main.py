"""The UnderCover backend."""

from fastapi import FastAPI

from backend.routers import claims, documents, reference, runs

app = FastAPI(title="UnderCover")
for module in (claims, documents, reference, runs):
    app.include_router(module.router)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}
