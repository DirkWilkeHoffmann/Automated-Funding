# api/routes/pending.py
"""Pending URLs — listing-page sub-URLs awaiting user review before scraping."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api import dependencies
from api.schemas import ApprovePendingRequest, RejectPendingRequest
from utils.db.pending_urls_store import (
    approve_batch,
    list_pending,
    mark_scraped,
    pending_count,
    reject_batch,
)

router = APIRouter(prefix="/admin/pending-urls", tags=["pending-urls"])


@router.get("")
async def list_pending_urls(user=Depends(dependencies.require_superuser)):
    """Return all awaiting_review pending URLs."""
    return list_pending(status="awaiting_review")


@router.get("/count")
async def get_pending_count(user=Depends(dependencies.require_superuser)):
    """Return count of awaiting_review rows (for notification badge)."""
    return {"count": pending_count()}


@router.post("/approve")
async def approve_pending_urls(body: ApprovePendingRequest, user=Depends(dependencies.require_superuser)):
    """Approve a batch of pending URLs and trigger a scrape job for them."""
    if not body.ids:
        raise HTTPException(status_code=400, detail="No ids provided")

    urls = approve_batch(body.ids, user_id=str(user.id) if hasattr(user, "id") else None)
    if not urls:
        raise HTTPException(status_code=404, detail="No matching pending URLs found")

    from api.jobs import JobStore
    from utils.scrape_worker import start_background_scrape

    job_id = JobStore.create(urls)
    progress = start_background_scrape(urls, job_id=job_id)
    JobStore.attach(job_id, progress)
    mark_scraped(body.ids, scrape_job_id=job_id)

    return {"job_id": job_id, "url_count": len(urls), "urls": urls}


@router.post("/reject")
async def reject_pending_urls(body: RejectPendingRequest, user=Depends(dependencies.require_superuser)):
    """Mark a batch of pending URLs as rejected."""
    if not body.ids:
        raise HTTPException(status_code=400, detail="No ids provided")
    reject_batch(body.ids)
    return {"rejected": len(body.ids)}
