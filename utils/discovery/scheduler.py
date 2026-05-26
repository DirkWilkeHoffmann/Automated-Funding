"""APScheduler integration for the discovery pipeline."""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

JOB_ID = "auto_discovery"
BMF_IMPORT_JOB_ID = "bmf_import"
GRANTS_GOV_IMPORT_JOB_ID = "grants_gov_import"

_scheduler: Optional[BackgroundScheduler] = None


def _get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            job_defaults={"coalesce": True, "max_instances": 1},
            timezone="UTC",
        )
    return _scheduler


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
    """Monthly IRS BMF import — runs 1st of month at 3am UTC."""
    try:
        from utils.discovery.importers.irs_bmf import run_bmf_import
        run_bmf_import()
    except Exception as exc:
        logger.error("Scheduled BMF import raised: %s", exc, exc_info=True)


def _grants_gov_import_job() -> None:
    """Daily Grants.gov XML import — runs at 5am UTC."""
    try:
        from utils.discovery.importers.grants_gov_xml import run_grants_gov_import
        run_grants_gov_import()
    except Exception as exc:
        logger.error("Scheduled Grants.gov import raised: %s", exc, exc_info=True)


def start_scheduler() -> None:
    """
    Start the APScheduler BackgroundScheduler and register the discovery job.
    Reads the current cron_expression from discovery_config (defaults to Mon 2am UTC).
    Called once from FastAPI lifespan startup.
    """
    sched = _get_scheduler()
    if sched.running:
        logger.debug("Scheduler already running")
        return

    cron = "0 2 * * 1"  # default: Monday 2am UTC
    try:
        from utils.discovery.config_store import load_config
        cfg = load_config()
        cron = cfg.get("cron_expression") or cron
    except Exception as exc:
        logger.warning("Could not load discovery config for scheduler; using default cron: %s", exc)

    try:
        trigger = CronTrigger.from_crontab(cron, timezone="UTC")
    except Exception:
        logger.warning("Invalid cron expression %r; falling back to default", cron)
        trigger = CronTrigger.from_crontab("0 2 * * 1", timezone="UTC")

    sched.add_job(
        _discovery_job,
        trigger=trigger,
        id=JOB_ID,
        replace_existing=True,
    )
    sched.add_job(
        _bmf_import_job,
        trigger=CronTrigger.from_crontab("0 3 1 * *", timezone="UTC"),
        id=BMF_IMPORT_JOB_ID,
        replace_existing=True,
    )
    sched.add_job(
        _grants_gov_import_job,
        trigger=CronTrigger.from_crontab("0 5 * * *", timezone="UTC"),
        id=GRANTS_GOV_IMPORT_JOB_ID,
        replace_existing=True,
    )
    sched.start()
    logger.info("Discovery scheduler started (cron=%r)", cron)


def stop_scheduler() -> None:
    """Shutdown the scheduler gracefully. Called on FastAPI lifespan exit."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Discovery scheduler stopped")
    _scheduler = None


def reschedule_discovery(cron_expression: str) -> None:
    """
    Update the scheduled discovery job with a new cron expression.
    Called by the config update endpoint whenever cron_expression changes.
    """
    sched = _get_scheduler()
    if not sched.running:
        logger.warning("Scheduler not running; cannot reschedule")
        return
    try:
        trigger = CronTrigger.from_crontab(cron_expression, timezone="UTC")
        sched.reschedule_job(JOB_ID, trigger=trigger)
        logger.info("Discovery job rescheduled to cron=%r", cron_expression)
    except Exception as exc:
        logger.error("Could not reschedule discovery job: %s", exc)
