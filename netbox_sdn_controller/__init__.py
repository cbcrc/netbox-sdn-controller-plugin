from netbox.plugins import PluginConfig

class NetBoxSdnController(PluginConfig):
    """
    Plugin configuration for the NetBox SDN Controller.

    This plugin synchronizes the software-defined network (SDN) with NetBox.
    """
    name = 'netbox_sdn_controller'
    verbose_name = 'Netbox SDN Controller'
    description = 'Synchronizes the software defined network (SDN) with NetBox'
    version = '1.4.2'
    base_url = 'netbox-sdn-controller'
    middleware = ['netbox_sdn_controller.middleware.DynamicModuleTemplateMiddleware']

config = NetBoxSdnController
