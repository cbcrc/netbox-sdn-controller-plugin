from django.db.models import QuerySet
from django.db.models.query_utils import Q
from netbox.filtersets import NetBoxModelFilterSet
from .models import SdnController, SdnControllerDevicePrototype

class SdnControllerFilterSet(NetBoxModelFilterSet):
    """
    Filter set for filtering SDN Controllers.

    This filter set allows filtering of `SdnController` objects based on various fields
    and a customizable search method for text-based queries.

    Methods:
        search(queryset: QuerySet[SdnController], name: str, value: str) -> QuerySet[SdnController]:
            Filters the queryset based on the provided search value.
    """

    class Meta:
        model = SdnController
        fields = ('id', 'hostname', 'sdn_type')

    def search(self, queryset: QuerySet[SdnController], name: str, value: str) -> QuerySet[SdnController]:
        """
        Filters the queryset by searching in the `hostname` and `sdn_type` fields.

        Args:
            queryset (QuerySet[SdnController]): The initial queryset to filter.
            name (str): The name of the field being searched (not used in this method).
            value (str): The search term entered by the user.

        Returns:
            QuerySet[SdnController]: The filtered queryset.
        """
        if not value.strip():
            return queryset

        return queryset.filter(
            Q(hostname__icontains=value) |
            Q(sdn_type__icontains=value)
        ).distinct()


class SdnControllerDevicePrototypeFilterSet(NetBoxModelFilterSet):
    """
    Filter set for filtering SDN Controller Device Prototypes.

    This filter set allows filtering of `SdnControllerDevicePrototype` objects based on fields like:
    - Matching NetBox devices
    - SDN controller details
    - Device type, role, primary IPv4 address, serial, sync status, and instance UUID.

    Additionally, a `search` method provides advanced text-based filtering across multiple fields.
    """

    class Meta:
        model = SdnControllerDevicePrototype
        fields = ('matching_netbox_device',
                  'sdn_controller',
                  'device_type',
                  'role',
                  'primary_ip4',
                  'serial',
                  'sync_status',
                  'instance_uuid')

    def search(
        self,
        queryset: QuerySet[SdnControllerDevicePrototype],
        name: str,
        value: str
    ) -> QuerySet[SdnControllerDevicePrototype]:
        """
        Perform a search on the `SdnControllerDevicePrototype` queryset.

        This method filters the queryset based on a search term (`value`), looking for matches across
        multiple fields, including:
        - Matching NetBox device name
        - SDN controller hostname and SDN type
        - Device type model and role name
        - Primary IPv4 address, serial number, and sync status
        - SDN-specific attributes like `sdn_device_type`, `sdn_role`, `sdn_management_ip`, and `sdn_hostname`
        - Instance UUID.

        The search is case-insensitive and supports partial matches for most fields.

        Args:
            queryset (QuerySet[SdnControllerDevicePrototype]): The initial queryset to filter.
            name (str): The name of the field being searched (not used in this method).
            value (str): The search term entered by the user.

        Returns:
            QuerySet[SdnControllerDevicePrototype]: The filtered queryset containing matches.

        Notes:
            - If `value` is empty or whitespace, the original queryset is returned.
            - `distinct()` is applied to avoid duplicate entries when filtering across related fields.
        """
        if not value.strip():
            return queryset

        return queryset.filter(
            Q(matching_netbox_device__name__icontains=value) |
            Q(sdn_controller__hostname__icontains=value) |
            Q(sdn_controller__sdn_type__icontains=value) |
            Q(device_type__model__icontains=value) |
            Q(role__name__icontains=value) |
            Q(primary_ip4__address__istartswith=value) |
            Q(serial__icontains=value) |
            Q(sdn_device_type__icontains=value) |
            Q(sdn_role__icontains=value) |
            Q(instance_uuid__icontains=value) |
            Q(sdn_management_ip__icontains=value) |
            Q(sdn_hostname__icontains=value) |
            Q(family__icontains=value) |
            Q(sync_status__istartswith=value)
        ).distinct()
