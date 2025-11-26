import asyncio
import logging
from aiohttp import web
import threading

from config import Config
from database import Database
from economic_bot import EconomicBot

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def health_check(request):
    return web.Response(text="OK")

async def start_web_server(port):
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Web server started on port {port}")

def run_web_server(port):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_web_server(port))
    loop.run_forever()

async def main():
    config = Config()
    db = Database()
    
    bot = EconomicBot(config, db)
    
    # Запускаем веб-сервер в отдельном потоке
    web_thread = threading.Thread(target=run_web_server, args=(config.port,), daemon=True)
    web_thread.start()
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
