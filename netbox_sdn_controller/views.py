from typing import Type
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.db.models import QuerySet
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as _
from utilities.views import register_model_view, ViewTab
from dcim.models.devices import Device
from dcim.views import ModuleEditView, ModuleView, DeviceEditView, DeviceView
from dcim.forms import ModuleForm, DeviceForm
from core.models import ObjectType
from netbox.views import generic
from extras.models import CustomField, CustomFieldChoiceSet
from extras.choices import CustomFieldTypeChoices, CustomFieldFilterLogicChoices
from . import forms, models, tables, filtersets, tasks, choices


def fetch_job_not_ready(instance: models.SdnController) -> bool:
    """
    Checks if the last fetch job for the given SDN controller instance is not ready.

    Args:
        instance (models.SdnController): The SDN controller instance.

    Returns:
        bool: True if the last fetch job is not ready, False otherwise.
    """
    if instance.last_fetch_job:
        return instance.last_fetch_job.status in choices.unfinished_job_status
    return False

def fetch_status(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Retrieves the fetch status and related counts for a specific SDN controller.

    Args:
        request (HttpRequest): The HTTP request object.
        pk (int): The primary key of the SDN controller.

    Returns:
        JsonResponse: A JSON response containing fetch status and counts.
    """
    obj: models.SdnController = get_object_or_404(models.SdnController, pk=pk)
    last_fetch_job_not_ready: bool = fetch_job_not_ready(obj)

    deleted_count: int = models.SdnControllerDevicePrototype.objects.filter(
        sync_status=choices.DevicePrototypeStatusChoices.DELETED, sdn_controller=obj).count()

    inventory_count: int = models.SdnControllerDevicePrototype.objects.filter(sdn_controller=obj).exclude(
        sync_status=choices.DevicePrototypeStatusChoices.DELETED
    ).count()

    discovered_count: int = models.SdnControllerDevicePrototype.objects.filter(
        sync_status=choices.DevicePrototypeStatusChoices.DISCOVERED, sdn_controller=obj).count()

    imported_count: int = models.SdnControllerDevicePrototype.objects.filter(
        sync_status=choices.DevicePrototypeStatusChoices.IMPORTED, sdn_controller=obj).count()

    data: dict = {
        "last_fetch_status": obj.last_fetch_job.status if obj.last_fetch_job else "N/A",
        "last_sync_status": obj.last_sync_job.status if obj.last_sync_job else "N/A",
        "last_fetch_job_not_ready": last_fetch_job_not_ready,
        "deleted_count": deleted_count,
        "inventory_count": inventory_count,
        "discovered_count": discovered_count,
        "imported_count": imported_count,
        "last_sync_job_success": obj.last_sync_job_success
    }

    return JsonResponse(data)


@require_POST
def launch_task(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Launches an asynchronous task to fetch data related to the SDN controller.

    Args:
        request (HttpRequest): The HTTP request object.
        pk (int): The primary key of the SDN controller.

    Returns:
        HttpResponse: A redirect response to the referring URL.
    """
    user_id = request.user.id
    tasks.fetch(pk, user_id)  # pk is the SDN controller ID
    return redirect(request.META.get('HTTP_REFERER'))

@require_POST
def transfer_to_netbox_task(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Processes a bulk action for transferring selected elements to NetBox.

    Args:
        request (HttpRequest): The HTTP request object.
        pk (int): The primary key of the SDN controller.

    Returns:
        HttpResponse: A redirect response to the SDN controller detail page.
    """
    selected_ids = request.POST.getlist('pk')  # List of selected object IDs
    if not selected_ids:
        # Optional: Handle the case where no items are selected
        return redirect('plugins:netbox_sdn_controller:sdncontroller', pk=pk)
    user_id = request.user.id
    tasks.create_in_netbox(pk, selected_ids, user_id)
    return redirect('plugins:netbox_sdn_controller:sdncontroller', pk=pk)

@require_POST
def fetch_selected_task(request: HttpRequest, pk: int) -> HttpResponse:
    """Handles a POST request to fetch and sync selected SDN controller tasks.

    This view extracts selected object IDs from the POST request, then triggers
    task creation in NetBox using the provided controller primary key and user ID.

    Args:
        request (HttpRequest): The HTTP request object containing POST data and user info.
        pk (int): The primary key of the SDN controller.

    Returns:
        HttpResponse: A redirect response to the SDN controller detail view.
    """
    selected_ids = request.POST.getlist('pk')  # List of selected object IDs
    if not selected_ids:
        # Optional: Handle the case where no items are selected
        return redirect('plugins:netbox_sdn_controller:sdncontroller', pk=pk)
    user_id = request.user.id
    tasks.create_in_netbox(pk, selected_ids, user_id, True)
    return redirect('plugins:netbox_sdn_controller:sdncontroller', pk=pk)

@require_POST
def sync_prototype_task(request: HttpRequest, pk: int) -> HttpResponse:
    """Synchronizes a prototype task for a given SDN controller device.

    Args:
        request (HttpRequest): The HTTP request object.
        pk (int): The primary key of the `SdnControllerDevicePrototype` instance.

    Returns:
        HttpResponse: A redirect response to the SDN controller detail view.
    """

    current_prototype = models.SdnControllerDevicePrototype.objects.filter(id=pk).first()
    instance_uuid = current_prototype.instance_uuid

    #Same stack devices / switches
    related_prototype_ids = list(models.SdnControllerDevicePrototype.objects.filter(
        instance_uuid=instance_uuid
    ).values_list("id", flat=True)
    )
    user_id = request.user.id
    sdn_controller_id = current_prototype.sdn_controller_id
    tasks.create_in_netbox(sdn_controller_id, related_prototype_ids, user_id)
    return redirect('plugins:netbox_sdn_controller:sdncontroller', pk=sdn_controller_id)

@require_POST
def fetch_and_sync_prototype_task(request: HttpRequest, pk: int) -> HttpResponse:
    """Fetches and synchronizes all device prototypes sharing the same instance UUID.

    This view locates the current device prototype by ID, finds all related prototypes
    in the same stack (i.e., with the same instance UUID), and triggers a NetBox
    synchronization task for them.

    Args:
        request (HttpRequest): The HTTP request containing user info.
        pk (int): The primary key of the selected device prototype.

    Returns:
        HttpResponse: A redirect response to the SDN controller detail page.
    """
    current_prototype = models.SdnControllerDevicePrototype.objects.filter(id=pk).first()
    instance_uuid = current_prototype.instance_uuid

    #Same stack devices / switches
    related_prototype_ids = list(models.SdnControllerDevicePrototype.objects.filter(
        instance_uuid=instance_uuid
    ).values_list("id", flat=True)
    )
    user_id = request.user.id
    sdn_controller_id = current_prototype.sdn_controller_id
    tasks.create_in_netbox(sdn_controller_id, related_prototype_ids, user_id, True)
    return redirect('plugins:netbox_sdn_controller:sdncontroller', pk=sdn_controller_id)


class SdnControllerListView(generic.ObjectListView):
    """
    View to list all SDN Controllers.

    Attributes:
        queryset: A query set of all SDN Controllers.
        table: A table for displaying the SDN Controllers.
        filterset: A filterset for filtering SDN Controllers.
    """
    queryset = models.SdnController.objects.all()
    table = tables.SdnControllerTable

    filterset = filtersets.SdnControllerFilterSet

class SdnControllerView(generic.ObjectView):
    """
    View to display details of a specific SDN Controller.

    Attributes:
        queryset: A query set of all SDN Controllers.
    """
    queryset = models.SdnController.objects.all()

    def get_extra_context(self, request, instance: models.SdnController) -> dict:
        """
        Adds additional context to the view for displaying SDN controller details.

        Args:
            request: The HTTP request object.
            instance: The SDN controller instance.

        Returns:
            dict: Additional context data for the view.
        """
        instance.last_fetch_job_not_ready = fetch_job_not_ready(instance)

        return {
            'request_format': 'json'
        }

class SdnControllerEditView(generic.ObjectEditView):
    """
    View to edit an SDN Controller.

    Attributes:
        queryset: A query set of all SDN Controllers.
        form: The form for editing SDN Controllers.
    """
    queryset = models.SdnController.objects.all()
    form = forms.SdnControllerForm


class SdnControllerDeleteView(generic.ObjectDeleteView):
    """
    View to delete an SDN Controller.

    Attributes:
        queryset: A query set of all SDN Controllers.
    """
    queryset = models.SdnController.objects.all()




class SdnControllerDevicePrototypeListView(generic.ObjectListView):
    """
    View to list all SDN Controller Device Prototypes.

    Attributes:
        queryset: A query set of all SDN Controller Device Prototypes.
        table: A table for displaying the device prototypes.
        filterset: A filterset for filtering device prototypes.
    """
    queryset = models.SdnControllerDevicePrototype.objects.order_by("instance_uuid","stack_index").all()
    table = tables.SdnControllerDevicePrototypeTable
    filterset = filtersets.SdnControllerDevicePrototypeFilterSet
    filterset_form = forms.SdnControllerDevicePrototypeFilterForm

class SdnControllerDevicePrototypeView(generic.ObjectView):
    """
    View to display details of a specific SDN Controller Device Prototype.

    Attributes:
        queryset: A query set of all SDN Controller Device Prototypes.
    """
    queryset = models.SdnControllerDevicePrototype.objects.all()

    def get_extra_context(self, request, instance: models.SdnControllerDevicePrototype) -> dict:
        """
        Adds additional context to the view for displaying SDN controller device prototype details.

        Args:
            request: The HTTP request object.
            instance: The device prototype instance.

        Returns:
            dict: Additional context data for the view.
        """
        return {'request_format': 'json'}


class SdnControllerDevicePrototypeEditView(generic.ObjectEditView):
    """
    View to edit a specific SDN Controller Device Prototype.

    Attributes:
        queryset: A query set of all SDN Controller Device Prototypes.
        form: The form for editing device prototypes.
    """
    queryset = models.SdnControllerDevicePrototype.objects.all()
    form = forms.SdnControllerDevicePrototypeForm


class SdnControllerDevicePrototypeDeleteView(generic.ObjectDeleteView):
    """
    View to delete a specific SDN Controller Device Prototype.

    Attributes:
        queryset: A query set of all SDN Controller Device Prototypes.
    """
    queryset = models.SdnControllerDevicePrototype.objects.all()

class SdnControllerDevicePrototypeBulkEditView(generic.BulkEditView):
    """
    View to edit multiple SDN Controller Device Prototypes.

    Attributes:
        queryset: A query set of all SDN Controller Device Prototypes.
        filterset: A filterset for filtering device prototypes.
        table: A table for displaying device prototypes.
        form: The form for bulk editing device prototypes.
    """
    queryset = models.SdnControllerDevicePrototype.objects.all()
    filterset = filtersets.SdnControllerDevicePrototypeFilterSet
    table = tables.SdnControllerDevicePrototypeTable
    form = forms.SdnControllerDevicePrototypeBulkEditForm

class SdnControllerDevicePrototypeBulkDeleteView(generic.BulkDeleteView):
    """
    View to delete multiple SDN Controller Device Prototypes.

    Attributes:
        queryset: A query set of all SDN Controller Device Prototypes.
        filterset: A filterset for filtering device prototypes.
        table: A table for displaying device prototypes.
    """
    queryset = models.SdnControllerDevicePrototype.objects.all()
    filterset = filtersets.SdnControllerDevicePrototypeFilterSet
    table = tables.SdnControllerDevicePrototypeTable


@register_model_view(Device, 'SDN')
class DnacDataView(generic.ObjectView):
    """
    View to display data for the DNAC equivalent of a device.

    Attributes:
        template_name: The template to use for the view.
        queryset: A query set of all devices.
        tab: The tab for displaying the SDN data.
    """
    template_name = 'netbox_sdn_controller/sdncontrollerdeviceprototypecontext.html'
    queryset = Device.objects.all()

    tab = ViewTab(
        label=_('SDN'),
        weight=509,
        badge=lambda obj: get_dnac_equivalent_count(obj),
        hide_if_empty=True
    )

    def get_extra_context(self, request, instance: Device) -> dict:
        """
        Adds extra context for the DNAC data view.

        Args:
            request: The HTTP request object.
            instance: The device instance.

        Returns:
            dict: The context data for the view.
        """
        context_data = instance.get_config_context()
        context_data.update({'device': instance})

        actual_dnac_config = models.SdnControllerDevicePrototype.objects.filter(
            matching_netbox_device_id=instance.id).first()

        return {
            'context_data': context_data,
            'request_format': 'json',
            'dnac_config': actual_dnac_config
        }

def get_dnac_equivalent_count(parent: models.SdnController) -> int:
    """
    Returns the count of DNAC-equivalent device prototypes for a given parent SDN controller.

    Args:
        parent: The SDN controller instance.

    Returns:
        int: The number of equivalent device prototypes.
    """
    return 1 if models.SdnControllerDevicePrototype.objects.filter(matching_netbox_device_id=parent.id) else 0



@register_model_view(models.SdnController, name='imported', path='imported')
class ImportedChildrenView(generic.ObjectChildrenView):
    """
    View to display imported SDN controller device prototypes.

    Args:
        generic.ObjectChildrenView: Inherited class to view object children.
    """
    child_model = models.SdnControllerDevicePrototype
    table = tables.SdnControllerDevicePrototypeTable
    filterset = filtersets.SdnControllerDevicePrototypeFilterSet
    template_name = 'netbox_sdn_controller/prototype_list.html'
    queryset = models.SdnController.objects.all()

    tab = ViewTab(
        label=_('Imported'),
        badge=lambda obj: models.SdnControllerDevicePrototype.objects.filter(
            sync_status=choices.DevicePrototypeStatusChoices.IMPORTED, sdn_controller=obj).count(),
        weight=509,
        hide_if_empty=False
    )

    def get_children(self, request: HttpRequest, parent: models.SdnController) -> QuerySet:
        """
        Retrieves the children (SDN controller device prototypes) that are marked as 'IMPORTED'.

        Args:
            request: The HTTP request object.
            parent: The parent SDN controller object.

        Returns:
            QuerySet: A QuerySet of imported SDN controller device prototypes.
        """
        return self.child_model.objects.filter(
            sync_status=choices.DevicePrototypeStatusChoices.IMPORTED, sdn_controller=parent
        ).order_by("instance_uuid", "stack_index")


@register_model_view(models.SdnController, name='discovered', path='discovered')
class DiscoveredChildrenView(generic.ObjectChildrenView):
    """
    View to display 'Discovered' SDN controller device prototypes.

    Args:
        generic.ObjectChildrenView: Inherited class to view object children.
    """
    child_model: Type[models.SdnControllerDevicePrototype] = models.SdnControllerDevicePrototype
    table: Type[tables.SdnControllerDevicePrototypeTable] = tables.SdnControllerDevicePrototypeTable
    filterset: Type[filtersets.SdnControllerDevicePrototypeFilterSet] = filtersets.SdnControllerDevicePrototypeFilterSet
    template_name = 'netbox_sdn_controller/prototype_list.html'
    queryset: QuerySet[models.SdnController] = models.SdnController.objects.all()

    tab: ViewTab = ViewTab(
        label=_('Discovered'),
        badge=lambda obj: models.SdnControllerDevicePrototype.objects.filter(
            sync_status=choices.DevicePrototypeStatusChoices.DISCOVERED, sdn_controller=obj).count(),
        weight=511,
        hide_if_empty=False
    )

    def get_children(self,
                     request: HttpRequest,
                     parent: models.SdnController
                     ) -> QuerySet[models.SdnControllerDevicePrototype]:
        """
        Retrieves the children (SDN controller device prototypes) that are marked as 'DISCOVERED'.

        Args:
            request: The HTTP request object.
            parent: The parent SDN controller object.

        Returns:
            QuerySet: A QuerySet of discovered SDN controller device prototypes.
        """
        if parent.last_sync_job:
            parent.last_sync_job_not_ready = (
                parent.last_sync_job.status in choices.unfinished_job_status
            )
        else:
            parent.last_sync_job_not_ready = False

        return self.child_model.objects.filter(
            sync_status=choices.DevicePrototypeStatusChoices.DISCOVERED, sdn_controller=parent
        ).order_by("instance_uuid", "stack_index")


@register_model_view(models.SdnController, name='deleted', path='deleted')
class DeletedChildrenView(generic.ObjectChildrenView):
    """
    View to display 'Deleted' SDN controller device prototypes.

    Args:
        generic.ObjectChildrenView: Inherited class to view object children.
    """
    child_model: Type[models.SdnControllerDevicePrototype] = models.SdnControllerDevicePrototype
    table: Type[tables.SdnControllerDevicePrototypeTable] = tables.SdnControllerDevicePrototypeTable
    filterset: Type[filtersets.SdnControllerDevicePrototypeFilterSet] = filtersets.SdnControllerDevicePrototypeFilterSet
    template_name: str = 'generic/object_children.html'
    queryset: QuerySet[models.SdnController] = models.SdnController.objects.all()

    tab: ViewTab = ViewTab(
        label=_('Archived'),
        badge=lambda obj: models.SdnControllerDevicePrototype.objects.filter(
            sync_status=choices.DevicePrototypeStatusChoices.DELETED, sdn_controller=obj).count(),
        weight=517,
        hide_if_empty=False
    )

    def get_children(self,
                     request: HttpRequest,
                     parent: models.SdnController
                     ) -> QuerySet[models.SdnControllerDevicePrototype]:
        """
        Retrieves the children (SDN controller device prototypes) that are marked as 'DELETED'.

        Args:
            request: The HTTP request object.
            parent: The parent SDN controller object.

        Returns:
            QuerySet: A QuerySet of deleted SDN controller device prototypes.
        """
        return self.child_model.objects.filter(
            sync_status=choices.DevicePrototypeStatusChoices.DELETED, sdn_controller=parent
        ).order_by("instance_uuid", "stack_index")


@register_model_view(models.SdnController, name='inventory', path='inventory')
class InventoryChildrenView(generic.ObjectChildrenView):
    """
    View to display all SDN controller device prototypes in the inventory.

    Args:
        generic.ObjectChildrenView: Inherited class to view object children.
    """
    child_model: Type[models.SdnControllerDevicePrototype] = models.SdnControllerDevicePrototype
    table: Type[tables.SdnControllerDevicePrototypeTable] = tables.SdnControllerDevicePrototypeTable
    filterset: Type[filtersets.SdnControllerDevicePrototypeFilterSet] = filtersets.SdnControllerDevicePrototypeFilterSet
    template_name = 'netbox_sdn_controller/prototype_list.html'
    queryset: QuerySet[models.SdnController] = models.SdnController.objects.all()

    tab: ViewTab = ViewTab(
        label=_('Inventory'),
        badge=lambda obj: models.SdnControllerDevicePrototype.objects.filter(sdn_controller=obj
        ).exclude(
            sync_status=choices.DevicePrototypeStatusChoices.DELETED
        ).count(),
        weight=515,
        hide_if_empty=False
    )

    def get_children(self,
                     request: HttpRequest,
                     parent: models.SdnController
                     ) -> QuerySet[models.SdnControllerDevicePrototype]:
        """
        Retrieves the children (SDN controller device prototypes) from the inventory.

        Args:
            request: The HTTP request object.
            parent: The parent SDN controller object.

        Returns:
            QuerySet: A QuerySet of SDN controller device prototypes in the inventory.
        """
        return self.child_model.objects.filter(
            sdn_controller=parent
        ).exclude(
            sync_status=choices.DevicePrototypeStatusChoices.DELETED
        ).order_by("instance_uuid", "stack_index")

@register_model_view(models.SdnModule, 'edit')
class SdnModuleEditView(ModuleEditView):
    """View for editing SdnModule objects."""
    queryset = models.SdnModule.objects.all()
    form = ModuleForm

@register_model_view(models.SdnModule)
class SdnModuleView(ModuleView):
    """View for displaying SdnModule objects."""
    queryset = models.SdnModule.objects.all()

@register_model_view(models.SdnDevice, 'edit')
class SdnDeviceEditView(DeviceEditView):
    """View for editing SdnDevice objects."""
    queryset = models.SdnDevice.objects.all()
    form = DeviceForm

@register_model_view(models.SdnDevice)
class SdnDeviceView(DeviceView):
    """View for displaying SdnDevice objects."""
    queryset = models.SdnDevice.objects.all()
