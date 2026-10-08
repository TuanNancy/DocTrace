"""Bound upload admission per API process; indexing runs separately in RQ."""
from anyio import WouldBlock
from fastapi import HTTPException, Request


async def require_upload_slot(request: Request):
    limiter = request.app.state.upload_limiter
    try:
        limiter.acquire_nowait()
    except WouldBlock:
        raise HTTPException(
            status_code=429, detail="Máy chủ đang tiếp nhận một PDF khác. Vui lòng thử lại sau 5 giây.",
            headers={"Retry-After": "5"},
        )
    try:
        yield
    finally:
        limiter.release()
