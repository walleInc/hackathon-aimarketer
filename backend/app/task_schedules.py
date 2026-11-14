"""UTC execution times, with calendar recurrences anchored in an IANA timezone."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def local_instant(day, clock: str, zone: str) -> datetime:
    naive = datetime.combine(day, datetime.strptime(clock, "%H:%M").time())
    tz = ZoneInfo(zone)
    # fold=0 selects the first occurrence. Advance through a DST gap minute by minute.
    for _ in range(181):
        aware = naive.replace(tzinfo=tz, fold=0)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(tz).replace(tzinfo=None) == naive:
            return utc.replace(tzinfo=None)
        naive += timedelta(minutes=1)
    raise ValueError("Недопустимое местное время")


def following(task, after: datetime) -> datetime | None:
    if task.schedule_kind == "once":
        return None
    if task.schedule_kind in ("interval", "legacy"):
        return after + timedelta(minutes=task.interval_minutes)
    tz = ZoneInfo(task.timezone)
    day = after.replace(tzinfo=timezone.utc).astimezone(tz).date()
    days = {int(x) for x in task.weekdays.split(",") if x}
    for offset in range(9):
        candidate_day = day + timedelta(days=offset)
        if task.schedule_kind == "weekly" and candidate_day.weekday() not in days:
            continue
        candidate = local_instant(candidate_day, task.local_time, task.timezone)
        if candidate > after:
            return candidate
    raise ValueError("Не найдена следующая дата")


def latest_due(task, initial: datetime, now: datetime) -> datetime:
    if task.schedule_kind in ("interval", "legacy"):
        step = timedelta(minutes=task.interval_minutes)
        return initial + max(0, (now - initial) // step) * step
    if task.schedule_kind == "once":
        return initial
    # Find the most recent calendar slot without walking through years of downtime.
    start = max(initial - timedelta(microseconds=1), now - timedelta(days=8))
    current = following(task, start)
    latest = initial
    while current and current <= now:
        latest = current
        current = following(task, current)
    return latest
