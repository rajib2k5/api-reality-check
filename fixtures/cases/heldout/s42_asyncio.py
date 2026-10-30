import asyncio
async def main():
    await asyncio.sleep(0)
    t = asyncio.create_task(asyncio.sleep(0, result=1), name="t")
    r = await asyncio.wait_for(t, timeout=1)
    res = await asyncio.gather(asyncio.sleep(0), return_exceptions=True)
    return r, res
print(asyncio.run(main(), debug=False))
