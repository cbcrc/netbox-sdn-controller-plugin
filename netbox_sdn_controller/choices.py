from typing import List
from django.utils.translation import gettext_lazy as _
from core.choices import JobStatusChoices
from utilities.choices import ChoiceSet


class DevicePrototypeStatusChoices(ChoiceSet):
    """
    Choices for the synchronization status of SDN Controller Device Prototypes.

    Attributes:
        key (str): The unique identifier for the choice set.
        DISCOVERED (str): Status indicating the device prototype has been discovered.
        IMPORTED (str): Status indicating the device prototype has been imported.
        DELETED (str): Status indicating the device prototype has been marked as deleted.
        CHOICES (List[Tuple[str, str, str]]): List of status choices, each represented as
            a tuple of the status key, display label, and associated color.
    """
    key = 'SdnControllerDevicePrototype.sync_status'

    DISCOVERED = 'discovered'
    IMPORTED = 'imported'
    DELETED = 'deleted'

    CHOICES = [
        (DISCOVERED, _('Discovered'), 'yellow' ),
        (IMPORTED, _('Imported'), 'green'),
        (DELETED, _('Archived'), 'red'),
    ]


unfinished_job_status: List[str] = [
    JobStatusChoices.STATUS_PENDING,
    JobStatusChoices.STATUS_RUNNING,
    JobStatusChoices.STATUS_SCHEDULED,
]
