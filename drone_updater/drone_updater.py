#!/usr/bin/env python3
import asyncio
import os
import sys
import logging
import re
import subprocess
from bleak import BleakScanner
import time
from PIL import Image, ImageDraw, ImageFont
import os
import sys
import socket

#libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)),'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)
from waveshare_epd import epd2in13_V4

# --- Configuration ---
WORK_DIR = "/opt/drone_updater/"
CONFIG_DIR = "/boot/firmware/drone_updater/"

MAPPING_FILE = os.path.join(CONFIG_DIR, "firmware_mapping.txt")
DFU_MAPPING_FILE = os.path.join(CONFIG_DIR, "dfu_mapping.txt")

OVERRIDE_FW = os.path.join(CONFIG_DIR, "firmware.zip")
DFU_OVERRIDE_FW = os.path.join(CONFIG_DIR, "dfu.zip")

LOG_FILE = "/var/log/drone_updater.log"
DFU_SCRIPT = os.path.join(WORK_DIR, "dfu_cli.py")

PRN_VALUE = "8"
RETRY_N = "5"
extra_params = "--scan"

SCREEN_UPDATE_INT = 5

# --- Configure Logging ---
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

service_running = False
totAttempts = 0
totSuccess = 0
pct = 0
log1 = ""
log2 = ""
log3 = ""



def get_battery_percentage():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(("127.0.0.1", 8423))
        s.sendall(b"get battery\n")
        response = s.recv(1024).decode().strip()

    # Expected format: "battery: 79.56304"
    try:
        value = response.split(":")[1].strip()
        return int(float(value))  # Convert to float first, then int
    except (IndexError, ValueError):
        raise ValueError(f"Unexpected response format: {response}")

def get_temperature():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(("127.0.0.1", 8423))
        s.sendall(b"get temperature\n")
        response = s.recv(1024).decode().strip()

    # Expected format: "battery: 00.000"
    try:
        value = response.split(":")[1].strip()
        return int(float(value))  # Convert to float first, then int
    except (IndexError, ValueError):
        raise ValueError(f"Unexpected response format: {response}")
def get_charge_status():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(("127.0.0.1", 8423))
        s.sendall(b"get battery_power_plugged\n")
        response = s.recv(1024).decode().strip()

    # Expected format: "battery_power_plugged: true|false"
    try:
        value = response.split(":")[1].strip()
        if value == 'false':
            return "🔋"
        else:  
            return "🔌"
    except (IndexError, ValueError):
        raise ValueError(f"Unexpected response format: {response}")


async def update_eink_display():
    global service_running, log1,log2,log3, totAttempts, totSuccess
    epd = epd2in13_V4.EPD()
    epd.init()
    epd.Clear(0xFF)
    font24 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    font25 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    font26 = ImageFont.truetype("/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",12)
    font27 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    font28 = ImageFont.truetype("/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",10)


    time_image = Image.new('1', (epd.height, epd.width), 255)
    time_draw = ImageDraw.Draw(time_image)
    epd.displayPartBaseImage(epd.getbuffer(time_image))
    num = 0
    while (True):
        time_draw.rectangle((0, 0, epd.height, 15), fill = 0) #Draw background behind clock
        time_draw.rectangle((0, 16, epd.height, epd.width), fill = 255) #Draw background behind everything else
        time_draw.text((100, 2), time.strftime('%H:%M:%S'), font = font24, fill = 255) #draw time
        time_draw.text((210,2), f"{await asyncio.to_thread(get_battery_percentage)}%", font= font25, fill=255) #draw battery percentage
        time_draw.text((200,2), await asyncio.to_thread(get_charge_status), font= font26, fill=255) #draw battery percentage    
        time_draw.line((0,40,epd.height,40), width=2) #draw divider for status area
        time_draw.text((50,20), "Service Running" if service_running else "Service Stopped", font= font24, fill=0) #draw service status       
        time_draw.line((0,epd.width-15,epd.height,epd.width-15), width=2) #draw divider for nerd stats
        time_draw.text((0,45), log1, font= font25, fill=0) #draw log line 1
        if pct >0:
            time_draw.rectangle((60, 65, epd.height-20, 80), outline = 0, width=1) #draw progress bar outline
            time_draw.rectangle((60, 65, ((pct*(epd.height-80))/100)+60, 80), fill = 0) #draw progress fill     
            time_draw.text((120,65), f"{pct}%", font= font25, fill=0 if pct <50 else 255) #draw log line 2
            time_draw.text((0,65), "Progress:", font= font25, fill=0) #draw log line 2

        time_draw.text((0,85), log3, font= font25, fill=0) #draw log line 3
        time_draw.text((0,epd.width-15), f"{totSuccess}/{totAttempts}", font= font27, fill=0)  #draw successes/attempts   
        time_draw.text((110,epd.width-15), f"{await asyncio.to_thread(get_temperature)}°C", font= font27, fill=0)  #draw temperature   
        time_draw.text((100,epd.width-15), "🌡️", font= font28, fill=0)  #draw temperature   


        await asyncio.to_thread(epd.displayPartial, epd.getbuffer(time_image))
        await asyncio.sleep(SCREEN_UPDATE_INT)

def update_eink_stopped():
    global service_running, log1,log2,log3, totAttempts, totSuccess
    epd = epd2in13_V4.EPD()
    epd.init()
    epd.Clear(0xFF)
    font24 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    font25 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    font26 = ImageFont.truetype("/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",12)
    font27 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    font28 = ImageFont.truetype("/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",10)
    time_image = Image.new('1', (epd.height, epd.width), 255)
    time_draw = ImageDraw.Draw(time_image)
    epd.displayPartBaseImage(epd.getbuffer(time_image))
    num = 0
    time_draw.rectangle((0, 0, epd.height, 15), fill = 0) #Draw background behind clock
    time_draw.rectangle((0, 16, epd.height, epd.width), fill = 255) #Draw background behind everything else
    time_draw.text((100, 2), time.strftime('%H:%M:%S'), font = font24, fill = 255) #draw time
    time_draw.line((0,40,epd.height,40), width=2) #draw divider for status area
    time_draw.text((50,20), "Service Stopped", font= font24, fill=0) #draw service status       
    time_draw.line((0,epd.width-15,epd.height,epd.width-15), width=2) #draw divider for nerd stats
    if pct >0:
        time_draw.rectangle((60, 65, epd.height-20, 80), outline = 0, width=1) #draw progress bar outline
        time_draw.rectangle((60, 65, ((pct*(epd.height-80))/100)+60, 80), fill = 0) #draw progress fill     
        time_draw.text((120,65), f"{pct}%", font= font25, fill=0 if pct <50 else 255) #draw log line 2
        time_draw.text((0,65), "Progress:", font= font25, fill=0) #draw log line 2

    time_draw.text((0,85), log3, font= font25, fill=0) #draw log line 3
    time_draw.text((0,epd.width-15), f"{totSuccess}/{totAttempts}", font= font27, fill=0)  #draw successes/attempts   
    time_draw.text((100,epd.width-15), "🌡️", font= font28, fill=0)  #draw temperature   


    epd.displayPartial, epd.getbuffer(time_image)




async def wait_for_downloader():
    """Wait for the downloader service to finish to prevent file conflicts."""
    service_name = "firmware-downloader.service"
    while True:
        try:
            cmd = ["systemctl", "is-active", service_name]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if stdout.decode().strip() in ["active", "activating"]:
                logging.info("Downloader service active. Waiting...")
                await asyncio.sleep(5)
            else:
                break
        except:
            break

def load_mapping(mapping_file_path, force_override_path=None):
    """Loads device mappings, prioritizing .zip override files if they exist."""
    mapping = {}
    if not os.path.exists(mapping_file_path):
        return mapping

    active_override = force_override_path if (force_override_path and os.path.exists(force_override_path)) else None

    try:
        with open(mapping_file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"): continue
                parts = line.split(None, 1)
                if len(parts) >= 1:
                    device_name = parts[0]
                    raw_path = active_override if active_override else (parts[1] if len(parts) == 2 else "")
                    if raw_path:
                        real_path = os.path.realpath(raw_path)
                        if os.path.exists(real_path):
                            mapping[device_name] = real_path
    except Exception as e:
        logging.error(f"Error reading mapping {mapping_file_path}: {e}")
    return mapping

async def run_dfu(target_name, address, firmware_path):
    global pct, totAttempts,totSuccess, log1, log2, log3
    """Executes the DFU process with real-time progress logging and log cleaning."""
    logging.info(f"STARTING OTA: {target_name} [{address}]")
    logging.info(f"FIRMWARE: {firmware_path}")
    log1 = f"Found OTA: {target_name}"
    totAttempts +=1

    # Force the sub-process to flush output immediately
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [sys.executable, DFU_SCRIPT, "--prn", PRN_VALUE, "--retry", RETRY_N, extra_params, firmware_path, address]
    # Patterns for cleaning redundant timestamps and finding percentages
    cleanup_pattern = re.compile(r"^\d{2}:\d{2}:\d{2}\s+\[\w+\]\s+")
    percent_pattern = re.compile(r"(\d{1,3})\s?%")
    last_logged_percent = -1
    char_buffer = []

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env
        )
        while True:
            char_bytes = await process.stdout.read(1)
            if not char_bytes:
                break
            char = char_bytes.decode('utf-8', errors='ignore')
            # If we hit a line delimiter (\n or \r), process the accumulated text
            if char == '\n' or char == '\r':
                line = "".join(char_buffer).strip()
                char_buffer = []
                if not line: continue

                # Check if this line is a progress update we haven't logged yet
                match_pct = percent_pattern.search(line)
                if match_pct:
                    pct = int(match_pct.group(1))
                    if pct != last_logged_percent:
                        logging.info(f"DFU: Flashing Progress: {pct}%")
                        last_logged_percent = pct
                else:
                    # Log standard status messages, cleaning redundant info
                    clean_line = cleanup_pattern.sub("", line)
                    if any(k in line for k in ["Target", "Connect", "Jump", "Upload", "Success", "Error", "Exception", "Timeout", "Verifying", "Successful"]):
                        logging.info(f"DFU: {clean_line}")
                        log3 = clean_line
            else:
                # Add character to buffer
                char_buffer.append(char)
                # IMMEDIATE PERCENTAGE CHECK:
                # Check the buffer as it grows so we don't wait for the next \r
                current_buffer_str = "".join(char_buffer)
                match_pct = percent_pattern.search(current_buffer_str)
                if match_pct:
                    pct = int(match_pct.group(1))
                    if pct != last_logged_percent:
                        logging.info(f"DFU: Flashing Progress: {pct}%")
                        last_logged_percent = pct
                        # Note: We do NOT clear the buffer here, we let \r or \n do that
                        # to ensure we don't chop off non-percentage text.

        await process.wait()

        if process.returncode == 0:
            logging.info(f"SUCCESS: Flashing finished for {target_name}")
            log3 = f"Success: {target_name}"
            totSuccess +=1

            # Delete override files after successful flash
            if firmware_path == OVERRIDE_FW or firmware_path == DFU_OVERRIDE_FW:
                if os.path.exists(firmware_path):
                    os.remove(firmware_path)
                    logging.info(f"Cleanup: Removed override file {os.path.basename(firmware_path)}")
            return True
        else:
            logging.error(f"FAILED: Flashing ended with code {process.returncode}")
            return False

    except Exception as e:
        logging.error(f"Execution Exception: {e}")
        return False

async def service_loop():
    global service_running, log1,log2,log3
    """Main loop: prioritizes DFU mapping then standard mapping."""
    await wait_for_downloader()
    screen_update_task = asyncio.create_task(update_eink_display())
    logging.info("--- Drone Auto-Updater Service Started ---")
    service_running = True

    while True:
        try:
            dfu_mapping = load_mapping(DFU_MAPPING_FILE, DFU_OVERRIDE_FW)
            standard_mapping = load_mapping(MAPPING_FILE, OVERRIDE_FW)
            devices = await BleakScanner.discover(timeout=3.0)

            for dev in devices:
                name = dev.name
                if not name: continue
                log1 = "SCANNING ..."
                # Priority 1: DFU Mapping
                if name in dfu_mapping:
                    logging.info(f"DFU MATCH: {name}")
                    log1 = f"DFU: {name}"
                    await run_dfu(name, dev.address, dfu_mapping[name])
                    break

                # Priority 2: Standard Mapping
                elif name in standard_mapping:
                    logging.info(f"STANDARD MATCH: {name}")
                    log1 = f"OTA: {name}"
                    await run_dfu(name, dev.address, standard_mapping[name])
                    break

            await asyncio.sleep(1)

        except Exception as e:
            logging.error(f"Main Loop Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(service_loop())
        

    except KeyboardInterrupt:
        pass
