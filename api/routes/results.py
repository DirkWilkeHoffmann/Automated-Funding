import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api import dependencies
from api.schemas import BulkDeleteRequest, RefreshResultsResponse, ResultsResponse, StaleResultsResponse
from utils import tools
from utils.db.client import get_supabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/results", tags=["results"])


@router.get("/", response_model=ResultsResponse)
def list_results(
    response: Response,
    force_refresh: bool = Query(False),
    tools_module: tools = Depends(dependencies.get_tools_module),
    _user=Depends(dependencies.require_user),
) -> ResultsResponse:
    if force_refresh:
        tools_module.clear_results_cache()
    df = tools_module.load_results_csv(force_refresh=force_refresh)
    df = tools_module.latest_results_by_url(df)
    records = df.to_dict(orient="records") if not df.empty else []
    response.headers["Cache-Control"] = "no-store"
    return ResultsResponse(results=records)


@router.get("/stale", response_model=StaleResultsResponse)
def list_stale_results(
    response: Response,
    months: int = Query(3, ge=1, le=24),
    force_refresh: bool = Query(False),
    tools_module: tools = Depends(dependencies.get_tools_module),
    _user=Depends(dependencies.require_user),
) -> StaleResultsResponse:
    if force_refresh:
        tools_module.clear_results_cache()
    df = tools_module.load_results_csv(force_refresh=force_refresh)
    stale_df = tools_module.stale_results_by_url(df, months=months)
    records = stale_df.to_dict(orient="records") if not stale_df.empty else []
    cutoff = tools_module.subtract_months(datetime.now(), months).isoformat()
    response.headers["Cache-Control"] = "no-store"
    return StaleResultsResponse(results=records, months=months, cutoff_timestamp=cutoff)


@router.post("/delete", status_code=status.HTTP_200_OK)
def delete_results(
    payload: BulkDeleteRequest,
    tools_module: tools = Depends(dependencies.get_tools_module),
    _user=Depends(dependencies.require_user),
) -> dict:
    if not payload.urls:
        return {"deleted": 0}
    try:
        get_supabase().table("funds").delete().in_("fund_url", payload.urls).execute()
        tools_module.clear_results_cache()
        return {"deleted": len(payload.urls)}
    except Exception as exc:
        logger.exception("Failed to delete %d results", len(payload.urls))
        raise HTTPException(status_code=500, detail="Failed to delete results. Please try again.")


@router.post("/refresh", response_model=RefreshResultsResponse)
def refresh_results(
    response: Response,
    tools_module: tools = Depends(dependencies.get_tools_module),
    _user=Depends(dependencies.require_user),
) -> RefreshResultsResponse:
    tools_module.clear_results_cache()
    df = tools_module.load_results_csv(force_refresh=True)
    response.headers["Cache-Control"] = "no-store"
    return RefreshResultsResponse(total_results=len(df.index))
