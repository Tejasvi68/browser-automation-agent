"""
Scheduler Service – runs saved workflows on a recurring cron schedule.

Uses APScheduler (AsyncIOScheduler) so jobs run on the same asyncio event
loop as the FastAPI app without spawning new threads.

A workflow is scheduled when the user saves it with a schedule_cron field
(e.g. "0 9 * * *" for every day at 9 AM). Jobs survive server restarts
only if APScheduler is configured with a persistent job store (not shown here).
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database.database import SessionLocal
from app.services.automation_service import automation_service


class SchedulerService:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Starts the scheduler if it isn't already running. Called on app startup."""
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self) -> None:
        """Stops the scheduler gracefully. Called on app shutdown."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def schedule_workflow(self, workflow_id: str, user_id: str, task_prompt: str, cron_expr: str) -> None:
        """
        Schedules a workflow to run automatically on a cron schedule.

        cron_expr must be a standard 5-field expression:
          "minute hour day_of_month month day_of_week"
          e.g. "0 9 * * *" = every day at 9:00 AM

        Raises ValueError if the expression doesn't have exactly 5 fields.
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(
                "Cron expression must have exactly 5 fields: "
                "'minute hour day month day_of_week'  "
                f"(got: '{cron_expr}')"
            )

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

        # Each scheduled run gets its own DB session
        async def _run_scheduled_job():
            db = SessionLocal()
            try:
                await automation_service.start_task(db=db, user_id=user_id, task=task_prompt)
            finally:
                db.close()

        self.scheduler.add_job(
            _run_scheduled_job,
            trigger=trigger,
            id=f"wf_{workflow_id}",
            replace_existing=True,   # Update if the same workflow is re-saved
        )

    def remove_schedule(self, workflow_id: str) -> None:
        """Removes a scheduled job. Safe to call even if the job doesn't exist."""
        job_id = f"wf_{workflow_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)


# Single shared instance used by the FastAPI app and workflow routes
scheduler_service = SchedulerService()
