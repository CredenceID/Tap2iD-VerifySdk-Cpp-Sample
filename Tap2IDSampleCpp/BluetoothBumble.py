import asyncio
import argparse
import logging
import threading
import os
import sys
import time

APP_FOLDER_NAME = "Tap2iD"

# Set working directory to script directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Define application folder in "Documents"
documents_path = os.path.join(os.path.expanduser("~"), "Documents")
app_folder_path = os.path.join(documents_path, APP_FOLDER_NAME)

# Ensure the application folder exists
os.makedirs(app_folder_path, exist_ok=True)
log_file_path = os.path.join(app_folder_path, "bluetooth_bumble.log")

# Configure the root logger early
logging.basicConfig(
    level=os.environ.get('BUMBLE_LOGLEVEL', 'DEBUG').upper(),
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    filename=log_file_path,
    filemode='w'
)
logging.getLogger("bumble").setLevel(logging.ERROR)
# Create a console handler to see log output in real time
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
console_handler.setFormatter(formatter)
logging.getLogger().addHandler(console_handler)

# Now get your module logger (this ensures it uses the root configuration)
logger = logging.getLogger(__name__)
logger.debug("Current working directory: %s", os.getcwd())

from bumble.core import UUID, AdvertisingData
from bumble.device import Device, Connection, Peer
from bumble.gatt import (
    Service,
    Characteristic,
    CharacteristicValue,
    Descriptor,
    GATT_CHARACTERISTIC_USER_DESCRIPTION_DESCRIPTOR,
    GATT_MANUFACTURER_NAME_STRING_CHARACTERISTIC,
    GATT_DEVICE_INFORMATION_SERVICE,
)
from bumble.transport import open_transport_or_link
from bumble.utils import AsyncRunner
from bumble.hci import Address
from bumble.gatt import GATT_CLIENT_CHARACTERISTIC_CONFIGURATION_DESCRIPTOR
from bumble.gatt_client import ClientCharacteristicConfigurationBits
import struct

# Define the constant for state transmission.
STATE_START_TRANSMISSION = 0x01

# Global variable to store the server-to-client characteristic for later notifications.
global_server2client_characteristic = None

# Global variable to hold the callback.
_message_received_callback = None
_message_start_received_callback = None
_connection_init_started_callback = None

# Global variable to store the event loop.
global_event_loop = None
loop_thread = None
global_hci_transport = None

# Global variable to accumulate received data.
global_received_data = bytearray()
global_state_characteristic = None 

# Will hold the Peer object once connected
_global_peer: Peer = None
_global_device = None

# Will hold the two characteristics once we discover them for client
_global_char_client2server = None
_global_char_server2client = None

# A hook into which your .NET side can register a callback(data: bytes)
_message_notify_callback = None

def start_event_loop():
    global global_event_loop
    # Create a new event loop.
    global_event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(global_event_loop)
    logger.info("Starting persistent event loop")
    global_event_loop.run_forever()
    logger.info("Persistent event loop has stopped")

def start_persistent_event_loop():
    global loop_thread
    # Start the loop in a dedicated thread if it isn't already running.
    if loop_thread is None or not loop_thread.is_alive():
        loop_thread = threading.Thread(target=start_event_loop, daemon=True)
        loop_thread.start()
        logger.info("Persistent event loop thread started")
         # Wait until global_event_loop is set (with a timeout)
        timeout = 5.0
        start_time = time.time()
        while global_event_loop is None and (time.time() - start_time) < timeout:
            time.sleep(0.05)
        if global_event_loop is None:
            logger.error("Failed to initialize persistent event loop within timeout.")
        else:
            logger.info("Persistent event loop is ready.")

# Kick off our background loop immediately when the module loads
start_persistent_event_loop()

def disconnect_event_loop():
    global global_event_loop, loop_thread
    if global_event_loop is not None:
        logger.info("Stopping persistent event loop")
        # Schedule the loop to stop.
        global_event_loop.call_soon_threadsafe(global_event_loop.stop)
        # Optionally wait for the thread to finish.
        loop_thread.join(timeout=5)
        logger.info("Persistent event loop thread stopped")

# ------------------------------------------------------------------------------
# Listener for connection events
# ------------------------------------------------------------------------------
class MyListener(Device.Listener, Connection.Listener):
    def __init__(self, device):
        self.device = device

    def on_connection(self, connection):
        logger.info(f'=== Connected to {connection}')
        connection.listener = self
        if _connection_init_started_callback:
            try:
                _connection_init_started_callback()
            except Exception as e:
                logger.error("Error invoking ConnectionInitStarted callback: %s", e)

    def on_disconnection(self, reason):
        logger.info(f'### Disconnected, reason={reason}')

    def on_characteristic_subscription(self, connection, characteristic, notify_enabled, indicate_enabled):
        logger.info(
            f'$$$ Characteristic subscription for uuid {characteristic.uuid} '
            f'from {connection}: '
            f'notify {"enabled" if notify_enabled else "disabled"}, '
            f'indicate {"enabled" if indicate_enabled else "disabled"}'
        )

# ------------------------------------------------------------------------------
# Characteristic read/write handlers
# ------------------------------------------------------------------------------
def register_message_received_callback(callback):
    global _message_received_callback
    _message_received_callback = callback
    return "Callback registered"

def register_message_start_received_callback(callback):
    global _message_start_received_callback
    _message_start_received_callback = callback
    return "MessageStartReceived callback registered."

def register_connection_init_started_callback(callback):
    global _connection_init_started_callback
    _connection_init_started_callback = callback
    return "ConnectionInitStarted callback registered."


# Write callback for client2server characteristic.
def client2server_write_callback(conn, value):
    global global_received_data
    logger.debug("Client2Server write received: %s", value.hex())

    # Ensure the received frame is not empty.
    if not value or len(value) < 1:
        logger.error("Received an empty frame!")
        return

    # Read the marker from the first byte.
    marker = value[0]

    if marker == 0x01:
        if len(global_received_data) == 0:
            if _message_start_received_callback:
                try:
                    _message_start_received_callback()
                    logger.info("MessageStartReceived callback fired.")
                except Exception as e:
                    logger.error("Error calling MessageStartReceived callback: %s", e)
            else:
                logger.warning("No MessageStartReceived callback is registered.")
        # Intermediate frame: append data excluding the marker.
        global_received_data.extend(value[1:])       
    elif marker == 0x00:
        # Final frame: append data excluding the marker.
        global_received_data.extend(value[1:])
        
        # Now call the registered callback with the complete data.
        if _message_received_callback:
            try:
                _message_received_callback(bytes(global_received_data))
            except Exception as e:
                logger.error("Error calling message received callback: %s", e)
        else:
            logger.warning("No message received callback is registered.")
        
        # Clear the accumulated data for the next message.
        global_received_data.clear()
    else:
        logger.error("Unknown frame marker: 0x%02X", marker)

# ------------------------------------------------------------------------------
# Callback for state characteristic writes.
# ------------------------------------------------------------------------------
def state_write_callback(conn, value, state_future: asyncio.Future):
    logger.debug(f"State write received: {value}")
    if value and value[0] == STATE_START_TRANSMISSION:
        if not state_future.done():
            state_future.set_result(True)
            logger.info("State start transmission received; signaling setup completion.")

# ------------------------------------------------------------------------------
# Create custom characteristics and service
# ------------------------------------------------------------------------------
def create_custom_service(custom_service_uuid: UUID, state_write_event, ident_value: bytes) -> Service:
    global global_server2client_characteristic, global_state_characteristic # Explicitly declare global here
    
    # Define characteristic UUIDs for the custom service
    state_uuid         = UUID("00000005-a123-48ce-896b-4c76973373e6")
    client2server_uuid = UUID("00000006-a123-48ce-896b-4c76973373e6")
    server2client_uuid = UUID("00000007-a123-48ce-896b-4c76973373e6")
    ident_uuid         = UUID("00000008-a123-48ce-896b-4c76973373e6")
    l2cap_uuid         = UUID("0000000b-a123-48ce-896b-4c76973373e6")
    
    # Create characteristics
    global_state_characteristic = Characteristic(
        uuid=state_uuid,
        properties=Characteristic.Properties.NOTIFY | Characteristic.Properties.WRITE_WITHOUT_RESPONSE,
        permissions=Characteristic.READABLE | Characteristic.WRITEABLE,
        value=CharacteristicValue(
            write=state_write_event
        )
    )

    client2server_characteristic = Characteristic(
        uuid=client2server_uuid,
        properties=Characteristic.Properties.WRITE | Characteristic.Properties.WRITE_WITHOUT_RESPONSE,
        permissions=Characteristic.READABLE | Characteristic.WRITEABLE,
        value=CharacteristicValue(
            write=client2server_write_callback
        )
    )

    # This characteristic is used for sending notifications from the server to the client.
    global_server2client_characteristic = Characteristic(
        uuid=server2client_uuid,
        properties=Characteristic.Properties.READ | Characteristic.Properties.NOTIFY,
        permissions=Characteristic.READABLE     
    )

    def read_ident_callback(conn, offset=0):
        try:
            # Convert the .NET byte array to a Python bytes object.
            # Using list(ident_value) should enumerate the .NET array.
            py_ident_value = bytes(list(ident_value))
            logger.info("Ident value (hex): %s", py_ident_value.hex())
            return py_ident_value
        except Exception as e:
            logger.error("Error converting ident_value to hex: %s", e)
            # Fallback: return the original .NET array (though it may not behave as expected)
            return ident_value        

    ident_characteristic = Characteristic(
        uuid=ident_uuid,
        properties=Characteristic.Properties.READ,
        permissions=Characteristic.READABLE | Characteristic.WRITEABLE,
        value=CharacteristicValue(
            read=read_ident_callback
        )
    )
    
    # Create and return the service with all characteristics.
    return Service(
        uuid=custom_service_uuid,
        characteristics=[
            global_state_characteristic,
            client2server_characteristic,
            global_server2client_characteristic,
            ident_characteristic
        ]
    )

# ------------------------------------------------------------------------------
# Main asynchronous setup function
#
# This function sets up the BLE server, waits for the state characteristic to receive
# a specific value (or times out), and then returns while leaving the server running.
# ------------------------------------------------------------------------------
async def setup_bluetooth_server(config_file: str, transport: str, service_uuid_str: str, ident_value: bytes, timeout: float = 30.0):
    logger.debug("Starting Bluetooth server setup with uuid %s.", service_uuid_str)
    custom_service_uuid = UUID(service_uuid_str)

    # Create a Future to signal when the state characteristic receives the "start transmission" value.
    state_future = asyncio.get_event_loop().create_future()
    
     # Create a lambda that captures the state_future.
    state_write_lambda = lambda conn, value: state_write_callback(conn, value, state_future)

    custom_service = create_custom_service(custom_service_uuid, state_write_lambda, ident_value)
    logger.info('<<< Connecting to HCI...')
   
    hci_transport = await open_transport_or_link(transport)

    global global_hci_transport
    global_hci_transport = hci_transport  # Save transport globally

    # async with await open_transport_or_link(transport) as hci_transport:
    logger.info('<<< Connected to HCI transport')

    # Create the Bluetooth device with HCI transport
    device = Device.from_config_file_with_hci(config_file, hci_transport.source, hci_transport.sink)

    # Attach a listener for connection events
    device.listener = MyListener(device)

    # Add the custom service to the device
    device.add_services([custom_service])

    # Debug: Print all GATT attributes for verification
    for attribute in device.gatt_server.attributes:
        logger.debug("GATT attribute: %s", attribute)

    await device.power_on()

    # Set the advertising data to include the custom service UUID (or any desired data)
    device.advertising_data = bytes(
        AdvertisingData(
            [
                (
                    AdvertisingData.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS,
                    bytes(custom_service_uuid)
                )
            ]
        )
    )

    logger.info(f"Advertising custom service UUID: {custom_service_uuid}")
    await device.start_advertising(auto_restart=True)

    # Spawn a background task to keep the server running.
    async def keep_server_running():
        try:
            await hci_transport.source.wait_for_termination()
        except Exception as e:
            logger.error("Error waiting for termination: %s", e)
    asyncio.create_task(keep_server_running())

    # Wait for a connection or timeout.
    try:
        await asyncio.wait_for(state_future, timeout=timeout)
        logger.info("State event received; returning from setup.")
    except asyncio.TimeoutError as e:
        logger.warning("Timeout waiting for connection after %s seconds", timeout)
        raise e

    # Return the device and connection.
    return device, state_future.done()

def get_server2client_characteristic():
    return global_server2client_characteristic
   
# ------------------------------------------------------------------------------
# Asynchronous function to send data from the server to the client.
# ------------------------------------------------------------------------------
async def send_data_to_client(device, data: bytes):
    logger.info("send data to cvlient")
    global global_server2client_characteristic
    if global_server2client_characteristic is None:
        logger.error("Server-to-client characteristic is not available.")
        return

    logger.info("Server-to-client characteristic found: %s", global_server2client_characteristic.uuid)

    # Ensure that data is a Python bytes object.
    if not isinstance(data, bytes):
        try:
            data = bytes(list(data))
        except Exception as e:
            logger.error("Could not convert data to Python bytes: %s", e)
            return

    logger.info("Data send to client: %s", data.hex())
    try:
        # Set characteristic value before notifying
        global_server2client_characteristic.value = data
        result = await device.gatt_server.notify_subscribers(global_server2client_characteristic)
            
        if not result:
            logger.warning("No subscribers received the notification!")
        else:
            logger.info("Notification sent successfully to %d subscribers", len(result))
            for res in result:
                logger.info("Client received status: %s", getattr(res, "Status", "N/A"))

    except Exception as e:
        logger.error("Error during notification: %s", e)

# ------------------------------------------------------------------------------
# Disconnect method that closes the HCI transport and then stops the event loop.
# ------------------------------------------------------------------------------
def disconnect():
    global global_hci_transport, global_event_loop, global_state_characteristic, global_server2client_characteristic
    if global_hci_transport is not None:
        logger.info("Closing HCI transport...")
        try:
            # Schedule the close coroutine on the persistent loop and wait for it to complete.
            future = asyncio.run_coroutine_threadsafe(global_hci_transport.close(), global_event_loop)
            # Wait up to 5 seconds for the close to complete.
            future.result(timeout=5)
            logger.info("HCI transport closed successfully.")
        except Exception as e:
            logger.error("Error closing HCI transport: %s", e)
        global_hci_transport = None
    else:
        logger.warning("HCI transport is not initialized.")
    # Clear the global characteristic references so that a new connection will reinitialize them.
    global_state_characteristic = None
    global_server2client_characteristic = None

async def send_session_termination(device):
    logger.info("send_session_termination")
    termination_message = bytes([0x02])
    
    if global_state_characteristic is None:
        logger.error("State characteristic is not available for termination message.")
        return
    
    try:
        logger.info("Update the characteristic's value and notify")
        # Update the characteristic's value and notify.
        global_state_characteristic.value = termination_message      
        result = await device.gatt_server.notify_subscribers(global_state_characteristic)
        logger.info("Session termination notification sent successfully. Subscribers: %d", len(result) if result else 0)
    except Exception as e:
        logger.error("Error sending session termination: %s", e)

# -----------------------------------------------------------------------------
#  Gatt Client
# ----------------------------------------------------------------------------
STATE_UUID          = UUID("00000001-a123-48ce-896b-4c76973373e6")
CLIENT2SERVER_UUID  = UUID("00000002-a123-48ce-896b-4c76973373e6")
SERVER2CLIENT_UUID  = UUID("00000003-a123-48ce-896b-4c76973373e6")
CCCD_UUID = UUID("00002902-0000-1000-8000-00805F9B34FB")

"""
    Register a Python callable (from .NET) that will be
    invoked with each notification's raw bytes.
"""
def register_server2client_callback(py_callable):   
    global _message_notify_callback
    _message_notify_callback = py_callable


class ClientListener(Device.Listener):
    def __init__(self, device, target_service_uuid):
        self.device = device
        self.target_service_uuid = target_service_uuid
        self.service_found_future = global_event_loop.create_future() #asyncio.get_event_loop().create_future()
        self.connecting = False
        self.current_connection = None
        logger.info(f'Target service UUID: {self.target_service_uuid}')  


    def on_advertisement(self, advertisement):
        logger.info(f'Received advertisement from {advertisement.address}')     
        addr = advertisement.address

        # Already connecting? Ignore.
        if self.connecting:
            logger.info(f'already connecting') 
            return

        # Grab the complete or shortened local name
        name = (
            advertisement.data.get(AdvertisingData.COMPLETE_LOCAL_NAME)
            or advertisement.data.get(AdvertisingData.SHORTENED_LOCAL_NAME)
        )

        # grab both complete & incomplete 128-bit lists, defaulting to [] if missing
        complete = advertisement.data.get(
            AdvertisingData.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS
        ) or []
        incomplete = advertisement.data.get(
            AdvertisingData.INCOMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS
        ) or []

        # now safe to concatenate
        uuids = complete + incomplete

        # Check if we should connect:
        connect_based_on_name = name and len(name) == 4
        connect_based_on_uuid = self.target_service_uuid in uuids

        if connect_based_on_name or connect_based_on_uuid:
            reason = "name" if connect_based_on_name else "UUID"
            logger.info(f"Match found by {reason} ('{name}' / {self.target_service_uuid}), connecting to {addr}…")

            self.connecting = True
            # stop scanning and connect
            asyncio.create_task(self.device.stop_scanning())
            asyncio.create_task(self.device.connect(addr))
            #asyncio.create_task(self._stop_and_connect(addr))

    @AsyncRunner.run_in_task()
    async def on_connection(self, connection):
        global _global_peer, _global_char_client2server, _global_char_server2client
        logger.info(f'=== Connected to {connection}')
        self.current_connection = connection
        if _connection_init_started_callback:
            try:
                _connection_init_started_callback()
            except Exception as e:
                logger.error("Error invoking ConnectionInitStarted callback: %s", e)  
        _global_peer = Peer(connection)
        # Step 1: Negotiate MTU
        try:
            mtu = await _global_peer.request_mtu(515)
            logger.info(f'Negotiated MTU: {mtu}')
        except Exception as e:
            logger.warning(f'Failed to negotiate MTU: {e}')

        # Step 2: Discover services and characteristics
        await _global_peer.discover_services()
        logger.info('Services discovered')

        for service in _global_peer.services:
            logger.info(f'Discovered service UUID: {service.uuid}')
             # Look only at your target service:
            if service.uuid != self.target_service_uuid:
                continue

            logger.info(f"=== Found target service {service.uuid}, discovering characteristics")
            await service.discover_characteristics()

            # find the three chars
            for char in service.characteristics:
                if char.uuid == STATE_UUID:
                    # your existing state write
                    await _global_peer.write_value(char, b'\x01')
                    logger.info("State written (0x01)")

                elif char.uuid == CLIENT2SERVER_UUID:
                    _global_char_client2server = char
                    logger.info("Discovered client server characteristic")

                elif char.uuid == SERVER2CLIENT_UUID:
                    _global_char_server2client = char                    
                    logger.info("Discovered server client characteristic")

            # subscribe to notifications on server client
            if _global_char_server2client:  
                logger.info("Discovered descriptor")
                # 1) Discover its descriptors so we can find the CCCD
                await _global_char_server2client.discover_descriptors()
                for desc in _global_char_server2client.descriptors:
                    logger.info(f"    Descriptor: handle=0x{desc.handle:04x} uuid={desc.type} ")
             
                # define how to handle incoming notifications:
                def _on_notify(value):                   
                    global global_received_data
                    logger.debug("Notification received: %s", value.hex())

                    # Ensure the received frame is not empty
                    if not value or len(value) < 1:
                        logger.error("Received an empty frame!")
                        return

                    # Read the marker from the first byte
                    marker = value[0]

                    if marker == 0x01:
                        if len(global_received_data) == 0:
                            if _message_start_received_callback:
                                try:
                                    _message_start_received_callback()
                                    logger.info("MessageStartReceived callback fired.")
                                except Exception as e:
                                    logger.error("Error calling MessageStartReceived callback: %s", e)
                            else:
                                logger.warning("No MessageStartReceived callback is registered.")
                        # Intermediate frame: append data excluding the marker
                        global_received_data.extend(value[1:])
                    elif marker == 0x00:
                        # Final frame: append data excluding the marker
                        global_received_data.extend(value[1:])

                        # Now call the registered callback with the complete data
                        if _message_notify_callback:
                            try:
                                _message_notify_callback(bytes(global_received_data))
                            except Exception as e:
                                logger.error("Error calling message received callback: %s", e)
                        else:
                            logger.warning("No message received callback is registered.")

                        # Clear the accumulated data for the next message
                        global_received_data.clear()
                    else:
                        logger.error("Unknown frame marker: 0x%02X", marker)
                               

                # Check if the characteristic supports notifications or indications
                #if _global_char_server2client.properties & Characteristic.NOTIFY:
                logger.info("Characteristic supports NOTIFY")
                # Ensure CCCD is correctly configured
                cccd = _global_char_server2client.get_descriptor(CCCD_UUID)
                if cccd:
                    try:
                        # Enable notifications by writing to CCCD
                        await _global_peer.write_value(cccd, b'\x03\x00', with_response=True)
                        logger.info("CCCD configured for both notifications and indications")

                        # Manually set up the callback for indications
                        # This is a simplified example; you may need to adjust based on your specific needs
                        def handle_indication(value):
                            _on_notify(value)

                        # Add the callback to the indication subscribers //needed for Virghinia wallet
                        subscriber_set = _global_peer.gatt_client.indication_subscribers.setdefault(_global_char_server2client.handle, set())
                        subscriber_set.add(_on_notify)

                        # Add the callback to  notification  subscribers
                        notification_subscriber_set = _global_peer.gatt_client.notification_subscribers.setdefault(_global_char_server2client.handle, set())
                        notification_subscriber_set.add(_on_notify)
                        logger.info("Subscribed to server client characteristic NOTIFY & INDICATE")
                    except Exception as e:
                        # some peripherals reject INDICATE; fall back to generic subscribe()
                        logger.warning(f"CCCD write failed ({e}); falling back to subscribe() helper")
                        await _global_peer.gatt_client.subscribe(
                            _global_char_server2client,
                            subscriber=_on_notify,      
                            prefer_notify=True         # request NOTIFY only
                        )
                        logger.info("Subscribed via subscribe() helper")                                  
                else:
                    logger.error("Characteristic does not support NOTIFY or INDICATE")

                logger.info("Subscribed to server client characteristic")                     
                # 5) Give the controller a moment to process the write
                await asyncio.sleep(0.5)

            # signal your main future so scan/connect completes
            self.service_found_future.set_result((connection, service))
            return

        logger.warning(f'=== Service with UUID {self.target_service_uuid} not found')
        if not self.service_found_future.done():
            self.service_found_future.set_result(None)

    def on_disconnection(self, connection, reason):
        logger.info(f"### Disconnected {connection}, reason={reason}")
        # clear it
        if self.current_connection == connection:
            self.current_connection = None
  
    async def _stop_and_connect(self, addr):
        try:
            await self.device.stop_scanning()
            await self.device.connect(addr)
        except Exception as e:
            logger.error(f"Failed to connect to {addr}: {e}")
            self.connecting = False  # Allow retry on failure

# -----------------------------------------------------------------------------
async def scan_and_connect(config_file: str, transport: str, target_service_uuid: UUID, timeout: int = 10):
    global global_hci_transport, _global_device

    if global_hci_transport is None:
        global_hci_transport = await open_transport_or_link(transport)

    device = Device.from_config_file_with_hci(config_file, global_hci_transport.source, global_hci_transport.sink)

    _global_device = device

    if device.is_scanning:
        await device.stop_scanning()

    listener = ClientListener(device, target_service_uuid)

    # First, if we already have a connection, tear it down
    if listener.current_connection is not None:
        await listener.current_connection.disconnect()
        logger.info("Disconnected previous connection")

    device.listener = listener
    await device.power_on()

 
    # Start scanning for devices
    logger.info('=== Scanning for devices...')
    await device.start_scanning(active=True, legacy=True)
    logger.info('=== Scanning started')

    # Wait for the service to be found or timeout
    try:
        result = await asyncio.wait_for(listener.service_found_future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        logger.warning('=== Timed out while scanning for devices')
        return None
    finally:
        logger.info('=== Stopping scanning')
        await device.stop_scanning(legacy=True)
        logger.info('=== Scan stop')

async def disconnect_device():
    global _global_device
    global _global_peer

    if _global_peer:
        try:
            logger.info('[INFO] Disconnecting from device...')
            await _global_device.disconnect(_global_peer.connection)
            logger.info('[INFO] Disconnected.')
        except Exception as e:
            logger.info(f'[ERROR] Failed to disconnect: {e}')
        finally:
            _global_peer = None
    else:
        logger.error('[INFO] No active peer to disconnect.')

# -----------------------------------------------------------------------------
def run_scan_and_connect(config_file: str, transport: str, target_service_uuid: str, timeout: int = 10):
    try:
        future = asyncio.run_coroutine_threadsafe(
            scan_and_connect(config_file, transport, UUID(target_service_uuid), timeout),
            global_event_loop
        )
        connection = future.result(timeout=timeout + 2)  # Add timeout buffer

        if connection is None:
            raise RuntimeError("Scan/connect returned None")

        return True

    except Exception as e:
        logger.error(f"[Python] Error during scan/connect: {e}")
        raise  # This will be caught in C# if needed

def run_disconnect(timeout: int = 5):
    try:
        future = asyncio.run_coroutine_threadsafe(
            disconnect_device(),
            global_event_loop
        )
        result = future.result(timeout=timeout)
        return True
    except Exception as e:
        logger.error(f"[Python] Error during disconnect: {e}")
        raise

def run_send_data_to_server(data: bytes):
    if _global_char_client2server is None:
        raise RuntimeError("client2server characteristic not available")

    if _global_peer is None or _global_char_client2server is None:
        raise RuntimeError("Not connected or write characteristic not ready")

    # Ensure that data is a Python bytes object.
    if not isinstance(data, bytes):
        try:
            data = bytes(list(data))
        except Exception as e:
            logger.error("Could not convert data to Python bytes: %s", e)
            return
        
    logger.info(f"Sending {data.hex()} via Peer.write_value(...)")
    future = asyncio.run_coroutine_threadsafe(
        _global_peer.write_value(_global_char_client2server, data, with_response=False),
        global_event_loop
    )
    # this will block until the write is sent (no response expected)
    future.result(timeout=5.0)
    logger.info("send_data_to_server: write_value completed")
    return True

# ------------------------------------------------------------------------------
# Synchronous wrapper for setup.
# ------------------------------------------------------------------------------
def run_setup_bluetooth_server(config_file: str, transport: str, service_uuid_str: str, ident_value: bytes,):  
    # Schedule the coroutine on the persistent loop.
    future = asyncio.run_coroutine_threadsafe(
        setup_bluetooth_server(config_file, transport, service_uuid_str, ident_value),
        global_event_loop
    )
    device, _ = future.result()
    return device  # Return only the device

def run_send_data(device, data: bytes):
    future = asyncio.run_coroutine_threadsafe(
        send_data_to_client(device, data),
        global_event_loop
    )
    return future.result()

def run_send_session_termination(device):
    logger.info("run_send_session_termination")
    future = asyncio.run_coroutine_threadsafe(
        send_session_termination(device),
        global_event_loop
    )
         
    return future.result(1.0)


# ------------------------------------------------------------------------------
# Command-line entry point
# ------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Run a GATT server with a custom service and advertise it.")
    parser.add_argument("config_file", help="Path to the device config file (JSON)")
    parser.add_argument("transport", help="Transport (e.g., usb:0, serial:/dev/ttyUSB0, tcp-client:127.0.0.1:1234)")
    parser.add_argument("service_uuid", help="Custom service UUID to advertise")
    args = parser.parse_args()

    svc_uuid = UUID(args.service_uuid)
    logger.info(f"Starting scan/connect for service {svc_uuid}")

    # 1) Scan & connect (blocking call)
    result = run_scan_and_connect(args.config_file, args.transport, args.service_uuid)
    if result is None:
        logger.error("Failed to find or connect to target service")
        return
    conn, service = result
    logger.info(f"Connected & discovered service {service.uuid}")

    # 2) Send a 5-byte test payload
    payload = bytes.fromhex("0001010101")
    logger.info(f"Sending test payload: {payload.hex()}")
    try:
        ok = run_send_data_to_server(payload)
        logger.info(f"Payload send returned: {ok}")
    except Exception as e:
        logger.exception("Exception during send_data_to_server")
    
    #target_service_uuid = UUID("18CED8CB-943A-46E4-84EB-2AEBB00675A7")
    #asyncio.run(scan_and_connect(args.config_file, args.transport, target_service_uuid))
   
    #asyncio.run(setup_bluetooth_server(args.config_file, args.transport, args.service_uuid))

if __name__ == "__main__":
    main()
