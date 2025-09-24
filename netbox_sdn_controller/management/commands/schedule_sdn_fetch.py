import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from django.core.management.base import BaseCommand
from netbox.jobs import JobRunner
from netbox_sdn_controller.models import SdnController
from netbox_sdn_controller.tasks import fetch


class DailySdnFetchJob(JobRunner):
    """
    Job that fetches SDN Controller data on a daily basis.

    This job is specific to the Cisco Catalyst Center SDN Controller.
    """

    class Meta:
        name = "Daily Cisco Catalyst Center SDN Controller Fetch"
        model = SdnController

    def run(self, *args: Any, **kwargs: Any) -> None:

        sdn_controller_id = kwargs.get("sdn_controller_id", None)
        if sdn_controller_id:
            fetch(int(sdn_controller_id))


class Command(BaseCommand):
    """Django management command to schedule a daily SDN fetch job."""

    help = "Schedule a daily SDN fetch job."

    def handle(self, *args: Any, **options: Any) -> None:
        """
        Schedules the DailySdnFetchJob to run every 24 hours, starting at the configured hour.

        Environment Variables:
            SDN_FETCH_HOUR (int or str): The hour at which the job should run daily (0–23). Default is 6.
            SDN_FETCH_TIMEZONE (str): IANA time zone name for scheduling. Default is 'America/Toronto'.

        This will look for a SdnController of type "Catalyst Center" and enqueue a job
        starting at the specified time (adjusted to UTC), repeating every 1440 minutes.
        """
        hour_fetch_raw = os.getenv("SDN_FETCH_HOUR", "4") #ALSO SET IN deplops-apps-deployment
        try:
            hour_fetch = int(hour_fetch_raw)
        except ValueError:
            hour_fetch = 6

        interval_in_minutes_raw = os.getenv("SDN_INTERVAL_IN_MINUTES", "1440")
        try:
            interval_in_minutes = int(interval_in_minutes_raw)
        except ValueError:
            interval_in_minutes = 1440  #1440 minutes = 24 hours

        timezone_fetch = os.getenv("SDN_FETCH_TIMEZONE", "America/Toronto")
        local_tz = ZoneInfo(timezone_fetch)
        local_now = datetime.now(local_tz)
        abbrev_zone = local_now.tzname()

        scheduled_time = datetime.combine(
            local_now.date(), time(hour=hour_fetch, minute=1), tzinfo=local_tz
        )

        if scheduled_time < local_now:
            scheduled_time += timedelta(days=1)

        scheduled_time_utc_naive = scheduled_time.astimezone(ZoneInfo("UTC")).replace(
            tzinfo=None
        )

        sdn_controller = SdnController.objects.filter(
            sdn_type="Catalyst Center"
        ).first()

        if sdn_controller:
            DailySdnFetchJob.enqueue_once(
                schedule_at=scheduled_time_utc_naive,
                interval=interval_in_minutes,
                instance=sdn_controller,
                sdn_controller_id=sdn_controller.id,
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Scheduled daily SDN fetch for {scheduled_time.isoformat()} {abbrev_zone}"
                )
            )
