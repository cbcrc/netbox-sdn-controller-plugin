from typing import Callable, Optional, Tuple, Dict
from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin
from django.urls import resolve
from dcim.models import Device, DeviceType

from netbox_sdn_controller.views import SdnModuleEditView, SdnDeviceEditView

class DynamicModuleTemplateMiddleware(MiddlewareMixin):
    """Middleware to dynamically swap ModuleEditView with SdnModuleEditView for POST requests."""

    def process_view(
        self,
        request: HttpRequest,
        _: Callable[..., HttpResponse],
        view_args: Tuple,
        view_kwargs: Dict
    ) -> Optional[HttpResponse]:
        """Processes the view before it is called.

        Args:
            request (HttpRequest): The incoming HTTP request.
            _ (Callable[..., HttpResponse]): The original view function (not used).
            view_args (Tuple): Positional arguments for the view.
            view_kwargs (Dict): Keyword arguments for the view.

        Returns:
            Optional[HttpResponse]: A response if the view is swapped,
            otherwise None to continue with the original view.
        """

        resolver_match = resolve(request.path)

        if request.method == "POST" and resolver_match.view_name == 'dcim:module_add':
            selected_device = request.POST.get('device')
            if selected_device is not None:

                selected_device_id = int(selected_device)
                device = Device.objects.filter(id=selected_device_id).first()
                if device and device.device_type.manufacturer.name == 'Cisco':
                    new_view = SdnModuleEditView.as_view()
                    return new_view(request, *view_args, **view_kwargs)

        if request.method == "POST" and resolver_match.view_name in ['dcim:device_add', 'plugins:netbox_iname:custom_device_add']:

            device_type = request.POST.get("device_type")
            if device_type is not None:
                manufacturer = DeviceType.objects.filter(id=int(device_type)).first().manufacturer.name
                if manufacturer == 'Cisco':
                    new_view = SdnDeviceEditView.as_view()
                    return new_view(request, *view_args, **view_kwargs)


        return None  # Continue with the original view
