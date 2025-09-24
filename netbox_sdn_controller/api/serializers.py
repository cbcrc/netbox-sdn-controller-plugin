from rest_framework import serializers
from dcim.api.serializers import ModuleSerializer, DeviceSerializer
from netbox.api.serializers import NetBoxModelSerializer
from ..models import SdnController, SdnControllerDevicePrototype, SdnModule, SdnDevice


class SdnControllerSerializer(NetBoxModelSerializer):
    """
    Serializer for the SdnController model.

    This serializer is responsible for converting the SdnController model
    instances to JSON format and validating incoming data for creating or updating
    instances of the SdnController model.
    """

    url: serializers.HyperlinkedIdentityField = serializers.HyperlinkedIdentityField(
        view_name='plugins-api:netbox_sdn_controller-api:sdncontroller-detail'
    )

    class Meta:
        model = SdnController
        fields = '__all__'


class SdnControllerDevicePrototypeSerializer(NetBoxModelSerializer):
    """
    Serializer for the SdnControllerDevicePrototype model.

    This serializer is responsible for converting SdnControllerDevicePrototype model
    instances to JSON format and validating incoming data for creating or updating
    instances of the SdnControllerDevicePrototype model.
    """

    url: serializers.HyperlinkedIdentityField = serializers.HyperlinkedIdentityField(
        view_name='plugins-api:netbox_sdn_controller-api:sdncontrollerdeviceprototype-detail'
    )

    class Meta:
        model = SdnControllerDevicePrototype
        fields = '__all__'


class SdnModuleSerializer(ModuleSerializer):
    """Serializer for the SdnModule model."""
    class Meta:
        model = SdnModule
        fields = '__all__'

class SdnDeviceSerializer(DeviceSerializer):
    """Serializer for the SdnDevice model."""
    class Meta:
        model = SdnDevice
        fields = '__all__'
