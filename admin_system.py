import logging
import sqlite3
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Any
import matplotlib.pyplot as plt
import io
import shutil

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

class AdminSystem:
    def __init__(self, db_connection):
        self.conn = db_connection
        self.audit_log = []
    
    async def init_admin_tables(self):
        """Инициализация таблиц администрирования"""
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_type TEXT,
                target_id INTEGER,
                old_value TEXT,
                new_value TEXT,
                timestamp TEXT,
                reason TEXT
            )
        ''')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                description TEXT,
                updated_by INTEGER,
                updated_at TEXT
            )
        ''')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS economy_settings (
                parameter TEXT PRIMARY KEY,
                value REAL,
                min_value REAL,
                max_value REAL,
                description TEXT
            )
        ''')
        
        # Инициализация настроек экономики
        default_settings = [
            ('daily_base_reward', 50, 10, 200, 'Базовая награда за ежедневный бонус'),
            ('daily_streak_bonus', 10, 5, 50, 'Бонус за серию ежедневных бонусов'),
            ('message_min_reward', 1, 0, 5, 'Минимальная награда за сообщение'),
            ('message_max_reward', 3, 1, 10, 'Максимальная награда за сообщение'),
            ('xp_per_message', 1, 0, 5, 'Опыт за сообщение'),
            ('tax_rate_small', 0.1, 0, 0.3, 'Налог на мелкие переводы'),
            ('tax_rate_large', 0.15, 0.1, 0.5, 'Налог на крупные переводы'),
            ('duel_tax', 0.05, 0, 0.2, 'Налог на дуэли'),
            ('clan_creation_cost', 1000, 500, 5000, 'Стоимость создания клана')
        ]
        
        for setting in default_settings:
            await self.conn.execute('''
                INSERT OR IGNORE INTO economy_settings 
                (parameter, value, min_value, max_value, description)
                VALUES (?, ?, ?, ?, ?)
            ''', setting)
        
        await self.conn.commit()

    async def admin_edit_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Редактирование данных пользователя"""
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        if len(context.args) < 4:
            await update.message.reply_text(
                "❌ Использование: /admin_edit @username поле значение причина\n"
                "📝 Поля: balance, xp, level, warns, daily_streak\n"
                "💡 Пример: /admin_edit @user balance 1000 \"Награда за активность\""
            )
            return
        
        target_username = context.args[0].lstrip('@')
        field = context.args[1].lower()
        new_value = context.args[2]
        reason = ' '.join(context.args[3:])
        
        # Получаем пользователя
        cursor = await self.conn.execute(
            'SELECT user_id, username FROM users WHERE username = ?',
            (target_username,)
        )
        target_user = await cursor.fetchone()
        
        if not target_user:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
        
        user_id, username = target_user
        
        # Получаем старое значение
        cursor = await self.conn.execute(
            f'SELECT {field} FROM users WHERE user_id = ?',
            (user_id,)
        )
        old_value = (await cursor.fetchone())[0]
        
        try:
            # Обновляем значение
            if field in ['balance', 'xp', 'level', 'warns', 'daily_streak']:
                new_value = int(new_value)
            
            await self.conn.execute(
                f'UPDATE users SET {field} = ? WHERE user_id = ?',
                (new_value, user_id)
            )
            
            # Логируем действие
            await self.log_admin_action(
                update.effective_user.id,
                f'edit_user_{field}',
                'user',
                user_id,
                str(old_value),
                str(new_value),
                reason
            )
            
            await self.conn.commit()
            
            await update.message.reply_text(
                f"✅ Пользователь @{username} обновлен!\n"
                f"📊 Поле: {field}\n"
                f"🔄 С {old_value} на {new_value}\n"
                f"📝 Причина: {reason}"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка обновления: {e}")

    async def admin_system_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Расширенная статистика системы"""
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        # Базовая статистика
        cursor = await self.conn.execute('SELECT COUNT(*) FROM users')
        total_users = (await cursor.fetchone())[0]
        
        cursor = await self.conn.execute('SELECT SUM(balance) FROM users')
        total_coins = (await cursor.fetchone())[0] or 0
        
        cursor = await self.conn.execute('SELECT AVG(balance) FROM users')
        avg_balance = (await cursor.fetchone())[0] or 0
        
        cursor = await self.conn.execute('SELECT COUNT(*) FROM users WHERE balance > 1000')
        rich_users = (await cursor.fetchone())[0]
        
        # Активность
        cursor = await self.conn.execute('''
            SELECT COUNT(*) FROM users 
            WHERE last_message > datetime('now', '-1 day')
        ''')
        active_today = (await cursor.fetchone())[0]
        
        cursor = await self.conn.execute('''
            SELECT COUNT(*) FROM users 
            WHERE last_message > datetime('now', '-7 days')
        ''')
        active_week = (await cursor.fetchone())[0]
        
        # Экономика
        cursor = await self.conn.execute('''
            SELECT type, COUNT(*), SUM(amount) 
            FROM transactions 
            WHERE timestamp > datetime('now', '-1 day')
            GROUP BY type
        ''')
        today_transactions = await cursor.fetchall()
        
        message = (
            "🤖 **Расширенная статистика системы**\n\n"
            f"👥 **Пользователи:** {total_users}\n"
            f"💰 **Общая экономика:** {total_coins:,} коинов\n"
            f"📊 **Средний баланс:** {avg_balance:.0f} коинов\n"
            f"🎩 **Состоятельных:** {rich_users} пользователей\n\n"
            f"📈 **Активность:**\n"
            f"• За сегодня: {active_today} пользователей\n"
            f"• За неделю: {active_week} пользователей\n\n"
            f"💸 **Транзакции за сегодня:**\n"
        )
        
        for trans_type, count, amount in today_transactions:
            message += f"• {trans_type}: {count} операций, {amount or 0:,} коинов\n"
        
        # График активности
        cursor = await self.conn.execute('''
            SELECT date(timestamp), COUNT(*) 
            FROM transactions 
            WHERE timestamp > datetime('now', '-30 days')
            GROUP BY date(timestamp)
            ORDER BY date(timestamp)
        ''')
        activity_data = await cursor.fetchall()
        
        if activity_data:
            dates = [row[0][5:] for row in activity_data]  # MM-DD
            counts = [row[1] for row in activity_data]
            
            plt.figure(figsize=(12, 4))
            plt.plot(dates, counts, marker='o', linewidth=2)
            plt.title('Активность за 30 дней')
            plt.xticks(rotation=45)
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            await update.message.reply_photo(
                photo=buf,
                caption=message,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(message, parse_mode='Markdown')

    async def admin_economy_control(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Управление экономическими параметрами"""
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        if not context.args:
            # Показать текущие настройки
            cursor = await self.conn.execute('''
                SELECT parameter, value, min_value, max_value, description 
                FROM economy_settings
            ''')
            settings = await cursor.fetchall()
            
            message = "⚙️ **Текущие экономические настройки:**\n\n"
            for param, value, min_val, max_val, desc in settings:
                message += f"**{param}**: {value}\n"
                message += f"📝 {desc}\n"
                message += f"📊 Диапазон: {min_val} - {max_val}\n\n"
            
            message += "💡 Использование: /admin_economy параметр новое_значение"
            await update.message.reply_text(message, parse_mode='Markdown')
            return
        
        if len(context.args) < 2:
            await update.message.reply_text("❌ Использование: /admin_economy параметр значение")
            return
        
        parameter = context.args[0]
        try:
            new_value = float(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Значение должно быть числом!")
            return
        
        # Проверяем существование параметра и границы
        cursor = await self.conn.execute('''
            SELECT min_value, max_value FROM economy_settings WHERE parameter = ?
        ''', (parameter,))
        result = await cursor.fetchone()
        
        if not result:
            await update.message.reply_text("❌ Неизвестный параметр!")
            return
        
        min_val, max_val = result
        
        if not (min_val <= new_value <= max_val):
            await update.message.reply_text(f"❌ Значение должно быть в диапазоне {min_val} - {max_val}!")
            return
        
        # Обновляем параметр
        await self.conn.execute('''
            UPDATE economy_settings SET value = ? WHERE parameter = ?
        ''', (new_value, parameter))
        
        await self.log_admin_action(
            update.effective_user.id,
            'economy_update',
            'system',
            None,
            str(result),
            str(new_value),
            f"Изменение параметра {parameter}"
        )
        
        await self.conn.commit()
        
        await update.message.reply_text(
            f"✅ Экономический параметр обновлен!\n"
            f"📊 **{parameter}**: {new_value}\n"
            f"📝 Теперь используется новое значение."
        )

    async def admin_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Массовая рассылка сообщений"""
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        if not context.args:
            await update.message.reply_text(
                "❌ Использование: /admin_broadcast сообщение\n"
                "💡 Пример: /admin_broadcast Важное обновление системы!"
            )
            return
        
        message = ' '.join(context.args)
        confirmed_message = (
            f"📢 **Массовая рассылка**\n\n{message}\n\n"
            f"⚠️ Вы уверены что хотите отправить это сообщение всем пользователям?"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, отправить", callback_data="broadcast_confirm"),
                InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            confirmed_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def admin_user_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Расширенный поиск пользователей"""
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        if not context.args:
            await update.message.reply_text(
                "❌ Использование: /admin_search критерий значение\n"
                "📝 Критерии: balance_gt, balance_lt, level_gt, level_lt, warns_gt, active\n"
                "💡 Пример: /admin_search balance_gt 1000"
            )
            return
        
        if len(context.args) < 2:
            await update.message.reply_text("❌ Недостаточно аргументов!")
            return
        
        criterion = context.args[0]
        value = context.args[1]
        
        query = "SELECT user_id, username, balance, level, warns, last_message FROM users WHERE "
        params = []
        
        if criterion == 'balance_gt':
            query += "balance > ?"
            params.append(int(value))
        elif criterion == 'balance_lt':
            query += "balance < ?" 
            params.append(int(value))
        elif criterion == 'level_gt':
            query += "level > ?"
            params.append(int(value))
        elif criterion == 'level_lt':
            query += "level < ?"
            params.append(int(value))
        elif criterion == 'warns_gt':
            query += "warns > ?"
            params.append(int(value))
        elif criterion == 'active':
            query += "last_message > datetime('now', '-7 days')"
        else:
            await update.message.reply_text("❌ Неизвестный критерий!")
            return
        
        query += " ORDER BY balance DESC LIMIT 50"
        
        cursor = await self.conn.execute(query, params)
        users = await cursor.fetchall()
        
        if not users:
            await update.message.reply_text("❌ Пользователи не найдены!")
            return
        
        message = f"🔍 **Результаты поиска ({criterion}: {value}):**\n\n"
        
        for user_id, username, balance, level, warns, last_message in users:
            last_active = "недавно" if last_message and \
                (datetime.now() - datetime.fromisoformat(last_message)).days < 1 else "давно"
            
            message += (
                f"👤 @{username} (ID: {user_id})\n"
                f"💰 {balance:,} коинов | 🏅 Ур. {level} | ⚠️ {warns} пред.\n"
                f"📅 Активность: {last_active}\n\n"
            )
        
        await update.message.reply_text(message, parse_mode='Markdown')

    async def admin_system_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Расширенное резервное копирование"""
        if not await self.is_owner(update):
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        backup_type = context.args[0] if context.args else 'full'
        
        try:
            backup_dir = Path("backups")
            backup_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            if backup_type == 'full':
                filename = f"full_backup_{timestamp}.zip"
                await self.create_full_backup(backup_dir / filename)
            elif backup_type == 'database':
                filename = f"db_backup_{timestamp}.db"
                await self.create_database_backup(backup_dir / filename)
            elif backup_type == 'logs':
                filename = f"logs_backup_{timestamp}.zip" 
                await self.create_logs_backup(backup_dir / filename)
            else:
                await update.message.reply_text(
                    "❌ Неизвестный тип бэкапа!\n"
                    "💡 Доступно: full, database, logs"
                )
                return
            
            await update.message.reply_document(
                document=backup_dir / filename,
                caption=f"📦 Резервная копия ({backup_type}) от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка создания бэкапа: {e}")

    async def create_full_backup(self, filepath: Path):
        """Создание полной резервной копии"""
        with zipfile.ZipFile(filepath, 'w') as zipf:
            # База данных
            zipf.write('bot_database.db', 'bot_database.db')
            
            # Конфиги
            for config_file in ['bad_words.json', 'config.json']:
                if Path(config_file).exists():
                    zipf.write(config_file, config_file)
            
            # Логи
            log_files = list(Path('.').glob('*.log'))
            for log_file in log_files:
                zipf.write(log_file, f"logs/{log_file.name}")

    async def create_database_backup(self, filepath: Path):
        """Создание резервной копии базы данных"""
        import shutil
        shutil.copy2('bot_database.db', filepath)

    async def create_logs_backup(self, filepath: Path):
        """Создание резервной копии логов"""
        with zipfile.ZipFile(filepath, 'w') as zipf:
            log_files = list(Path('.').glob('*.log'))
            for log_file in log_files:
                zipf.write(log_file, log_file.name)

    async def log_admin_action(self, admin_id: int, action: str, target_type: str, 
                             target_id: Optional[int], old_value: str, 
                             new_value: str, reason: str):
        """Логирование действий администратора"""
        await self.conn.execute('''
            INSERT INTO admin_logs 
            (admin_id, action, target_type, target_id, old_value, new_value, timestamp, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (admin_id, action, target_type, target_id, old_value, new_value, 
              datetime.now().isoformat(), reason))
        await self.conn.commit()

    async def get_admin_logs(self, days: int = 7, limit: int = 50):
        """Получение логов администратора"""
        cursor = await self.conn.execute('''
            SELECT al.action, al.target_type, al.old_value, al.new_value, 
                   al.timestamp, al.reason, u.username
            FROM admin_logs al
            JOIN users u ON al.admin_id = u.user_id
            WHERE al.timestamp > datetime('now', ?)
            ORDER BY al.timestamp DESC
            LIMIT ?
        ''', (f'-{days} days', limit))
        return await cursor.fetchall()

    async def is_owner(self, update: Update) -> bool:
        # Замените на вашу логику проверки владельца
        return update.effective_user.id == 123456789  # Замените на ваш ID
