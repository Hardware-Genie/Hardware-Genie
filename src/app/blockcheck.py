import asyncio
from pypartpicker import AsyncClient

async def check():
    # DO NOT set no_js=True; we NEED JS rendering for Cloudflare
    async with AsyncClient() as pcpp:
        try:
            # Adding a common User-Agent can help bypass basic blocks
            res = await pcpp.get_part_search("3060", region="ca")
            print(f"Found {len(res.parts)} parts")
            for part in res.parts[:3]:
                print(f"- {part.name}")
        except Exception as e:
            print(f"Error: {e}")

asyncio.run(check())