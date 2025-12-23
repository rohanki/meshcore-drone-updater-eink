#!/usr/bin/env python3
import asyncio
import os
import sys
import logging
import re
import subprocess
from bleak import BleakScanner

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
    """Executes the DFU process with real-time progress logging and log cleaning."""
    logging.info(f"STARTING OTA: {target_name} [{address}]")
    logging.info(f"FIRMWARE: {firmware_path}")

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
    """Main loop: prioritizes DFU mapping then standard mapping."""
    await wait_for_downloader()
    logging.info("--- Drone Auto-Updater Service Started ---")

    while True:
        try:
            dfu_mapping = load_mapping(DFU_MAPPING_FILE, DFU_OVERRIDE_FW)
            standard_mapping = load_mapping(MAPPING_FILE, OVERRIDE_FW)
            devices = await BleakScanner.discover(timeout=3.0)

            for dev in devices:
                name = dev.name
                if not name: continue

                # Priority 1: DFU Mapping
                if name in dfu_mapping:
                    logging.info(f"DFU MATCH: {name}")
                    await run_dfu(name, dev.address, dfu_mapping[name])
                    break

                # Priority 2: Standard Mapping
                elif name in standard_mapping:
                    logging.info(f"STANDARD MATCH: {name}")
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
