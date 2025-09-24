import re
from typing import Optional, Dict
from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from core.models import Job
from dcim.models import Device, DeviceType, DeviceRole, Site, Module, InterfaceTemplate
from ipam.models import IPAddress
from tenancy.models import Tenant
from netbox_sdn_controller.utils import create_or_edit_link, netbox_stack_position
from netbox_sdn_controller.choices import DevicePrototypeStatusChoices
from netbox.models import NetBoxModel



class NetBoxDevice(Device):
    """Proxy model for NetBoxDevice, extending the base Device model.

    This model adds additional functionality specific to NetBox devices.
    """

    class Meta:
        """Metadata for the NetBoxDevice proxy model."""
        verbose_name = "netbox device"
        verbose_name_plural = "netbox devices"
        proxy = True

    @property
    def netbox_stack_index(self) -> str:
        """Retrieve the stack index of the NetBox device.

        Returns:
            str: A comma-separated string of sorted numeric prefixes of interface names.
        """
        related_prototype = SdnControllerDevicePrototype.objects.filter(matching_netbox_device=self).first()
        if related_prototype and not related_prototype.virtual_chassis:
            return "1"

        return netbox_stack_position(self)

    def get_absolute_url(self) -> str:
        """Return the URL to the core NetBox device detail view."""
        return reverse("dcim:device", args=[self.pk])


class SdnController(NetBoxModel):
    """
    Represents an SDN (Software-Defined Networking) Controller.

    Attributes:
        created (datetime): The timestamp when the controller was created.
        last_updated (datetime): The timestamp of the last update to the controller.
        hostname (str): The hostname of the SDN controller.
        sdn_type (str): The type of SDN controller (e.g., Catalyst Center).
        last_fetch_job (Job | None): The last fetch job associated with this controller.
        last_sync_job (Job | None): The last synchronization job associated with this controller.
        version (str): The version of the SDN controller software.
        regex_template (dict | None): A JSON field containing regex templates for parsing hostnames.
    """

    SDN_TYPE = (
        ('Catalyst Center', 'Catalyst Center'),
    )

    DEVICE_FAMILY_CHOICES = [
        ('Switches and Hubs', 'Switches and Hubs'),
        ('Routers', 'Routers'),
        ('Wireless Sensor', 'Wireless Sensor'),
        ('Third Party Device', 'Third Party Device'),
        ('Universal Gateways and Access Servers', 'Universal Gateways and Access Servers'),
        ('Wireless Controller', 'Wireless Controller'),
        ('Unified AP', 'Unified AP'),
    ]

    created = models.DateTimeField(
        auto_now_add=True,
        blank=True,
        null=True
    )
    last_updated = models.DateTimeField(
        auto_now=True,
        blank=True,
        null=True
    )
    hostname = models.CharField(max_length=200)
    sdn_type = models.CharField(
        default="Catalyst Center",
        max_length=30,
        choices=SDN_TYPE
    )

    last_sync_job = models.ForeignKey(
        to=Job,
        on_delete=models.SET_NULL,
        related_name='sdncontroller',
        blank=True,
        null=True

    )

    last_sync_job_success = models.BooleanField(
        default=True
    )

    last_fetch_job = models.ForeignKey(
        to=Job,
        on_delete=models.SET_NULL,
        related_name='sdncontrollerfetch',
        blank=True,
        null=True
    )
    version = models.CharField(max_length=10)

    device_families = ArrayField(
        models.CharField(max_length=50, choices=DEVICE_FAMILY_CHOICES),
        default=list,
        blank=True,
        verbose_name='Device Families',
        help_text='Device families filtered for this SDN Network Controller.'
    )

    regex_template = models.JSONField(
        verbose_name='regex template',
        help_text='Contains multiple regex for parsing hostnames',
        blank=True,
        null=True
    )

    default_tenant = models.ForeignKey(
        verbose_name='default tenant',
        help_text='Default tenant for fetched devices',
        to='tenancy.Tenant',
        on_delete=models.SET_NULL,
        related_name='sdncontroller',
        blank=True,
        null=True
    )

    class Meta:
        """
        Meta for SdnController model
        """
        verbose_name = 'SDN Controller'
        verbose_name_plural = 'SDN Controllers'
        ordering = ["hostname"]
        unique_together = [
            ('hostname', 'device_families')
        ]

    def __str__(self):
        return str(self.hostname)

    def get_absolute_url(self) -> str:
        """
        Returns the URL to access the SDNController object.

        Returns:
            str: URL for the SDNController instance.
        """
        return reverse("plugins:netbox_sdn_controller:sdncontroller", args=[self.pk])


class SdnControllerDevicePrototype(NetBoxModel):
    """
    Represents a device prototype associated with an SDN Controller.

    Attributes:
        serial (str | None): Serial number of the device.
        sdn_hostname (str | None): Hostname assigned to the device by the SDN controller.
        sdn_management_ip (str | None): Management IP address assigned by the SDN controller.
        primary_ip4 (IPAddress | None): The primary IPv4 address associated with the device.
        matching_netbox_device (Device | None): A NetBox device matching the prototype.
        sdn_device_type (str | None): Device type in the SDN controller.
        device_type (DeviceType | None): Device type in NetBox.
        sdn_role (str | None): Role assigned to the device by the SDN controller.
        role (DeviceRole | None): Device role in NetBox.
        raw_data (dict): Raw data of the device from the SDN controller.
        sdn_controller (SdnController): The SDN controller this prototype belongs to.
        instance_uuid (str): A unique identifier for the instance.
        family (str | None): Family of the device.
        site (Site | None): The site associated with the device.
        tenant (Tenant | None): The tenant associated with the device.
        sync_status (str): The synchronization status of the device.
        score (int): The sync score of the device.
        clone_fields (tuple): Fields that can be cloned when creating a new device prototype.
    """

    serial = models.CharField(
        max_length=50,
        verbose_name=_('serial number'),
        blank=True,
        null=True
    )

    sdn_hostname = models.CharField(
        max_length=50,
        verbose_name=_('sdn hostname'),
        blank=True,
        null=True
    )

    sdn_management_ip = models.CharField(
        max_length=50,
        verbose_name=_('sdn management ip'),
        blank=True,
        null=True
    )

    primary_ip4 = models.ForeignKey(
        to=IPAddress,
        on_delete=models.SET_NULL,
        related_name='prototype+',
        blank=True,
        null=True,
        verbose_name=_('primary IPv4')
    )

    matching_netbox_device = models.ForeignKey(
        to=NetBoxDevice,
        on_delete=models.SET_NULL,
        related_name='matchingdevice',
        verbose_name=_('matching serial'),
        blank=True,
        null=True
    )

    related_netbox_device = models.ForeignKey(
        to=NetBoxDevice,
        on_delete=models.SET_NULL,
        related_name='relateddevice',
        verbose_name=_('related device'),
        blank=True,
        null=True
    )

    sdn_device_type = models.CharField(
        max_length=50,
        verbose_name=_('sdn device type'),
        blank=True,
        null=True
    )

    device_type = models.ForeignKey(
        to=DeviceType,
        on_delete=models.SET_NULL,
        verbose_name=_('netbox device type'),
        related_name='prototypeinstances',
        blank=True,
        null=True
    )

    sdn_role = models.CharField(
        max_length=50,
        verbose_name=_('sdn role'),
        blank=True,
        null=True
    )

    role = models.ForeignKey(
        to=DeviceRole,
        on_delete=models.SET_NULL,
        verbose_name=_('netbox role'),
        related_name='prototypedevices',
        blank=True,
        null=True
    )

    raw_data = models.JSONField(
        default=dict,
        verbose_name='raw data',
        help_text='Device raw data from sdn controller'
    )

    stack_info = models.JSONField(
        verbose_name='stack info',
        help_text='Complete stack indexes',
        default=dict
    )

    stack_index = models.CharField(
        verbose_name='sdn stack index',
        default="1"
    )

    sdn_controller = models.ForeignKey(
        to=SdnController,
        on_delete=models.CASCADE,
        related_name='deviceprototype'
    )

    instance_uuid = models.CharField(
        max_length=50

    )

    family = models.CharField(
        max_length=50,
        verbose_name=_('family'),
        blank=True,
        null=True
    )


    site = models.ForeignKey(
        to=Site,
        on_delete=models.SET_NULL,
        related_name='siteprototypedevices',
        blank=True,
        null=True
    )

    tenant = models.ForeignKey(
        to=Tenant,
        on_delete=models.SET_NULL,
        related_name='tenantprototypedevices',
        blank=True,
        null=True
    )

    sync_status = models.CharField(
        max_length=10,
        choices=DevicePrototypeStatusChoices,
        default=DevicePrototypeStatusChoices.DISCOVERED,
        verbose_name=_("sync_status")
    )

    score = models.IntegerField(
        verbose_name=_('sync score'),
        default=0
    )

    clone_fields = (
        'device_type', 'role', 'site', 'tenant'
    )

    class Meta:
        """
        Meta for SdnControllerDevicePrototype model
        """
        verbose_name = 'Device Prototype'
        verbose_name_plural = 'Device Prototypes'
        unique_together = ('instance_uuid', 'serial')
        ordering = ["instance_uuid", "stack_index"]

    def __str__(self) -> str:
        return str(self.instance_uuid)

    def get_absolute_url(self) -> str:
        """
        Returns the URL to access the SdnControllerDevicePrototype object.

        Returns:
            str: URL for the SdnControllerDevicePrototype instance.
        """
        return reverse("plugins:netbox_sdn_controller:sdncontrollerdeviceprototype", args=[self.pk])

    @property
    def create_or_edit(self) -> str:
        """
        Returns a link for creating or editing the object.

        Returns:
            str: HTML link for creating or editing the object.
        """
        return create_or_edit_link(self)

    @property
    def virtual_chassis(self):
        return len(self.stack_info) > 1

    @property
    def has_cards(self):
        return len(self.raw_data.get("all_cards", {})) > 0

    def get_sync_status_color(self):
        return DevicePrototypeStatusChoices.colors.get(self.sync_status)

class SdnModule(Module):
    """Proxy model for SdnModule with customized save behavior."""
    class Meta:
        """Meta for SdnModule."""
        verbose_name = 'sdn module'
        verbose_name_plural = 'sdn modules'
        proxy = True

    def save(self, *args: tuple, **kwargs: dict) -> None:
        """
        Custom save method to handle renaming of interface templates.
        """
        def extract_switch_number(text: str) -> str | None:
            related_prototype = SdnControllerDevicePrototype.objects.filter(matching_netbox_device=self.device).first()
            if not related_prototype or not related_prototype.virtual_chassis:
                return "1"

            match = re.search(r"(Switch|Chassis) (\d+)", text)
            return match.group(2) if match else None

        def get_max_template_slashes():
            related_interface_templates = InterfaceTemplate.objects.filter(module_type=self.module_type)
            max_slashes = 0

            for interface_template in related_interface_templates:
                slashes_count = interface_template.name.count('/')
                max_slashes = max(max_slashes, slashes_count)

            return max_slashes

        def get_max_device_interface_slashes():
            related_prototype = SdnControllerDevicePrototype.objects.filter(matching_netbox_device=self.device).first()
            all_prototype_interfaces = related_prototype.raw_data.get("interfaces", {})
            max_slashes = 0

            for iface_name in all_prototype_interfaces:
                slashes_count = iface_name.count('/')
                max_slashes = max(max_slashes, slashes_count)

            return max_slashes

        def init_template_name_mapping(chassis: Optional[str]) -> Dict[str, str]:

            related_prototype = SdnControllerDevicePrototype.objects.filter(matching_netbox_device=self.device).first()
            truncate_chassis = False
            if related_prototype:
                truncate_chassis = get_max_template_slashes() > get_max_device_interface_slashes()
            template_name_mapping = {}
            if chassis:
                related_interface_templates = InterfaceTemplate.objects.filter(module_type=self.module_type)

                for interface_template in related_interface_templates:
                    template_name = interface_template.name
                    modified_name = interface_template.name.replace("{chassis}", chassis)
                    if (related_prototype and not related_prototype.virtual_chassis and
                            "{module}" in interface_template.name and
                            truncate_chassis):
                        modified_name = interface_template.name.replace("{chassis}/", "")

                    template_name_mapping[template_name] = modified_name
                    template_name_mapping[modified_name] = template_name

            return template_name_mapping

        def rewrite_templates(chassis: Optional[str], template_name_mapping: Dict[str, str]) -> None:
            if chassis:

                related_interface_templates = InterfaceTemplate.objects.filter(module_type=self.module_type)

                for interface_template in related_interface_templates:
                    interface_template.name = template_name_mapping.get(interface_template.name)
                    interface_template.save()


        chassis = extract_switch_number(self.module_bay.name)# to review

        template_name_mapping = init_template_name_mapping(chassis)

        rewrite_templates(chassis, template_name_mapping)

        super().save(*args, **kwargs)

        rewrite_templates(chassis, template_name_mapping)


class SdnDevice(Device):
    """Proxy model for SdnDevice with customized save behavior."""
    class Meta:
        """Meta for SdnDevice"""
        verbose_name = 'sdn device'
        verbose_name_plural = 'sdn devices'
        proxy = True

    def save(self, *args: tuple, **kwargs: dict) -> None:
        """
        Custom save method to handle renaming of interface templates.
        """

        def init_template_name_mapping(chassis: Optional[str]) -> Dict[str, str]:

            template_name_mapping = {}
            if chassis:
                related_interface_templates = InterfaceTemplate.objects.filter(device_type=self.device_type)

                for interface_template in related_interface_templates:
                    template_name_mapping[interface_template.name] = interface_template.name.replace("{chassis}",
                                                                                                     chassis)
                    template_name_mapping[
                        interface_template.name.replace("{chassis}", chassis)] = interface_template.name

            return template_name_mapping

        def rewrite_templates(chassis: Optional[str], template_name_mapping: Dict[str, str]) -> None:
            if chassis:

                related_interface_templates = InterfaceTemplate.objects.filter(device_type=self.device_type)

                for interface_template in related_interface_templates:
                    interface_template.name = template_name_mapping.get(interface_template.name)
                    interface_template.save()


        device_prototype = SdnControllerDevicePrototype.objects.filter(serial=self.serial).first()
        chassis = "1"
        if device_prototype:
            chassis =  SdnControllerDevicePrototype.objects.filter(serial=self.serial).first().stack_index
        elif self.vc_position:
            chassis = str(self.vc_position)

        template_name_mapping = init_template_name_mapping(chassis)

        rewrite_templates(chassis, template_name_mapping)

        super().save(*args, **kwargs)

        rewrite_templates(chassis, template_name_mapping)
