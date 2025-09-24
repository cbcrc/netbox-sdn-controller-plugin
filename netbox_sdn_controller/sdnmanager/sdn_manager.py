import os
import re
import uuid
from copy import deepcopy
from typing import Callable, List, Optional, Dict, Any, Union, NoReturn
from dnacentersdk import api
from dnacentersdk.exceptions import ApiError
from django.contrib.contenttypes.models import ContentType
from netutils.interface import canonical_interface_name, abbreviated_interface_name
from dcim.models import (Device,
                         DeviceType,
                         Site,
                         Interface,
                         ModuleBay,
                         ModuleType,
                         DeviceRole,
                         MACAddress)
from dcim.choices import ModuleStatusChoices, InterfaceTypeChoices
from ipam.models import IPAddress
from ipam.choices import IPAddressStatusChoices
from tenancy.models import Tenant
from core.models import ObjectChange, ObjectType
from core.choices import ObjectChangeActionChoices
from extras.models.customfields import CustomField
from users.models import User
from netbox_sdn_controller.models import SdnController, SdnControllerDevicePrototype, SdnModule, SdnDevice
from netbox_sdn_controller.choices import DevicePrototypeStatusChoices
from netbox_sdn_controller.utils import (get_site_from_prefix,
                                         get_link_text,
                                         get_edit_link_text,
                                         mask_to_cidr,
                                         get_most_common_interface_type,
                                         extract_chassis_number,
                                         extract_slot_or_module_number,
                                         is_valid_interface,
                                         is_device_type_template,
                                         element_list_to_dict,
                                         cisco_intermediate_interface_name,
                                         extract_position)

from extras.scripts import BaseScript

class SdnManager:
    """
    SDN Manager for handling interactions with SDN controllers.

    This class provides functionality for authenticating with an SDN controller,
    fetching devices and interfaces, syncing them with the NetBox database, and
    handling device prototypes.
    """

    def __init__(self, script: Optional[BaseScript] = None, **kwargs: Union[int, List[int]]) -> None:
        """
        Initialize the SDN Manager.

        Args:
            script (Optional[BaseScript]): An optional reference to a script for logging or additional functionality.
            **kwargs (Union[int, List[int]]): Additional keyword arguments. Supported keys:
                - pk (int): The primary key of the SDN controller.
                  If provided, the corresponding controller is fetched and authenticated.
                - prototype_id_list (List[int]): A list of prototype IDs to filter on.
                  The related prototypes are fetched, excluding those marked as deleted.

        Attributes:
            script (Optional[BaseScript]): The script instance provided during initialization.
            device_list (Optional[List]):
                Placeholder for a list of devices managed by the SDN Manager (initialized as `None`).
            prototype_list (Optional[List]): Placeholder for a list of prototypes (initialized as `None`).
            prototype_object_list (Optional[QuerySet]):
                A queryset of prototype objects filtered by `prototype_id_list` (if provided).
            sdn_controller (Optional[SdnController]):
                The SDN controller instance fetched based on the `pk` (if provided).
            api: The authenticated API client for interacting with the SDN controller
                (initialized if `pk` is provided).
        """
        self.script = script
        self.device_list = None
        self.prototype_list = None
        self.prototype_object_list = None
        self.prototype_uuid_list = None
        self.log_all_errors = False
        self.user = None

        if "user_id" in kwargs:
            self.user = User.objects.filter(id=kwargs["user_id"]).first()

        if "pk" in kwargs and isinstance(kwargs["pk"], int):
            self.sdn_controller = SdnController.objects.filter(pk=kwargs["pk"]).first()
            self.api = self.auth()

        if "log_all_errors" in kwargs and isinstance(kwargs["log_all_errors"], bool):
            self.log_all_errors = kwargs["log_all_errors"]

        if "prototype_id_list" in kwargs:
            self.prototype_object_list = SdnControllerDevicePrototype.objects.filter(
                id__in=kwargs["prototype_id_list"]
            ).exclude(
                sync_status=DevicePrototypeStatusChoices.DELETED
            )
            if "fetch_and_sync" in kwargs:
                self.prototype_uuid_list = [
                    obj.instance_uuid for obj in self.prototype_object_list
                ]


    def auth(self) -> Optional[api.DNACenterAPI]:
        """
        Authenticate with the SDN controller and return the API client object.

        :return: An authenticated `DNACenterAPI` object if successful, otherwise None.
        """
        try:
            if self.sdn_controller.sdn_type == "Catalyst Center":
                api_obj = api.DNACenterAPI(
                    username=os.getenv('DNAC_USER', ''),
                    password=os.getenv('DNAC_PASSWORD', ''),
                    base_url="https://" + self.sdn_controller.hostname,
                    version=self.sdn_controller.version,
                    verify=True, # Verifies SSL certificates
                )

                return api_obj

        except Exception as error_msg:
            if self.script:
                self.script.log_failure(f"Error for {self.sdn_controller.hostname}: {error_msg}")

        return None

    def object_changelog(self, object_action: int, instance: object) -> None:
        """Creates and saves an ObjectChange entry if a user is available.

        Args:
            object_action (int): The action performed on the object (e.g., create, update, delete).
            instance (object): The instance of the changed object.
        """
        if self.user:
            change = ObjectChange(
                action=object_action,
                changed_object=instance,
                object_repr=str(instance),
                request_id=uuid.uuid4(),
                user=self.user,
                user_name=self.user.get_username()
            )
            change.save()

    def offset_handler(self,
                       fetch_function: Callable[[api.DNACenterAPI, int, Optional[str], Optional[str]],
                       List[Dict[str, Any]]],
                       family: Optional[str] = None,
                       prototype_device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Generalized method to fetch paginated data from the SDN controller.

        :param fetch_function: A callable function to fetch data with parameters
                               (API, offset, family, prototype_device_id).
        :param family: The family type to filter devices (if applicable).
        :param prototype_device_id: The ID of the device for which to fetch interfaces (if applicable).
        :return: A list of dictionaries containing the aggregated data.
        """
        data = []
        offset = 1

        while True:
            if prototype_device_id:
                # Fetching interfaces for a specific device
                partial_list = fetch_function(self.api, offset, None, prototype_device_id)
            elif family:
                # Fetching devices with a specific family
                partial_list = fetch_function(self.api, offset, family, None)
            else:
                # General fetching (without family or device filtering)
                partial_list = fetch_function(self.api, offset, None, None)

            if partial_list:
                data.extend(partial_list)
                if len(partial_list) < 500:
                    break  # Stop if we received fewer than 500 items
                offset += 500  # Move to the next batch
            else:
                break  # No more data to fetch

        return data

    def import_devices(self) -> Optional[List[Dict[str, Any]]]:

        """
        Fetch and import the list of devices from the SDN controller.

        This method checks the SDN controller type and, if it matches the expected type
        ("Catalyst Center"), fetches the device list using a handler for paginated API responses.

        Returns:
            Optional[List[Dict[str, Any]]]: A list of device dictionaries if successful, otherwise None.
        """
        if self.sdn_controller.sdn_type == "Catalyst Center":
            self.device_list = self.offset_handler(
                fetch_function=lambda controller_api, offset, family, _: (
                    controller_api.devices.get_device_list(offset=offset, family=family).response
                ),
                family=self.sdn_controller.device_families
            )
            return self.device_list
        return None


    def sync_sdn_controller_devices(self) -> None:
        """
        Fetch devices and their related data from the SDN controller
        and synchronize them with the database.

        This includes fetching interfaces, VLANs, and other relevant data,
        and saving them as device prototypes.
        """

        def extract_interface_number(interface_name: str) -> Optional[int]:
            """
            Extracts the number before the first slash in a given interface name.

            Args:
                interface_name (str): The interface name (e.g., "TenGigabitEthernet2/1/4").

            Returns:
                Optional[int]: The number before the first slash, or None if no number is found.
            """
            match = re.match(r".*?(\d+)/", interface_name)
            return int(match.group(1)) if match else None



        if not self.device_list:
            self.import_devices()

        prototype_list = []

        if self.sdn_controller.sdn_type == "Catalyst Center":
            splitted_device_list = self.split_device_list()
            for prototype_device in splitted_device_list:
                try:
                    prototype_device.has_modules = False

                    modules = self.extract_module_positions(prototype_device)
                    prototype_device.has_modules = len(modules) > 0

                    interfaces = self.offset_handler(
                                    fetch_function=lambda controller_api, offset, _, prototype_device_id: (
                                        controller_api.devices.get_interface_info_by_id(
                                            device_id=prototype_device_id,
                                            offset=offset
                                        ).response
                                    ),
                                    prototype_device_id=prototype_device.id
                                )


                    if prototype_device.is_multiple:
                        rank = prototype_device.rank

                        def should_include_interface(interface: Dict[str, Any]) -> bool:
                            """
                            Determine whether an interface should be included based on its type, rank, and properties.

                            Args:
                                interface (Dict[str, Any]): A dictionary representing the interface. Expected keys:
                                    - portName (str): The name of the port, used to extract the interface number.
                                    - interfaceType (str): The type of the interface (e.g., "Virtual").

                            Returns:
                                bool: True if the interface meets the inclusion criteria
                                      based on the rank and its properties, otherwise False.

                            Notes:
                                - The inclusion criteria depend on the global variable `rank`.
                                - If `rank` is 1, interfaces of type "Virtual"
                                  or with a port number less than 2 are included.
                                - For other values of `rank`, the interface is included
                                  if its port number matches `rank`.
                            """

                            if "appgigabitethernet" in interface.portName.lower():
                                return False

                            interface_number = extract_interface_number(interface.portName)

                            # Include conditions based on rank and interface properties
                            if rank == 1:
                                return (interface_number is None or interface_number < 2)

                            return interface_number == rank if interface_number else False

                        def should_include_module(module) -> bool:

                            module_switch_number = module.switchnumber

                            return int(module_switch_number) == rank if module_switch_number else False




                        interfaces = [
                            interface for interface in interfaces if should_include_interface(interface)
                        ]

                        modules = [
                            module for module in modules if should_include_module(module)
                        ]

                    vlans = self.api.devices.get_device_interface_vlans(prototype_device.id).response

                except ApiError as e:  # dnacentersdk does not handle empty list
                    if "404" in str(e):
                        interfaces = []
                        vlans = []


                vlan_dict = element_list_to_dict(vlans, 'vlanNumber')

                # Step 1: Filter out interfaces with duplicate `ipv4Address`
                filtered_interfaces = {}
                for interface in interfaces:
                    ipv4 = interface.ipv4Address
                    if ipv4 and (
                        ipv4 not in filtered_interfaces
                        or interface.interfaceType == "Physical"
                    ):
                        filtered_interfaces[ipv4] = interface

                # Step 2: Prioritize 'physical' interfaces over virtual interface with same address
                for interface in interfaces:
                    interface.vlan = vlan_dict.get(interface["vlanId"], {})
                    if not interface.ipv4Address:
                        continue
                    if filtered_interfaces.get(interface.ipv4Address) != interface:
                        interface.ipv4Address = None

                    if interface.ipv4Address == prototype_device.managementIpAddress:
                        prototype_device.managementIpAddressInterface = interface

                modules_dict = element_list_to_dict(modules, 'name')
                prototype_device.modules = modules_dict

                interfaces_dict = element_list_to_dict(interfaces, 'portName')
                prototype_device.interfaces = interfaces_dict
                prototype_device.vlans = vlans

                processed_prototype = self.process_prototype(prototype_device)
                prototype_list.append(processed_prototype)

        self.prototype_list = prototype_list

    def check_for_deleted_devices(self) -> None:
        """
        Mark device prototypes as deleted if they are no longer present in the SDN controller.

        This method checks the current `prototype_list` of device prototypes retrieved from the SDN controller
        against the prototypes stored in the database. If a database-stored device prototype is not present
        in the `prototype_list`, its `sync_status` is updated to `DELETED`.

        Side Effects:
        - Calls `sync_sdn_controller_devices` to populate `prototype_list` if it is empty.
        - Updates the `sync_status` of deleted device prototypes and saves them to the database.
        """
        if not self.prototype_list:
            self.sync_sdn_controller_devices()

        prototype_keys = {(dp.instance_uuid, dp.serial) for dp in self.prototype_list}
        existing_prototypes = SdnControllerDevicePrototype.objects.filter(sdn_controller=self.sdn_controller)

        # Mark and save prototypes not found in the current prototype list as deleted
        for existing_device_prototype in existing_prototypes:
            key = (existing_device_prototype.instance_uuid, existing_device_prototype.serial)
            if key not in prototype_keys:
                existing_device_prototype.sync_status = DevicePrototypeStatusChoices.DELETED
                existing_device_prototype.save()
                self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, existing_device_prototype)

    def process_prototype(self, prototype: Dict[str, Any]) -> Optional[SdnControllerDevicePrototype]:
        """
        Process a device dictionary into an `SdnControllerDevicePrototype`.

        Args:
            prototype (Dict[str, Any]): A dictionary containing device details.

        Returns:
            Optional[SdnControllerDevicePrototype]: An `SdnControllerDevicePrototype` object,
            or None if processing fails.
        """
        tenant = None
        if self.sdn_controller.default_tenant:
            tenant = Tenant.objects.filter(id=self.sdn_controller.default_tenant.id).first()
        hostname = prototype.hostname.split(".")[0]
        serial = prototype.serialNumber
        sdn_role = prototype.role
        raw_data = prototype.get_dict()
        sdn_management_ip = None
        if prototype.managementIpAddress:
            sdn_management_ip = prototype.managementIpAddress
            sdn_management_ip_address_interface= raw_data.get("managementIpAddressInterface", None)
            if sdn_management_ip_address_interface:
                ipv4_mask = sdn_management_ip_address_interface.get("ipv4Mask", None)
                if ipv4_mask:
                    sdn_management_ip = sdn_management_ip + mask_to_cidr(ipv4_mask)

        stack_info = prototype.stack_info.get_dict()
        instance_uuid = prototype.instanceUuid
        family = prototype.family
        sdn_device_type = prototype.platformId
        related_netbox_device = None
        stack_index = (str(prototype.rank)).strip()


        matching_netbox_device = Device.objects.filter(serial=serial).first()
        if matching_netbox_device:
            if hostname[-2:] == "-1" and matching_netbox_device.name[-2:] != "-1":
                rename = matching_netbox_device.name + "-1"
                if not Device.objects.filter(name=rename).first():
                    matching_netbox_device.name = rename
                    matching_netbox_device.save()
                    self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, matching_netbox_device)


        device_type = DeviceType.objects.filter(model=sdn_device_type).first()
        if not device_type:
            device_type = DeviceType.objects.filter(part_number=sdn_device_type).first()


        role = None
        site = None
        score = 0
        primary_ip4 = None

        if sdn_management_ip:
            primary_ip4 = IPAddress.objects.filter(address__istartswith=sdn_management_ip).first()
            if not primary_ip4:
                primary_ip4 = IPAddress(
                                address=sdn_management_ip,
                                status=IPAddressStatusChoices.STATUS_ACTIVE,
                                tenant=tenant # Set the IP address status
                                )
                primary_ip4.save()
                self.object_changelog(ObjectChangeActionChoices.ACTION_CREATE, primary_ip4)



            if primary_ip4:
                site = get_site_from_prefix(primary_ip4)
            else:
                site = get_site_from_prefix(sdn_management_ip.split("/")[0])

        if (not matching_netbox_device) and hostname:
            related_netbox_device = Device.objects.filter(name=hostname).first()

        if (not related_netbox_device) and primary_ip4:
            related_netbox_device = Device.objects.filter(primary_ip4=primary_ip4).first()

        if not related_netbox_device:
            related_netbox_device = Device.objects.filter(name__icontains=hostname).first()

        if related_netbox_device and not matching_netbox_device and serial:
            if not related_netbox_device.serial or related_netbox_device.serial == "":
                related_netbox_device.serial = serial
                related_netbox_device.save()
                self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, related_netbox_device)
                matching_netbox_device = related_netbox_device

        sync_status = DevicePrototypeStatusChoices.DISCOVERED

        if matching_netbox_device:
            site = matching_netbox_device.site
            if matching_netbox_device.tenant:
                tenant = matching_netbox_device.tenant
            role = matching_netbox_device.role

        if matching_netbox_device:
            score += 5
            if serial == matching_netbox_device.serial:
                score += 1
            if hostname == matching_netbox_device.name:
                score += 1

        def extract_facility_from_hostname(field: str) -> str | None:
            pattern = self.sdn_controller.regex_template.get(field)
            if hostname and pattern:
                match = re.search(pattern, hostname)
                return match.group(1).strip() if match else None
            return None

        if not site and self.sdn_controller.regex_template:
            site_facility = extract_facility_from_hostname("site")
            if site_facility:
                site = Site.objects.filter(facility__iexact=site_facility).first()

        if not role and self.sdn_controller.regex_template:
            role_facility = extract_facility_from_hostname("role")
            if role_facility:
                possible_roles = DeviceRole.objects.filter(custom_field_data__facility=role_facility)
                for possible_role in possible_roles:
                    all_devices = Device.objects.filter(role=possible_role)
                    for possible_device in all_devices:
                        if possible_device.device_type.manufacturer.name.lower() == "cisco":
                            role = possible_role
                            break
                    if role:
                        break


        if primary_ip4:
            score += 1
        if device_type:
            score += 1
        if site:
            score += 1

        sdn_controller_device_prototype = SdnControllerDevicePrototype(
            serial=serial,
            sdn_hostname=hostname,
            sdn_management_ip=sdn_management_ip,
            primary_ip4=primary_ip4,
            matching_netbox_device=matching_netbox_device,
            related_netbox_device=related_netbox_device,
            sdn_device_type=sdn_device_type,
            device_type=device_type,
            sdn_role=sdn_role,
            stack_info=stack_info,
            stack_index=stack_index,
            role=role,
            raw_data=raw_data,
            sdn_controller=self.sdn_controller,
            instance_uuid=instance_uuid,
            family=family,
            site=site,
            tenant=tenant,
            score=score,
            sync_status=sync_status,
        )

        existing_device_prototype = SdnControllerDevicePrototype.objects.filter(
            instance_uuid=sdn_controller_device_prototype.instance_uuid,
            serial=sdn_controller_device_prototype.serial,
        ).first()

        prototype_action = ObjectChangeActionChoices.ACTION_UPDATE
        if not existing_device_prototype:
            existing_device_prototype = sdn_controller_device_prototype
            prototype_action = ObjectChangeActionChoices.ACTION_CREATE
        else:
            for field in sdn_controller_device_prototype._meta.fields:
                field_name = field.name
                if field_name not in ["id", "device_type", "primary_ip4", "site", "tenant", "role"]:
                    setattr(existing_device_prototype, field_name, getattr(sdn_controller_device_prototype, field_name))

        existing_device_prototype.save()
        self.object_changelog(prototype_action, existing_device_prototype)


        if prototype.get("errorCode"):
            error_message = (
                f"Check {existing_device_prototype.sdn_controller.sdn_type} error for prototype "
                f"{get_link_text(existing_device_prototype)}. "
                f"Error code: {prototype['errorCode']}. "
                f"Error description: {prototype['errorDescription']}."
            )
            self.script.log_failure(error_message)

        return existing_device_prototype

    def import_fetched_elements_in_netbox(self) -> bool:
        """
        Import device prototypes fetched from the SDN Controller into NetBox.

        This method iterates through a list of device prototypes, checks for their
        existence in NetBox, and creates them if they don't exist. If a device already
        exists, it logs a message indicating so. Each prototype is updated with its
        corresponding NetBox device and its sync status.

        Returns:
            bool: True if the import process completes without critical errors, otherwise False.
        """

        def log_mismatch(attribute: str,
                         selected_prototype: SdnControllerDevicePrototype,
                         netbox_device: Device) -> None:
            """
            Log a warning when there is a mismatch between a prototype and a NetBox device attribute.

            Args:
                attribute (str): The name of the attribute that does not match.
                selected_prototype (SdnControllerDevicePrototype): The prototype object involved in the mismatch.
                netbox_device (Device): The NetBox device object involved in the mismatch.

            Behavior:
                - Logs a warning using the `script.log_warning` method.
                - The log message includes the mismatched attribute and links to the prototype and NetBox device.
            """
            self.script.log_warning(
                f"{attribute} doesn't match between prototype "
                f"{get_link_text(selected_prototype)} and "
                f"NetBox Device {get_link_text(netbox_device)}"
            )

        def process_device_attributes(new_device: Device, selected_prototype: SdnControllerDevicePrototype) -> None:
            """
            Evaluate and log mismatched attributes between a new device and a selected prototype.

            Args:
                new_device (Device): The device object to evaluate.
                selected_prototype (SdnControllerDevicePrototype): The prototype object to compare against.

            Behavior:
                - Compares specific attributes of the `new_device` with the `selected_prototype`:
                    - `name` vs. `sdn_hostname`
                    - `role`
                    - `device_type`
                    - `tenant`
                    - `site`
                    - `serial`
                - Logs a warning for each mismatched attribute using the `log_mismatch` function.
                - The attribute name in the log message is capitalized for readability.
            """
            mismatched_attributes = {
                "name": new_device.name != selected_prototype.sdn_hostname,
                "role": new_device.role != selected_prototype.role,
                "device_type": new_device.device_type != selected_prototype.device_type,
                "tenant": new_device.tenant != selected_prototype.tenant,
                "site": new_device.site != selected_prototype.site,
                "serial": new_device.serial != selected_prototype.serial,
            }

            for attr, mismatch in mismatched_attributes.items():
                if mismatch:
                    log_mismatch(attr.capitalize(), selected_prototype, new_device)

        def matching_interfaces(selected_prototype: SdnControllerDevicePrototype, existing_device: Device) -> bool:
            """
            Determine whether any interface from the selected prototype matches an interface on the existing device.

            Args:
                selected_prototype (SdnControllerDevicePrototype):
                    The prototype object containing interface definitions.
                existing_device (Device):
                    The existing device whose interfaces are to be checked for matches.

            Returns:
                bool:
                    - `True` if at least one interface matches between the prototype and the existing device.
                    - `True` if the existing device has no interfaces defined.
                    - `False` if no matches are found.

            Behavior:
                - Retrieves all interfaces associated with the `existing_device`.
                - If the existing device has no interfaces, it considers them as matching (`True`).
                - Compares each interface from the `selected_prototype`'s `raw_data["interfaces"]`:
                    1. Checks for an exact match by interface name.
                    2. If no exact match, attempts to match based on a suffix pattern
                       extracted from the prototype's interface name.
                - Uses regex to match interface names with potential suffix variations.

            Notes:
                - The `raw_data` field in `selected_prototype` must contain an `interfaces` dictionary.
                - Interface name matching is case-sensitive and relies
                  on the specific naming conventions of `iface_name`.
            """
            existing_interfaces = Interface.objects.filter(device=existing_device)
            existing_interfaces_count = existing_interfaces.count()
            if existing_interfaces_count == 0:
                return True


            all_prototype_interfaces = selected_prototype.raw_data.get("interfaces", {})

            for iface_name, _ in all_prototype_interfaces.items():

                interface_object = existing_interfaces.filter(name__iexact=iface_name).first()

                if interface_object:
                    return True

                # Extract the relevant portion of iface_name
                iface_pattern = re.search(r'(\d+(/\d+)+)$', iface_name, re.IGNORECASE)
                iface_suffix = iface_pattern.group(1) if iface_pattern else None
                if iface_suffix:
                    # Adjust regex pattern for Django filtering
                    regex_pattern = rf'(\D|^){iface_suffix}(\D|$)'
                    interface_object = existing_interfaces.filter(name__iregex=regex_pattern).first()
                    if interface_object:
                        return True

            return False

        def process_interfaces(
                new_device: "Device",
                selected_prototype: "Prototype",
                map_interfaces: bool
            ) -> bool:
            """
            Process and map interfaces for a new device based on a selected prototype.

            Args:
                new_device (Device): The NetBox device object to which interfaces will be mapped.
                selected_prototype (Prototype): The prototype object containing interface definitions and attributes.
                map_interfaces (bool): Indicates whether to map the prototype interfaces to the new device's interfaces.

            Returns:
                bool:
                    - `True` if all interfaces were successfully processed and mapped.
                    - `False` if interface mapping fails due to mismatches or errors.

            Behavior:
                - Retrieves existing interfaces for the `new_device` and compares them with the prototype's interfaces.
                - Logs a failure and aborts if interface naming conventions
                  do not match and `map_interfaces` is enabled.
                - For each interface in the prototype:
                    1. Checks if a corresponding interface exists on the `new_device`.
                    2. Matches interfaces based on exact names or regex patterns derived from naming conventions.
                    3. Sets or updates attributes such as `speed`, `description`, `MAC address`, and `duplex`.
                    4. Creates new interface objects if necessary, using defaults and inferred values for `type`.
                - Logs warnings for mismatched attributes between the prototype and the device.
                - Handles associated IP addresses for each interface using `process_ip_addresses`.

            Error Handling:
                - Logs failures for exceptions encountered while creating or updating interfaces.
                - Logs a failure and stops if interface matching falls below expected thresholds.

            Notes:
                - Prototype interface attributes are sourced from the `raw_data["interfaces"]` dictionary.
                - Interface matching uses a fallback regex pattern to accommodate naming variations.
                - The `duplex` attribute is matched against a predefined set of choices (`"half"`, `"full"`, `"auto"`).
                - The method assumes that interface type mappings,
                  if needed, are predefined (e.g., `speed_to_type_map`).

            Example:
                ```python
                success = process_interfaces(new_device=device, selected_prototype=prototype, map_interfaces=True)
                if success:
                    print("Interfaces processed successfully.")
                else:
                    print("Interface processing failed.")
                ```
            """
            created_by_custom_field = CustomField.objects.filter(name='created_by').first()

            duplex_choices = ["half", "full", "auto"]

            template_created_interfaces = Interface.objects.filter(device=new_device)

            if map_interfaces and not matching_interfaces(selected_prototype, new_device):
                self.script.log_failure(f"Device {get_link_text(new_device)} interface naming doesnt match " +
                                        f"{selected_prototype.sdn_controller.sdn_type} " +
                                        f"{get_link_text(selected_prototype)} prototype interfaces. " +
                                        "Check serial number and stack number")

                return False

            all_prototype_interfaces = selected_prototype.raw_data.get("interfaces", {})
            for iface_name, iface_data in all_prototype_interfaces.items():
                try:
                    iface_duplex = next(
                        (choice for choice in duplex_choices if choice in iface_data.get("duplex", "").lower()), None)

                    iface_attrs = {
                        "speed": int(iface_data.get("speed", 0)) if iface_data.get("speed") else None,
                        "description": iface_data.get("description"),
                        "duplex": iface_duplex
                    }

                    interface_object = template_created_interfaces.filter(name__iexact=iface_name).first()
                    interface_action = ObjectChangeActionChoices.ACTION_UPDATE
                    # check for interface match percentage and abort if less than 70%
                    if not interface_object and is_valid_interface(iface_name):
                        interface_type = iface_data.get("interfaceType", None)
                        if interface_type.lower() == "physical":
                            most_common = get_most_common_interface_type(iface_name)
                            if most_common:
                                interface_type = most_common

                        if interface_type.lower() == "virtual" and "port-channel" in iface_name.lower():
                            interface_type = InterfaceTypeChoices.TYPE_LAG

                        interface_object = Interface(device=new_device,
                                                     name=iface_name,
                                                     type=interface_type)

                        interface_action = ObjectChangeActionChoices.ACTION_CREATE


                    if interface_object:

                        for attr, value in iface_attrs.items():
                            existing_value = getattr(interface_object, attr, None)
                            if existing_value and existing_value != value:
                                self.script.log_warning(f"{attr.capitalize()} doesn't match between "
                                                        f"prototype {get_link_text(selected_prototype)} " +
                                                        f"interface {iface_name} and NetBox device " +
                                                        f"{get_link_text(new_device)}")
                            elif not existing_value:
                                setattr(interface_object, attr, value)

                        existing_mac = getattr(interface_object, "primary_mac_address", None)
                        prototype_mac = iface_data.get("macAddress")

                        if prototype_mac:
                            needs_update = not existing_mac or existing_mac.mac_address != prototype_mac

                            if needs_update:
                                mac_object, created = MACAddress.objects.get_or_create(
                                    mac_address=prototype_mac,
                                    defaults={"assigned_object": interface_object},
                                )
                                if created:
                                    created_by_custom_field.object_types.add(
                                        ObjectType.objects.get_for_model(mac_object.__class__))
                                    mac_object.custom_field_data['created_by'] = created_by_custom_field.serialize(
                                        self.user)
                                    mac_object.save()
                                interface_object.primary_mac_address = mac_object


                        if iface_data.get("portMode") == "access":
                            interface_object.mode = "access"
                        elif iface_data.get("portMode") == "trunk":
                            interface_object.mode = "tagged"



                        interface_object.save()
                        self.object_changelog(interface_action, interface_object)
                        process_ip_addresses(selected_prototype, iface_data, interface_object)


                except Exception as e:
                    self.script.log_failure(
                        f"Unable to create interface {iface_name} for prototype " +
                        f"{get_link_text(selected_prototype)} - {e}")

            return True


        def process_module_bays(
                new_device: "Device",
                selected_prototype: "Prototype"
            ) -> bool:
            """
            Processes the module bays for the given device based on the selected prototype.

            Args:
                new_device (Device): The device to process the module bays for.
                selected_prototype (Prototype): The prototype to match module bays against.
                map_module_bays (bool): Flag indicating whether to map module bays or not.

            Returns:
                bool: True if the module bays were processed successfully, False otherwise.
            """


            template_created_module_bays = ModuleBay.objects.filter(device=new_device)


            all_prototype_module_bays = selected_prototype.raw_data.get("modules", {})
            for module_bay_name, module_bay_data in all_prototype_module_bays.items():
                try:
                    module_bay_attrs = {
                        "description": module_bay_data.get("description"),
                    }
                    position_match = re.search(r'(\d+)(?=\D*$)', module_bay_name)
                    position = position_match.group(1) if position_match else None

                    module_bay_object = template_created_module_bays.filter(name__iexact=module_bay_name).first()

                    if not module_bay_object:
                        module_bay_object = template_created_module_bays.filter(position=position).first()
                        if module_bay_object:
                            module_bay_object.name = module_bay_name
                            module_bay_object.save()
                            self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, module_bay_object)

                    if not module_bay_object:
                        for template_created_module_bay in template_created_module_bays:
                            if extract_position(template_created_module_bay.name) == position:
                                module_bay_object = template_created_module_bay
                                module_bay_object.name = module_bay_name
                                module_bay_object.save()
                                self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, module_bay_object)
                                break

                    module_bay_action = ObjectChangeActionChoices.ACTION_UPDATE
                    if not module_bay_object:

                        module_bay_object = ModuleBay(
                            device=new_device,
                            name=module_bay_name,
                            position=position

                        )
                        module_bay_action = ObjectChangeActionChoices.ACTION_CREATE

                    for attr, value in module_bay_attrs.items():
                        existing_value = getattr(module_bay_object, attr, None)
                        if existing_value and existing_value != value:
                            self.script.log_warning(f"{attr.capitalize()} doesn't match between "
                                                    f"prototype {get_link_text(selected_prototype)} " +
                                                    f"module bay {module_bay_name} and NetBox device " +
                                                    f"{get_link_text(new_device)}")
                        elif not existing_value:
                            setattr(module_bay_object, attr, value)


                    module_bay_object.save()
                    self.object_changelog(module_bay_action, module_bay_object)

                    new_device.module_bay_count = ModuleBay.objects.filter(device=new_device).count()
                    new_device.save()
                    self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, new_device)

                    process_module(selected_prototype, module_bay_data, module_bay_object)


                except Exception as e:
                    self.script.log_failure(
                        f"Unable to create module bay {module_bay_name} for prototype " +
                        f"{get_link_text(selected_prototype)} - {e}")

            return True


        def process_module(
                selected_prototype: "Prototype",
                module_bay_data: Dict[str, str],
                module_bay_object: "ModuleBay"
        ) -> bool:
            """
            Processes and creates a module for a given module bay based on the prototype data.

            Args:
                selected_prototype (Prototype): The prototype that provides the module data.
                module_bay_data (dict): The data for the module bay including part number and serial number.
                module_bay_object (ModuleBay): The module bay to associate the module with.

            Returns:
                bool: True if the module was processed successfully, False otherwise.
            """

            try:
                current_device = module_bay_object.device

                module_type = module_bay_data.get("partNumber")
                module_type_object = ModuleType.objects.filter(model=module_type).first()
                if not module_type_object:
                    module_type_object = ModuleType.objects.filter(part_number=module_type).first()

                if module_type_object:


                    module_attrs = {
                        "module_type": module_type_object,
                        "serial": module_bay_data.get("serialNumber"),
                        "description": module_bay_data.get("description"),

                    }

                    existing_module = SdnModule.objects.filter(module_bay=module_bay_object).first()
                    module_action = ObjectChangeActionChoices.ACTION_UPDATE
                    if not existing_module:

                        existing_module = SdnModule(
                            device=current_device,
                            module_bay=module_bay_object,
                            status=ModuleStatusChoices.STATUS_ACTIVE,
                            serial=module_bay_data.get("serialNumber"),
                            module_type=module_type_object
                        )
                        module_action = ObjectChangeActionChoices.ACTION_CREATE

                    for attr, value in module_attrs.items():
                        existing_value = getattr(existing_module, attr, None)
                        if existing_value and existing_value != value:
                            self.script.log_warning(f"{attr.capitalize()} doesn't match between "
                                                    f"prototype {get_link_text(selected_prototype)} " +
                                                    f"module and module {get_link_text(existing_module)}")

                        elif not existing_value:
                            setattr(existing_module, attr, value)

                    existing_module._adopt_components = True
                    existing_module.save()
                    self.object_changelog(module_action, existing_module)

                    module_bay_object.save()
                    self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, module_bay_object)




                return True

            except Exception as e:
                self.script.log_warning(
                    f"Unable to create module with module type {module_type} for device " +
                    f"{get_link_text(current_device)} and module bay " +
                    f"{get_link_text(module_bay_object)} with prototype {get_link_text(selected_prototype)} - {e}")
                return False

        def process_ip_addresses(
                selected_prototype: "Prototype",
                iface_data: dict,
                interface_object: "Interface"
            ) -> None:
            """
            Processes and assigns IP addresses to a specific interface based on prototype data.

            Args:
                selected_prototype (Prototype): The prototype object containing raw data for IP address configuration.
                iface_data (dict): A dictionary containing interface-related data, including IP address and subnet mask.
                interface_object (Interface): The NetBox interface object to which the IP address will be assigned.

            Behavior:
                - Extracts the IPv4 address and subnet mask from `iface_data` and converts them to CIDR notation.
                - Checks if the IP address already exists in the database:
                    - If it exists, verifies its assignment and reassigns if necessary.
                    - If it doesn't exist, creates a new `IPAddress` object and assigns it to the `interface_object`.
                - Ensures the IP address has the appropriate `tenant` and `status` attributes.
                - Identifies and assigns the IP address as the device's primary IPv4 address
                  if it matches the prototype's management IP.

            Logging:
                - Logs warnings for mismatched or already assigned IP addresses.
                - Logs failures for exceptions during IP address creation or assignment.

            Error Handling:
                - Captures and logs exceptions that occur during the IP address processing.
                - Continues execution even if individual IP address processing fails.

            Notes:
                - Prototype IP addresses are retrieved from the `raw_data["managementIpAddress"]`
                  and `iface_data["ipv4Address"]` fields.
                - The method assumes the existence of a `mask_to_cidr` utility
                  for converting subnet masks to CIDR notation.
            """
            try:
                interface_object_type_id = ContentType.objects.get_for_model(interface_object).pk
                current_device = interface_object.device
                management_ip_address = selected_prototype.raw_data.get("managementIpAddress", None)
                ipv4_address = iface_data.get("ipv4Address", None)

                address_is_primary = False
                if management_ip_address and ipv4_address and management_ip_address == ipv4_address:
                    address_is_primary = True

                ipv4_mask = iface_data.get("ipv4Mask", None)
                if ipv4_address and ipv4_mask:
                    ipv4_address = ipv4_address + mask_to_cidr(ipv4_mask)

                if ipv4_address:
                    ip_address_object = IPAddress.objects.filter(address=ipv4_address).first()
                    ip_address_action = ObjectChangeActionChoices.ACTION_UPDATE

                    if not ip_address_object:
                        ip_address_object = IPAddress(
                            address=ipv4_address,
                            status=IPAddressStatusChoices.STATUS_ACTIVE,  # Set the IP address status
                            assigned_object=interface_object,
                            assigned_object_type_id=interface_object_type_id
                        )
                        ip_address_action = ObjectChangeActionChoices.ACTION_CREATE

                    else:
                        if ip_address_object.assigned_object and ip_address_object.assigned_object != interface_object:
                            self.script.log_warning(f"Address {get_link_text(ip_address_object)} for " +
                                                    f"{get_link_text(interface_object)} already assigned to " +
                                                    f"{get_link_text(ip_address_object.assigned_object)}")
                        else:
                            ip_address_object.assigned_object = interface_object
                            ip_address_object.assigned_object_type_id = interface_object_type_id
                            ip_address_object.status = IPAddressStatusChoices.STATUS_ACTIVE

                    if not ip_address_object.tenant:
                        ip_address_object.tenant = current_device.tenant
                    ip_address_object.save()
                    self.object_changelog(ip_address_action, ip_address_object)



                    if address_is_primary:
                        if current_device.primary_ip4:
                            if current_device.primary_ip4 != ip_address_object:
                                self.script.log_warning(f"Primary ipv4 {get_link_text(ip_address_object)} " +
                                                        f"for prototype {get_link_text(selected_prototype)} " +
                                                        f"does not match device {get_link_text(current_device)} and " +
                                                        f"{get_link_text(current_device.primary_ip4)}")
                        else:
                            current_device.primary_ip4 = ip_address_object
                            current_device.save()
                            self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, current_device)





            except Exception as e:
                self.script.log_failure(
                    f"Unable to create ip address {ipv4_address} in interface {get_link_text(interface_object)} " +
                    f"for prototype {get_link_text(selected_prototype)} - {e}")


        if not self.prototype_object_list:
            self.script.log_failure("No item was selected")
            return False

        message_list = []
        for selected_prototype in self.prototype_object_list:
            try:
                # check other switches in stack call validation function that returns a boolean
                # to either process or continue
                selected_prototype.refresh_from_db()
                self.clean_prototype_interfaces(selected_prototype)
                is_valid, message_list = self.validate_prototype(selected_prototype,
                                                                 message_list,
                                                                 self.log_all_errors)
                if not is_valid:
                    selected_prototype.sync_status = DevicePrototypeStatusChoices.DISCOVERED
                    selected_prototype.save()
                    self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, selected_prototype)
                    self.script.log_info(f'Prototype {get_link_text(selected_prototype)} is DISCOVERED')
                    continue

                map_interfaces = True
                new_device = selected_prototype.matching_netbox_device

                if not new_device:
                    map_interfaces = False
                    new_device = SdnDevice(
                        name=selected_prototype.sdn_hostname,
                        role=selected_prototype.role,
                        device_type=selected_prototype.device_type,
                        tenant=selected_prototype.tenant,
                        site=selected_prototype.site,
                        serial=selected_prototype.serial
                    )
                    new_device.save()
                    self.object_changelog(ObjectChangeActionChoices.ACTION_CREATE, new_device)


                    # remove module bays created by new device template
                    template_created_module_bays = ModuleBay.objects.filter(device=new_device)
                    for template_created_module_bay in template_created_module_bays:
                        template_created_module_bay.delete()

                    self.script.log_info(f'New device {get_link_text(new_device)} created with prototype ' +
                                         f'{get_link_text(selected_prototype)}')

                else:
                    if not new_device.serial:
                        new_device.serial = selected_prototype.serial
                        new_device.save()
                        self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, new_device)

                    else:
                        if new_device.serial != selected_prototype.serial:
                            log_mismatch("Serial", selected_prototype, new_device)
                    process_device_attributes(new_device, selected_prototype)
                    self.script.log_info(f'Device {get_link_text(new_device)} updated with prototype ' +
                                         f'{get_link_text(selected_prototype)}')


                selected_prototype.matching_netbox_device = new_device
                selected_prototype.sync_status = DevicePrototypeStatusChoices.IMPORTED
                selected_prototype.tags.add(selected_prototype.sdn_controller.sdn_type)
                selected_prototype.save()
                self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, selected_prototype)

                new_device.tags.add(selected_prototype.sdn_controller.sdn_type)
                if selected_prototype.device_type:
                    new_device.device_type = selected_prototype.device_type
                new_device.save()
                self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, new_device)

                process_module_bays(new_device, selected_prototype)
                process_interfaces(new_device, selected_prototype, map_interfaces)


                self.remap_interfaces(selected_prototype, new_device)

                after_modules = True
                selected_prototype.refresh_from_db()
                is_valid, message_list = self.validate_prototype(selected_prototype,
                                                                 message_list,
                                                                 self.log_all_errors,
                                                                 after_modules)
                if not is_valid:
                    selected_prototype.sync_status = DevicePrototypeStatusChoices.DISCOVERED
                    selected_prototype.save()
                    self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, selected_prototype)
                    self.script.log_info(f'Prototype {get_link_text(selected_prototype)} is DISCOVERED')
                else:
                    self.script.log_info(f'Prototype {get_link_text(selected_prototype)} is IMPORTED')

            except Exception as exc:
                self.script.log_failure(f"Unable to create prototype : {get_link_text(selected_prototype)} - {exc}")

        return not self.script.failed

    def find_missing_interface_types(self) -> None:
        """
        Iterates over all SdnControllerDevicePrototypes and updates the interface type of any
        matching interfaces that are of type 'physical', setting the type to the most common
        interface type associated with that interface name.

        This method does not return any value. It updates the interface types in the database.

        Args:
            self: The instance of the class to which this method belongs.

        Returns:
            None
        """
        all_prototypes = SdnControllerDevicePrototype.objects.all()
        for prototype in all_prototypes:
            if prototype.matching_netbox_device:
                all_matching_interfaces = Interface.objects.filter(device=prototype.matching_netbox_device)
                for matching_interface in all_matching_interfaces:
                    if matching_interface.type.lower() == "physical":
                        most_common = get_most_common_interface_type(matching_interface.name)
                        if most_common:
                            matching_interface.type = most_common
                            matching_interface.save()
                            self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, matching_interface)

                    if "port-channel" in matching_interface.name.lower() and matching_interface.type.lower() == "virtual":
                        matching_interface.type = InterfaceTypeChoices.TYPE_LAG
                        matching_interface.save()
                        self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, matching_interface)


    def split_device_list(self) -> List[Device]:
        """
        Splits the device list into separate devices based on their serial numbers and platform IDs.

        Returns:
            List[Device]: A list of split device prototypes.
        """

        def get_chassis_index(prototype_id: int) -> Dict[str, int]:
            """
            Retrieves the chassis index for a given prototype ID.

            Args:
                prototype_id (int): The ID of the device prototype.

            Returns:
                Dict[str, int]: A dictionary mapping serial numbers to chassis indices.
            """
            chassis_index = {}
            stack_list = self.api.devices.get_stack_details_for_device(prototype_id).response

            if not stack_list or not stack_list.stackSwitchInfo:
                chassis_list = self.api.devices.get_chassis_details_for_device(prototype_id).response
                for switch in chassis_list:
                    chassis_index[switch.serialNumber.strip()] = int(''.join(filter(str.isdigit, switch.name)))
            else:
                for switch in stack_list.stackSwitchInfo:
                    chassis_index[switch.serialNumber.strip()] = switch.stackMemberNumber

            return chassis_index

        def no_serial_indexes(prototype_id: int) -> List[int]:
            """
            Retrieves the serial indexes for a given prototype ID where no serial number is present.

            Args:
                prototype_id (int): The ID of the device prototype.

            Returns:
                List[int]: A list of serial indexes from 1 to the maximum of stack or chassis length.
            """
            stack_length = 0
            all_stack = self.api.devices.get_stack_details_for_device(prototype_id).response
            if all_stack.stackSwitchInfo:
                stack_length = len(all_stack.stackSwitchInfo)

            chassis_length = len(self.api.devices.get_chassis_details_for_device(prototype_id).response)

            # Find the maximum value between stack_length, chassis_length, and 1
            max_value = max(stack_length, chassis_length, 1)

            # Return the list from 1 to max_value inclusive
            return list(range(1, max_value + 1))

        splitted_device_list = []
        for prototype_device in self.device_list:
            if "nexus" in prototype_device.type.lower():
                continue

            if self.prototype_uuid_list:
                if prototype_device.id not in self.prototype_uuid_list:
                    continue

            prototype_device.hostname = prototype_device.hostname.split(".")[0]
            prototype_device.rank = 1
            prototype_device.total_serial = 1
            prototype_device.is_multiple = False
            prototype_device.stack_info = {}

            if prototype_device.serialNumber:
                serials = prototype_device.serialNumber.split(",")
                chassis_index = {serials[0].strip(): 1}
                if len(serials) > 1:
                    chassis_index = get_chassis_index(prototype_device.id)
                    prototype_device.is_multiple = True

                prototype_device.stack_info = chassis_index
                platform_ids = prototype_device.platformId.split(",")
                serial_counter = 0
                for serial in serials:
                    prototype_device_copy = deepcopy(prototype_device)

                    stack_number = chassis_index[serial.strip()]
                    if stack_number > 1:
                        prototype_device_copy.managementIpAddress = None #appply primary ipv4 to first device only
                    if len(serials) > 1:
                        prototype_device_copy.hostname = prototype_device.hostname + "-" + str(stack_number)

                    prototype_device_copy.rank = stack_number
                    prototype_device_copy.total_serial = len(serials)


                    serial = serial.strip()
                    prototype_device_copy.serialNumber = serial
                    prototype_device_copy.platformId = platform_ids[serial_counter].strip()
                    splitted_device_list.append(prototype_device_copy)
                    serial_counter += 1
            else:
                switch_indexes = no_serial_indexes(prototype_device.id)
                for switch_index in switch_indexes:
                    prototype_device_copy = deepcopy(prototype_device)
                    if len(switch_indexes) > 1:
                        prototype_device_copy.hostname = prototype_device.hostname + "-" + str(switch_index)
                        prototype_device_copy.is_multiple = True
                        prototype_device_copy.rank = switch_index
                        prototype_device_copy.total_serial = len(switch_indexes)

                    if switch_index > 1:
                        prototype_device_copy.managementIpAddress = None

                    splitted_device_list.append(prototype_device_copy)


        return splitted_device_list

    def clean_prototype_interfaces(self, sdn_prototype: SdnControllerDevicePrototype) -> NoReturn:
        """Cleans up interfaces for a given SDN prototype by removing unused ones.

        Args:
            sdn_prototype (SdnControllerDevicePrototype): The SDN prototype to process.

        Returns:
            NoReturn: This function does not return anything.
        """

        same_stack_prototypes = SdnControllerDevicePrototype.objects.filter(instance_uuid=sdn_prototype.instance_uuid)
        for same_stack_prototype in same_stack_prototypes:
            if same_stack_prototype.matching_netbox_device:
                actual_interfaces = Interface.objects.filter(device=same_stack_prototype.matching_netbox_device)
                for actual_interface in actual_interfaces:

                    if (not actual_interface.cable and
                            not actual_interface.module and
                            not is_valid_interface(actual_interface.name) and
                            not is_device_type_template(actual_interface)):
                        actual_interface.delete()



    def validate_prototype(self, sdn_prototype, message_list, with_logs, after_modules = False) -> bool:
        """Logs a validation failure message and appends it to the message list if not already present.

        Args:
            message (str): The failure message to log.
        """
        prototype_is_ok = True

        required_fields = [
            'sdn_hostname',
            'role',
            'device_type',
            'tenant',
            'site',
            'serial'
        ]

        same_stack_prototypes = SdnControllerDevicePrototype.objects.filter(instance_uuid=sdn_prototype.instance_uuid)

        def log_failure(message):
            if message not in message_list:
                message_list.append(message)

                if with_logs:
                    self.script.log_failure(message)

        for same_stack_prototype in same_stack_prototypes:

            # Validate Related and not matching
            if not same_stack_prototype.matching_netbox_device and same_stack_prototype.related_netbox_device:
                prototype_serial = same_stack_prototype.related_netbox_device.serial
                if not prototype_serial:
                    prototype_serial = "NONE"

                log_failure(
                    f"Verify if serial number {prototype_serial} should be changed for prototype serial " +
                    f"{same_stack_prototype.serial} in related device " +
                    f"{get_edit_link_text(same_stack_prototype.related_netbox_device, same_stack_prototype.serial)}. " +
                    "It could then become matching device in " +
                    f"{get_edit_link_text(same_stack_prototype, str(same_stack_prototype.related_netbox_device.id))}"
                )
                prototype_is_ok = False


            # Validate required fields
            for field in required_fields:
                if not getattr(same_stack_prototype, field, None):
                    log_failure(
                        f"Prototype {get_link_text(same_stack_prototype)} does not have required field {field}"
                    )
                    prototype_is_ok = False

            # Validate stack index
            if (
                same_stack_prototype.matching_netbox_device
                and same_stack_prototype.matching_netbox_device.netbox_stack_index
                and same_stack_prototype.matching_netbox_device.netbox_stack_index != same_stack_prototype.stack_index
            ):
                log_failure(
                    f"Prototype {get_link_text(same_stack_prototype)} sdn stack index does not match with " +
                    f"NetBox device {get_link_text(same_stack_prototype.matching_netbox_device)} stack index"
                )
                prototype_is_ok = False


            # Validate primary IP address
            if (
                same_stack_prototype.matching_netbox_device
                and same_stack_prototype.matching_netbox_device.primary_ip4
                and same_stack_prototype.primary_ip4
                and same_stack_prototype.matching_netbox_device.primary_ip4 != same_stack_prototype.primary_ip4
            ):
                log_failure(
                    f"Prototype {get_link_text(same_stack_prototype)} address "
                    f"{get_link_text(same_stack_prototype.primary_ip4)} does not match with Netbox device "
                    f"{get_link_text(same_stack_prototype.matching_netbox_device.primary_ip4)}"
                )
                prototype_is_ok = False

            if after_modules:
                # Validate present interfaces
                if same_stack_prototype.matching_netbox_device:
                    actual_interfaces = Interface.objects.filter(device=same_stack_prototype.matching_netbox_device)
                    all_prototype_interfaces = same_stack_prototype.raw_data.get("interfaces", {})
                    interface_lower_names = []
                    for prototype_interface in all_prototype_interfaces:
                        interface_lower_names.append(prototype_interface.lower())




                    for actual_interface in actual_interfaces:
                        if (actual_interface.type.lower() in ["virtual", "lag"] and
                                actual_interface.name.lower() in interface_lower_names):
                            continue

                        #spcl management interface
                        if "0/0" in actual_interface.name or ".100" in actual_interface.name:
                            continue

                        if actual_interface.name not in all_prototype_interfaces:


                            log_failure(
                                f"Device {get_link_text(same_stack_prototype.matching_netbox_device)} " +
                                f"interface {get_link_text(actual_interface)} is not found in " +
                                f"prototype {get_link_text(same_stack_prototype)}"
                            )
                            prototype_is_ok = False

                        if (not is_valid_interface(actual_interface.name) and
                                not actual_interface.module and
                                not is_device_type_template(actual_interface)):

                            log_failure(
                                f"Device {get_link_text(same_stack_prototype.matching_netbox_device)} " +
                                f"interface {get_link_text(actual_interface)} doesnt belong to a module "
                            )
                            prototype_is_ok = False

                if same_stack_prototype.matching_netbox_device:
                    actual_module_bays = ModuleBay.objects.filter(device=same_stack_prototype.matching_netbox_device)
                    all_prototype_module_bays = same_stack_prototype.raw_data.get("modules", {})
                    module_bay_lower_names = []
                    for prototype_module_bay in all_prototype_module_bays:
                        module_bay_lower_names.append(prototype_module_bay.lower())

                    for actual_module_bay in actual_module_bays:
                        if actual_module_bay.name.lower() not in module_bay_lower_names:
                            log_failure(
                                f"Module bay {get_link_text(actual_module_bay)} doesnt belong to " +
                                f"device {get_link_text(same_stack_prototype.matching_netbox_device)}"
                            )
                            prototype_is_ok = False






        return prototype_is_ok, message_list


    def extract_module_positions(self, prototype_device: SdnControllerDevicePrototype) -> List[Dict[str, Any]]:
        """Extracts module positions from a prototype device.

        Args:
            prototype_device (SdnControllerDevicePrototype): The prototype device containing module details.

        Returns:
            List[Dict[str, Any]]: A list of module details with assigned slot and switch numbers.
        """
        apimodules = self.api.devices.get_modules(prototype_device.id).response
        linecards = self.api.devices.get_linecard_details_v1(prototype_device.id).response
        supervisorcards = self.api.devices.get_supervisor_card_detail_v1(prototype_device.id).response
        allcards = linecards + supervisorcards
        allcardsdict = element_list_to_dict(allcards, "serialno")

        prototype_device.all_cards = allcardsdict

        modules = [
            apimodule
            for apimodule in apimodules
            if len(apimodule.serialNumber) > 3
        ]

        for dnacmodule in modules:
            slotnumber = None

            if dnacmodule['serialNumber'] in allcardsdict:
                switchnumber = "1"
                if allcardsdict[dnacmodule['serialNumber']]['switchno'] and \
                        allcardsdict[dnacmodule['serialNumber']]['switchno'].isdigit():
                    switchnumber = allcardsdict[dnacmodule['serialNumber']]['switchno']
                if allcardsdict[dnacmodule['serialNumber']]['slotno'] and \
                        allcardsdict[dnacmodule['serialNumber']]['slotno'].isdigit():
                    slotnumber = allcardsdict[dnacmodule['serialNumber']]['slotno']

                elif "SPA subslot " in dnacmodule["name"]:
                    match = re.search(r'SPA subslot (\d+)/([1-9]\d*)', dnacmodule["name"])
                    if match:
                        switchnumber = match.group(1)
                        slotnumber = match.group(2)
            else:
                if not prototype_device.is_multiple:
                    switchnumber = "1"
                else:
                    switchnumber = extract_chassis_number(dnacmodule['name'], True)
                slotnumber = extract_slot_or_module_number(dnacmodule['name'], True)

                if switchnumber and not slotnumber:
                    if prototype_device.total_serial == len(modules):
                        slotnumber = "1"

            dnacmodule["dnac_name"] = dnacmodule["name"]
            if slotnumber:
                dnacmodule['slotnumber'] = slotnumber
            if switchnumber:
                dnacmodule['switchnumber'] = switchnumber

            if switchnumber and slotnumber:
                dnacmodule["name"] = f"Switch {switchnumber} Module {slotnumber}"

        return modules


    def remap_interfaces(self, sdn_prototype: Any, netbox_device: Device) -> None:
        """Remaps and merges duplicate interfaces on a NetBox device based on SDN prototype interface data.

        This method compares different naming variants (canonical, abbreviated, intermediate) of interfaces
        on the NetBox device. When duplicates are found, it optionally merges modules and cables based
        on predefined logic, updates NetBox records, and logs changes.

        Args:
            sdn_prototype (Any): SDN prototype object with `raw_data["interfaces"]`.
            netbox_device (Device): The NetBox device object whose interfaces are being remapped.

        Returns:
            None
        """

        def merge_duplicate_interfaces(a_interface: Interface, b_interface: Interface, with_module: bool = False) -> bool:
            """Merges two duplicate interfaces, optionally updating module information.

            Args:
                a_interface (Interface): The interface to keep.
                b_interface (Interface): The interface to delete.
                with_module (bool): If True, transfers module info from `b_interface` to `a_interface`.

            Returns:
                bool: True if merge was successful, False otherwise.
            """
            try:
                if with_module:
                    a_interface.module = b_interface.module
                a_interface.name = prototype_interface_mapping_table[canonical_interface_name(a_interface.name)]
                self.object_changelog(ObjectChangeActionChoices.ACTION_DELETE, b_interface)
                b_interface.delete()
                self.object_changelog(ObjectChangeActionChoices.ACTION_UPDATE, a_interface)
                a_interface.save()
                return True
            except Exception as e:
                return False

        all_prototype_interfaces = sdn_prototype.raw_data.get("interfaces", {})
        prototype_interface_mapping_table = {}
        for prototype_interface in all_prototype_interfaces:
            prototype_interface_mapping_table[canonical_interface_name(prototype_interface)] = prototype_interface

        processed_interfaces = []
        all_matched_interfaces = []
        actual_interfaces = Interface.objects.filter(device=netbox_device)

        # Define the transformation functions
        transformations = [
            canonical_interface_name,
            abbreviated_interface_name,
            cisco_intermediate_interface_name
        ]


        for actual_interface in actual_interfaces:

            if actual_interface in processed_interfaces:
                continue

            for transform in transformations:
                transformed_name = transform(actual_interface.name)
                matched_iface = Interface.objects.filter(device=netbox_device, name=transformed_name).first()

                if matched_iface and matched_iface != actual_interface:
                    processed_interfaces.append(actual_interface)
                    processed_interfaces.append(matched_iface)
                    matched_pair = [actual_interface, matched_iface]
                    all_matched_interfaces.append(matched_pair)
                    break  # Stop after the first successful match

        for matching_interface in all_matched_interfaces:
            if matching_interface[0].cable and not matching_interface[0].module and matching_interface[1].module and not matching_interface[1].cable:
                merge_duplicate_interfaces(matching_interface[0], matching_interface[1], True)

            if matching_interface[0].module and not matching_interface[0].cable and matching_interface[1].cable and not matching_interface[1].module:
                merge_duplicate_interfaces(matching_interface[1], matching_interface[0], True)

            if matching_interface[0].name in all_prototype_interfaces and matching_interface[1].name not in all_prototype_interfaces:
                merge_duplicate_interfaces(matching_interface[1], matching_interface[0])

            if matching_interface[1].name in all_prototype_interfaces and matching_interface[0].name not in all_prototype_interfaces:
                merge_duplicate_interfaces(matching_interface[0], matching_interface[1])


