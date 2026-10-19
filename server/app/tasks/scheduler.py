"""APScheduler 调度器装配。

五个提醒/定版时点（与《需求规格说明书》7.1 一致）：

| 任务            | 触发时机          | 说明                       |
|-----------------|-------------------|----------------------------|
| roll_call       | 周一 00:05        | 生成本周点名名册           |
| remind fri_1000 | 周五 10:00        | 首次提醒                   |
| remind fri_1700 | 周五 17:00        | 截止预警（仅未动笔者）     |
| remind sun_2000 | 周日 20:00        | 周末催办                   |
| remind mon_0830 | 周一 08:30        | 最后通牒 + 抄送组长        |
| finalize        | 周一 09:30        | 定版结算 + 推送统计摘要    |
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.tasks import jobs

logger = get_logger(__name__)

scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)

_JOBS = [
    (jobs.job_generate_roll_call, CronTrigger(day_of_week="mon", hour=0, minute=5), "roll_call"),
    (jobs.job_remind, CronTrigger(day_of_week="fri", hour=10, minute=0), "remind_fri_1000"),
    (jobs.job_remind, CronTrigger(day_of_week="fri", hour=17, minute=0), "remind_fri_1700"),
    (jobs.job_remind, CronTrigger(day_of_week="sun", hour=20, minute=0), "remind_sun_2000"),
    (jobs.job_remind, CronTrigger(day_of_week="mon", hour=8, minute=30), "remind_mon_0830"),
    (jobs.job_finalize, CronTrigger(day_of_week="mon", hour=9, minute=30), "finalize"),
]

# 提醒任务的相位参数与 job id 一一对应
_PHASE_OF_ID = {
    "remind_fri_1000": "fri_1000",
    "remind_fri_1700": "fri_1700",
    "remind_sun_2000": "sun_2000",
    "remind_mon_0830": "mon_0830",
}


def start_scheduler() -> None:
    """注册并启动全部定时任务（受 ``SCHEDULER_ENABLED`` 控制）。"""
    if not settings.scheduler_enabled:
        logger.info("定时任务已关闭（SCHEDULER_ENABLED=false）")
        return
    if scheduler.running:
        return

    for func, trigger, job_id in _JOBS:
        args = [phase] if (phase := _PHASE_OF_ID.get(job_id)) else []
        scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=job_id,
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
            args=args,
        )

    scheduler.start()
    jobs.run_startup_backfill()
    logger.info("定时任务已启动，共注册 %s 个", len(_JOBS))


def shutdown_scheduler() -> None:
    """优雅停止调度器（等待运行中的任务结束，最多 10 秒）。"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("定时任务已停止")


def run_job_now(job_id: str) -> None:
    """手动触发一次任务（供管理员在界面/命令行排障用）。"""
    mapping = {
        "roll_call": lambda: jobs.job_generate_roll_call(),
        "finalize": jobs.job_finalize,
        **{key: (lambda phase=phase: jobs.job_remind(phase)) for key, phase in _PHASE_OF_ID.items()},
    }
    func = mapping.get(job_id)
    if func is None:
        raise KeyError(f"未知任务：{job_id}")
    func()
