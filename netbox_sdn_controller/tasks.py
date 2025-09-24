import traceback
from typing import Any, Dict, List, Optional
import uuid
import django_rq
from django.utils.translation import gettext_lazy as _
from utilities.exceptions import AbortScript
from utilities.rqworker import get_queue_for_model
from core.choices import JobStatusChoices
from core.models import Job, ObjectType
from extras.scripts import BaseScript
from .models import SdnController, SdnControllerDevicePrototype
from .choices import DevicePrototypeStatusChoices
from .sdnmanager.sdn_manager import SdnManager
from .utils import get_link_text


def fetch(sdn_controller_id: int, user_id: Optional[int] = None) -> None:
    """
    Fetch task for SDN Controller synchronization.

    Args:
        sdn_controller_id (int): ID of the SDN Controller.
        user_id (Optional[int]): ID of the user initiating the fetch (if applicable).

    Returns:
        None
    """
    current_sdn_controller = SdnController.objects.filter(id=sdn_controller_id).first()

    script_module = ObjectType.objects.get(app_label="extras", model="scriptmodule")
    rq_queue_name = get_queue_for_model(script_module.model)
    queue = django_rq.get_queue(rq_queue_name)

    params={"sdn_controller_id": sdn_controller_id}
    if user_id:
        params["user_id"] = user_id

    job = Job.objects.create(
        object_type=script_module,
        status=JobStatusChoices.STATUS_PENDING,
        job_id=uuid.uuid4(),
        data={'input': params}
    )
    current_sdn_controller.last_fetch_job = job
    current_sdn_controller.save()
    queue.enqueue(run_task, job_id=str(job.job_id), job=job, job_timeout=7200, **params)

def create_in_netbox(sdn_controller_id: int, prototype_id_list: List[int], user_id: Optional[int] = None, fetch_and_sync=False) -> None:
    """
    Create a synchronization job in NetBox for the given SDN Controller and device prototypes.

    This function creates a job in the NetBox system to synchronize device prototypes with
    a specified SDN Controller. The job is enqueued in the appropriate queue for asynchronous
    processing.

    Args:
        sdn_controller_id (int): The ID of the SDN Controller to sync with.
        prototype_id_list (List[int]): A list of IDs for the device prototypes to be synchronized.
        user_id (Optional[int]): ID of the user initiating the sync (if applicable).

    Returns:
        None
    """

    current_sdn_controller = SdnController.objects.filter(id=sdn_controller_id).first()

    script_module = ObjectType.objects.get(app_label="extras", model="scriptmodule")
    rq_queue_name = get_queue_for_model(script_module.model)
    queue = django_rq.get_queue(rq_queue_name)
    params={"sdn_controller_id": sdn_controller_id, "prototype_id_list": prototype_id_list}
    if fetch_and_sync:
        params["fetch_and_sync"] = True

    if user_id:
        params["user_id"] = user_id
    job = Job.objects.create(
        object_type=script_module,
        status=JobStatusChoices.STATUS_PENDING,
        job_id=uuid.uuid4(),
        data={'input': params}
    )
    current_sdn_controller.last_sync_job = job
    current_sdn_controller.save()
    queue.enqueue(run_task, job_id=str(job.job_id), job=job, job_timeout=7200, **params)

def run_task(job: Job, **kwargs: Any) -> None:
    """
    Run the task associated with the job.

    Args:
        job (Job): The job object representing the task.
        kwargs (Any): Additional keyword arguments for the task.
    """
    if kwargs.get("prototype_id_list", None):
        if kwargs.get("fetch_and_sync", None):
            script = FetchAndSync()
        else:
            script = ImportDataInNetBox()
    else:
        script = NetworkControllerFetch()

    script.log_info(f"Task: {type(script).__name__}")
    commit = kwargs.get("commit", True)
    try:
        job.start()
        try:
            script.output = script.run(kwargs, commit)

        except Exception as e:
            if isinstance(e, AbortScript):
                msg = _("Script aborted with error: ") + str(e)
                script.log_failure(msg)
            else:
                stacktrace = traceback.format_exc()
                script.log_failure(
                    message=_("An exception occurred: ") + f"`{type(e).__name__}: {e}`\n```\n{stacktrace}\n```"
                )
        finally:
            job.data.update(script.get_job_data())
        job.terminate()
    except Exception as e:
        job.terminate(status=JobStatusChoices.STATUS_ERRORED, error=repr(e))


class NetworkControllerFetch(BaseScript):
    """Fetch data from a network controller"""
    class Meta:
        description = "Fetch Data From Network Controller"

    def run(self, data: Dict[str, Any], _) -> bool:
        """
        Run method for NetworkControllerFetch script.

        Args:
            data (Dict[str, Any]): Input data for the script.
            _ (Any): Ignored argument.

        Returns:
            bool: True if the script executes successfully.
        """
        kwargs = {"pk": data['sdn_controller_id'],
                  "log_all_errors": False}
        user_id = data.get('user_id', None)
        if user_id:
            kwargs["user_id"] = user_id
        sdn_manager = SdnManager(script=self, **kwargs)

        sdn_manager.sync_sdn_controller_devices()
        sdn_manager.check_for_deleted_devices()

        sdn_manager.prototype_object_list = SdnControllerDevicePrototype.objects.exclude(
            sync_status=DevicePrototypeStatusChoices.DELETED
        )

        job_success = sdn_manager.import_fetched_elements_in_netbox()
        sdn_manager.find_missing_interface_types()
        sdn_manager.sdn_controller.save()

        self.log_info(f"Verify fetch result for : {get_link_text(sdn_manager.sdn_controller)}")

        return job_success

class ImportDataInNetBox(BaseScript):
    """
    A script to import data into NetBox from an SDN Controller.

    This script fetches data from an SDN Controller using the provided data,
    processes the elements, and imports them into NetBox. It also logs the result
    of the import operation.

    Attributes:
        Meta.description (str): A brief description of the script.
    """
    class Meta:
        description = "Import data in NetBox"

    def run(self, data: Dict[str, Any], _: Any) -> bool:
        """
        Executes the script to import data into NetBox.

        Args:
            data (Dict[str, Any]): A dictionary containing the input data required for import.
                Expected keys:
                - 'sdn_controller_id' (int): The ID of the SDN Controller to fetch data from.
                - 'prototype_id_list' (List[int]): A list of IDs of device prototypes to process.
            _ (Any): Placeholder for additional arguments, currently unused.

        Returns:
            bool: True if the import process was successful, otherwise False.
        """

        kwargs = {"pk": data['sdn_controller_id'],
                  "prototype_id_list": data["prototype_id_list"],
                  "log_all_errors": True}

        user_id = data.get('user_id', None)
        if user_id:
            kwargs["user_id"] = user_id
        sdn_manager = SdnManager(script=self, **kwargs)
        job_success = sdn_manager.import_fetched_elements_in_netbox()
        sdn_manager.sdn_controller.last_sync_job_success = job_success
        sdn_manager.sdn_controller.save()

        self.log_info(f"Verify import result for : {get_link_text(sdn_manager.sdn_controller)}")
        return job_success

class FetchAndSync(BaseScript):
    """
    Script to fetch and synchronize data from an SDN controller.

    This script triggers the `sync_sdn_controller_devices` and
    `import_fetched_elements_in_netbox` methods using the provided controller ID
    and prototype list. Optionally, a user ID can be included for audit or tracking.
    """

    class Meta:
        description = "Fetch and Sync"

    def run(self, data: Dict[str, Any], _: Any) -> bool:
        """Run the fetch and sync operation for the SDN controller.

        Args:
            data (Dict[str, Any]): Dictionary containing input parameters:
                - 'sdn_controller_id' (int): ID of the SDN controller.
                - 'prototype_id_list' (List[int]): List of prototype IDs to sync.
                - 'user_id' (Optional[int]): Optional ID of the user running the script.
            _ (Any): Placeholder for unused argument (typically context or request).

        Returns:
            bool: True if the import was successful, False otherwise.
        """

        kwargs = {"pk": data['sdn_controller_id'],
                  "prototype_id_list": data["prototype_id_list"],
                  "fetch_and_sync": True,
                  "log_all_errors": True}

        user_id = data.get('user_id', None)
        if user_id:
            kwargs["user_id"] = user_id
        sdn_manager = SdnManager(script=self, **kwargs)
        sdn_manager.sync_sdn_controller_devices()
        job_success = sdn_manager.import_fetched_elements_in_netbox()
        sdn_manager.sdn_controller.last_sync_job_success = job_success
        sdn_manager.sdn_controller.save()

        self.log_info(f"Verify import result for : {get_link_text(sdn_manager.sdn_controller)}")
        return job_success
