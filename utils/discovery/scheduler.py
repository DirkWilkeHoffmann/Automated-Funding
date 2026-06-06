"""APScheduler integration for the discovery pipeline.

Manages five recurring jobs:

| Job ID                  | Default cron       | What it does                              |
|-------------------------|--------------------|-------------------------------------------|
| auto_discovery          | 0 2 * * 1          | Run the discovery orchestrator            |
| bmf_import              | 0 3 * * 0          | Refresh IRS Business Master File          |
| irs_990_index_import    | 0 4 * * 0          | Refresh IRS 990 e-file index (2yr window) |
| grants_gov_import       | 0 5 * * *          | Refresh Grants.gov XML extract (daily)    |
| sam_cfda_import         | 0 6 * * 0          | Refresh SAM.gov Assistance Listings/CFDA  |

Each dataset's cron can be overridden via discovery_config.import_config.*_cron
keys — see config_store._IMPORT_CONFIG_DEFAULTS for the defaults.
"""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

JOB_ID = "auto_discovery"
BMF_IMPORT_JOB_ID = "bmf_import"
IRS_990_INDEX_IMPORT_JOB_ID = "irs_990_index_import"
GRANTS_GOV_IMPORT_JOB_ID = "grants_gov_import"
SAM_CFDA_IMPORT_JOB_ID = "sam_cfda_import"

# Defaults — kept in sync with config_store._IMPORT_CONFIG_DEFAULTS so the
# scheduler still boots if the config row is missing.
_DEFAULT_BMF_CRON = "0 3 * * 0"
_DEFAULT_IRS_990_INDEX_CRON = "0 4 * * 0"
_DEFAULT_GRANTS_GOV_CRON = "0 5 * * *"
_DEFAULT_SAM_CFDA_CRON = "0 6 * * 0"
_DEFAULT_DISCOVERY_CRON = "0 2 * * 1"

_scheduler: Optional[BackgroundScheduler] = None


def _get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            job_defaults={"coalesce": True, "max_instances": 1},
            timezone="UTC",
        )
    return _scheduler


# ── Job wrappers (lazy imports avoid circular references at module load) ─────


def _discovery_job() -> None:
    """Wrapper so APScheduler can call run_discovery without an import cycle at load time."""
    try:
        from utils.discovery.config_store import clear_config_cache
        from utils.discovery.orchestrator import run_discovery
        clear_config_cache()
        run_discovery(trigger="scheduled")
    except Exception as exc:
        logger.error("Scheduled discovery job raised: %s", exc, exc_info=True)


def _bmf_import_job() -> None:
    """Weekly IRS BMF import."""
    try:
        from utils.discovery.importers.irs_bmf import run_bmf_import
        run_bmf_import()
    except Exception as exc:
        logger.error("Scheduled BMF import raised: %s", exc, exc_info=True)


def _irs_990_index_import_job() -> None:
    """Weekly IRS 990 e-file index refresh — current year + 1 prior year."""
    try:
        from datetime import datetime, timezone
        from utils.discovery.sources.irs_990_index import refresh_index_for_year
        current_year = datetime.now(timezone.utc).year
        for year in (current_year - 1, current_year):
            try:
                refresh_index_for_year(year, force=False)
            except Exception as exc:
                logger.warning("990 index refresh for %s failed: %s", year, exc)
    except Exception as exc:
        logger.error("Scheduled 990 index import raised: %s", exc, exc_info=True)


def _grants_gov_import_job() -> None:
    """Daily Grants.gov XML import."""
    try:
        from utils.discovery.importers.grants_gov_xml import run_grants_gov_import
        run_grants_gov_import()
    except Exception as exc:
        logger.error("Scheduled Grants.gov import raised: %s", exc, exc_info=True)


def _sam_cfda_import_job() -> None:
    """Weekly SAM.gov Assistance Listings (CFDA) import."""
    try:
        from utils.discovery.importers.sam_cfda import run_sam_cfda_import
        run_sam_cfda_import()
    except Exception as exc:
        logger.error("Scheduled SAM.gov CFDA import raised: %s", exc, exc_info=True)


# ── Trigger building ─────────────────────────────────────────────────────────


def _trigger(cron: str, fallback: str) -> CronTrigger:
    """Parse a cron expression, falling back to a known-good default on failure."""
    try:
        return CronTrigger.from_crontab(cron, timezone="UTC")
    except Exception:
        logger.warning("Invalid cron %r; falling back to %r", cron, fallback)
        return CronTrigger.from_crontab(fallback, timezone="UTC")


def _load_crons() -> dict:
    """Read all 5 cron expressions from discovery_config, with defaults.

    Returns a dict of {key: cron_string} for each job.
    """
    crons = {
        "discovery": _DEFAULT_DISCOVERY_CRON,
        "bmf": _DEFAULT_BMF_CRON,
        "irs_990_index": _DEFAULT_IRS_990_INDEX_CRON,
        "grants_gov": _DEFAULT_GRANTS_GOV_CRON,
        "sam_cfda": _DEFAULT_SAM_CFDA_CRON,
    }
    try:
        from utils.discovery.config_store import load_config, load_import_config
        cfg = load_config()
        crons["discovery"] = cfg.get("cron_expression") or crons["discovery"]
        ic = load_import_config()
        crons["bmf"] = ic.get("bmf_cron") or crons["bmf"]
        crons["irs_990_index"] = ic.get("irs_990_index_cron") or crons["irs_990_index"]
        crons["grants_gov"] = ic.get("grants_gov_cron") or crons["grants_gov"]
        crons["sam_cfda"] = ic.get("sam_cfda_cron") or crons["sam_cfda"]
    except Exception as exc:
        logger.warning("Could not load cron overrides from discovery_config: %s", exc)
    return crons


# ── Lifecycle ────────────────────────────────────────────────────────────────


def start_scheduler() -> None:
    """Register all 5 jobs and start the scheduler. Idempotent."""
    sched = _get_scheduler()
    if sched.running:
        logger.debug("Scheduler already running")
        return

    crons = _load_crons()

    sched.add_job(
        _discovery_job,
        trigger=_trigger(crons["discovery"], _DEFAULT_DISCOVERY_CRON),
        id=JOB_ID,
        replace_existing=True,
    )
    sched.add_job(
        _bmf_import_job,
        trigger=_trigger(crons["bmf"], _DEFAULT_BMF_CRON),
        id=BMF_IMPORT_JOB_ID,
        replace_existing=True,
    )
    sched.add_job(
        _irs_990_index_import_job,
        trigger=_trigger(crons["irs_990_index"], _DEFAULT_IRS_990_INDEX_CRON),
        id=IRS_990_INDEX_IMPORT_JOB_ID,
        replace_existing=True,
    )
    sched.add_job(
        _grants_gov_import_job,
        trigger=_trigger(crons["grants_gov"], _DEFAULT_GRANTS_GOV_CRON),
        id=GRANTS_GOV_IMPORT_JOB_ID,
        replace_existing=True,
    )
    sched.add_job(
        _sam_cfda_import_job,
        trigger=_trigger(crons["sam_cfda"], _DEFAULT_SAM_CFDA_CRON),
        id=SAM_CFDA_IMPORT_JOB_ID,
        replace_existing=True,
    )

    sched.start()
    logger.info(
        "Discovery scheduler started (discovery=%r, bmf=%r, 990idx=%r, grants=%r, sam=%r)",
        crons["discovery"], crons["bmf"], crons["irs_990_index"],
        crons["grants_gov"], crons["sam_cfda"],
    )


def stop_scheduler() -> None:
    """Shutdown the scheduler gracefully. Called on FastAPI lifespan exit."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Discovery scheduler stopped")
    _scheduler = None


def reschedule_discovery(cron_expression: str) -> None:
    """Update the scheduled discovery job's cron without restarting."""
    sched = _get_scheduler()
    if not sched.running:
        logger.warning("Scheduler not running; cannot reschedule")
        return
    try:
        trigger = _trigger(cron_expression, _DEFAULT_DISCOVERY_CRON)
        sched.reschedule_job(JOB_ID, trigger=trigger)
        logger.info("Discovery job rescheduled to cron=%r", cron_expression)
    except Exception as exc:
        logger.error("Could not reschedule discovery job: %s", exc)


def reschedule_imports() -> None:
    """Re-read import_config crons from discovery_config and re-trigger the 4 import jobs.

    Called after a PUT /discovery/config when the operator changes any of the
    per-dataset cron overrides. The discovery job itself is rescheduled via
    reschedule_discovery() — this function only touches the 4 import jobs.
    """
    sched = _get_scheduler()
    if not sched.running:
        logger.warning("Scheduler not running; cannot reschedule imports")
        return
    crons = _load_crons()
    for job_id, cron, fallback in [
        (BMF_IMPORT_JOB_ID,           crons["bmf"],           _DEFAULT_BMF_CRON),
        (IRS_990_INDEX_IMPORT_JOB_ID, crons["irs_990_index"], _DEFAULT_IRS_990_INDEX_CRON),
        (GRANTS_GOV_IMPORT_JOB_ID,    crons["grants_gov"],    _DEFAULT_GRANTS_GOV_CRON),
        (SAM_CFDA_IMPORT_JOB_ID,      crons["sam_cfda"],      _DEFAULT_SAM_CFDA_CRON),
    ]:
        try:
            sched.reschedule_job(job_id, trigger=_trigger(cron, fallback))
        except Exception as exc:
            logger.warning("Could not reschedule %s: %s", job_id, exc)
    logger.info(
        "Import jobs rescheduled (bmf=%r, 990idx=%r, grants=%r, sam=%r)",
        crons["bmf"], crons["irs_990_index"], crons["grants_gov"], crons["sam_cfda"],
    )
