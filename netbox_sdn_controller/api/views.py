from dcim.api.views import ModuleViewSet, DeviceViewSet
from netbox.api.viewsets import NetBoxModelViewSet
from .. import filtersets, models
from .serializers import (
    SdnControllerSerializer,
    SdnControllerDevicePrototypeSerializer
)

class SdnControllerViewSet(NetBoxModelViewSet):
    """
    ViewSet for managing SdnController instances.

    This view set provides CRUD operations for SdnController model instances.
    It handles queries, serializations, and filtering using the provided filterset.
    """

    queryset: models.SdnController = models.SdnController.objects.all()
    serializer_class: SdnControllerSerializer = SdnControllerSerializer
    filterset_class: filtersets.SdnControllerFilterSet = filtersets.SdnControllerFilterSet


class SdnModuleViewSet(ModuleViewSet):
    """ViewSet for managing SdnModule objects."""
    queryset = models.SdnModule.objects.all()

class SdnDeviceViewSet(DeviceViewSet):
    """ViewSet for managing SdnDevice objects."""
    queryset = models.SdnDevice.objects.all()

class SdnControllerDevicePrototypeViewSet(NetBoxModelViewSet):
    """
    ViewSet for managing SdnControllerDevicePrototype instances.

    This view set provides CRUD operations for SdnControllerDevicePrototype model instances.
    It handles queries, serializations, and filtering using the provided filterset.
    """

    queryset: models.SdnControllerDevicePrototype = models.SdnControllerDevicePrototype.objects.all()
    serializer_class: SdnControllerDevicePrototypeSerializer = SdnControllerDevicePrototypeSerializer
    filterset_class: filtersets.SdnControllerDevicePrototypeFilterSet = filtersets.SdnControllerDevicePrototypeFilterSet
