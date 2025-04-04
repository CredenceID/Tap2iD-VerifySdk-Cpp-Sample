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
from bumble.device import Device, Connection
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

    # Optionally add a small delay here to ensure services are fully published.
    await asyncio.sleep(1)

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
    parser.add_argument("--service_uuid", required=True, help="Custom service UUID to advertise")
    args = parser.parse_args()

    asyncio.run(setup_bluetooth_server(args.config_file, args.transport, args.service_uuid))

if __name__ == "__main__":
    main()
