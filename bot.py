import logging
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import random
import matplotlib.pyplot as plt
import io
import aiosqlite
import redis.asyncio as redis
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ChatPermissions,
    ChatMember
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
import apscheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import json
import re
import string
from PIL import Image, ImageDraw, ImageFont
import os
import aiohttp
import zipfile
from pathlib import Path
import psutil

from seasonal_system import SeasonalSystem, Season, SeasonType
from admin_system import AdminSystem

class EconomicBot:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        
        self.redis_client = None
        self.message_queue = asyncio.Queue()
        
        self.scheduler = AsyncIOScheduler()
        
        self.hourly_multipliers = {
            'peak': (20, 23, 0.8),
            'quiet': (4, 7, 1.3),
            'normal': (0, 24, 1.0)
        }
        
        self.achievements_list = {
            'first_daily': {'name': 'Первый шаг', 'description': 'Получите первый ежедневный бонус', 'secret': False},
            'rich': {'name': 'Богач', 'description': 'Накопите 10,000 коинов', 'secret': False},
            'social': {'name': 'Социальная бабочка', 'description': 'Отправьте 100 сообщений', 'secret': False},
            'gambler': {'name': 'Азартный игрок', 'description': 'Выиграйте 5 дуэлей', 'secret': False},
            'veteran': {'name': 'Ветеран', 'description': 'Достигните 20 уровня', 'secret': False},
            'trader': {'name': 'Торговец', 'description': 'Совершите 10 переводов', 'secret': False},
            'collector': {'name': 'Коллекционер', 'description': 'Купите 5 предметов в магазине', 'secret': False},
            'king': {'name': 'Король чата', 'description': 'Займите первое место в рейтинге', 'secret': False},
            'no_life': {'name': 'Без жизни', 'description': 'Проведите в чате более 100 часов', 'secret': True},
            'lucky': {'name': 'Везунчик', 'description': 'Выиграйте 3 дуэли подряд', 'secret': True},
            'philanthropist': {'name': 'Филантроп', 'description': 'Пожертвуйте 5000 коинов другим игрокам', 'secret': True},
            'early_bird': {'name': 'Ранняя пташка', 'description': 'Получите ежедневный бонус в 4-6 утра', 'secret': True}
        }

        self.name_colors = {
            'red': '🔴',
            'blue': '🔵', 
            'green': '🟢',
            'yellow': '🟡',
            'purple': '🟣',
            'orange': '🟠',
            'rainbow': '🌈'
        }

        # Модерация
        self.bad_words = self.load_bad_words()
        self.spam_detection = {}
        self.user_join_times = {}
        
        # Мониторинг
        self.start_time = datetime.now()
        self.message_stats = {
            'total': 0,
            'today': 0,
            'last_reset': datetime.now()
        }

        # Новые системы
        self.seasonal_system = SeasonalSystem(self)
        self.admin_system = AdminSystem(self)

    def load_bad_words(self) -> List[str]:
        """Загрузка списка запрещенных слов"""
        try:
            with open('bad_words.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            default_words = [
                'оскорбление1', 'оскорбление2', 'спам', 'реклама'
            ]
            with open('bad_words.json', 'w', encoding='utf-8') as f:
                json.dump(default_words, f, ensure_ascii=False, indent=2)
            return default_words

    async def init_database(self):
        self.conn = await aiosqlite.connect('bot_database.db')
        await self.conn.execute('PRAGMA journal_mode=WAL')
        
        # Основные таблицы
        await self.conn.execute('''
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
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                type TEXT,
                timestamp TEXT,
                description TEXT
            )
        ''')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                achievement_name TEXT,
                unlocked_at TEXT
            )
        ''')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                price INTEGER,
                item_type TEXT,
                duration_days INTEGER
            )
        ''')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS user_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_id INTEGER,
                purchased_at TEXT,
                expires_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS clans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                description TEXT,
                owner_id INTEGER,
                created_at TEXT,
                balance INTEGER DEFAULT 0
            )
        ''')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS clan_members (
                clan_id INTEGER,
                user_id INTEGER,
                role TEXT DEFAULT 'member',
                joined_at TEXT,
                PRIMARY KEY (clan_id, user_id)
            )
        ''')
        
        await self.conn.execute('''
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
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS user_activity (
                user_id INTEGER,
                date TEXT,
                message_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date)
            )
        ''')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS duel_stats (
                user_id INTEGER PRIMARY KEY,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0
            )
        ''')
        
        # Новые таблицы для модерации
        await self.conn.execute('''
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
        
        await self.conn.execute('''
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
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS word_filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT UNIQUE,
                action TEXT,
                created_by INTEGER,
                created_at TEXT
            )
        ''')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS user_verification (
                user_id INTEGER PRIMARY KEY,
                captcha_text TEXT,
                attempts INTEGER DEFAULT 0,
                verified INTEGER DEFAULT 0,
                join_time TEXT
            )
        ''')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_stats (
                date TEXT PRIMARY KEY,
                message_count INTEGER DEFAULT 0,
                user_count INTEGER DEFAULT 0,
                new_users INTEGER DEFAULT 0
            )
        ''')
        
        # Инициализация новых систем
        await self.seasonal_system.init_seasonal_tables()
        await self.admin_system.init_admin_tables()
        
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
            await self.conn.execute('''
                INSERT OR IGNORE INTO shop_items (name, description, price, item_type, duration_days)
                VALUES (?, ?, ?, ?, ?)
            ''', item)
        
        await self.conn.commit()

    async def init_redis(self):
        try:
            redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
            self.redis_client = await redis.from_url(redis_url, decode_responses=True)
            await self.redis_client.ping()
            logging.info("Redis подключен успешно")
        except Exception as e:
            logging.warning(f"Redis не доступен: {e}. Используем in-memory кэш")
            self.redis_client = None

    async def init_scheduler(self):
        self.scheduler.add_job(
            self.recalculate_multipliers,
            CronTrigger(day_of_week=0, hour=0, minute=0),
            id='recalculate_multipliers'
        )
        
        self.scheduler.add_job(
            self.reset_weekly_activity,
            CronTrigger(day_of_week=0, hour=0, minute=0),
            id='reset_weekly_activity'
        )
        
        self.scheduler.add_job(
            self.process_message_queue,
            'interval',
            seconds=30,
            id='process_message_queue'
        )
        
        # Новые задачи
        self.scheduler.add_job(
            self.daily_stats_report,
            CronTrigger(hour=23, minute=59),
            id='daily_stats'
        )
        
        self.scheduler.add_job(
            self.cleanup_old_data,
            CronTrigger(hour=3, minute=0),
            id='cleanup'
        )
        
        # Сезонные задачи
        self.scheduler.add_job(
            self.seasonal_system.check_seasonal_events,
            'interval',
            hours=1,
            id='check_seasons'
        )
        
        self.scheduler.add_job(
            self.seasonal_system.end_current_season,
            CronTrigger(hour=0, minute=0),
            id='end_seasons'
        )
        
        self.scheduler.start()

    async def recalculate_multipliers(self):
        try:
            cursor = await self.conn.execute('''
                SELECT user_id, weekly_activity 
                FROM users 
                WHERE weekly_activity > 0
                ORDER BY weekly_activity DESC
                LIMIT 10
            ''')
            top_active_users = await cursor.fetchall()
            
            if top_active_users:
                activities = [activity for _, activity in top_active_users]
                median_activity = sorted(activities)[len(activities) // 2]
                
                activity_factor = min(1.5, max(0.5, median_activity / 100))
                
                self.hourly_multipliers = {
                    'peak': (20, 23, 0.8 * activity_factor),
                    'quiet': (4, 7, 1.3 * activity_factor),
                    'normal': (0, 24, 1.0 * activity_factor)
                }
                
                logging.info(f"Множители пересчитаны. Фактор активности: {activity_factor:.2f}")
        except Exception as e:
            logging.error(f"Ошибка при пересчете множителей: {e}")

    async def reset_weekly_activity(self):
        try:
            await self.conn.execute('UPDATE users SET weekly_activity = 0')
            await self.conn.commit()
            logging.info("Недельная активность сброшена")
        except Exception as e:
            logging.error(f"Ошибка при сбросе активности: {e}")

    async def process_message_queue(self):
        try:
            for _ in range(100):
                try:
                    user_id, message_data = self.message_queue.get_nowait()
                    await self.process_single_message(user_id, message_data)
                except asyncio.QueueEmpty:
                    break
        except Exception as e:
            logging.error(f"Ошибка при обработке очереди сообщений: {e}")

    async def process_single_message(self, user_id: int, message_data: dict):
        try:
            base_xp = message_data.get('xp_gain', 1)
            base_coins = message_data.get('coins_gain', random.randint(1, 3))
            
            # Применяем сезонные множители
            xp, coins = await self.seasonal_system.apply_seasonal_multipliers(base_xp, base_coins)
            
            await self.conn.execute('''
                UPDATE users 
                SET xp = xp + ?, balance = balance + ?, 
                    total_message_count = total_message_count + 1,
                    weekly_activity = weekly_activity + 1
                WHERE user_id = ?
            ''', (xp, coins, user_id))
            
            # Обновляем сезонную статистику
            await self.seasonal_system.update_user_season_stats(user_id, xp, coins)
            
            await self.conn.commit()
            
        except Exception as e:
            logging.error(f"Ошибка при обработке сообщения пользователя {user_id}: {e}")

    def setup_handlers(self):
        # Основные команды
        self.application.add_handler(CommandHandler("balance", self.balance))
        self.application.add_handler(CommandHandler("bal", self.balance))
        self.application.add_handler(CommandHandler("daily", self.daily))
        self.application.add_handler(CommandHandler("pay", self.pay))
        self.application.add_handler(CommandHandler("shop", self.shop))
        self.application.add_handler(CommandHandler("buy", self.buy_item))
        self.application.add_handler(CommandHandler("inventory", self.inventory))
        self.application.add_handler(CommandHandler("history", self.transaction_history))
        self.application.add_handler(CommandHandler("weekly_stats", self.weekly_stats))
        
        self.application.add_handler(CommandHandler("top", self.leaderboard))
        self.application.add_handler(CommandHandler("leaderboard", self.leaderboard))
        self.application.add_handler(CommandHandler("achievements", self.achievements))
        self.application.add_handler(CommandHandler("profile", self.profile))
        
        self.application.add_handler(CommandHandler("duel", self.duel))
        self.application.add_handler(CommandHandler("accept", self.accept_duel))
        self.application.add_handler(CommandHandler("decline", self.decline_duel))
        
        self.application.add_handler(CommandHandler("clan", self.clan))
        self.application.add_handler(CommandHandler("create_clan", self.create_clan))
        self.application.add_handler(CommandHandler("join_clan", self.join_clan))
        self.application.add_handler(CommandHandler("leave_clan", self.leave_clan))
        self.application.add_handler(CommandHandler("clan_info", self.clan_info))
        self.application.add_handler(CommandHandler("clan_deposit", self.clan_deposit))
        self.application.add_handler(CommandHandler("clan_withdraw", self.clan_withdraw))
        
        self.application.add_handler(CommandHandler("warn", self.warn))
        self.application.add_handler(CommandHandler("ban", self.ban))
        self.application.add_handler(CommandHandler("mute", self.mute))
        
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("admin", self.admin_panel))
        self.application.add_handler(CommandHandler("stats", self.stats))
        
        self.application.add_handler(CommandHandler("pinme", self.pinme))
        self.application.add_handler(CommandHandler("color", self.change_color))
        self.application.add_handler(CommandHandler("analyze", self.analyze_activity))
        
        # Новые команды
        self.application.add_handler(CommandHandler("report", self.report_user))
        self.application.add_handler(CommandHandler("add_filter", self.add_word_filter))
        self.application.add_handler(CommandHandler("remove_filter", self.remove_word_filter))
        self.application.add_handler(CommandHandler("filters", self.list_filters))
        self.application.add_handler(CommandHandler("clean", self.clean_messages))
        
        self.application.add_handler(CommandHandler("find", self.find_user))
        self.application.add_handler(CommandHandler("verify", self.manual_verify))
        self.application.add_handler(CommandHandler("status", self.bot_status))
        self.application.add_handler(CommandHandler("backup", self.create_backup))
        
        # Новые команды сезонов
        self.application.add_handler(CommandHandler("season_info", self.season_info))
        self.application.add_handler(CommandHandler("season_top", self.season_top))
        self.application.add_handler(CommandHandler("season_shop", self.season_shop))
        
        # Новые команды администрирования
        self.application.add_handler(CommandHandler("admin_edit", self.admin_system.admin_edit_user))
        self.application.add_handler(CommandHandler("admin_stats", self.admin_system.admin_system_stats))
        self.application.add_handler(CommandHandler("admin_economy", self.admin_system.admin_economy_control))
        self.application.add_handler(CommandHandler("admin_broadcast", self.admin_system.admin_broadcast))
        self.application.add_handler(CommandHandler("admin_search", self.admin_system.admin_user_search))
        self.application.add_handler(CommandHandler("admin_backup", self.admin_system.admin_system_backup))
        self.application.add_handler(CommandHandler("admin_logs", self.admin_logs))
        
        # Обработчики сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Новые обработчики
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self.auto_moderate
        ))
        
        self.application.add_handler(MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            self.handle_new_members
        ))

    # ===== ОСНОВНЫЕ ФУНКЦИИ =====

    async def balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_data = await self.get_user_data(user_id)
        
        if user_data:
            level, xp, balance = user_data[3], user_data[4], user_data[2]
            next_level_xp = self.calculate_required_xp(level + 1)
            progress_bar = self.create_progress_bar(xp - self.calculate_required_xp(level), 
                                                  next_level_xp - self.calculate_required_xp(level))
            
            current_hour = datetime.now().hour
            multiplier = self.get_current_multiplier(current_hour)
            multiplier_text = self.get_multiplier_text(multiplier, current_hour)
            
            active_boosts = await self.get_active_boosts(user_id)
            boost_text = ""
            if active_boosts:
                boost_text = "\n🔮 Активные бусты:\n" + "\n".join([f"  • {boost}" for boost in active_boosts])
            
            message = (
                f"👤 {update.effective_user.first_name}\n"
                f"🏅 Уровень {level} ({xp}/{next_level_xp} XP)\n"
                f"{progress_bar}\n"
                f"💰 Кошелек: {balance:,} коинов\n"
                f"⚡ {multiplier_text}"
                f"{boost_text}"
            )
            
            await update.message.reply_text(message)

    async def daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        now = datetime.now().isoformat()
        
        await self.ensure_user_exists(user_id, update.effective_user.username)
        
        cursor = await self.conn.execute(
            'SELECT last_daily, daily_streak FROM users WHERE user_id = ?', 
            (user_id,)
        )
        result = await cursor.fetchone()
        
        last_daily_str, streak = result
        current_streak = streak
        
        if last_daily_str:
            last_daily = datetime.fromisoformat(last_daily_str)
            time_diff = datetime.now() - last_daily
            
            if time_diff < timedelta(hours=24):
                next_daily = last_daily + timedelta(hours=24)
                wait_time = next_daily - datetime.now()
                hours = wait_time.seconds // 3600
                minutes = (wait_time.seconds % 3600) // 60
                
                await update.message.reply_text(
                    f"⏰ Следующий ежедневный бонус через {hours}ч {minutes}м!"
                )
                return
                
            elif time_diff < timedelta(hours=48):
                current_streak += 1
            else:
                current_streak = 1
        else:
            current_streak = 1
            
        base_reward = 50
        streak_bonus = current_streak * 10
        total_reward = base_reward + streak_bonus
        
        if await self.has_active_item(user_id, 'vip_status'):
            total_reward = int(total_reward * 1.5)
        
        await self.conn.execute('''
            UPDATE users 
            SET balance = balance + ?, last_daily = ?, daily_streak = ?
            WHERE user_id = ?
        ''', (total_reward, now, current_streak, user_id))
        
        await self.conn.execute('''
            INSERT INTO transactions (user_id, amount, type, timestamp, description)
            VALUES (?, ?, 'daily', ?, ?)
        ''', (user_id, total_reward, now, f"Ежедневный бонус (день {current_streak})"))
        
        await self.conn.commit()
        
        if current_streak == 1:
            await self.unlock_achievement(user_id, 'first_daily', update)
        
        next_reward = base_reward + (current_streak + 1) * 10
        await update.message.reply_text(
            f"🎉 День {current_streak}! Ваш ежедневный бонус: {total_reward} коинов! "
            f"Вернитесь завтра за {next_reward} коинов!"
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Расширенный обработчик сообщений"""
        await self.update_message_stats()
        
        user_id = update.effective_user.id
        message_text = update.message.text.strip()
        now = datetime.now().isoformat()
        
        await self.ensure_user_exists(user_id, update.effective_user.username)
        
        if (len(message_text) > 15 and 
            not message_text.startswith('/') and
            await self.can_receive_message_reward(user_id)):
            
            message_data = {
                'xp_gain': 1,
                'coins_gain': random.randint(1, 3),
                'timestamp': now,
                'text_length': len(message_text)
            }
            
            await self.message_queue.put((user_id, message_data))
            
            await self.conn.execute(
                'UPDATE users SET last_message = ? WHERE user_id = ?',
                (now, user_id)
            )
            
            today = datetime.now().strftime('%Y-%m-%d')
            await self.conn.execute('''
                INSERT INTO user_activity (user_id, date, message_count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, date) 
                DO UPDATE SET message_count = message_count + 1
            ''', (user_id, today))
            
            await self.conn.commit()
            
            await self.check_secret_achievements(user_id, update)

    async def pay(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("❌ Использование: /pay @username сумма")
            return
            
        target_username = context.args[0].lstrip('@')
        try:
            amount = int(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Сумма должна быть числом!")
            return
            
        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть положительной!")
            return
            
        from_user_id = update.effective_user.id
        
        cursor = await self.conn.execute(
            'SELECT user_id FROM users WHERE username = ?', 
            (target_username,)
        )
        target_user = await cursor.fetchone()
        
        if not target_user:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
            
        target_user_id = target_user[0]
        
        if from_user_id == target_user_id:
            await update.message.reply_text("❌ Нельзя переводить самому себе!")
            return
            
        tax_rate = 0.15 if amount > 1000 else 0.10
        tax = int(amount * tax_rate)
        total_deduction = amount + tax
        
        cursor = await self.conn.execute(
            'SELECT balance FROM users WHERE user_id = ?', 
            (from_user_id,)
        )
        sender_balance = (await cursor.fetchone())[0]
        
        if sender_balance < total_deduction:
            await update.message.reply_text("❌ Недостаточно средств для перевода!")
            return
            
        keyboard = [
            [
                InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_pay_{target_user_id}_{amount}"),
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_pay")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"💸 Вы хотите перевести пользователю @{target_username} {amount} коинов?\n"
            f"💳 Комиссия составит {tax} коинов.\n"
            f"💰 Итого с вашего счета будет списано {total_deduction} коинов.",
            reply_markup=reply_markup
        )

    async def shop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("🎁 Временные бенефиты", callback_data="shop_temporary")],
            [InlineKeyboardButton("⭐ Постоянные привилегии", callback_data="shop_permanent")],
            [InlineKeyboardButton("🔧 Дополнения", callback_data="shop_enhancements")],
            [InlineKeyboardButton("📦 Мой инвентарь", callback_data="inventory_view")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🛒 Добро пожаловать в магазин привилегий!\n"
            "Выберите категорию:",
            reply_markup=reply_markup
        )

    async def buy_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("❌ Использование: /buy ID_предмета")
            return
            
        try:
            item_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ ID предмета должен быть числом!")
            return
            
        user_id = update.effective_user.id
        
        cursor = await self.conn.execute(
            'SELECT id, name, description, price, item_type, duration_days FROM shop_items WHERE id = ?',
            (item_id,)
        )
        item = await cursor.fetchone()
        
        if not item:
            await update.message.reply_text("❌ Предмет не найден!")
            return
            
        item_id, name, description, price, item_type, duration_days = item
        
        cursor = await self.conn.execute(
            'SELECT balance FROM users WHERE user_id = ?',
            (user_id,)
        )
        balance = (await cursor.fetchone())[0]
        
        if balance < price:
            await update.message.reply_text("❌ Недостаточно средств для покупки!")
            return
            
        now = datetime.now()
        expires_at = (now + timedelta(days=duration_days)).isoformat() if duration_days > 0 else None
        
        await self.conn.execute('''
            INSERT INTO user_inventory (user_id, item_id, purchased_at, expires_at, is_active)
            VALUES (?, ?, ?, ?, 1)
        ''', (user_id, item_id, now.isoformat(), expires_at))
        
        await self.conn.execute(
            'UPDATE users SET balance = balance - ? WHERE user_id = ?',
            (price, user_id)
        )
        
        await self.conn.execute('''
            INSERT INTO transactions (user_id, amount, type, timestamp, description)
            VALUES (?, ?, 'purchase', ?, ?)
        ''', (user_id, -price, now.isoformat(), f"Покупка: {name}"))
        
        await self.conn.commit()
        
        await self.apply_item_effects(user_id, item_type, update)
        
        await self.check_purchase_achievements(user_id, update)
        
        await update.message.reply_text(
            f"🎉 Поздравляем с покупкой {name}!\n"
            f"💰 Списано: {price} коинов\n"
            f"📝 {description}"
        )

    async def inventory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        cursor = await self.conn.execute('''
            SELECT si.name, si.description, ui.purchased_at, ui.expires_at
            FROM user_inventory ui
            JOIN shop_items si ON ui.item_id = si.id
            WHERE ui.user_id = ? AND ui.is_active = 1
        ''', (user_id,))
        
        items = await cursor.fetchall()
        
        if not items:
            await update.message.reply_text("📦 Ваш инвентарь пуст!")
            return
            
        message = "📦 Ваш инвентарь:\n\n"
        for name, description, purchased_at, expires_at in items:
            purchased = datetime.fromisoformat(purchased_at)
            message += f"• {name}\n"
            message += f"  📝 {description}\n"
            message += f"  🛒 Куплен: {purchased.strftime('%d.%m.%Y')}\n"
            
            if expires_at:
                expires = datetime.fromisoformat(expires_at)
                days_left = (expires - datetime.now()).days
                message += f"  ⏰ Осталось: {days_left} дней\n"
            else:
                message += f"  ✅ Постоянный предмет\n"
            message += "\n"
            
        await update.message.reply_text(message)

    def calculate_required_xp(self, level: int) -> int:
        return int(100 * (level ** 1.5))

    async def check_level_up(self, user_id: int, update: Update):
        cursor = await self.conn.execute(
            'SELECT xp, level FROM users WHERE user_id = ?', 
            (user_id,)
        )
        xp, current_level = await cursor.fetchone()
        
        new_level = current_level
        while xp >= self.calculate_required_xp(new_level + 1):
            new_level += 1
            
        if new_level > current_level:
            await self.conn.execute(
                'UPDATE users SET level = ? WHERE user_id = ?', 
                (new_level, user_id)
            )
            await self.conn.commit()
            
            await self.send_level_up_message(update, user_id, new_level)
            
            if new_level >= 20:
                await self.unlock_achievement(user_id, 'veteran', update)

    async def send_level_up_message(self, update: Update, user_id: int, new_level: int):
        level_titles = {
            5: "Опытный",
            10: "Эксперт", 
            20: "Мастер",
            30: "Легенда",
            50: "Бог"
        }
        
        title = level_titles.get(new_level, "Новичок")
        
        message = (
            f"🎉 Поздравляем, {update.effective_user.first_name} "
            f"достиг(ла) уровня {new_level} - {title}!"
        )
        
        await update.message.reply_text(message)

    async def achievements(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        cursor = await self.conn.execute('''
            SELECT achievement_name, unlocked_at 
            FROM achievements 
            WHERE user_id = ?
        ''', (user_id,))
        
        unlocked = await cursor.fetchall()
        unlocked_dict = {name: unlocked_at for name, unlocked_at in unlocked}
        
        message = "🏆 Ваши достижения:\n\n"
        
        for achievement_id, achievement_data in self.achievements_list.items():
            name = achievement_data['name']
            description = achievement_data['description']
            is_secret = achievement_data['secret']
            
            if achievement_id in unlocked_dict:
                message += f"✅ {name}\n"
                message += f"   📝 {description}\n"
                unlocked_at = datetime.fromisoformat(unlocked_dict[achievement_id])
                message += f"   🕐 Разблокировано: {unlocked_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            else:
                if is_secret:
                    message += f"🔒 ???\n"
                    message += f"   📝 ???\n"
                    message += f"   ❓ Секретное достижение\n\n"
                else:
                    message += f"🔒 {name}\n"
                    message += f"   📝 {description}\n"
                    message += f"   🔒 Не разблокировано\n\n"
                
        await update.message.reply_text(message)

    async def leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        leaderboard_type = context.args[0] if context.args else "balance"
        
        if leaderboard_type == "level":
            cursor = await self.conn.execute('''
                SELECT username, level, xp 
                FROM users 
                ORDER BY level DESC, xp DESC 
                LIMIT 10
            ''')
            title = "🏆 Топ по уровням"
        else:
            cursor = await self.conn.execute('''
                SELECT username, balance, level 
                FROM users 
                ORDER BY balance DESC 
                LIMIT 10
            ''')
            title = "💰 Топ по балансу"
            
        top_users = await cursor.fetchall()
        
        if not top_users:
            await update.message.reply_text("📊 Пока нет данных для рейтинга!")
            return
            
        message = f"{title}:\n\n"
        
        for i, user_data in enumerate(top_users, 1):
            if leaderboard_type == "level":
                username, level, xp = user_data
                message += f"{i}. @{username} - Ур. {level} ({xp} XP)\n"
            else:
                username, balance, level = user_data
                message += f"{i}. @{username} - {balance:,} коинов (Ур. {level})\n"
                
        await update.message.reply_text(message)

    async def profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_data = await self.get_user_data(user_id)
        
        if not user_data:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
            
        username, balance, level, xp = user_data[1], user_data[2], user_data[3], user_data[4]
        next_level_xp = self.calculate_required_xp(level + 1)
        progress_bar = self.create_progress_bar(xp - self.calculate_required_xp(level), 
                                              next_level_xp - self.calculate_required_xp(level))
        
        clan_name = await self.get_user_clan(user_id)
        
        cursor = await self.conn.execute(
            'SELECT COUNT(*) FROM achievements WHERE user_id = ?',
            (user_id,)
        )
        achievements_count = (await cursor.fetchone())[0]
        
        message = (
            f"👤 Профиль пользователя @{username}\n"
            f"🏅 Уровень: {level}\n"
            f"📊 Опыт: {xp}/{next_level_xp}\n"
            f"{progress_bar}\n"
            f"💰 Баланс: {balance:,} коинов\n"
        )
        
        if clan_name:
            message += f"👥 Клан: {clan_name}\n"
            
        message += f"🏆 Достижения: {achievements_count}/{len(self.achievements_list)}"
        
        await update.message.reply_text(message)

    async def duel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("❌ Использование: /duel @username сумма")
            return
            
        target_username = context.args[0].lstrip('@')
        try:
            amount = int(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Сумма должна быть числом!")
            return
            
        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть положительной!")
            return
            
        challenger_id = update.effective_user.id
        
        cursor = await self.conn.execute(
            'SELECT user_id FROM users WHERE username = ?', 
            (target_username,)
        )
        target_user = await cursor.fetchone()
        
        if not target_user:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
            
        challenged_id = target_user[0]
        
        if challenger_id == challenged_id:
            await update.message.reply_text("❌ Нельзя вызвать на дуэль самого себя!")
            return
            
        cursor = await self.conn.execute(
            'SELECT balance FROM users WHERE user_id = ?', 
            (challenger_id,)
        )
        challenger_balance = (await cursor.fetchone())[0]
        
        if challenger_balance < amount:
            await update.message.reply_text("❌ Недостаточно средств для дуэли!")
            return
            
        now = datetime.now().isoformat()
        await self.conn.execute('''
            INSERT INTO duels (challenger_id, challenged_id, amount, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
        ''', (challenger_id, challenged_id, amount, now))
        
        await self.conn.commit()
        
        keyboard = [
            [
                InlineKeyboardButton("⚔️ Принять дуэль", callback_data=f"accept_duel_{challenger_id}"),
                InlineKeyboardButton("🏳️ Отказаться", callback_data=f"decline_duel_{challenger_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⚔️ {update.effective_user.first_name} вызывает на дуэль @{target_username}!\n"
            f"💰 Ставка: {amount} коинов\n"
            f"🎲 Победитель определяется случайным образом!",
            reply_markup=reply_markup
        )

    async def accept_duel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        cursor = await self.conn.execute('''
            SELECT id, challenger_id, amount 
            FROM duels 
            WHERE challenged_id = ? AND status = 'pending'
            ORDER BY created_at DESC 
            LIMIT 1
        ''', (user_id,))
        
        duel = await cursor.fetchone()
        
        if not duel:
            await update.message.reply_text("❌ Нет активных вызовов на дуэль!")
            return
            
        duel_id, challenger_id, amount = duel
        
        cursor = await self.conn.execute(
            'SELECT balance FROM users WHERE user_id = ?', 
            (user_id,)
        )
        challenged_balance = (await cursor.fetchone())[0]
        
        if challenged_balance < amount:
            await update.message.reply_text("❌ Недостаточно средств для принятия дуэли!")
            return
            
        cursor = await self.conn.execute(
            'SELECT balance FROM users WHERE user_id = ?', 
            (challenger_id,)
        )
        challenger_balance = (await cursor.fetchone())[0]
        
        if challenger_balance < amount:
            await update.message.reply_text("❌ У противника недостаточно средств!")
            return
            
        winner_id = random.choice([challenger_id, user_id])
        loser_id = challenger_id if winner_id == user_id else user_id
        
        await self.update_duel_stats(winner_id, loser_id)
        
        await self.conn.execute(
            'UPDATE users SET balance = balance - ? WHERE user_id = ?',
            (amount, loser_id)
        )
        await self.conn.execute(
            'UPDATE users SET balance = balance + ? WHERE user_id = ?',
            (amount, winner_id)
        )
        
        await self.conn.execute('''
            UPDATE duels SET status = 'finished', winner_id = ? WHERE id = ?
        ''', (winner_id, duel_id))
        
        now = datetime.now().isoformat()
        await self.conn.execute('''
            INSERT INTO transactions (user_id, amount, type, timestamp, description)
            VALUES (?, ?, 'duel', ?, ?)
        ''', (loser_id, -amount, now, f"Проигрыш в дуэли"))
        
        await self.conn.execute('''
            INSERT INTO transactions (user_id, amount, type, timestamp, description)
            VALUES (?, ?, 'duel', ?, ?)
        ''', (winner_id, amount, now, f"Победа в дуэли"))
        
        await self.conn.commit()
        
        cursor = await self.conn.execute(
            'SELECT username FROM users WHERE user_id IN (?, ?)',
            (challenger_id, user_id)
        )
        users = await cursor.fetchall()
        challenger_name = users[0][0]
        challenged_name = users[1][0]
        winner_name = challenger_name if winner_id == challenger_id else challenged_name
        
        if winner_id == user_id:
            await self.check_duel_achievements(user_id, update)
            await self.check_duel_streak(user_id, update)
        
        await update.message.reply_text(
            f"🎉 Дуэль завершена!\n"
            f"⚔️ {challenger_name} vs {challenged_name}\n"
            f"🏆 Победитель: @{winner_name}\n"
            f"💰 Выигрыш: {amount} коинов!"
        )

    async def decline_duel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        cursor = await self.conn.execute('''
            SELECT challenger_id FROM duels 
            WHERE challenged_id = ? AND status = 'pending'
            ORDER BY created_at DESC 
            LIMIT 1
        ''', (user_id,))
        
        duel = await cursor.fetchone()
        
        if not duel:
            await update.message.reply_text("❌ Нет активных вызовов на дуэль!")
            return
            
        challenger_id = duel[0]
        
        await self.conn.execute('''
            UPDATE duels SET status = 'declined' 
            WHERE challenged_id = ? AND status = 'pending'
        ''', (user_id,))
        
        await self.conn.commit()
        
        await update.message.reply_text("🏳️ Вы отказались от дуэли!")

    async def clan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("👥 Создать клан", callback_data="create_clan_dialog")],
            [InlineKeyboardButton("📊 Список кланов", callback_data="clans_list")],
            [InlineKeyboardButton("ℹ️ Мой клан", callback_data="my_clan_info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "👥 Система кланов:\n"
            "Объединяйтесь с друзьями для достижения общих целей!",
            reply_markup=reply_markup
        )

    async def create_clan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("❌ Использование: /create_clan название описание")
            return
            
        clan_name = context.args[0]
        description = ' '.join(context.args[1:])
        user_id = update.effective_user.id
        
        cursor = await self.conn.execute(
            'SELECT clan_id FROM users WHERE user_id = ?',
            (user_id,)
        )
        user_clan = await cursor.fetchone()
        
        if user_clan and user_clan[0]:
            await update.message.reply_text("❌ Вы уже состоите в клане!")
            return
            
        creation_cost = 1000
        cursor = await self.conn.execute(
            'SELECT balance FROM users WHERE user_id = ?',
            (user_id,)
        )
        balance = (await cursor.fetchone())[0]
        
        if balance < creation_cost:
            await update.message.reply_text(f"❌ Недостаточно средств! Нужно {creation_cost} коинов.")
            return
            
        try:
            now = datetime.now().isoformat()
            await self.conn.execute('''
                INSERT INTO clans (name, description, owner_id, created_at)
                VALUES (?, ?, ?, ?)
            ''', (clan_name, description, user_id, now))
            
            cursor = await self.conn.execute(
                'SELECT id FROM clans WHERE name = ?',
                (clan_name,)
            )
            clan_id = (await cursor.fetchone())[0]
            
            await self.conn.execute('''
                INSERT INTO clan_members (clan_id, user_id, role, joined_at)
                VALUES (?, ?, 'owner', ?)
            ''', (clan_id, user_id, now))
            
            await self.conn.execute(
                'UPDATE users SET clan_id = ? WHERE user_id = ?',
                (clan_id, user_id)
            )
            
            await self.conn.execute(
                'UPDATE users SET balance = balance - ? WHERE user_id = ?',
                (creation_cost, user_id)
            )
            
            await self.conn.commit()
            
            await update.message.reply_text(
                f"🎉 Клан '{clan_name}' успешно создан!\n"
                f"📝 {description}\n"
                f"💰 Списано: {creation_cost} коинов"
            )
            
        except sqlite3.IntegrityError:
            await update.message.reply_text("❌ Клан с таким названием уже существует!")

    async def clan_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        cursor = await self.conn.execute('''
            SELECT c.name, c.description, c.balance, c.owner_id,
                   (SELECT COUNT(*) FROM clan_members WHERE clan_id = c.id) as member_count
            FROM clans c
            JOIN users u ON u.clan_id = c.id
            WHERE u.user_id = ?
        ''', (user_id,))
        
        clan_info = await cursor.fetchone()
        
        if not clan_info:
            await update.message.reply_text("❌ Вы не состоите в клане!")
            return
            
        name, description, balance, owner_id, member_count = clan_info
        
        cursor = await self.conn.execute('''
            SELECT u.username, cm.role
            FROM clan_members cm
            JOIN users u ON cm.user_id = u.user_id
            WHERE cm.clan_id = (SELECT clan_id FROM users WHERE user_id = ?)
            ORDER BY 
                CASE cm.role 
                    WHEN 'owner' THEN 1
                    WHEN 'admin' THEN 2
                    ELSE 3 
                END,
                cm.joined_at
        ''', (user_id,))
        
        members = await cursor.fetchall()
        
        message = (
            f"👥 Клан: {name}\n"
            f"📝 Описание: {description}\n"
            f"💰 Казна: {balance} коинов\n"
            f"👥 Участников: {member_count}\n\n"
            f"📋 Состав клана:\n"
        )
        
        for username, role in members:
            role_icon = "👑" if role == "owner" else "⭐" if role == "admin" else "👤"
            message += f"{role_icon} @{username} - {role}\n"
            
        await update.message.reply_text(message)

    async def warn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.is_moderator(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
            
        if not context.args:
            await update.message.reply_text("❌ Использование: /warn @username причина")
            return
            
        target_username = context.args[0].lstrip('@')
        reason = ' '.join(context.args[1:]) if len(context.args) > 1 else "Не указана"
        
        cursor = await self.conn.execute(
            'SELECT user_id, warns FROM users WHERE username = ?', 
            (target_username,)
        )
        target_user = await cursor.fetchone()
        
        if not target_user:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
            
        user_id, current_warns = target_user
        new_warns = current_warns + 1
        
        await self.conn.execute(
            'UPDATE users SET warns = ? WHERE user_id = ?', 
            (new_warns, user_id)
        )
        await self.conn.commit()
        
        warn_message = (
            f"⚠️ Вам вынесено предупреждение в чате {update.effective_chat.title}.\n"
            f"📝 Причина: {reason}\n"
            f"🔢 У вас {new_warns}/3 предупреждений.\n"
            f"При достижении 3-х — мут 24ч."
        )
        
        try:
            await context.bot.send_message(chat_id=user_id, text=warn_message)
        except:
            await update.message.reply_text("❌ Не удалось отправить предупреждение в ЛС")
            
        await update.message.reply_text(
            f"✅ Пользователю @{target_username} выдано предупреждение. "
            f"Текущее количество: {new_warns}/3"
        )
        
        if new_warns >= 3:
            await self.mute_user(update, context, user_id, 24 * 60 * 60)

    async def mute_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, duration: int):
        try:
            until_date = datetime.now() + timedelta(seconds=duration)
            await context.bot.restrict_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False
                ),
                until_date=until_date
            )
            
            await self.conn.execute(
                'UPDATE users SET warns = 0 WHERE user_id = ?',
                (user_id,)
            )
            await self.conn.commit()
            
            await update.message.reply_text(
                f"🔇 Пользователь получил мут на {duration // 3600} часов."
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при муте: {e}")

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
            
        keyboard = [
            [InlineKeyboardButton("💰 Выдать коины", callback_data="admin_give_coins")],
            [InlineKeyboardButton("⭐ Выдать XP", callback_data="admin_give_xp")],
            [InlineKeyboardButton("🎯 Установить уровень", callback_data="admin_set_level")],
            [InlineKeyboardButton("📊 Статистика бота", callback_data="admin_stats")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "👑 Панель администратора:\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        cursor = await self.conn.execute('SELECT COUNT(*) FROM users')
        total_users = (await cursor.fetchone())[0]
        
        cursor = await self.conn.execute('SELECT SUM(balance) FROM users')
        total_coins = (await cursor.fetchone())[0] or 0
        
        cursor = await self.conn.execute('SELECT COUNT(*) FROM clans')
        total_clans = (await cursor.fetchone())[0]
        
        cursor = await self.conn.execute('SELECT COUNT(*) FROM duels WHERE status = "finished"')
        total_duels = (await cursor.fetchone())[0]
        
        message = (
            f"📊 Статистика бота:\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"💰 Всего коинов в системе: {total_coins:,}\n"
            f"👥 Кланов: {total_clans}\n"
            f"⚔️ Проведено дуэлей: {total_duels}\n"
        )
        
        await update.message.reply_text(message)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("👤 Обычные команды", callback_data="help_user")],
            [InlineKeyboardButton("🛡️ Команды модератора", callback_data="help_moderator")],
            [InlineKeyboardButton("👑 Команды владельца", callback_data="help_owner")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🤖 Список доступных команд:\n"
            "Выберите категорию:",
            reply_markup=reply_markup
        )

    async def pinme(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not await self.has_active_item(user_id, 'pin_message'):
            await update.message.reply_text("❌ У вас нет привилегии закрепления сообщений!")
            return
            
        if not update.message.reply_to_message:
            await update.message.reply_text("❌ Ответьте на сообщение, которое хотите закрепить!")
            return
            
        try:
            message_id = update.message.reply_to_message.message_id
            await context.bot.pin_chat_message(
                chat_id=update.effective_chat.id,
                message_id=message_id,
                disable_notification=True
            )
            
            await self.deactivate_item(user_id, 'pin_message')
            
            await update.message.reply_text("📌 Сообщение закреплено!")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Не удалось закрепить сообщение: {e}")

    async def change_color(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not await self.has_active_item(user_id, 'color_change'):
            await update.message.reply_text("❌ У вас нет привилегии смены цвета ника!")
            return
            
        if not context.args:
            colors_text = "Доступные цвета:\n" + "\n".join([f"{emoji} {color}" for color, emoji in self.name_colors.items()])
            await update.message.reply_text(
                f"{colors_text}\n\nИспользование: /color [название_цвета]"
            )
            return
            
        color_name = context.args[0].lower()
        
        if color_name not in self.name_colors:
            await update.message.reply_text("❌ Неизвестный цвет! Используйте /color для списка доступных цветов.")
            return
            
        try:
            await self.conn.execute(
                'UPDATE users SET name_color = ? WHERE user_id = ?',
                (color_name, user_id)
            )
            await self.conn.commit()
            
            new_name = f"{self.name_colors[color_name]} {update.effective_user.first_name}"
            try:
                await context.bot.set_chat_administrator_custom_title(
                    chat_id=update.effective_chat.id,
                    user_id=user_id,
                    custom_title=new_name
                )
            except:
                pass
            
            await update.message.reply_text(f"🎨 Цвет ника изменен на {color_name}!")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при смене цвета: {e}")

    async def analyze_activity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        cursor = await self.conn.execute('''
            SELECT total_message_count, weekly_activity, created_at
            FROM users WHERE user_id = ?
        ''', (user_id,))
        
        user_stats = await cursor.fetchall()
        
        if not user_stats:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
            
        total_messages, weekly_activity, created_at = user_stats
        
        cursor = await self.conn.execute('''
            SELECT date, message_count 
            FROM user_activity 
            WHERE user_id = ? 
            ORDER BY date DESC 
            LIMIT 7
        ''', (user_id,))
        
        last_week_activity = await cursor.fetchall()
        
        dates = []
        counts = []
        for date, count in reversed(last_week_activity):
            dates.append(date[-5:])
            counts.append(count)
        
        if counts:
            plt.figure(figsize=(10, 4))
            plt.plot(dates, counts, marker='o', linewidth=2, markersize=8)
            plt.title('Активность за последнюю неделю')
            plt.xlabel('Дата')
            plt.ylabel('Сообщений')
            plt.grid(True, alpha=0.3)
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=80, bbox_inches='tight')
            buf.seek(0)
            plt.close()
            
            await update.message.reply_photo(
                photo=buf,
                caption=(
                    f"📊 Анализ активности:\n"
                    f"💬 Всего сообщений: {total_messages}\n"
                    f"📈 Активность за неделю: {weekly_activity}\n"
                    f"📅 В системе с: {datetime.fromisoformat(created_at).strftime('%d.%m.%Y')}"
                )
            )
        else:
            await update.message.reply_text(
                f"📊 Анализ активности:\n"
                f"💬 Всего сообщений: {total_messages}\n"
                f"📈 Активность за неделю: {weekly_activity}\n"
                f"📅 В системе с: {datetime.fromisoformat(created_at).strftime('%d.%m.%Y')}\n"
                f"ℹ️ Недостаточно данных для построения графика"
            )

    async def weekly_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        cursor = await self.conn.execute('''
            SELECT username, weekly_activity, level 
            FROM users 
            WHERE weekly_activity > 0 
            ORDER BY weekly_activity DESC 
            LIMIT 10
        ''')
        
        top_users = await cursor.fetchall()
        
        if not top_users:
            await update.message.reply_text("📊 На этой неделе еще нет активности!")
            return
            
        message = "🏆 Топ активности за неделю:\n\n"
        
        for i, (username, activity, level) in enumerate(top_users, 1):
            message += f"{i}. @{username} - {activity} сообщ. (Ур. {level})\n"
            
        cursor = await self.conn.execute('SELECT SUM(weekly_activity) FROM users')
        total_activity = (await cursor.fetchone())[0] or 0
        
        cursor = await self.conn.execute('SELECT COUNT(*) FROM users WHERE weekly_activity > 0')
        active_users = (await cursor.fetchone())[0]
        
        message += f"\n📈 Общая статистика:\n"
        message += f"💬 Всего сообщений: {total_activity}\n"
        message += f"👥 Активных пользователей: {active_users}\n"
        message += f"📊 Средняя активность: {total_activity // active_users if active_users > 0 else 0} сообщ./пользователь"
        
        await update.message.reply_text(message)

    # ===== НОВЫЕ ФУНКЦИИ МОДЕРАЦИИ =====

    async def auto_moderate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Автоматическая модерация сообщений"""
        user_id = update.effective_user.id
        message_text = update.message.text.lower()
        message_id = update.message.message_id
        chat_id = update.effective_chat.id
        
        # Проверка на спам
        if await self.detect_spam(user_id, message_text, update):
            return
            
        # Проверка запрещенных слов
        if await self.check_bad_words(message_text, user_id, update):
            try:
                await update.message.delete()
                await update.message.reply_text(
                    f"⚠️ Сообщение удалено из-за нарушения правил. "
                    f"Пользователь {update.effective_user.mention_html()} получил предупреждение.",
                    parse_mode='HTML'
                )
                return
            except Exception as e:
                logging.error(f"Ошибка удаления сообщения: {e}")

    async def detect_spam(self, user_id: int, text: str, update: Update) -> bool:
        """Обнаружение спама"""
        now = datetime.now()
        
        if user_id not in self.spam_detection:
            self.spam_detection[user_id] = {
                'messages': [],
                'warnings': 0
            }
        
        user_data = self.spam_detection[user_id]
        user_data['messages'].append(now)
        
        # Очистка старых сообщений
        user_data['messages'] = [
            msg_time for msg_time in user_data['messages']
            if (now - msg_time).seconds < 60
        ]
        
        # Проверка лимита сообщений
        if len(user_data['messages']) > 5:  # 5 сообщений в минуту
            user_data['warnings'] += 1
            
            if user_data['warnings'] >= 3:
                await self.mute_user(update, update.context, user_id, 300)  # 5 минут
                await update.message.reply_text(
                    f"🔇 Пользователь {update.effective_user.mention_html()} "
                    f"получил мут на 5 минут за спам.",
                    parse_mode='HTML'
                )
                user_data['warnings'] = 0
                user_data['messages'] = []
                return True
            else:
                await update.message.reply_text(
                    f"⚠️ {update.effective_user.mention_html()}, "
                    f"прекратите спам! Предупреждение {user_data['warnings']}/3",
                    parse_mode='HTML'
                )
                return True
        
        return False

    async def check_bad_words(self, text: str, user_id: int, update: Update) -> bool:
        """Проверка на запрещенные слова"""
        cursor = await self.conn.execute('SELECT word, action FROM word_filters')
        filters = await cursor.fetchall()
        
        for word, action in filters:
            if word.lower() in text:
                await self.conn.execute('''
                    INSERT INTO moderation_logs 
                    (user_id, action, reason, timestamp, message_text)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, 'auto_moderate', f'Нарушение фильтра: {word}', 
                     datetime.now().isoformat(), text))
                
                await self.conn.execute(
                    'UPDATE users SET warns = warns + 1 WHERE user_id = ?',
                    (user_id,)
                )
                
                cursor = await self.conn.execute(
                    'SELECT warns FROM users WHERE user_id = ?',
                    (user_id,)
                )
                warns = (await cursor.fetchone())[0]
                
                if warns >= 3:
                    await self.mute_user(update, update.context, user_id, 1440)  # 24 часа
                
                await self.conn.commit()
                return True
        return False

    async def report_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Система жалоб"""
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "❌ Использование: /report @username причина\n"
                "Пример: /report @username оскорбление в чате"
            )
            return
        
        if not update.message.reply_to_message:
            await update.message.reply_text(
                "❌ Пожалуйста, ответьте на сообщение нарушителя для создания жалобы с контекстом."
            )
            return
        
        target_username = context.args[0].lstrip('@')
        reason = ' '.join(context.args[1:])
        
        cursor = await self.conn.execute(
            'SELECT user_id FROM users WHERE username = ?',
            (target_username,)
        )
        target_user = await cursor.fetchone()
        
        if not target_user:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
        
        reported_user_id = target_user[0]
        reporter_id = update.effective_user.id
        
        # Сохраняем жалобу с контекстом
        context_message = update.message.reply_to_message.text or "Сообщение с медиа-файлом"
        
        await self.conn.execute('''
            INSERT INTO reports 
            (reporter_id, reported_user_id, reason, message_id, chat_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (reporter_id, reported_user_id, reason, 
              update.message.reply_to_message.message_id,
              update.effective_chat.id,
              datetime.now().isoformat()))
        
        await self.conn.commit()
        
        # Уведомляем модераторов
        moderators = await self.get_moderators()
        for mod_id in moderators:
            try:
                await context.bot.send_message(
                    chat_id=mod_id,
                    text=f"🚨 Новая жалоба!\n"
                         f"👤 Нарушитель: @{target_username}\n"
                         f"📝 Причина: {reason}\n"
                         f"👮 Жалобу подал: @{update.effective_user.username}\n"
                         f"💬 Контекст: {context_message[:200]}...\n"
                         f"🆔 ID сообщения: {update.message.reply_to_message.message_id}"
                )
            except Exception as e:
                logging.error(f"Не удалось уведомить модератора {mod_id}: {e}")
        
        await update.message.reply_text(
            "✅ Жалоба отправлена модераторам. Спасибо за бдительность!"
        )

    async def add_word_filter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Добавление слова в фильтр"""
        if not await self.is_moderator(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        if not context.args:
            await update.message.reply_text("❌ Использование: /add_filter слово действие")
            return
        
        word = context.args[0].lower()
        action = context.args[1] if len(context.args) > 1 else 'warn'
        
        try:
            await self.conn.execute('''
                INSERT INTO word_filters (word, action, created_by, created_at)
                VALUES (?, ?, ?, ?)
            ''', (word, action, update.effective_user.id, datetime.now().isoformat()))
            
            await self.conn.commit()
            await update.message.reply_text(f"✅ Фильтр для слова '{word}' добавлен!")
            
        except sqlite3.IntegrityError:
            await update.message.reply_text("❌ Это слово уже есть в фильтре!")

    async def list_filters(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Список фильтров"""
        cursor = await self.conn.execute('''
            SELECT wf.word, wf.action, u.username 
            FROM word_filters wf
            LEFT JOIN users u ON wf.created_by = u.user_id
        ''')
        filters = await cursor.fetchall()
        
        if not filters:
            await update.message.reply_text("📝 Список фильтров пуст.")
            return
        
        message = "📝 Список фильтров:\n\n"
        for word, action, creator in filters:
            message += f"• {word} → {action} (добавил: @{creator})\n"
        
        await update.message.reply_text(message)

    async def clean_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Очистка сообщений"""
        if not await self.is_moderator(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        count = int(context.args[0]) if context.args else 10
        count = min(count, 100)  # Лимит
        
        try:
            # Получаем ID сообщений для удаления
            messages_to_delete = []
            async for message in update.effective_chat.get_messages(limit=count + 1):
                if message.message_id != update.message.message_id:
                    messages_to_delete.append(message.message_id)
            
            # Удаляем сообщения
            for msg_id in messages_to_delete:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=msg_id
                    )
                    await asyncio.sleep(0.1)  # Защита от лимитов
                except Exception as e:
                    logging.error(f"Ошибка удаления сообщения {msg_id}: {e}")
            
            report_msg = await update.message.reply_text(
                f"🧹 Удалено {len(messages_to_delete)} сообщений"
            )
            
            # Удаляем отчет через 5 секунд
            await asyncio.sleep(5)
            await report_msg.delete()
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка очистки: {e}")

    async def handle_new_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка новых участников"""
        for new_member in update.message.new_chat_members:
            if new_member.id == context.bot.id:
                continue
                
            await self.start_verification(new_member, update, context)

    async def start_verification(self, user, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запуск верификации"""
        # Ограничиваем права
        try:
            await context.bot.restrict_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user.id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False
                )
            )
        except Exception as e:
            logging.error(f"Ошибка ограничения прав: {e}")

        # Генерируем капчу
        captcha_text = self.generate_captcha()
        
        # Сохраняем в базу
        await self.conn.execute('''
            INSERT OR REPLACE INTO user_verification 
            (user_id, captcha_text, join_time)
            VALUES (?, ?, ?)
        ''', (user.id, captcha_text, datetime.now().isoformat()))
        await self.conn.commit()

        # Создаем изображение капчи
        captcha_image = await self.generate_captcha_image(captcha_text)
        
        # Отправляем капчу
        keyboard = [[InlineKeyboardButton("🔐 Пройти верификацию", 
                                        url=f"t.me/{(await context.bot.get_me()).username}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_msg = await update.message.reply_photo(
            photo=captcha_image,
            caption=f"👋 Добро пожаловать, {user.mention_html()}!\n"
                   f"🔐 Для доступа к чату пройдите верификацию в ЛС бота.\n"
                   f"📝 Отправьте боту текст с картинки.",
            parse_mode='HTML',
            reply_markup=reply_markup
        )

        # Отправляем капчу в ЛС
        try:
            await context.bot.send_photo(
                chat_id=user.id,
                photo=captcha_image,
                caption=f"🔐 Верификация для чата {update.effective_chat.title}\n"
                       f"📝 Введите текст с картинки:"
            )
        except Exception as e:
            logging.error(f"Не удалось отправить капчу в ЛС: {e}")
            await welcome_msg.edit_caption(
                f"❌ Не удалось отправить вам сообщение. "
                f"Разрешите ЛС с ботом и напишите /verify"
            )

    async def generate_captcha_image(self, text: str) -> io.BytesIO:
        """Генерация изображения капчи"""
        width, height = 200, 80
        image = Image.new('RGB', (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except:
            font = ImageFont.load_default()
        
        # Добавляем шум
        for _ in range(100):
            x, y = random.randint(0, width), random.randint(0, height)
            draw.point((x, y), fill=(random.randint(0, 255), 
                                   random.randint(0, 255), 
                                   random.randint(0, 255)))
        
        # Рисуем текст
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        draw.text((x, y), text, font=font, fill=(0, 0, 0))
        
        # Сохраняем в буфер
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        buf.seek(0)
        return buf

    def generate_captcha(self) -> str:
        """Генерация текста капчи"""
        characters = string.ascii_letters + string.digits
        return ''.join(random.choice(characters) for _ in range(6))

    async def manual_verify(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ручная верификация"""
        user_id = update.effective_user.id
        
        cursor = await self.conn.execute('''
            SELECT captcha_text, attempts FROM user_verification 
            WHERE user_id = ? AND verified = 0
        ''', (user_id,))
        result = await cursor.fetchone()
        
        if not result:
            await update.message.reply_text("❌ У вас нет активной верификации.")
            return
        
        captcha_text, attempts = result
        
        if not context.args:
            # Показываем текущую капчу
            captcha_image = await self.generate_captcha_image(captcha_text)
            await update.message.reply_photo(
                photo=captcha_image,
                caption=f"📝 Введите текст с картинки:\n"
                       f"❌ Неверных попыток: {attempts}/3\n"
                       f"💡 Использование: /verify текст"
            )
            return
        
        user_input = context.args[0]
        
        if user_input.upper() == captcha_text.upper():
            # Успешная верификация
            await self.conn.execute('''
                UPDATE user_verification SET verified = 1 WHERE user_id = ?
            ''', (user_id,))
            await self.conn.commit()
            
            # Восстанавливаем права
            try:
                await context.bot.restrict_chat_member(
                    chat_id=update.effective_chat.id,  # Нужно сохранять chat_id
                    user_id=user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True
                    )
                )
            except Exception as e:
                logging.error(f"Ошибка восстановления прав: {e}")
            
            await update.message.reply_text(
                "✅ Верификация пройдена! Добро пожаловать в чат!"
            )
        else:
            # Неверная капча
            attempts += 1
            await self.conn.execute('''
                UPDATE user_verification SET attempts = ? WHERE user_id = ?
            ''', (attempts, user_id))
            await self.conn.commit()
            
            if attempts >= 3:
                # Кик за превышение попыток
                try:
                    await context.bot.ban_chat_member(
                        chat_id=update.effective_chat.id,
                        user_id=user_id
                    )
                    await update.message.reply_text(
                        "❌ Превышено количество попыток. Вы были исключены из чата."
                    )
                except Exception as e:
                    logging.error(f"Ошибка кика: {e}")
            else:
                await update.message.reply_text(
                    f"❌ Неверный код. Попыток осталось: {3 - attempts}"
                )

    async def find_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Умный поиск пользователей"""
        if not context.args:
            await update.message.reply_text("❌ Использование: /find имя_пользователя")
            return
        
        search_term = ' '.join(context.args)
        
        cursor = await self.conn.execute('''
            SELECT user_id, username, level, balance 
            FROM users 
            WHERE username LIKE ? OR user_id = ?
            ORDER BY 
                CASE 
                    WHEN username = ? THEN 1
                    WHEN username LIKE ? THEN 2
                    ELSE 3
                END
            LIMIT 10
        ''', (f'%{search_term}%', search_term, search_term, f'{search_term}%'))
        
        users = await cursor.fetchall()
        
        if not users:
            await update.message.reply_text("❌ Пользователи не найдены.")
            return
        
        message = "🔍 Результаты поиска:\n\n"
        for user_id, username, level, balance in users:
            message += f"👤 @{username} (ID: {user_id})\n"
            message += f"🏅 Уровень: {level} | 💰 Баланс: {balance:,}\n\n"
        
        await update.message.reply_text(message)

    async def bot_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Статус бота и мониторинг"""
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        # Статистика базы данных
        cursor = await self.conn.execute('SELECT COUNT(*) FROM users')
        total_users = (await cursor.fetchone())[0]
        
        cursor = await self.conn.execute('SELECT COUNT(*) FROM clans')
        total_clans = (await cursor.fetchone())[0]
        
        cursor = await self.conn.execute('SELECT COUNT(*) FROM duels WHERE status = "finished"')
        total_duels = (await cursor.fetchone())[0]
        
        # Использование памяти
        memory_usage = psutil.Process().memory_info().rss / 1024 / 1024
        
        # Время работы
        uptime = datetime.now() - self.start_time
        days = uptime.days
        hours = uptime.seconds // 3600
        minutes = (uptime.seconds % 3600) // 60
        
        # Статистика сообщений
        today_messages = self.message_stats['today']
        total_messages = self.message_stats['total']
        
        message = (
            "🤖 Статус бота:\n\n"
            f"⏰ Время работы: {days}д {hours}ч {minutes}м\n"
            f"💾 Память: {memory_usage:.1f} MB\n"
            f"👥 Пользователей: {total_users}\n"
            f"👥 Кланов: {total_clans}\n"
            f"⚔️ Дуэлей: {total_duels}\n"
            f"💬 Сообщений сегодня: {today_messages}\n"
            f"📊 Всего сообщений: {total_messages}\n"
            f"📈 Активных чатов: {len(self.application.chat_data or {})}"
        )
        
        await update.message.reply_text(message)

    async def create_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Создание резервной копии"""
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        try:
            backup_dir = Path("backups")
            backup_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_dir / f"backup_{timestamp}.zip"
            
            with zipfile.ZipFile(backup_file, 'w') as zipf:
                # Архивируем базу данных
                zipf.write('bot_database.db', 'bot_database.db')
                
                # Архивируем конфигурационные файлы
                for config_file in ['bad_words.json']:
                    if Path(config_file).exists():
                        zipf.write(config_file, config_file)
            
            await update.message.reply_document(
                document=backup_file,
                caption=f"📦 Резервная копия от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
            
            # Удаляем старые бэкапы (оставляем 5 последних)
            backup_files = sorted(backup_dir.glob("backup_*.zip"))
            for old_backup in backup_files[:-5]:
                old_backup.unlink()
                
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка создания бэкапа: {e}")

    async def get_moderators(self) -> List[int]:
        """Получение списка модераторов"""
        cursor = await self.conn.execute('''
            SELECT user_id FROM users 
            WHERE level >= 10 OR user_id IN (
                SELECT user_id FROM user_inventory ui
                JOIN shop_items si ON ui.item_id = si.id
                WHERE si.item_type = 'vip_status' AND ui.is_active = 1
            )
        ''')
        moderators = [row[0] for row in await cursor.fetchall()]
        return moderators

    async def update_message_stats(self):
        """Обновление статистики сообщений"""
        self.message_stats['total'] += 1
        self.message_stats['today'] += 1
        
        # Сброс дневной статистики
        if datetime.now().date() > self.message_stats['last_reset'].date():
            self.message_stats['today'] = 0
            self.message_stats['last_reset'] = datetime.now()

    async def daily_stats_report(self):
        """Ежедневный отчет статистики"""
        cursor = await self.conn.execute('''
            SELECT COUNT(*) FROM users WHERE date(created_at) = date('now')
        ''')
        new_users = (await cursor.fetchone())[0]
        
        cursor = await self.conn.execute('SELECT SUM(weekly_activity) FROM users')
        daily_activity = (await cursor.fetchone())[0] or 0
        
        # Сохраняем статистику за день
        await self.conn.execute('''
            INSERT OR REPLACE INTO chat_stats (date, message_count, new_users)
            VALUES (date('now'), ?, ?)
        ''', (daily_activity, new_users))
        await self.conn.commit()
        
        logging.info(f"Daily stats: {new_users} new users, {daily_activity} messages")

    async def cleanup_old_data(self):
        """Очистка старых данных"""
        # Удаляем старые сообщения активности (старше 30 дней)
        await self.conn.execute('''
            DELETE FROM user_activity 
            WHERE date < date('now', '-30 days')
        ''')
        
        # Удаляем старые транзакции (старше 90 дней)
        await self.conn.execute('''
            DELETE FROM transactions 
            WHERE date(timestamp) < date('now', '-90 days')
        ''')
        
        # Удаляем просроченные предметы
        await self.conn.execute('''
            UPDATE user_inventory 
            SET is_active = 0 
            WHERE expires_at < datetime('now')
        ''')
        
        await self.conn.commit()
        logging.info("Old data cleanup completed")

    # ===== НОВЫЕ ФУНКЦИИ СЕЗОНОВ =====

    async def season_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Информация о текущем сезоне"""
        season = await self.seasonal_system.get_current_season()
        
        if not season:
            await update.message.reply_text(
                "📅 В данный момент нет активных сезонов.\n"
                "Следите за анонсами следующих событий!"
            )
            return
        
        days_left = (season.end_date - datetime.now()).days
        progress = (datetime.now() - season.start_date).days / \
                  (season.end_date - season.start_date).days * 100
        
        message = (
            f"🎉 **Текущий сезон: {season.name}**\n\n"
            f"📅 Период: {season.start_date.strftime('%d.%m')} - {season.end_date.strftime('%d.%m.%Y')}\n"
            f"⏰ Осталось: {days_left} дней\n"
            f"📊 Прогресс: {progress:.1f}%\n\n"
            f"✨ **Бонусы сезона:**\n"
            f"📈 Опыт: x{season.xp_multiplier}\n"
            f"💰 Коины: x{season.coin_multiplier}\n\n"
            f"🎁 Особые предметы доступны в /season_shop"
        )
        
        await update.message.reply_text(message, parse_mode='Markdown')

    async def season_top(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Топ игроков текущего сезона"""
        season = await self.seasonal_system.get_current_season()
        
        if not season:
            await update.message.reply_text("❌ Сейчас нет активного сезона!")
            return
        
        top_players = await self.seasonal_system.get_season_leaderboard(season.id, 10)
        
        if not top_players:
            await update.message.reply_text("📊 В этом сезоне еще нет активности!")
            return
        
        message = f"🏆 **Топ игроков сезона {season.name}:**\n\n"
        
        for i, (username, xp_earned, coins_earned, rank) in enumerate(top_players, 1):
            message += f"{i}. @{username} - {xp_earned} XP, {coins_earned} коинов\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')

    async def season_shop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Магазин сезонных предметов"""
        season = await self.seasonal_system.get_current_season()
        
        if not season:
            await update.message.reply_text("❌ Сезонный магазин доступен только во время событий!")
            return
        
        cursor = await self.conn.execute('''
            SELECT id, name, description, price, limited_quantity, sold_count
            FROM seasonal_shop_items 
            WHERE season_type = ?
        ''', (season.type.value,))
        
        items = await cursor.fetchall()
        
        if not items:
            await update.message.reply_text("❌ В сезонном магазине пока нет предметов!")
            return
        
        message = f"🎁 **Сезонный магазин: {season.name}**\n\n"
        keyboard = []
        
        for item_id, name, description, price, limit, sold in items:
            available = limit - sold if limit else "∞"
            message += f"🆔 {item_id}. {name}\n"
            message += f"📝 {description}\n"
            message += f"💰 Цена: {price} коинов\n"
            message += f"🎯 Доступно: {available} шт.\n\n"
            
            if limit and available > 0:
                keyboard.append([InlineKeyboardButton(
                    f"Купить {name} - {price} коинов",
                    callback_data=f"buy_seasonal_{item_id}"
                )])
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup)

    async def admin_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Просмотр логов администрации"""
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        days = int(context.args[0]) if context.args else 7
        logs = await self.admin_system.get_admin_logs(days)
        
        if not logs:
            await update.message.reply_text(f"📝 Логов за последние {days} дней нет.")
            return
        
        message = f"📋 **Логи администрации ({days} дней):**\n\n"
        
        for action, target_type, old_val, new_val, timestamp, reason, admin in logs:
            time = datetime.fromisoformat(timestamp).strftime('%d.%m %H:%M')
            message += f"🕐 {time} | 👤 {admin}\n"
            message += f"🔧 {action} | 🎯 {target_type}\n"
            if old_val and new_val:
                message += f"📊 {old_val} → {new_val}\n"
            message += f"📝 {reason}\n\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====

    async def get_user_data(self, user_id: int):
        cursor = await self.conn.execute('''
            SELECT user_id, username, balance, level, xp, 
                   last_daily, daily_streak, last_message 
            FROM users WHERE user_id = ?
        ''', (user_id,))
        return await cursor.fetchone()

    async def ensure_user_exists(self, user_id: int, username: str):
        cursor = await self.conn.execute(
            'SELECT 1 FROM users WHERE user_id = ?',
            (user_id,)
        )
        if not await cursor.fetchone():
            await self.conn.execute('''
                INSERT INTO users (user_id, username, created_at)
                VALUES (?, ?, ?)
            ''', (user_id, username, datetime.now().isoformat()))
            await self.conn.commit()

    async def can_receive_message_reward(self, user_id: int) -> bool:
        cursor = await self.conn.execute(
            'SELECT last_message FROM users WHERE user_id = ?', 
            (user_id,)
        )
        result = await cursor.fetchone()
        
        if not result or not result[0]:
            return True
            
        last_message = datetime.fromisoformat(result[0])
        return (datetime.now() - last_message) > timedelta(seconds=60)

    def get_current_multiplier(self, current_hour: int) -> float:
        for period, (start, end, multiplier) in self.hourly_multipliers.items():
            if start <= current_hour < end:
                return multiplier
        return 1.0

    def get_multiplier_text(self, multiplier: float, hour: int) -> str:
        if multiplier < 1.0:
            return f"Текущий множитель активности: x{multiplier} (час пик)"
        elif multiplier > 1.0:
            return f"Текущий множитель активности: x{multiplier} (ночное время)"
        else:
            return f"Текущий множитель активности: x{multiplier} (нормальное время)"

    def create_progress_bar(self, current: int, total: int, length: int = 10) -> str:
        if total == 0:
            return "[░░░░░░░░░░] 0%"
        progress = min(current / total, 1.0)
        filled = int(length * progress)
        bar = "█" * filled + "░" * (length - filled)
        return f"[{bar}] {progress*100:.1f}%"

    async def is_moderator(self, update: Update) -> bool:
        try:
            chat_member = await update.effective_chat.get_member(update.effective_user.id)
            return chat_member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
        except:
            return False

    async def is_owner(self, update: Update) -> bool:
        try:
            chat_member = await update.effective_chat.get_member(update.effective_user.id)
            return chat_member.status == ChatMember.OWNER
        except:
            return update.effective_user.id == 123456789  # Замените на ваш ID

    async def has_active_item(self, user_id: int, item_type: str) -> bool:
        cursor = await self.conn.execute('''
            SELECT 1 FROM user_inventory ui
            JOIN shop_items si ON ui.item_id = si.id
            WHERE ui.user_id = ? AND si.item_type = ? AND ui.is_active = 1
            AND (ui.expires_at IS NULL OR ui.expires_at > ?)
        ''', (user_id, item_type, datetime.now().isoformat()))
        return await cursor.fetchone() is not None

    async def get_active_boosts(self, user_id: int) -> List[str]:
        boosts = []
        if await self.has_active_item(user_id, 'xp_boost'):
            boosts.append("🚀 Буст опыта x1.5")
        if await self.has_active_item(user_id, 'vip_status'):
            boosts.append("👑 VIP статус")
        return boosts

    async def apply_item_effects(self, user_id: int, item_type: str, update: Update):
        if item_type == 'color_change':
            pass
        elif item_type == 'pin_message':
            pass

    async def get_user_clan(self, user_id: int) -> Optional[str]:
        cursor = await self.conn.execute('''
            SELECT c.name FROM clans c
            JOIN users u ON u.clan_id = c.id
            WHERE u.user_id = ?
        ''', (user_id,))
        result = await cursor.fetchone()
        return result[0] if result else None

    async def unlock_achievement(self, user_id: int, achievement_id: str, update: Update):
        cursor = await self.conn.execute('''
            SELECT 1 FROM achievements 
            WHERE user_id = ? AND achievement_name = ?
        ''', (user_id, achievement_id))
        
        if await cursor.fetchone():
            return
            
        achievement_data = self.achievements_list[achievement_id]
        await self.conn.execute('''
            INSERT INTO achievements (user_id, achievement_name, unlocked_at)
            VALUES (?, ?, ?)
        ''', (user_id, achievement_id, datetime.now().isoformat()))
        
        await self.conn.commit()
        
        await update.message.reply_text(
            f"🎉 Новое достижение разблокировано!\n"
            f"🏆 {achievement_data['name']}\n"
            f"📝 {achievement_data['description']}"
        )

    async def check_message_achievements(self, user_id: int, update: Update):
        cursor = await self.conn.execute('''
            SELECT COUNT(*) FROM transactions 
            WHERE user_id = ? AND type = 'message'
        ''', (user_id,))
        
        message_count = (await cursor.fetchone())[0]
        
        if message_count >= 100:
            await self.unlock_achievement(user_id, 'social', update)

    async def check_purchase_achievements(self, user_id: int, update: Update):
        cursor = await self.conn.execute('''
            SELECT COUNT(*) FROM transactions 
            WHERE user_id = ? AND type = 'purchase'
        ''', (user_id,))
        
        purchase_count = (await cursor.fetchone())[0]
        
        if purchase_count >= 5:
            await self.unlock_achievement(user_id, 'collector', update)

    async def check_duel_achievements(self, user_id: int, update: Update):
        cursor = await self.conn.execute('''
            SELECT COUNT(*) FROM duels 
            WHERE winner_id = ? AND status = 'finished'
        ''', (user_id,))
        
        duel_wins = (await cursor.fetchone())[0]
        
        if duel_wins >= 5:
            await self.unlock_achievement(user_id, 'gambler', update)

    async def check_balance_achievements(self, user_id: int, update: Update):
        cursor = await self.conn.execute(
            'SELECT balance FROM users WHERE user_id = ?',
            (user_id,)
        )
        
        balance = (await cursor.fetchone())[0]
        
        if balance >= 10000:
            await self.unlock_achievement(user_id, 'rich', update)

    async def check_secret_achievements(self, user_id: int, update: Update):
        cursor = await self.conn.execute(
            'SELECT total_message_count FROM users WHERE user_id = ?',
            (user_id,)
        )
        total_messages = (await cursor.fetchone())[0]
        
        if total_messages >= 500:
            await self.unlock_achievement(user_id, 'no_life', update)
        
        current_hour = datetime.now().hour
        if 4 <= current_hour <= 6:
            cursor = await self.conn.execute(
                'SELECT last_daily FROM users WHERE user_id = ?',
                (user_id,)
            )
            last_daily = await cursor.fetchone()
            if last_daily and last_daily[0]:
                last_daily_time = datetime.fromisoformat(last_daily[0])
                if last_daily_time.date() == datetime.now().date():
                    await self.unlock_achievement(user_id, 'early_bird', update)
        
        cursor = await self.conn.execute('''
            SELECT SUM(amount) FROM transactions 
            WHERE user_id = ? AND type = 'transfer_out' AND amount < 0
        ''', (user_id,))
        
        total_donated = abs((await cursor.fetchone())[0] or 0)
        if total_donated >= 5000:
            await self.unlock_achievement(user_id, 'philanthropist', update)

    async def check_duel_streak(self, user_id: int, update: Update):
        cursor = await self.conn.execute('''
            SELECT current_streak, best_streak 
            FROM duel_stats 
            WHERE user_id = ?
        ''', (user_id,))
        
        result = await cursor.fetchone()
        if result:
            current_streak, best_streak = result
            if current_streak >= 3:
                await self.unlock_achievement(user_id, 'lucky', update)

    async def update_duel_stats(self, winner_id: int, loser_id: int):
        cursor = await self.conn.execute('''
            INSERT OR IGNORE INTO duel_stats (user_id, wins, losses, current_streak, best_streak)
            VALUES (?, 0, 0, 0, 0)
        ''', (winner_id,))
        
        await self.conn.execute('''
            UPDATE duel_stats 
            SET wins = wins + 1, current_streak = current_streak + 1,
                best_streak = MAX(best_streak, current_streak + 1)
            WHERE user_id = ?
        ''', (winner_id,))
        
        cursor = await self.conn.execute('''
            INSERT OR IGNORE INTO duel_stats (user_id, wins, losses, current_streak, best_streak)
            VALUES (?, 0, 0, 0, 0)
        ''', (loser_id,))
        
        await self.conn.execute('''
            UPDATE duel_stats 
            SET losses = losses + 1, current_streak = 0
            WHERE user_id = ?
        ''', (loser_id,))

    async def deactivate_item(self, user_id: int, item_type: str):
        await self.conn.execute('''
            UPDATE user_inventory 
            SET is_active = 0 
            WHERE user_id = ? AND item_id IN (
                SELECT id FROM shop_items WHERE item_type = ?
            )
        ''', (user_id, item_type))
        await self.conn.commit()

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith('shop_'):
            await self.handle_shop_navigation(query, data)
        elif data.startswith('confirm_pay_'):
            await self.handle_payment_confirmation(query, data)
        elif data == 'cancel_pay':
            await query.edit_message_text("❌ Перевод отменен")
        elif data.startswith('help_'):
            await self.handle_help_buttons(query, data)
        elif data.startswith('admin_'):
            await self.handle_admin_buttons(query, data)
        elif data.startswith('accept_duel_'):
            await self.handle_duel_acceptance(query, data)
        elif data.startswith('decline_duel_'):
            await self.handle_duel_decline(query, data)
        elif data == 'inventory_view':
            await self.show_inventory(query)
        elif data.startswith('buy_seasonal_'):
            await self.handle_seasonal_purchase(query, data)

    async def handle_shop_navigation(self, query, data):
        if data == "shop_temporary":
            await self.show_temporary_items(query)
        elif data == "shop_permanent":
            await self.show_permanent_items(query)
        elif data == "shop_enhancements":
            await self.show_enhancement_items(query)

    async def show_temporary_items(self, query):
        cursor = await self.conn.execute('''
            SELECT id, name, description, price, duration_days 
            FROM shop_items 
            WHERE duration_days > 0
        ''')
        items = await cursor.fetchall()
        
        message = "🎁 Временные бенефиты:\n\n"
        keyboard = []
        
        for item_id, name, description, price, duration in items:
            message += f"🆔 {item_id}. {name}\n"
            message += f"   📝 {description}\n"
            message += f"   💰 Цена: {price} коинов\n"
            message += f"   ⏰ Длительность: {duration} дней\n\n"
            
            keyboard.append([InlineKeyboardButton(
                f"Купить {name} - {price} коиins", 
                callback_data=f"buy_{item_id}"
            )])
            
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_shop")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)

    async def handle_payment_confirmation(self, query, data):
        try:
            parts = data.split('_')
            target_user_id = int(parts[2])
            amount = int(parts[3])
            
            from_user_id = query.from_user.id
            
            tax_rate = 0.15 if amount > 1000 else 0.10
            tax = int(amount * tax_rate)
            total_deduction = amount + tax
            
            cursor = await self.conn.execute(
                'SELECT balance FROM users WHERE user_id = ?', 
                (from_user_id,)
            )
            sender_balance = (await cursor.fetchone())[0]
            
            if sender_balance < total_deduction:
                await query.edit_message_text("❌ Недостаточно средств для перевода!")
                return
                
            await self.conn.execute(
                'UPDATE users SET balance = balance - ? WHERE user_id = ?',
                (total_deduction, from_user_id)
            )
            await self.conn.execute(
                'UPDATE users SET balance = balance + ? WHERE user_id = ?',
                (amount, target_user_id)
            )
            
            now = datetime.now().isoformat()
            await self.conn.execute('''
                INSERT INTO transactions (user_id, amount, type, timestamp, description)
                VALUES (?, ?, 'transfer_out', ?, ?)
            ''', (from_user_id, -total_deduction, now, f"Перевод пользователю {target_user_id}"))
            
            await self.conn.execute('''
                INSERT INTO transactions (user_id, amount, type, timestamp, description)
                VALUES (?, ?, 'transfer_in', ?, ?)
            ''', (target_user_id, amount, now, f"Перевод от пользователя {from_user_id}"))
            
            await self.conn.commit()
            
            await self.check_balance_achievements(from_user_id, query)
            await self.unlock_achievement(from_user_id, 'trader', query)
            
            cursor = await self.conn.execute(
                'SELECT username FROM users WHERE user_id = ?',
                (target_user_id,)
            )
            target_username = (await cursor.fetchone())[0]
            
            await query.edit_message_text(
                f"✅ Перевод выполнен!\n"
                f"💸 Получатель: @{target_username}\n"
                f"💰 Сумма: {amount} коинов\n"
                f"💳 Комиссия: {tax} коинов\n"
                f"📊 Итого списано: {total_deduction} коинов"
            )
            
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при переводе: {e}")

    async def handle_help_buttons(self, query, data):
        if data == "help_user":
            commands = """
👤 Команды для пользователей:
/balance - Ваш баланс и уровень
/daily - Ежедневный бонус
/shop - Магазин привилегий
/buy - Купить предмет из магазина
/inventory - Ваш инвентарь
/top - Таблица лидеров
/achievements - Ваши достижения
/profile - Ваш профиль
/pay - Перевод коинов
/duel - Вызвать на дуэль
/accept - Принять дуэль
/decline - Отказаться от дуэли
/clan - Система кланов
/create_clan - Создать клан
/clan_info - Информация о клане
/season_info - Информация о сезоне
/season_top - Топ сезона
/season_shop - Сезонный магазин
            """
            await query.edit_message_text(commands)
            
        elif data in ["help_moderator", "help_owner"]:
            message = "🛡️ Для просмотра команд модератора/владельца, пожалуйста, напишите боту в личные сообщения!"
            await query.edit_message_text(message)

    async def handle_duel_acceptance(self, query, data):
        challenger_id = int(data.split('_')[2])
        await self.accept_duel_callback(query, challenger_id)

    async def handle_duel_decline(self, query, data):
        challenger_id = int(data.split('_')[2])
        await self.decline_duel_callback(query, challenger_id)

    async def accept_duel_callback(self, query, challenger_id):
        user_id = query.from_user.id
        await query.edit_message_text("⚔️ Вы приняли дуэль! Результат будет определен случайным образом.")

    async def decline_duel_callback(self, query, challenger_id):
        await query.edit_message_text("🏳️ Вы отказались от дуэли!")

    async def show_inventory(self, query):
        user_id = query.from_user.id
        await self.inventory_callback(query, user_id)

    async def inventory_callback(self, query, user_id):
        cursor = await self.conn.execute('''
            SELECT si.name, si.description, ui.purchased_at, ui.expires_at
            FROM user_inventory ui
            JOIN shop_items si ON ui.item_id = si.id
            WHERE ui.user_id = ? AND ui.is_active = 1
        ''', (user_id,))
        
        items = await cursor.fetchall()
        
        if not items:
            await query.edit_message_text("📦 Ваш инвентарь пуст!")
            return
            
        message = "📦 Ваш инвентарь:\n\n"
        for name, description, purchased_at, expires_at in items:
            purchased = datetime.fromisoformat(purchased_at)
            message += f"• {name}\n"
            message += f"  📝 {description}\n"
            message += f"  🛒 Куплен: {purchased.strftime('%d.%m.%Y')}\n"
            
            if expires_at:
                expires = datetime.fromisoformat(expires_at)
                days_left = (expires - datetime.now()).days
                message += f"  ⏰ Осталось: {days_left} дней\n"
            else:
                message += f"  ✅ Постоянный предмет\n"
            message += "\n"
            
        await query.edit_message_text(message)

    async def handle_seasonal_purchase(self, query, data):
        """Обработка покупки сезонных предметов"""
        try:
            item_id = int(data.split('_')[2])
            user_id = query.from_user.id
            
            cursor = await self.conn.execute('''
                SELECT name, description, price, limited_quantity, sold_count
                FROM seasonal_shop_items 
                WHERE id = ?
            ''', (item_id,))
            
            item = await cursor.fetchone()
            
            if not item:
                await query.answer("❌ Предмет не найден!", show_alert=True)
                return
                
            name, description, price, limit, sold = item
            
            # Проверяем лимит
            if limit and sold >= limit:
                await query.answer("❌ Этот предмет закончился!", show_alert=True)
                return
            
            # Проверяем баланс
            cursor = await self.conn.execute(
                'SELECT balance FROM users WHERE user_id = ?',
                (user_id,)
            )
            balance = (await cursor.fetchone())[0]
            
            if balance < price:
                await query.answer("❌ Недостаточно средств!", show_alert=True)
                return
            
            # Совершаем покупку
            await self.conn.execute(
                'UPDATE users SET balance = balance - ? WHERE user_id = ?',
                (price, user_id)
            )
            
            await self.conn.execute('''
                UPDATE seasonal_shop_items 
                SET sold_count = sold_count + 1 
                WHERE id = ?
            ''', (item_id,))
            
            now = datetime.now().isoformat()
            await self.conn.execute('''
                INSERT INTO transactions (user_id, amount, type, timestamp, description)
                VALUES (?, ?, 'seasonal_purchase', ?, ?)
            ''', (user_id, -price, now, f"Сезонная покупка: {name}"))
            
            await self.conn.commit()
            
            await query.answer(f"✅ Вы купили {name}!", show_alert=True)
            await query.edit_message_text(
                f"🎉 Поздравляем с покупкой {name}!\n"
                f"💰 Списано: {price} коинов\n"
                f"📝 {description}"
            )
            
        except Exception as e:
            await query.answer(f"❌ Ошибка покупки: {e}", show_alert=True)

    async def transaction_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        limit = min(int(context.args[0]) if context.args else 10, 20)
        
        cursor = await self.conn.execute('''
            SELECT amount, type, timestamp, description 
            FROM transactions 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (user_id, limit))
        
        transactions = await cursor.fetchall()
        
        if not transactions:
            await update.message.reply_text("📊 История транзакций пуста!")
            return
            
        message = "📊 История транзакций:\n\n"
        total_income = 0
        total_expense = 0
        
        for amount, trans_type, timestamp, description in transactions:
            date = datetime.fromisoformat(timestamp).strftime('%d.%m.%Y %H:%M')
            icon = "⬆️" if amount > 0 else "⬇️"
            color = "🟢" if amount > 0 else "🔴"
            
            message += f"{color} {date}\n"
            message += f"{icon} {description}: {amount:+,} коинов\n\n"
            
            if amount > 0:
                total_income += amount
            else:
                total_expense += abs(amount)
                
        message += f"📈 Всего пополнений: {total_income:,} коинов\n"
        message += f"📉 Всего списаний: {total_expense:,} коинов\n"
        message += f"💰 Чистый доход: {total_income - total_expense:,} коинов"
        
        await update.message.reply_text(message)

    async def ban(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
            
        if not context.args:
            await update.message.reply_text("❌ Использование: /ban @username причина")
            return
            
        target_username = context.args[0].lstrip('@')
        reason = ' '.join(context.args[1:]) if len(context.args) > 1 else "Не указана"
        
        cursor = await self.conn.execute(
            'SELECT user_id FROM users WHERE username = ?', 
            (target_username,)
        )
        target_user = await cursor.fetchone()
        
        if not target_user:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
            
        user_id = target_user[0]
        
        try:
            await context.bot.ban_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user_id
            )
            
            await self.conn.execute(
                'UPDATE users SET is_banned = 1 WHERE user_id = ?',
                (user_id,)
            )
            await self.conn.commit()
            
            await update.message.reply_text(
                f"🔨 Пользователь @{target_username} забанен.\n"
                f"📝 Причина: {reason}"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при бане: {e}")

    async def mute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.is_moderator(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
            
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("❌ Использование: /mute @username время_в_минутах причина")
            return
            
        target_username = context.args[0].lstrip('@')
        try:
            duration_minutes = int(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Время должно быть числом!")
            return
            
        reason = ' '.join(context.args[2:]) if len(context.args) > 2 else "Не указана"
        
        cursor = await self.conn.execute(
            'SELECT user_id FROM users WHERE username = ?', 
            (target_username,)
        )
        target_user = await cursor.fetchone()
        
        if not target_user:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
            
        user_id = target_user[0]
        duration_seconds = duration_minutes * 60
        
        await self.mute_user(update, context, user_id, duration_seconds)

    async def handle_admin_buttons(self, query, data):
        if data == "admin_stats":
            await self.show_admin_stats(query)

    async def show_admin_stats(self, query):
        cursor = await self.conn.execute('SELECT COUNT(*) FROM users')
        total_users = (await cursor.fetchone())[0]
        
        cursor = await self.conn.execute('SELECT SUM(balance) FROM users')
        total_coins = (await cursor.fetchone())[0] or 0
        
        cursor = await self.conn.execute('SELECT COUNT(*) FROM clans')
        total_clans = (await cursor.fetchone())[0]
        
        message = (
            f"👑 Статистика администратора:\n"
            f"👥 Пользователей: {total_users}\n"
            f"💰 Всего коинов: {total_coins:,}\n"
            f"👥 Кланов: {total_clans}\n"
        )
        
        await query.edit_message_text(message)

    async def run(self):
        await self.init_database()
        await self.init_redis()
        await self.init_scheduler()
        self.setup_handlers()
        
        await self.application.run_polling()

    async def close(self):
        if self.redis_client:
            await self.redis_client.close()
        if self.scheduler:
            self.scheduler.shutdown()
        await self.conn.close()
