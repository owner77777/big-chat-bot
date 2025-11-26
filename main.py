import asyncio
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import Config
from database import Database
from economic_bot import EconomicBot

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

def run_web_server(port):
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    logging.info(f"Web server started on port {port}")
    server.serve_forever()

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
