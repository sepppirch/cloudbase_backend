# run multiple bots that fly in a circle around Vienna.


import asyncio
import json
import math
import time
from contextlib import suppress
import ssl

import websockets
VIENNA_CENTER = (47.29450235327786, 12.772791361811358)
BRATISLAVA_CENTER = (48.1486, 17.1077)
UPDATE_INTERVAL = 0.2  # 200ms between updates
WS_URI = "wss://jetskeee.com:8765/ws"


class CircleBot:
    def __init__(self, name, radius_km, speed_deg_per_sec, center=VIENNA_CENTER, altitude=1000):
        self.name = name
        self.radius_km = radius_km
        self.speed_deg_per_sec = speed_deg_per_sec
        self.center = center
        self.altitude = altitude
        self.start_time = None

    async def start(self, websocket):
        self.start_time = time.time()
        await websocket.send(
            json.dumps({"event_name": "GAMESERVER_SET_NAME", "to": "others", "payload": {"name": self.name}})
        )

    def calculate_position(self, elapsed_time):
        angle_deg = (elapsed_time * self.speed_deg_per_sec) % 360
        angle_rad = math.radians(angle_deg)

        lat = self.center[0] + (self.radius_km / 111) * math.cos(angle_rad)
        lon = self.center[1] + (self.radius_km / (111 * math.cos(math.radians(self.center[0])))) * math.sin(angle_rad)
        direction = (angle_deg) % 360

        return lat, lon, direction


async def run_bot(bot):
    while True:  # Outer loop for reconnection
        try:
            # Create SSL context that ignores certificate verification
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            async with websockets.connect(WS_URI, ping_interval=20, ping_timeout=60, 
                                        ssl=ssl_context) as websocket:
                print(f"Connected to {WS_URI} for {bot.name}")
                await bot.start(websocket)

                while True:
                    receive_task = asyncio.create_task(websocket.recv())
                    send_task = asyncio.create_task(send_update(bot, websocket))

                    # Wait for either task to complete
                    done, pending = await asyncio.wait([receive_task, send_task], return_when=asyncio.FIRST_COMPLETED)

                    # Cancel pending tasks
                    for task in pending:
                        task.cancel()

                    # Process completed tasks
                    for task in done:
                        with suppress(asyncio.CancelledError):
                            await task

                    await asyncio.sleep(UPDATE_INTERVAL)

        except websockets.exceptions.ConnectionClosed:
            print(f"Connection closed for {bot.name}, attempting to reconnect...")
            await asyncio.sleep(5)  # Wait before reconnecting
        except Exception as e:
            print(f"Error for {bot.name}: {e}")
            await asyncio.sleep(5)


async def send_update(bot, websocket):
    """Helper function to send position updates"""
    current_time = time.time()
    elapsed_time = current_time - bot.start_time
    lat, lon, direction = bot.calculate_position(elapsed_time)

    message = {
        "event_name": "GAMESERVER_CLIENT_UPDATE_STATE",
        "to": "others",
        "payload": {"lat": lat, "long": lon, "alt": bot.altitude, "rot_x": 0.5, "rot_y": 0.5, "rot_z": direction, "type": 1, "anim": 0},
    }

    await websocket.send(json.dumps(message))
    if int(elapsed_time) % 5 == 0:  # Print every 5 seconds
        print(f"{bot.name} - Position: {lat:.4f}, {lon:.4f}, Direction: {direction:.1f}°")


async def run_bots(bots):
    tasks = [run_bot(bot) for bot in bots]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    bots = [
        CircleBot("Fast Observer 780", radius_km=0.01, speed_deg_per_sec=360/10, altitude=780),
        CircleBot("Fast Observer 800", radius_km=0.02, speed_deg_per_sec=360/11, altitude=800),
        CircleBot("Fast Observer 820", radius_km=0.05, speed_deg_per_sec=360/12, altitude=820),
        CircleBot("Fast Observer 840", radius_km=0.1, speed_deg_per_sec=360/40, altitude=840),
        CircleBot("Fast Observer 860", radius_km=0.2, speed_deg_per_sec=360/60, altitude=860),
        CircleBot("Fast Observer 880", radius_km=0.3, speed_deg_per_sec=360/40, altitude=880),
        CircleBot("Fast Observer 890", radius_km=0.4, speed_deg_per_sec=360/60, altitude=890),
        CircleBot("Fast Observer 895", radius_km=0.35, speed_deg_per_sec=360/70, altitude=895),
        CircleBot("Fast Observer 898", radius_km=0.7, speed_deg_per_sec=360/70, altitude=898),
        CircleBot("Fast Observer 900", radius_km=1, speed_deg_per_sec=360/70, altitude=900),
    ]

    for bot in bots:
        print(f"Bot: {bot.name}, Radius: {bot.radius_km}km, Speed: {bot.speed_deg_per_sec:.1f}°/s, Altitude: {bot.altitude}m")

    asyncio.run(run_bots(bots))
