import aiohttp
import asyncio

async def _session():
    base_url = "http://<redacted>/webapp/data/getLoginWebApp.php"
    params = {
        "login_ide": "",
        "login_pwd": ""
    }

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "ko,en-US;q=0.9,en;q=0.8,ko-KR;q=0.7",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Dnt": "1",
        "Host": "<redacted>",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 <redacted>"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url=base_url, params=params, headers=headers) as response:
                if response.status != 200:
                    print(f"Session failed with status {response.status}")
                    return

                try:
                    data = await response.json(content_type="text/html")
                except Exception as json_ex:
                    print(f"Failed to parse JSON response: {type(json_ex).__name__}: {json_ex}")
                    return

                if "_fair" in data.get("ret", ""):
                    print(f"Session failed with status 200: Invalid value: {data.get('msg', 'No message')}")
                else:
                    print(f"Session successful: {data}")

                    cookies = response.cookies
                    phpsessid = cookies.get('PHPSESSID')
                    user_id = cookies.get('user_id')
                    user_name = cookies.get('user_name')

                    print(f"PHPSESSID: {phpsessid.value if phpsessid else 'Not found'}")
                    print(f"user_id: {user_id.value if user_id else 'Not found'}")
                    print(f"user_name: {user_name.value if user_name else 'Not found'}")

                    new_cookie = {
                        'PHPSESSID': phpsessid.value if phpsessid else None,
                        'user_id': user_id.value if user_id else None,
                        'user_name': user_name.value if user_name else None,
                    }

                    print(f"New cookie: {new_cookie}")

    except Exception as ex:
        print(f"Exception during session: {type(ex).__name__}: {ex}")


if __name__ == "__main__":
    asyncio.run(_session())
