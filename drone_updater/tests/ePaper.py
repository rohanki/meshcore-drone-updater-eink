import asyncio
from datetime import datetime
import time
from PIL import Image, ImageDraw, ImageFont
import os
import sys
import socket

libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)
from waveshare_epd import epd2in13_V4

service_running = False



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
        print(value)
    except (IndexError, ValueError):
        raise ValueError(f"Unexpected response format: {response}")


async def update_eink_display():
    global service_running
    epd = epd2in13_V4.EPD()
    epd.init()
    epd.Clear(0xFF)
    font24 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    font25 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    font26 = ImageFont.truetype("/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",12)


    time_image = Image.new('1', (epd.height, epd.width), 255)
    time_draw = ImageDraw.Draw(time_image)
    epd.displayPartBaseImage(epd.getbuffer(time_image))
    num = 0
    while (True):
        time_draw.rectangle((0, 0, epd.height, 15), fill = 0) #Draw background behind clock
        time_draw.text((80, 2), time.strftime('%H:%M:%S'), font = font24, fill = 255) #draw time
        print(get_battery_percentage())
        time_draw.text((210,2), f"{get_battery_percentage()}%", font= font25, fill=255) #draw battery percentage
        time_draw.text((200,2), get_charge_status(), font= font26, fill=255) #draw battery percentage    
        time_draw.line((0,40,epd.height,40), width=2) #draw divider for status area
        time_draw.text((50,20), "Service Running" if service_running else "Service Stopped", font= font24, fill=0) #draw service status       
        time_draw.line((0,epd.width-15,epd.height,epd.width-15), width=2) #draw divider for nerd stats
        time_draw.text((0,45), "Log Line 1", font= font25, fill=0) #draw log line 1      
        time_draw.text((0,65), "Log Line 2", font= font25, fill=0) #draw log line 2     
        time_draw.text((0,85), "Log Line 3", font= font25, fill=0) #draw log line 2     

        epd.displayPartial(epd.getbuffer(time_image))
        get_charge_status()
        num = num + 1
        time.sleep(2)


async def main():
    await update_eink_display()


if __name__ == "__main__":
    asyncio.run(main())