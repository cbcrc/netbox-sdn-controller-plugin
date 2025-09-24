from typing import Any, Optional
from django import forms
from django.utils.translation import gettext as _
from dcim.models import Device, DeviceType, DeviceRole, Site
from ipam.models import IPAddress
from tenancy.models import Tenant
from utilities.forms.fields import DynamicModelChoiceField, DynamicModelMultipleChoiceField, TagFilterField
from utilities.forms.rendering import FieldSet
from utilities.forms import add_blank_choice
from netbox_sdn_controller.choices import DevicePrototypeStatusChoices
from netbox_sdn_controller.models import SdnController, SdnControllerDevicePrototype
from netbox.forms import NetBoxModelForm, NetBoxModelFilterSetForm, NetBoxModelBulkEditForm


class SdnControllerForm(NetBoxModelForm):
    """
    Form for managing `SdnController` instances.

    Provides validation to ensure hostname uniqueness and device family consistency
    across related controllers.
    """


    device_families = forms.MultipleChoiceField(
        choices=SdnController.DEVICE_FAMILY_CHOICES,
        required=False,
        widget=forms.SelectMultiple(attrs={'size': 7})
    )

    class Meta:
        """
        Meta for SdnControllerForm
        """
        model = SdnController
        fields = [
            "hostname",
            "version",
            "sdn_type",
            "device_families",
            "default_tenant",
            "regex_template"
        ]

    def clean(self) -> Optional[Any]:
        """
        Perform custom validation for SdnControllerForm.

        Validates:
        - Hostname uniqueness across `SdnController` instances.
        - Device families consistency between related controllers.

        Returns:
            Optional[Any]: Cleaned data after validation.
        """
        hostname = self.cleaned_data.get("hostname", None)
        device_families = self.cleaned_data.get("device_families", None)
        related_controllers = SdnController.objects.filter(hostname=hostname)
        if self.instance and self.instance.pk:
            related_controllers = related_controllers.exclude(pk=self.instance.pk)

        if device_families == [] and related_controllers.exists():
            raise forms.ValidationError(f'{hostname} already exist in controller {related_controllers.first().id}')

        for related_controller in related_controllers:
            related_controller_device_families = related_controller.device_families
            if related_controller_device_families == []:
                raise forms.ValidationError(f'{hostname} already exist in controller {related_controller.id}')

            for previous_device_family in related_controller_device_families:
                if previous_device_family in device_families:
                    raise forms.ValidationError(f'{previous_device_family} and {hostname} ' +
                                                f'combination already exist in controller {related_controller.id}')

        super().clean()

class SdnControllerDevicePrototypeForm(NetBoxModelForm):
    """
    Form for managing `SdnControllerDevicePrototype` instances.

    Allows selecting related models such as matching NetBox devices, SDN controllers,
    device types, roles, sites, tenants, and primary IPv4 addresses.
    """
    matching_netbox_device = DynamicModelChoiceField(
        queryset=Device.objects.filter(),
        required=False
    )

    sdn_controller = DynamicModelChoiceField(
        queryset=SdnController.objects.filter()
    )

    device_type = DynamicModelChoiceField(
        queryset=DeviceType.objects.filter(),
        required=False
    )

    role = DynamicModelChoiceField(
        queryset=DeviceRole.objects.filter(),
        required=False
    )

    site = DynamicModelChoiceField(
        queryset=Site.objects.filter(),
        required=False
    )

    tenant = DynamicModelChoiceField(
        queryset=Tenant.objects.filter(),
        required=False
    )

    primary_ip4 = DynamicModelChoiceField(
        queryset=IPAddress.objects.filter(),
        required=False
    )

    class Meta:
        """
        Meta for SdnControllerDevicePrototypeForm
        """
        model = SdnControllerDevicePrototype
        fields = [
            "serial", "matching_netbox_device", "sdn_hostname", "sdn_management_ip", "primary_ip4", "sdn_device_type",
            "device_type", "family", "sdn_role", "role", "site", "tenant", "sync_status", "sdn_controller",
        ]

class SdnControllerDevicePrototypeFilterForm(NetBoxModelFilterSetForm):
    """
    Filter form for filtering `SdnControllerDevicePrototype` instances.

    Provides fields for filtering by matching NetBox device, SDN controller, device type,
    role, site, tenant, primary IPv4 address, and sync status.
    """
    model = SdnControllerDevicePrototype
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('matching_netbox_device', 'device_type', 'role', 'primary_ip4', name=_('NetBox Device Fields')),
        FieldSet('sdn_controller', 'sync_status', 'family', name=_('Prototype Device Fields'))
    )
    selector_fields = ('filter_id',
                       'q',
                       'matching_netbox_device',
                       'sdn_controller',
                       'device_type',
                       'role',
                       'primary_ip4',
                       'family',
                       'sync_status')

    matching_netbox_device = DynamicModelMultipleChoiceField(
        queryset=Device.objects.all(),
        required=False,
        label=_('Matching NetBox Device'),
    )

    sdn_controller = DynamicModelMultipleChoiceField(
        queryset=SdnController.objects.all(),
        required=False,
        label=_('SDN Controller')
    )

    device_type = DynamicModelMultipleChoiceField(
        queryset=DeviceType.objects.all(),
        required=False,
        label=_('Device Type')
    )

    role = DynamicModelMultipleChoiceField(
        queryset=DeviceRole.objects.all(),
        required=False,
        label=_('Device Role')
    )

    primary_ip4 = DynamicModelMultipleChoiceField(
        queryset=IPAddress.objects.all(),
        required=False,
        label=_('Primary IPv4 Address')
    )

    sync_status = forms.ChoiceField(
        label=_('sync_status'),
        required=False,
        choices=add_blank_choice(DevicePrototypeStatusChoices)
    )

    tag = TagFilterField(model)

class SdnControllerDevicePrototypeBulkEditForm(NetBoxModelBulkEditForm):
    """
    Bulk edit form for `SdnControllerDevicePrototype` instances.

    Allows bulk updates to fields such as device type, role, site, and tenant.
    """

    device_type = DynamicModelChoiceField(
        label=_('Device Type'),
        queryset=DeviceType.objects.all(),
        required=False
    )

    role = DynamicModelChoiceField(
        label=_('Device Role'),
        queryset=DeviceRole.objects.all(),
        required=False
    )


    site = DynamicModelChoiceField(
        label=_('Site'),
        queryset=Site.objects.all(),
        required=False
    )

    tenant = DynamicModelChoiceField(
        label=_('Tenant'),
        queryset=Tenant.objects.all(),
        required=False
    )

    model = SdnControllerDevicePrototype
