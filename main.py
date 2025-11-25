import os
import asyncio
import logging
from aiohttp import web
from bot import EconomicBot

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class BotWebServer:
    def __init__(self, bot_token: str):
        self.bot = EconomicBot(bot_token)
        self.app = web.Application()
        self.setup_routes()
        
    def setup_routes(self):
        self.app.router.add_get('/', self.health_check)
        self.app.router.add_get('/health', self.health_check)
        
    async def health_check(self, request):
        return web.Response(text="Bot is running!")
    
    async def start_bot(self):
        """Запуск бота"""
        try:
            await self.bot.init_database()
            await self.bot.init_redis()
            await self.bot.init_scheduler()
            self.bot.setup_handlers()
            
            # Запускаем бота в фоне
            asyncio.create_task(self.bot.application.run_polling())
            logging.info("Bot started successfully!")
            
        except Exception as e:
            logging.error(f"Failed to start bot: {e}")
            raise
    
    async def start_server(self):
        """Запуск веб-сервера"""
        port = int(os.environ.get('PORT', 8080))
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logging.info(f"Web server started on port {port}")
        
        # Бесконечный цикл для поддержания работы сервера
        while True:
            await asyncio.sleep(3600)  # Спим 1 час

async def main():
    # Получаем токен бота из переменных окружения
    bot_token = os.environ.get('8321881274:AAELeSsK6DpxNQUMN0UJE-7C0t_OMPyivGo')
    if not bot_token:
        raise ValueError("BOT_TOKEN environment variable is required!")
    
    # Создаем и запускаем сервер
    server = BotWebServer(bot_token)
    
    # Запускаем бота и сервер параллельно
    await asyncio.gather(
        server.start_bot(),
        server.start_server()
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Bot crashed: {e}")
