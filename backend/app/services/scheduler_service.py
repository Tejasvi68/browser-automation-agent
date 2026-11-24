from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.database.database import SessionLocal
from app.services.automation_service import automation_service


class SchedulerService:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def schedule_workflow(self, workflow_id: str, user_id: str, task_prompt: str, cron_expr: str) -> None:
        """Schedules a recurring workflow using a standard 5-part cron string (min hour day month dow)."""
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError("Cron expression must have 5 fields: 'minute hour day month day_of_week'")

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

        async def _job():
            db = SessionLocal()
            try:
                await automation_service.start_task(db=db, user_id=user_id, task=task_prompt)
            finally:
                db.close()

        self.scheduler.add_job(
            _job,
            trigger=trigger,
            id=f"wf_{workflow_id}",
            replace_existing=True,
        )

    def remove_schedule(self, workflow_id: str) -> None:
        job_id = f"wf_{workflow_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)


scheduler_service = SchedulerService()