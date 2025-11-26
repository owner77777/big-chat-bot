import aiosqlite
import logging

class Database:
    def __init__(self, db_path: str = 'bot_database.db'):
        self.db_path = db_path
        self.conn = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.db_path)
        await self.conn.execute('PRAGMA journal_mode=WAL')
        return self.conn

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def init_tables(self, conn):
        # Здесь мы инициализируем все таблицы, которые были в оригинальном коде
        # Мы вынесли сюда только общие таблицы, а таблицы для сезонов и админки инициализируются в своих системах
        # Основные таблицы
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                last_daily TEXT,
                daily_streak INTEGER DEFAULT 0,
                last_message TEXT,
                warns INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                clan_id INTEGER,
                created_at TEXT,
                name_color TEXT,
                total_message_count INTEGER DEFAULT 0,
                weekly_activity INTEGER DEFAULT 0
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                type TEXT,
                timestamp TEXT,
                description TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                achievement_name TEXT,
                unlocked_at TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                price INTEGER,
                item_type TEXT,
                duration_days INTEGER
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_id INTEGER,
                purchased_at TEXT,
                expires_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS clans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                description TEXT,
                owner_id INTEGER,
                created_at TEXT,
                balance INTEGER DEFAULT 0
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS clan_members (
                clan_id INTEGER,
                user_id INTEGER,
                role TEXT DEFAULT 'member',
                joined_at TEXT,
                PRIMARY KEY (clan_id, user_id)
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS duels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenger_id INTEGER,
                challenged_id INTEGER,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                winner_id INTEGER
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_activity (
                user_id INTEGER,
                date TEXT,
                message_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date)
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS duel_stats (
                user_id INTEGER PRIMARY KEY,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0
            )
        ''')
        
        # Новые таблицы для модерации
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS moderation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                moderator_id INTEGER,
                action TEXT,
                reason TEXT,
                duration_minutes INTEGER,
                timestamp TEXT,
                message_text TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER,
                reported_user_id INTEGER,
                reason TEXT,
                message_id INTEGER,
                chat_id INTEGER,
                status TEXT DEFAULT 'pending',
                timestamp TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS word_filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT UNIQUE,
                action TEXT,
                created_by INTEGER,
                created_at TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_verification (
                user_id INTEGER PRIMARY KEY,
                captcha_text TEXT,
                attempts INTEGER DEFAULT 0,
                verified INTEGER DEFAULT 0,
                join_time TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_stats (
                date TEXT PRIMARY KEY,
                message_count INTEGER DEFAULT 0,
                user_count INTEGER DEFAULT 0,
                new_users INTEGER DEFAULT 0
            )
        ''')
        
        # Инициализация товаров магазина
        shop_items = [
            ("🎨 Смена цвета ника", "Изменение цвета ника на 7 дней", 300, "color_change", 7),
            ("📌 Закреп сообщения", "Возможность закреплять сообщения на 1 час", 150, "pin_message", 1),
            ("🚀 Буст опыта x1.5", "Увеличение получаемого опыта на 50% на 3 дня", 500, "xp_boost", 3),
            ("👑 VIP статус", "Особый статус в чате на 30 дней", 1000, "vip_status", 30),
            ("💰 Банковский счёт", "Ежедневные проценты на баланс", 2000, "bank_account", 0),
            ("🎭 Анонимность", "Отправка анонимных сообщений на 7 дней", 400, "anonymity", 7)
        ]
        
        for item in shop_items:
            await conn.execute('''
                INSERT OR IGNORE INTO shop_items (name, description, price, item_type, duration_days)
                VALUES (?, ?, ?, ?, ?)
            ''', item)
        
        await conn.commit()
