import requests
import sseclient 
import aiohttp
import asyncio

def sync_sse_client(url):
    try:
        with requests.get(url, stream=True) as response:
            client = sseclient.SSEClient(response)
            for event in client.events():
                print(f"Event type: {event.event}")
                print(f"Event data: {event.data}")
    except Exception as e:
        print(f"Unexpected error occurred in sync_sse_client: {e}")
    finally:
        client.close()

async def async_sse_client(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                async for line in response.content:
                    if line.startswith(b"data:"):
                        message = line.decode('utf-8').strip("data:").strip()
                        print(f"Received message: {message}")
    except Exception as e:
        print(f"Unexpected error occurred in async_sse_client: {e}")


if __name__ == "__main__":
    url = "https://<redacted>/v2/admin/elevators/sse"
    #sync_sse_client(url)
    asyncio.run(async_sse_client(url))
