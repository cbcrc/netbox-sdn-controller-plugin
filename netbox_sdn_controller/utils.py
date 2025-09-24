import re
from collections import Counter
from typing import List, Optional, Dict, Any, Union
from functools import lru_cache
from django.utils.safestring import mark_safe
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from netutils.interface import canonical_interface_name
from dcim.models import Interface, InterfaceTemplate, Site
from ipam.models import Prefix


def netbox_stack_position(record: object) -> str:
    """Determine the stack position of a NetBox device based on its interfaces.

    Args:
        record (object): A NetBox device record to query its interfaces.

    Returns:
        str: A comma-separated string of sorted numeric prefixes of interface names.
    """
    all_device_interfaces = Interface.objects.filter(device=record)
    pattern = re.compile(r"^\D*(\d+)/")
    index_list = []

    for interface in all_device_interfaces:
        match = pattern.match(interface.name)
        if match:
            numeric_prefix: str = match.group(1)
            if numeric_prefix not in index_list:
                index_list.append(numeric_prefix)

    index_list = sorted(index_list, key=int)

    if len(index_list) > 4:
        return "1"

    if "0" in index_list and len(index_list) > 1:
        index_list.remove("0")

    return ",".join(index_list)

@lru_cache(maxsize=None)
def create_or_edit_link(record) -> str:
    """
    Generates a link for creating or editing a device based on the record provided.

    Args:
        record: The record that contains details for creating or editing a device.

    Returns:
        str: A safe HTML link to edit or create a device.
    """
    matching_netbox_device = record.matching_netbox_device
    primary_ip4 = record.primary_ip4
    device_type = record.device_type
    role = record.role
    site = record.site

    if matching_netbox_device:
        edit_url = (reverse('dcim:device_edit', kwargs={'pk': matching_netbox_device.id}) +
                    '?return_url=/plugins/netbox-sdn-controller/device-prototype/')

        if not matching_netbox_device.serial or matching_netbox_device.serial == "":
            serial_number = record.serial
            edit_url += f'&serial={serial_number}'

        if not matching_netbox_device.primary_ip4 and primary_ip4:
            edit_url += f'&primary_ip4={primary_ip4.id}'

        if not matching_netbox_device.device_type and device_type:
            edit_url += f'&device_type={device_type.id}'

        link_text = (f'<a href="{edit_url} "class="btn btn-primary btn-sm btn-warning lh-1" title="Edit">' +
                     '<i class="mdi mdi-pencil" aria-hidden="true"></i></a>')
    else:


        name = record.sdn_hostname
        create_url = (reverse('dcim:device_add')  +
                      '?return_url=/plugins/netbox-sdn-controller/device-prototype/')

        create_url += f'&name={name}'
        if record.device_type:
            create_url += f'&device_type={record.device_type.id}'
        if record.serial:
            create_url += f'&serial={record.serial}'
        if primary_ip4:
            create_url += f'&primary_ip4={primary_ip4.id}'
        if role:
            create_url += f'&role={role.id}'
        if site:
            create_url += f'&site={site.id}'

        link_text = (f'<a href="{create_url} "class="btn btn-primary btn-sm btn-green lh-1" title="Create">' +
                     '<i class="mdi mdi-plus-thick" aria-hidden="true"></i></a>')

    return mark_safe(link_text)


def get_site_from_prefix(primary_ip4: str) -> Optional['Site']:
    """
    Retrieves the site associated with the given prefix.

    Args:
        primary_ip4 (str): The IPv4 address to search for in the prefixes.

    Returns:
        Optional[Site]: The site associated with the prefix, or None if not found.
    """
    site_ct = ContentType.objects.get_for_model(Site)
    site = None
    parent_prefixes = Prefix.objects.filter(
        prefix__net_contains_or_equals=str(primary_ip4)
    )

    for parent_prefix in parent_prefixes:

        if parent_prefix.scope and parent_prefix.scope_type == site_ct:
            site = parent_prefix.scope
        if site:
            return site

    return site

def get_link_text(object_to_link: Any) -> str:
    """
    Generate an HTML link for a given object, depending on its model type.

    This function creates a clickable HTML button that links to the detail page of
    the provided object. The URL and display name are determined by the object's model type.

    Args:
        object_to_link (Any): An instance of a model for which the link is to be generated.
            The object must have a `_meta` attribute with a `model_name` property and
            relevant fields (`hostname` or `sdn_hostname`).

    Returns:
        str: An HTML string representing the link, or an empty string if the object's model
        type is unsupported.
    """
    model_name = object_to_link._meta.model_name
    if model_name == 'sdncontroller':
        object_url = 'plugins:netbox_sdn_controller:sdncontroller'
        object_name = object_to_link.hostname
    elif model_name == 'sdncontrollerdeviceprototype':
        object_url = 'plugins:netbox_sdn_controller:sdncontrollerdeviceprototype'
        object_name = object_to_link.sdn_hostname
    elif model_name == 'device':
        object_url = 'dcim:device'
        object_name = object_to_link.name
    elif model_name == 'netboxdevice':
        object_url = 'dcim:device'
        object_name = object_to_link.name
    elif model_name == 'devicetype':
        object_url = 'dcim:devicetype'
        object_name = object_to_link.model
    elif model_name == 'modulebay':
        object_url = 'dcim:modulebay'
        object_name = object_to_link.name
    elif model_name == 'ipaddress':
        object_url = 'ipam:ipaddress'
        object_name = object_to_link.address
    elif model_name == 'interface':
        object_url = 'dcim:interface'
        object_name = object_to_link.name
    else:
        return ''

    url = reverse(object_url, kwargs={'pk': object_to_link.id})
    return f'<a href="{url} "class="btn btn-primary btn-sm lh-1">{object_name}</a>'

def get_edit_link_text(object_to_link: Any, prefilled_argument: str) -> str:
    """
    Generate an HTML link for editing a given object, with a prefilled argument.

    Args:
        object_to_link (Any): An instance of a model for which the edit link is to be generated.
        prefilled_argument (str): The argument to prefill in the edit URL.

    Returns:
        str: An HTML string representing the edit link, or an empty string if the object's model
        type is unsupported.
    """
    model_name = object_to_link._meta.model_name
    if model_name == 'sdncontrollerdeviceprototype':
        object_url = 'plugins:netbox_sdn_controller:sdncontrollerdeviceprototype_edit'
        object_name = f"{object_to_link.sdn_hostname} PROTOTYPE"
        url = reverse(object_url, kwargs={'pk': object_to_link.id}) + f"?matching_netbox_device={prefilled_argument}"
    elif model_name in ['device', 'netboxdevice']:
        object_url = 'dcim:device_edit'
        object_name = object_to_link.name
        url = reverse(object_url, kwargs={'pk': object_to_link.id}) + f"?serial={prefilled_argument}"
    else:
        return ''

    return f'<a href="{url}" class="btn btn-primary btn-sm lh-1">{object_name}</a>'

def mask_to_cidr(ipv4_mask: str) -> str:
    """
    Converts an IPv4 subnet mask to its CIDR notation.

    Args:
        ipv4_mask (str): The IPv4 subnet mask in dot-decimal notation (e.g., "255.255.255.0").

    Returns:
        str: The CIDR notation corresponding to the subnet mask (e.g., "/24").
    """
    # Split the mask into octets
    octets = ipv4_mask.split(".")
    # Convert each octet to its binary form and count the '1's
    cidr = sum(bin(int(octet)).count('1') for octet in octets)
    # Return the CIDR notation
    return f"/{cidr}"

def get_most_common_interface_type(iface_name: str) -> Optional[str]:
    """Gets the most common interface type for a given interface name.

    Args:
        iface_name (str): The name of the interface.

    Returns:
        Optional[str]: The most common interface type, or None if not found.
    """

    def get_interface_base_name(interface_name: str) -> str:
        """Extracts the base name of an interface by removing numbers and special characters."""
        return re.sub(r'[\d/\-]', '', interface_name)

    interface_templates = InterfaceTemplate.objects.filter(name=iface_name)

    if not interface_templates.exists():
        interface_templates = InterfaceTemplate.objects.filter(name__icontains=iface_name)

    if not interface_templates.exists():
        interface_templates = InterfaceTemplate.objects.filter(
            name__icontains=get_interface_base_name(iface_name))

    if not interface_templates.exists():
        return None  # No matching interface templates found

    # Count occurrences of each type
    type_counts = Counter(template.type for template in interface_templates)

    # Get the most common type
    most_common_type, _ = type_counts.most_common(1)[0]

    return most_common_type

def extract_chassis_number(name: str, display_as_string: bool = False) -> Optional[Union[int, str]]:
    """Extracts the chassis number from a given name string.

    Args:
        name (str): The input string containing chassis information.
        display_as_string (bool, optional): Whether to return the number as a string. Defaults to False.

    Returns:
        Optional[Union[int, str]]: The extracted chassis number or None if not found.
    """

    match = re.search(r"(Switch|Chassis) (\d+)", name, re.IGNORECASE)
    if match:
        chassis_number = match.group(2)
        if not display_as_string:
            return int(chassis_number)
        return chassis_number
    return None

def extract_slot_or_module_number(name: str, display_as_string: bool = False) -> Optional[Union[int, str]]:
    """Extracts the slot or module number from a given name string.

    Args:
        name (str): The input string containing slot or module information.
        display_as_string (bool, optional): Whether to return the number as a string. Defaults to False.

    Returns:
        Optional[Union[int, str]]: The extracted slot or module number, or None if not found.
    """
    match = re.search(r"(Slot|Module) (\d+)", name, re.IGNORECASE)
    if match:
        slot_number = match.group(2)
        if not display_as_string:
            return int(slot_number)
        return slot_number

    # If no match, check for formats like "Gi1/9/32" or "Te1/3/1"
    match = re.search(r"\w+\d+/(\d+)/\d+(?:/\d+)?", name)
    if match:
        slot_number = match.group(1)  # Extract second number
        if not display_as_string:
            return int(slot_number)
        return slot_number

    return None


def is_valid_interface(interface_name: str) -> bool:
    """Checks if the given interface name is valid.

    Args:
        interface_name (str): The name of the interface.

    Returns:
        bool: True if the interface is valid, False otherwise.
    """

    if "appgigabitethernet" in interface_name.lower():
        return False

    match = re.search(r'\D+(\d+)/(\d+)', interface_name)

    if match:
        if int(match.group(1)) == 0:
            return True

        return int(match.group(2)) == 0

    return True

def extract_interface_type(name: str) -> str:
    # Extract leading alphabetic prefix from the interface name
    match = re.match(r"[A-Za-z\-]+", name)
    return match.group(0) if match else ""

def is_device_type_template(actual_interface) -> bool:
    related_device = actual_interface.device
    related_device_type = related_device.device_type
    related_interface_templates = InterfaceTemplate.objects.filter(device_type=related_device_type)

    actual_prefix = extract_interface_type(canonical_interface_name(actual_interface.name))

    for related_interface_template in related_interface_templates:
        template_prefix = extract_interface_type(canonical_interface_name(related_interface_template.name))
        if actual_prefix and actual_prefix == template_prefix:
            return True

    return False



def element_list_to_dict(list_to_transform: List[Dict[str, Union[str, int]]],
                         selected_key: str) -> Dict[str, Dict[str, Union[str, int]]]:
    """Transforms a list of dictionaries into a dictionary using a selected key as the new key.

    Args:
        list_to_transform (List[Dict[str, Union[str, int]]]): The list of dictionaries to transform.
        selected_key (str): The key to use as the new dictionary's key.

    Returns:
        Dict[str, Dict[str, Union[str, int]]]: The transformed dictionary.
    """

    new_dict = {}
    for list_element in list_to_transform:
        new_dict[str(list_element[selected_key])] = list_element
    return new_dict

def cisco_intermediate_interface_name(interface: str) -> str:
    # Mapping from canonical type to intermediate abbreviation
    INTERMEDIATE_ABBREVIATIONS = {
        "FastEthernet": "FastE",
        "GigabitEthernet": "GigE",
        "FortyGigabitEthernet": "FortyGigE",
        "HundredGigabitEthernet": "HundredGigE",
        "TwoHundredGigabitEthernet": "TwoHundredGigE",
        "FourHundredGigabitEthernet": "FourHundredGigE"
    }

    """
    Convert a canonical Cisco interface name into an intermediate abbreviation.
    E.g., 'HundredGigabitEthernet1/1/1' → 'HundredGigE1/1/1'
    """
    """
    Convert a canonical Cisco interface name into an intermediate abbreviation.
    Falls back to the original input if the interface type is unknown.
    """
    match = re.match(r"^([A-Za-z\-]+)(\d.*)", interface)
    if not match:
        return interface  # invalid format, return as-is

    iface_type, iface_suffix = match.groups()
    abbrev_type = INTERMEDIATE_ABBREVIATIONS.get(iface_type)

    if not abbrev_type:
        return interface  # unknown type, return as-is

    return abbrev_type + iface_suffix


def extract_position(module_bay_name: str) -> str:
    """Extracts the trailing numeric position from a module bay name string.

    This function reads the input string in reverse and collects trailing
    digits until a non-digit character is encountered. The resulting
    digits are then reversed to return them in their original order.

    Args:
        module_bay_name (str): The name of the module bay, potentially ending with digits.

    Returns:
        str: The numeric position extracted from the end of the input string.
             Returns an empty string if no trailing digits are found.
    """
    string_position = ""
    for char in reversed(module_bay_name):
        if char.isdigit():
            string_position += char
        else:
            break
    return string_position[::-1]

