from netbox.api.routers import NetBoxRouter
from . import views

app_name = 'netbox_sdn_controller'

router = NetBoxRouter()

router.register('sdncontroller', views.SdnControllerViewSet)
router.register('sdncontrollerdeviceprototype', views.SdnControllerDevicePrototypeViewSet)
router.register('sdnmodule', views.SdnModuleViewSet)
router.register('sdndevice', views.SdnDeviceViewSet)
urlpatterns = router.urls
