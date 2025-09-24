from netbox.plugins import PluginMenuButton, PluginMenuItem


sdncontroller_buttons = [
    PluginMenuButton(
        link='plugins:netbox_sdn_controller:sdncontroller_add',
        title='Add',
        icon_class='mdi mdi-plus-thick'
    )

]

sdncontrollerdeviceprototype_buttons = [
    PluginMenuButton(
        link='plugins:netbox_sdn_controller:sdncontrollerdeviceprototype_add',
        title='Add',
        icon_class='mdi mdi-plus-thick'
    )

]

menu_items = (
    PluginMenuItem(
        link='plugins:netbox_sdn_controller:sdncontroller_list',
        link_text='SDN Controllers',
        buttons=sdncontroller_buttons
    ),
     PluginMenuItem(
        link='plugins:netbox_sdn_controller:sdncontrollerdeviceprototype_list',
        link_text='Device Prototypes'
    ),
)
