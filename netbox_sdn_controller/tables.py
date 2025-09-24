from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django_tables2.utils import Accessor
import django_tables2 as tables
from netbox_sdn_controller.models import SdnController, SdnControllerDevicePrototype
from netbox.tables import NetBoxTable, columns



class SdnControllerTable(NetBoxTable):
    """
    Table representation for SdnController.
    Displays relevant fields for SdnController in a tabular format.
    """
    hostname = tables.Column(
        linkify=True
    )
    sdn_type =  tables.Column(
        verbose_name='Sdn Type',
    )
    version = tables.Column()
    verify = columns.BooleanColumn()
    status = columns.BooleanColumn()


    class Meta(NetBoxTable.Meta):
        """
        Meta for SdnControllerTable
        """
        model = SdnController
        fields = [
            "hostname",
            "device_families",
            "sdn_type",
            "version",
            "created",
            "last_updated",
            "version",
            "default_tenant"
        ]

        default_columns = (
            "hostname",
            "device_families",
            "sdn_type",
            "version",
            "last_updated",
        )

class SdnControllerDevicePrototypeTable(NetBoxTable):
    """
    Table representation for SdnControllerDevicePrototype.
    Displays relevant fields for device prototypes associated with SDN controllers.
    """

    matching_netbox_device = tables.Column(
        verbose_name='matching netbox device',
        linkify=True
    )

    related_netbox_device = tables.Column(
        verbose_name='related netbox device',
        linkify=True
    )

    netbox_stack_index = tables.Column(
        accessor=Accessor('matching_netbox_device.netbox_stack_index'),
        verbose_name='Netbox Stack Index',
    )

    create_or_edit = tables.Column(
        accessor=Accessor('create_or_edit'),
        orderable=False,
        verbose_name='create or edit'
    )

    serial = tables.Column(
        verbose_name='serial number'
    )

    sdn_hostname = tables.Column(
        verbose_name='sdn hostname'
    )

    primary_ip4 = tables.Column(
        verbose_name='sdn primary ipv4',
        linkify=True
    )

    sdn_device_type = tables.Column(
        verbose_name='sdn device type'
    )

    device_type = tables.Column(
        verbose_name='object',
        linkify=True
    )

    family = tables.Column(
        verbose_name='family'
    )

    sdn_role = tables.Column(
        verbose_name='sdn role'
    )

    role = tables.Column(
        verbose_name='device role',
        linkify=True
    )

    site = tables.Column(
        verbose_name='site',
        linkify=True
    )

    tenant = tables.Column(
        verbose_name='tenant',
        linkify=True
    )

    sync_status = columns.ChoiceFieldColumn(
        verbose_name=_('sync_status'),
    )

    sdn_controller = tables.Column(
        verbose_name='sdn controller',
        linkify=True
    )

    tags = columns.TagColumn(
        url_name='plugins:netbox_sdn_controller:sdncontrollerdeviceprototype_list'
    )

    def render_instance_uuid(self, record: SdnControllerDevicePrototype) -> str:
        return record.instance_uuid[:6]

    def render_netbox_stack_index(self, value: str, record: SdnControllerDevicePrototype) -> str:
        """Renders the NetBox stack index, highlighting mismatches in red.

        Args:
            self (Any): The instance of the class containing this method.
            value (str): The value to be rendered.
            record (SdnControllerDevicePrototype): The device prototype record containing stack index details.

        Returns:
            str: The rendered HTML string, with mismatches highlighted in red if applicable.
        """
        if (
                record.matching_netbox_device.netbox_stack_index
                and record.stack_index
                and record.matching_netbox_device.netbox_stack_index != record.stack_index
        ):
            return format_html('<span style="color: red;">{}</span>', value)
        return value


    def render_device_type(self, value: str, record: SdnControllerDevicePrototype) -> str:
        """Renders the device type, highlighting mismatches in red.

        Args:
            self (Any): The instance of the class containing this method.
            value (str): The device type value to be rendered.
            record (SdnControllerDevicePrototype): The device prototype record containing device type details.

        Returns:
            str: The rendered HTML string, with mismatches highlighted in red if applicable.
        """
        if (record.matching_netbox_device and
                record.device_type and
                record.matching_netbox_device.device_type != record.device_type):
            return format_html('<span style="color: red;">{}</span>', value)
        return value

    def render_primary_ip4(self, value: str, record: SdnControllerDevicePrototype) -> str:

        """Renders the primary IPv4 address, highlighting mismatches in red.

        Args:
            self (Any): The instance of the class containing this method.
            value (str): The primary IPv4 address value to be rendered.
            record (SdnControllerDevicePrototype): The device prototype record containing primary IPv4 address.

        Returns:
            str: The rendered HTML string, with mismatches highlighted in red if applicable.
        """

        if (record.matching_netbox_device and
                record.primary_ip4 and
                record.matching_netbox_device.primary_ip4 != record.primary_ip4):
            return format_html('<span style="color: red;">{}</span>', value)
        return value

    class Meta(NetBoxTable.Meta):
        """
        Meta for SdnControllerDevicePrototypeTable
        """
        model = SdnControllerDevicePrototype
        fields = [
            "id",

            "sync_status",
            "matching_netbox_device",
            "related_netbox_device",
            "serial",
            "instance_uuid",
            "stack_index",
            "sdn_hostname",
            "primary_ip4",
            "sdn_device_type",
            "device_type",
            "family",
            "sdn_role",
            "role",
            "site",
            "tenant",
            "sdn_controller",
            "score",
            "tags",
            "netbox_stack_index",

        ]

        default_columns = (
            "id",
            "sync_status",
            "sdn_hostname",
            "serial",
            "matching_netbox_device",
            "related_netbox_device",
            "instance_uuid",
            "stack_index",
            "netbox_stack_index",
            "primary_ip4",
            "sdn_device_type",
            "device_type",
            "sdn_role",
            "role",
            "site",
            "tenant",
        )
