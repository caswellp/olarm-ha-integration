"""Module to interact with the Olarm API."""
import aiohttp
import time
from .const import LOGGER
from .exceptions import (
    APIClientConnectorError,
    ListIndexError,
    DictionaryKeyError,
    APINotFoundError,
    APIContentTypeError
)
from aiohttp.client_exceptions import ContentTypeError
from datetime import datetime, timedelta
import asyncio

class OlarmApi:
    """
    This class provides an interface to the Olarm API. It handles authentication, and provides methods for making requests to arm, disarm, sleep, or stay a security zone.
    params:
        \tdevice_id (str): UUID for the Olarm device.
        \tapi_key (str): The key can be passed in an authorization header to authenticate to Olarm.
    """

    def __init__(self, device_id, api_key, device_name="") -> None:
        """
        Initatiates a connection to the Olarm API.
        params:
        \tdevice_id (str): UUID for the Olarm device.
        \tapi_key (str): The key can be passed in an authorization header to authenticate to Olarm.
        """
        self.device_id = device_id
        self.api_key = api_key
        self.data = []
        self.bypass_data = []
        self.panel_data = []
        self.devices = []
        self.device_name = device_name
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Home Assistant"
        }

    async def get_device_json(self) -> dict:
        """
        This method gets and returns the data from the Olarm API for a spesific device:

        return:\tdict\tThe info associated with a device
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://apiv4.olarm.co/api/v4/devices/{self.device_id}",
                    headers=self.headers,
                ) as response:
                    try:
                        resp = await response.json()
                        resp['error'] = None
                        return resp
        
                    except (APIContentTypeError, ContentTypeError) :
                        text = await response.text()
                        if "Forbidden" in text:
                            LOGGER.error(
                                "Could not get JSON data due to incorrect API key. Please update the api key"
                            )
                            return {'error': text}
                        
                        elif "Too Many Requests" in text:
                            LOGGER.error("Your refresh interval is set too frequent for the Olarm API to handle")
                            return {'error': text}
                        
                        else:
                            LOGGER.error(
                                "The api returned text instead of JSON. The text is:\n%s",
                                text,
                            )
                            return {'error': text}

        except APIClientConnectorError as ex:
            LOGGER.error("Olarm API Devices error\n%s", ex)
            return {'error': ex}

    async def get_changed_by_json(self, area) -> dict:
        """
        DOCSTRING:\tGets the actions for a spesific device from Olarm and returns the user that last chenged the state of an Area.
        return (str):\tThe user that triggered tha last state change of an area.
        """
        return_data = {"userFullname": "No User", "actionCreated": 0, "actionCmd": None}
        try:
            await asyncio.sleep(5)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://apiv4.olarm.co/api/v4/devices/{self.device_id}/actions",
                    headers=self.headers,
                ) as response:
                    if response.status == 404:
                        LOGGER.warning("Olarm has no saved history for device (%s)", self.device_name)
                        return return_data

                    try:
                        changes = await response.json()
                        for change in changes:
                            if (change["actionCmd"] not in ["zone-bypass", "pgm-open", "pgm-close", "pgm-pulse", "ukey-activate",] and int(change["actionNum"]) == int(area) and return_data["actionCreated"] < int(change["actionCreated"])):
                                return_data = change
                    
                    except (APIContentTypeError, ContentTypeError):
                        text = response.text
                        LOGGER.error("The Olarm API returned text instead of json. The text is:\n%s", text)
                    
                    try:
                        last_changed = datetime.strptime(
                            time.ctime(int(return_data['actionCreated'])),
                            "%a %b  %d %X %Y",
                        )
                        return_data['actionCreated'] = last_changed.strftime("%a %d %b %Y %X")

                    except TypeError:
                        last_changed = None
                    
                    await asyncio.sleep(5)
                    return return_data

        except APIClientConnectorError as ex:
            LOGGER.error("Olarm API Changed By error\n%s", ex)
            return return_data

        except APINotFoundError as ex:
            LOGGER.error("Olarm API Changed By error\n%s", ex)
            return return_data

    async def check_credentials(self) -> dict:
        """
        DOCSTRING:\tChecks if the details the user provided is valid.

        return (dict):\tThe device json from Olarm.
        """
        try:
            resp = await self.get_device_json()
            if resp['error'] is None:
                resp['auth_success'] = True
                return resp

            else:
                resp['auth_success'] = False
                return resp
        
        except Exception as ex:
            return {'auth_success': False, 'error': ex}

    async def get_sensor_states(self, devices_json) -> list:
        """
        DOCSTRING:\tGets the state for each zone for each area of your alarm panel.

        params:\n\t device_json (dict): The device json from get_devices_json.

        return:\tList:\t A sensor for each zone in each area of the alarm panel. As well as the power states.
        """
        olarm_state = devices_json["deviceState"]
        olarm_zones = devices_json["deviceProfile"]

        self.data = []

        try:
            for zone in range(0, olarm_zones["zonesLimit"]):
                if str(olarm_state["zones"][zone]).lower() == "a":
                    state = "on"

                else:
                    state = "off"

                try:
                    last_changed = datetime.strptime(
                        time.ctime(int(olarm_state["zonesStamp"][zone]) / 1000),
                        "%a %b  %d %X %Y",
                    )
                    last_changed = last_changed.strftime("%a %d %b %Y %X")

                except TypeError:
                    last_changed = None

                if zone < len(olarm_zones["zonesLabels"]) and (
                    olarm_zones["zonesLabels"][zone]
                    or olarm_zones["zonesLabels"][zone] == ""
                ):
                    zone_name = olarm_zones["zonesLabels"][zone]
                    zone_type = olarm_zones["zonesTypes"][zone]

                else:
                    zone_name = f"Zone {zone + 1}"
                    zone_type = 0

                self.data.append(
                    {
                        "name": zone_name,
                        "state": state,
                        "last_changed": last_changed,
                        "type": zone_type,
                        "zone_number": zone,
                    }
                )

            zone = zone + 1
            for key, value in olarm_state["power"].items():
                sensortype = 1000
                if int(value) == 1:
                    state = "on"

                else:
                    state = "off"

                if key == "Batt":
                    key = "Battery"
                    sensortype = 1001

                self.data.append(
                    {
                        "name": f"Powered by {key}",
                        "state": state,
                        "last_changed": None,
                        "type": sensortype,
                        "zone_number": zone,
                    }
                )
                zone = zone + 1

            return self.data

        except (DictionaryKeyError, KeyError, IndexError, ListIndexError) as ex:
            LOGGER.error("Olarm sensors error for  device (%s):\n%s", self.device_name, ex)
            return self.data

    async def get_sensor_bypass_states(self, devices_json) -> list:
        """
        DOCSTRING:\tGets the bypass state for each zone for each area of your alarm panel.

        params:\n\t device_json (dict): The device json from get_devices_json.

        return:\tList:\t A sensor for each zone's bypass state in each area of the alarm panel.
        """
        olarm_state = devices_json["deviceState"]
        olarm_zones = devices_json["deviceProfile"]

        self.bypass_data = []
        try:
            for zone in range(0, olarm_zones["zonesLimit"]):
                if str(olarm_state["zones"][zone]).lower() == "b":
                    state = "on"

                else:
                    state = "off"

                last_changed = datetime.strptime(
                    time.ctime(int(olarm_state["zonesStamp"][zone]) / 1000),
                    "%a %b  %d %X %Y",
                ) + timedelta(hours=2)

                last_changed = last_changed.strftime("%a %d %b %Y %X")

                if zone < len(olarm_zones["zonesLabels"]) and (
                    olarm_zones["zonesLabels"][zone]
                    or olarm_zones["zonesLabels"][zone] == ""
                ):
                    zone_name = olarm_zones["zonesLabels"][zone]

                else:
                    zone_name = f"Zone {zone + 1}"

                self.bypass_data.append(
                    {
                        "name": zone_name,
                        "state": state,
                        "last_changed": last_changed,
                        "zone_number": zone,
                    }
                )

            return self.bypass_data

        except (DictionaryKeyError, KeyError, IndexError, ListIndexError) as ex:
            LOGGER.error("Olarm Bypass sensors error for device (%s):\n%s", self.device_name, ex)
            return self.bypass_data

    async def get_panel_states(self, devices_json) -> list:
        """
        DOCSTRING:\tGets the state of each zone for the alarm panel from Olarm.
        params:\n\t device_json (dict): The device json from get_devices_json.

        return: (list):\tThe state for each are of the alarm panel.
        """
        olarm_state = devices_json["deviceState"]
        zones = devices_json["deviceProfile"]
        olarm_zones = zones["areasLabels"]

        self.panel_data = []

        area_count = zones["areasLimit"]
        for area_num in range(area_count):
            try:
                if olarm_zones[area_num] == "":
                    LOGGER.warning(
                        "This device's area names have not been set up in Olarm, generating automatically"
                    )
                    olarm_zones[area_num] = f"Area {area_num + 1}"

                if len(olarm_state["areas"]) > area_num:
                    self.panel_data.append(
                        {
                            "name": f"{olarm_zones[area_num]}",
                            "state": olarm_state["areas"][area_num],
                            "area_number": area_num + 1,
                        }
                    )

            except (DictionaryKeyError, KeyError) as ex:
                LOGGER.error("Olarm API Panel error for device (%s):\n%s", self.device_name, ex)

        return self.panel_data

    async def get_pgm_zones(self, devices_json) -> list:
        """
        Gets all the pgm's for the alarm panel.
        params:\n\t device_json (dict): The device json from get_devices_json.

        return: (list):\tThe pgm's for the alarm panel.
        """
        try:
            pgm_state = devices_json["deviceState"]["pgm"]
            pgm_labels = devices_json["deviceProfile"]["pgmLabels"]
            pgm_limit = devices_json["deviceProfile"]["pgmLimit"]
            pgm_setup = devices_json["deviceProfile"]["pgmControl"]

        except (DictionaryKeyError, KeyError):
            # Error with PGM setup from Olarm app. Skipping PGM's
            LOGGER.error(
                "Error geting pgm setup data for Olarm device (%s)", self.device_id
            )
            return []

        pgms = []
        try:
            for i in range(0, pgm_limit):
                state = str(pgm_state[i]).lower() == "a"
                name = pgm_labels[i]
                if pgm_setup[i] == "":
                    continue

                try:
                    enabled = pgm_setup[i][0] == "1"

                except ListIndexError:
                    continue

                try:
                    pulse = pgm_setup[i][2] == "1"

                except ListIndexError:
                    continue

                number = i + 1

                if name == "":
                    LOGGER.debug(
                        "PGM name not set. Generating automatically. PGM %s", number
                    )
                    name = f"PGM {number}"

                pgms.append(
                    {
                        "name": name,
                        "enabled": enabled,
                        "pulse": pulse,
                        "state": state,
                        "pgm_number": number,
                    }
                )
            return pgms

        except (DictionaryKeyError, KeyError, IndexError, ListIndexError) as ex:
            LOGGER.error("Olarm PGM Error for device (%s):\n%s", self.device_name, ex)
            return pgms

    async def get_ukey_zones(self, devices_json) -> list:
        """
        Gets all the Utility keys for the alarm panel.
        params:\n\t device_json (dict): The device json from get_devices_json.

        return: (list):\tThe utility keys for the alarm panel.
        """
        ukey_labels = devices_json["deviceProfile"]["ukeysLabels"]
        ukey_limit = devices_json["deviceProfile"]["ukeysLimit"]
        ukey_state = devices_json["deviceProfile"]["ukeysControl"]
        ukeys = []
        try:
            for i in range(0, ukey_limit):
                try:
                    state = int(ukey_state[i]) == 1
                    name = ukey_labels[i]
                    number = i + 1

                    if name == "":
                        LOGGER.debug(
                            "Ukey name not set. Generating automatically. Ukey %s",
                            number,
                        )
                        name = f"Ukey {number}"

                    ukeys.append({"name": name, "state": state, "ukey_number": number})

                except (DictionaryKeyError, KeyError) as ex:
                    LOGGER.error("Olarm Ukey Error for device (%s):\n%s", self.device_name, ex)
                    return []

            return ukeys

        except (DictionaryKeyError, KeyError, IndexError, ListIndexError) as ex:
            LOGGER.error("Olarm Ukey error for device (%s):\n%s", self.device_name, ex)

    async def get_alarm_trigger(self, devices_json) -> list:
        """
        Returns the data for the zones that triggered an alarm for the area.
        """
        return devices_json["deviceState"]["areasDetail"]

    async def send_action(self, post_data) -> bool:
        """
        DOCSTRING:\tSends an action to the Olarm API to perform an action on the device.
        params:\n\tpost_data (dict): The area to perform the action to. As well as the action.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url=f"https://apiv4.olarm.co/api/v4/devices/{self.device_id}/actions",
                    data=post_data,
                    headers=self.headers,
                ) as response:
                    try:
                        resp = await response.json()
                        return str(resp["actionStatus"]).lower() == "ok"
                    
                    except (APIContentTypeError, ContentTypeError):
                        text = await response.text()
                        LOGGER.error("Error Bypassing zone: %s on device (%s).\n\n%s", post_data['actionNum'], self.device_name, text)
            
        except APIClientConnectorError as ex:
            LOGGER.error(
                "Olarm API update zone error on device (%s):\nCould not set action:\t %s due to error:\n%s",
                self.device_name,
                post_data,
                ex,
            )
            return False

    async def update_pgm(self, pgm_data) -> bool:
        """
        DOCSTRING:\tSends an action to the Olarm API to perform a pgm action on the device.
        params:\n\tpost_data (dict): The pgm to perform the action to. As well as the action.
        """
        try:
            return await self.send_action(pgm_data)

        except APIClientConnectorError as ex:
            LOGGER.error(
                "Olarm API update pgm error on device (%s):\nCould not set action:\t %s due to error:\n%s",
                self.device_name,
                pgm_data,
                ex,
            )
            return False

    async def update_ukey(self, ukey_data) -> bool:
        """
        DOCSTRING:\tSends an action to the Olarm API to perform a pgm action on the device.
        params:\n\tukey_data (dict): The ukey to perform the action to. As well as the action.
        """
        try:
            return await self.send_action(ukey_data)

        except APIClientConnectorError as ex:
            LOGGER.error(
                "Olarm API update ukey error on device (%s):\nCould not set action:\t %s due to error:\n%s",
                self.device_name,
                ukey_data,
                ex,
            )
            return False

    async def arm_area(self, area=None) -> bool:
        """
        Sends the request to send_action to arm an area.
        params:\n\tarea (int): The number of the area to apply the zone to.
        """
        post_data = {"actionCmd": "area-arm", "actionNum": area}
        return await self.send_action(post_data)

    async def sleep_area(self, area=None) -> bool:
        """
        Sends the request to send_action to arm an area.
        params:\n\tarea (int): The number of the area to apply the zone to.
        """
        post_data = {"actionCmd": "area-sleep", "actionNum": area}
        return await self.send_action(post_data)

    async def stay_area(self, area=None) -> bool:
        """
        Sends the request to send_action to arm an area.
        params:\n\tarea (int): The number of the area to apply the zone to.
        """
        post_data = {"actionCmd": "area-stay", "actionNum": area}
        return await self.send_action(post_data)

    async def disarm_area(self, area=None) -> bool:
        """
        Sends the request to send_action to arm an area.
        params:\n\tarea (int): The number of the area to apply the zone to.
        """
        post_data = {"actionCmd": "area-disarm", "actionNum": area}
        return await self.send_action(post_data)

    async def bypass_zone(self, zone) -> bool:
        """
        Sends the request to send_action to bypass a zone.
        params:\n\tzone (dict): The number of the zone to apply the zone to.
        """
        post_data = {
            "actionCmd": "zone-bypass",
            "actionNum": zone.data["zone_num"],
        }
        return await self.send_action(post_data)

    async def get_all_devices(self) -> list:
        """
        This method gets and returns the devices from the Olarm API:

        return:\tlist\tThe devices assosiated with the api key.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://apiv4.olarm.co/api/v4/devices",
                    headers=self.headers,
                ) as response:
                    try:
                        olarm_resp = await response.json()
                        self.devices = olarm_resp["data"]
                        return self.devices

                    except (APIContentTypeError, ContentTypeError):
                        text = await response.text()
                        if "Forbidden" in text:
                            LOGGER.error(
                                "Could not get JSON data due to incorrect API key. Please update the api key"
                            )
                            return []
                        
                        elif "Too Many Requests" in text:
                            LOGGER.error("Your api key has been blocked due to too many frequent updates. Please regenerate the api key")
                            return []
                        
                        else:
                            LOGGER.error(
                                "The api returned text instead of JSON. The text is:\n%s",
                                text,
                            )
                            return []

        except APIClientConnectorError as ex:
            LOGGER.error("Olarm API Devices error\n%s", ex)
            return []


class OlarmSetupApi:
    """
    This class provides an interface to the Olarm API. It handles authentication, and provides methods for making requests to arm, disarm, sleep, or stay a security zone.
    params:
        \tdevice_id (str): UUID for the Olarm device.
        \tapi_key (str): The key can be passed in an authorization header to authenticate to Olarm.
    """

    def __init__(self, api_key) -> None:
        """
        Initatiates a connection to the Olarm API.
        params:
        \tapi_key (str): The key can be passed in an authorization header to authenticate to Olarm.
        """
        self.data = []
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def get_olarm_devices(self) -> list:
        """
        This method gets and returns the devices from the Olarm API:

        return:\tlist\tThe devices assosiated with the api key.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://apiv4.olarm.co/api/v4/devices",
                    headers=self.headers,
                ) as response:
                    try:
                        olarm_resp = await response.json()
                        self.data = olarm_resp["data"]
                        return self.data

                    except (ContentTypeError, APIContentTypeError):
                        text = await response.text()
                        if "Forbidden" in text:
                            LOGGER.error(
                                "Could not get JSON data due to incorrect API key. Please update the api key"
                            )
                            return None
                        
                        elif "Too Many Requests" in text:
                            LOGGER.error("Your api key has been blocked due to too many frequent updates. Please regenerate the api key")
                            return None
                        
                        else:
                            LOGGER.error(
                                "The setup api returned text instead of JSON. The text is:\n%s",
                                text,
                            )
                            return None

        except APIClientConnectorError as ex:
            LOGGER.error("Olarm SetupAPI Devices error\n%s", ex)
            return []
