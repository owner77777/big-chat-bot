import os
from typing import Optional

class Config:
    def __init__(self):
        self.token = os.getenv('BOT_TOKEN', '8321881274:AAELeSsK6DpxNQUMN0UJE-7C0t_OMPyivGo')
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis_db = int(os.getenv('REDIS_DB', 0))
        self.redis_password = os.getenv('REDIS_PASSWORD', None)
        self.port = int(os.getenv('PORT', 8080))

config = Config()
