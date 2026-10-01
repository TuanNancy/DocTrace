"""Bound expensive uploads per API process; reject excess work rather than queue PDFs."""
from anyio import WouldBlock
from fastapi import HTTPException, Request


async def require_upload_slot(request: Request):
    limiter = request.app.state.upload_limiter
    try:
        limiter.acquire_nowait()
    except WouldBlock:
        raise HTTPException(
            status_code=429, detail="Another PDF is being indexed. Please try again shortly.",
            headers={"Retry-After": "5"},
        )
    try:
        yield
    finally:
        limiter.release()
