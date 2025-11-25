import enum
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass

class SeasonType(enum.Enum):
    SPRING = "spring"
    SUMMER = "summer" 
    AUTUMN = "autumn"
    WINTER = "winter"
    HALLOWEEN = "halloween"
    CHRISTMAS = "christmas"
    NEW_YEAR = "new_year"

@dataclass
class Season:
    id: int
    name: str
    type: SeasonType
    start_date: datetime
    end_date: datetime
    xp_multiplier: float
    coin_multiplier: float
    special_items: List[int]
    is_active: bool

class SeasonalSystem:
    def __init__(self, bot):
        self.bot = bot
        self.current_season: Optional[Season] = None
        self.seasonal_events = {}
        self.setup_seasonal_events()
    
    def setup_seasonal_events(self):
        """Настройка сезонных событий"""
        current_year = datetime.now().year
        
        self.seasonal_events = {
            SeasonType.HALLOWEEN: {
                'name': '🎃 Хэллоуин',
                'start': datetime(current_year, 10, 25),
                'end': datetime(current_year, 11, 2),
                'xp_multiplier': 1.3,
                'coin_multiplier': 1.4,
                'color_theme': 'orange',
                'special_achievements': ['pumpkin_king', 'ghost_hunter'],
                'shop_items': [101, 102, 103]
            },
            SeasonType.CHRISTMAS: {
                'name': '🎄 Рождество',
                'start': datetime(current_year, 12, 20),
                'end': datetime(current_year, 12, 27),
                'xp_multiplier': 1.2,
                'coin_multiplier': 1.3,
                'color_theme': 'red_green',
                'special_achievements': ['santa_helper', 'gift_master'],
                'shop_items': [201, 202, 203]
            },
            SeasonType.NEW_YEAR: {
                'name': '🎆 Новый Год',
                'start': datetime(current_year, 12, 28),
                'end': datetime(current_year + 1, 1, 7),
                'xp_multiplier': 1.5,
                'coin_multiplier': 1.6,
                'color_theme': 'gold',
                'special_achievements': ['firework_expert', 'new_year_hero'],
                'shop_items': [301, 302, 303]
            }
        }

    async def init_seasonal_tables(self):
        """Инициализация таблиц для сезонов"""
        await self.bot.conn.execute('''
            CREATE TABLE IF NOT EXISTS seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                type TEXT,
                start_date TEXT,
                end_date TEXT,
                xp_multiplier REAL DEFAULT 1.0,
                coin_multiplier REAL DEFAULT 1.0,
                special_items TEXT,
                is_active INTEGER DEFAULT 0,
                created_at TEXT
            )
        ''')
        
        await self.bot.conn.execute('''
            CREATE TABLE IF NOT EXISTS user_season_stats (
                user_id INTEGER,
                season_id INTEGER,
                xp_earned INTEGER DEFAULT 0,
                coins_earned INTEGER DEFAULT 0,
                messages_sent INTEGER DEFAULT 0,
                achievements_unlocked INTEGER DEFAULT 0,
                final_rank INTEGER,
                rewards_claimed INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, season_id)
            )
        ''')
        
        await self.bot.conn.execute('''
            CREATE TABLE IF NOT EXISTS season_leaderboard (
                season_id INTEGER,
                user_id INTEGER,
                total_xp INTEGER DEFAULT 0,
                rank INTEGER,
                PRIMARY KEY (season_id, user_id)
            )
        ''')
        
        await self.bot.conn.execute('''
            CREATE TABLE IF NOT EXISTS seasonal_shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_type TEXT,
                name TEXT,
                description TEXT,
                price INTEGER,
                item_type TEXT,
                duration_days INTEGER,
                limited_quantity INTEGER,
                sold_count INTEGER DEFAULT 0
            )
        ''')
        
        await self.bot.conn.commit()

    async def get_current_season(self) -> Optional[Season]:
        """Получение текущего активного сезона"""
        cursor = await self.bot.conn.execute('''
            SELECT * FROM seasons 
            WHERE is_active = 1 
            AND datetime(start_date) <= datetime('now') 
            AND datetime(end_date) >= datetime('now')
        ''')
        season_data = await cursor.fetchone()
        
        if season_data:
            return Season(
                id=season_data[0],
                name=season_data[1],
                type=SeasonType(season_data[2]),
                start_date=datetime.fromisoformat(season_data[3]),
                end_date=datetime.fromisoformat(season_data[4]),
                xp_multiplier=season_data[5],
                coin_multiplier=season_data[6],
                special_items=json.loads(season_data[7] or '[]'),
                is_active=bool(season_data[8])
            )
        return None

    async def check_seasonal_events(self):
        """Проверка и активация сезонных событий"""
        now = datetime.now()
        
        for season_type, event_data in self.seasonal_events.items():
            if event_data['start'] <= now <= event_data['end']:
                # Создаем или активируем сезон
                await self.activate_seasonal_event(season_type, event_data)

    async def activate_seasonal_event(self, season_type: SeasonType, event_data: dict):
        """Активация сезонного события"""
        # Деактивируем предыдущие сезоны
        await self.bot.conn.execute('UPDATE seasons SET is_active = 0')
        
        # Создаем новый сезон
        await self.bot.conn.execute('''
            INSERT OR REPLACE INTO seasons 
            (name, type, start_date, end_date, xp_multiplier, coin_multiplier, 
             special_items, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        ''', (
            event_data['name'],
            season_type.value,
            event_data['start'].isoformat(),
            event_data['end'].isoformat(),
            event_data['xp_multiplier'],
            event_data['coin_multiplier'],
            json.dumps(event_data['shop_items']),
            datetime.now().isoformat()
        ))
        
        await self.bot.conn.commit()
        
        # Добавляем сезонные предметы в магазин
        await self.add_seasonal_shop_items(season_type, event_data)
        
        # Уведомляем пользователей
        await self.announce_season_start(event_data)

    async def add_seasonal_shop_items(self, season_type: SeasonType, event_data: dict):
        """Добавление сезонных предметов в магазин"""
        seasonal_items = {
            SeasonType.HALLOWEEN: [
                ("🎃 Тыква-светильник", "Сезонный предмет Хэллоуина", 500, "decoration", 30, 100),
                ("👻 Призрачный плащ", "Особый предмет на Хэллоуин", 1000, "costume", 7, 50),
                ("🍬 Корзина конфет", "Дает бонусные коины", 300, "boost", 1, 200)
            ],
            SeasonType.CHRISTMAS: [
                ("🎄 Рождественская ель", "Сезонное украшение", 600, "decoration", 30, 100),
                ("🎅 Костюм Санты", "Праздничный наряд", 1200, "costume", 7, 50),
                ("🎁 Подарок", "Случайный бонус", 400, "mystery", 1, 150)
            ],
            SeasonType.NEW_YEAR: [
                ("🎆 Фейерверк", "Новогоднее украшение", 700, "decoration", 30, 100),
                ("🕛 Часы до Нового Года", "Особый предмет", 1500, "special", 7, 30),
                ("🥂 Бокал шампанского", "Бонус на следующий год", 600, "boost", 365, 80)
            ]
        }
        
        items = seasonal_items.get(season_type, [])
        for item in items:
            await self.bot.conn.execute('''
                INSERT OR REPLACE INTO seasonal_shop_items 
                (season_type, name, description, price, item_type, duration_days, limited_quantity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (season_type.value, *item))

    async def announce_season_start(self, event_data: dict):
        """Анонс начала сезона"""
        message = (
            f"🎉 {event_data['name']} начался!\n\n"
            f"✨ Бонусы сезона:\n"
            f"📈 Множитель опыта: x{event_data['xp_multiplier']}\n"
            f"💰 Множитель коинов: x{event_data['coin_multiplier']}\n"
            f"🎁 Особые предметы в магазине!\n\n"
            f"⏰ Сезон продлится до {event_data['end'].strftime('%d.%m.%Y')}"
        )
        
        # Здесь можно добавить рассылку по всем чатам
        logging.info(f"Сезон начался: {event_data['name']}")

    async def apply_seasonal_multipliers(self, base_xp: int, base_coins: int) -> Tuple[int, int]:
        """Применение сезонных множителей"""
        season = await self.get_current_season()
        if season:
            return (
                int(base_xp * season.xp_multiplier),
                int(base_coins * season.coin_multiplier)
            )
        return base_xp, base_coins

    async def update_user_season_stats(self, user_id: int, xp: int, coins: int):
        """Обновление сезонной статистики пользователя"""
        season = await self.get_current_season()
        if not season:
            return
            
        await self.bot.conn.execute('''
            INSERT INTO user_season_stats 
            (user_id, season_id, xp_earned, coins_earned, messages_sent)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(user_id, season_id) 
            DO UPDATE SET 
                xp_earned = xp_earned + ?,
                coins_earned = coins_earned + ?,
                messages_sent = messages_sent + 1
        ''', (user_id, season.id, xp, coins, xp, coins))
        
        await self.bot.conn.commit()

    async def get_season_leaderboard(self, season_id: int, limit: int = 10):
        """Получение таблицы лидеров сезона"""
        cursor = await self.bot.conn.execute('''
            SELECT u.username, uss.xp_earned, uss.coins_earned, uss.final_rank
            FROM user_season_stats uss
            JOIN users u ON uss.user_id = u.user_id
            WHERE uss.season_id = ?
            ORDER BY uss.xp_earned DESC
            LIMIT ?
        ''', (season_id, limit))
        return await cursor.fetchall()

    async def end_current_season(self):
        """Завершение текущего сезона"""
        season = await self.get_current_season()
        if not season:
            return
            
        # Вычисляем финальные ранги
        await self.calculate_final_ranks(season.id)
        
        # Выдаем награды
        await self.distribute_season_rewards(season.id)
        
        # Деактивируем сезон
        await self.bot.conn.execute(
            'UPDATE seasons SET is_active = 0 WHERE id = ?',
            (season.id,)
        )
        
        await self.bot.conn.commit()
        
        # Анонсируем завершение
        await self.announce_season_end(season)

    async def calculate_final_ranks(self, season_id: int):
        """Вычисление финальных рангов"""
        cursor = await self.bot.conn.execute('''
            SELECT user_id, xp_earned 
            FROM user_season_stats 
            WHERE season_id = ?
            ORDER BY xp_earned DESC
        ''', (season_id,))
        
        users = await cursor.fetchall()
        
        for rank, (user_id, xp_earned) in enumerate(users, 1):
            await self.bot.conn.execute('''
                UPDATE user_season_stats 
                SET final_rank = ? 
                WHERE user_id = ? AND season_id = ?
            ''', (rank, user_id, season_id))
        
        await self.bot.conn.commit()

    async def distribute_season_rewards(self, season_id: int):
        """Распределение наград по итогам сезона"""
        rewards = {
            1: {'coins': 5000, 'xp': 1000, 'item': 'season_champion'},
            2: {'coins': 3000, 'xp': 700, 'item': 'season_runner_up'},
            3: {'coins': 2000, 'xp': 500, 'item': 'season_third_place'},
            'top10': {'coins': 1000, 'xp': 300},
            'top50': {'coins': 500, 'xp': 150},
            'participant': {'coins': 100, 'xp': 50}
        }
        
        cursor = await self.bot.conn.execute('''
            SELECT user_id, final_rank 
            FROM user_season_stats 
            WHERE season_id = ? AND final_rank IS NOT NULL
        ''', (season_id,))
        
        participants = await cursor.fetchall()
        
        for user_id, rank in participants:
            if rank == 1:
                reward = rewards[1]
            elif rank == 2:
                reward = rewards[2] 
            elif rank == 3:
                reward = rewards[3]
            elif rank <= 10:
                reward = rewards['top10']
            elif rank <= 50:
                reward = rewards['top50']
            else:
                reward = rewards['participant']
            
            # Выдаем награды
            await self.bot.conn.execute('''
                UPDATE users 
                SET balance = balance + ?, xp = xp + ?
                WHERE user_id = ?
            ''', (reward['coins'], reward['xp'], user_id))
            
            # Отмечаем получение наград
            await self.bot.conn.execute('''
                UPDATE user_season_stats 
                SET rewards_claimed = 1 
                WHERE user_id = ? AND season_id = ?
            ''', (user_id, season_id))
            
            # Выдаем особые предметы для топ-3
            if rank <= 3 and 'item' in reward:
                await self.give_seasonal_item(user_id, reward['item'])
        
        await self.bot.conn.commit()

    async def give_seasonal_item(self, user_id: int, item_type: str):
        """Выдача сезонного предмета"""
        await self.bot.conn.execute('''
            INSERT INTO user_inventory (user_id, item_id, purchased_at, is_active)
            VALUES (?, (SELECT id FROM seasonal_shop_items WHERE item_type = ?), ?, 1)
        ''', (user_id, item_type, datetime.now().isoformat()))

    async def soft_season_reset(self):
        """Мягкий сброс статистики между сезонами"""
        # Сохраняем достижения, инвентарь, баланс
        # Сбрасываем только сезонную статистику
        await self.bot.conn.execute('''
            UPDATE users 
            SET weekly_activity = 0,
                daily_streak = 0
        ''')
        
        # Архивируем старые сезонные данные
        await self.bot.conn.execute('''
            INSERT INTO season_archive 
            SELECT * FROM user_season_stats 
            WHERE season_id NOT IN (SELECT id FROM seasons WHERE is_active = 1)
        ''')
        
        # Очищаем старые данные
        await self.bot.conn.execute('''
            DELETE FROM user_season_stats 
            WHERE season_id NOT IN (SELECT id FROM seasons WHERE is_active = 1)
        ''')
        
        await self.bot.conn.commit()

    async def announce_season_end(self, season: Season):
        """Анонс завершения сезона"""
        # Получаем топ-3 игроков
        top_players = await self.get_season_leaderboard(season.id, 3)
        
        message = f"🎉 **Сезон {season.name} завершен!**\n\n🏆 **Топ-3 игроков:**\n"
        
        for i, (username, xp_earned, coins_earned, rank) in enumerate(top_players, 1):
            message += f"{i}. @{username} - {xp_earned} XP, {coins_earned} коинов\n"
        
        message += f"\n🎁 Награды были распределены. Спасибо всем за участие!"
        
        # Здесь можно добавить рассылку по всем чатам
        logging.info(f"Сезон завершен: {season.name}")
