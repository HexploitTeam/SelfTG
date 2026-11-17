# Com/scheduler.py
"""One background loop for every periodic job.

Why a single loop: one ``asyncio.sleep`` task per reminder (or per AFK cooldown)
disappears on restart, leaks when cancelled, and each task is a little more
memory on a 2 GiB Repl. Here there is exactly one task, it wakes on a fixed
tick, and each job reads its own persisted state to decide what is due. A
restart therefore resumes everything from disk instead of losing timers.

Jobs are registered by the command modules at import/setup time::

    scheduler.register("remind", remind.tick)

and each job is awaited inside its own try/except, so one broken job can never
stop the tick loop or reach the Telethon event loop.

The task reference lives here and is cancelled by main._shutdown(), which keeps
shutdown ordering (jobs stop before the client disconnects) explicit.
"""
import asyncio
import logging

log = logging.getLogger("selftg.scheduler")

TICK_SECONDS = 20
STARTUP_GRACE = 3  # let the client finish login before the first tick

_jobs = []
_task = None
_started_at = None


def register(name, job):
    """Add a periodic job: `job(client)` may be sync or async."""
    if any(existing == name for existing, _ in _jobs):
        return
    _jobs.append((name, job))


def jobs():
    return [name for name, _ in _jobs]


def started_at():
    """Unix time of the first tick, used to mark reminders missed while offline."""
    return _started_at


async def _run_job(name, job, client):
    try:
        result = job(client)
        if asyncio.iscoroutine(result):
            await result
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - isolation boundary for the whole tick
        log.exception("scheduler: job %s failed", name)


async def _loop(client):
    global _started_at
    await asyncio.sleep(STARTUP_GRACE)
    import time as _time

    _started_at = _time.time()
    log.info("scheduler: started with jobs %s", ", ".join(jobs()) or "none")

    while True:
        for name, job in list(_jobs):
            await _run_job(name, job, client)
        await asyncio.sleep(TICK_SECONDS)


def start(client):
    """Start the loop once. Safe to call again after a reconnect."""
    global _task
    if not _jobs:
        log.info("scheduler: no jobs registered, not starting")
        return None
    if _task is not None and not _task.done():
        return _task
    _task = asyncio.create_task(_loop(client), name="selftg-scheduler")
    return _task


async def stop():
    """Cancel the loop and wait for it, so nothing runs after shutdown starts."""
    global _task
    task, _task = _task, None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:  # noqa: BLE001
        log.exception("scheduler: error while stopping")
