# database.py
import aiosqlite
from datetime import datetime

DATABASE_FILE = "oasis_custom_data.db"

async def init_db():
    """Inicializa o banco de dados e cria todas as tabelas necessárias se não existirem."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('PRAGMA journal_mode=WAL;')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS absences (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, reason TEXT NOT NULL,
                return_date TEXT NOT NULL, submitted_at TEXT NOT NULL, is_active INTEGER DEFAULT 1
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS farm_tickets (user_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL)
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS farm_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, item_name TEXT NOT NULL,
                item_quantity INTEGER NOT NULL, image_url TEXT, private_message_id INTEGER,
                timestamp TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pendente'
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS cash_control (
                id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, amount REAL NOT NULL,
                reason TEXT NOT NULL, image_url TEXT, balance_before REAL NOT NULL,
                balance_after REAL NOT NULL, user_id INTEGER NOT NULL, timestamp TEXT NOT NULL
            )
        ''')
        await db.commit()
    print("Banco de dados consolidado inicializado com sucesso.")

# --- Funções do Sistema de Ausência ---
async def add_absence(user_id: int, reason: str, return_date: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("INSERT INTO absences (user_id, reason, return_date, submitted_at) VALUES (?, ?, ?, ?)", (user_id, reason, return_date, datetime.now().isoformat()))
        await db.commit()

async def get_expired_absences():
    today_str = datetime.now().strftime('%Y-%m-%d')
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("SELECT id, user_id FROM absences WHERE return_date <= ? AND is_active = 1", (today_str,))
        return await cursor.fetchall()

async def deactivate_absence(absence_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("UPDATE absences SET is_active = 0 WHERE id = ?", (absence_id,))
        await db.commit()

# --- Funções do Sistema de Farm ---
async def get_user_ticket(user_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("SELECT channel_id FROM farm_tickets WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()

async def create_farm_ticket(user_id: int, channel_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("INSERT INTO farm_tickets (user_id, channel_id) VALUES (?, ?)", (user_id, channel_id))
        await db.commit()

async def delete_farm_ticket(user_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("DELETE FROM farm_tickets WHERE user_id = ?", (user_id,))
        await db.commit()

async def add_farm_delivery(user_id: int, item_name: str, quantity: int, image_url: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("INSERT INTO farm_deliveries (user_id, item_name, item_quantity, image_url, timestamp) VALUES (?, ?, ?, ?, ?)", (user_id, item_name, quantity, image_url, datetime.now().isoformat()))
        await db.commit()
        return cursor.lastrowid

async def set_private_message_id(delivery_id: int, message_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("UPDATE farm_deliveries SET private_message_id = ? WHERE id = ?", (message_id, delivery_id))
        await db.commit()

async def get_delivery_info(delivery_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT user_id, private_message_id FROM farm_deliveries WHERE id = ?", (delivery_id,))
        return await cursor.fetchone()

async def update_delivery_status(delivery_id: int, new_status: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("UPDATE farm_deliveries SET status = ? WHERE id = ?", (new_status, delivery_id))
        await db.commit()

async def get_user_deliveries(user_id: int, limit: int = 10):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("SELECT item_name, item_quantity, image_url, status, timestamp FROM farm_deliveries WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        return await cursor.fetchall()

async def get_farm_ranking(limit: int = 10):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("SELECT user_id, SUM(item_quantity) as total FROM farm_deliveries WHERE status = 'aprovado' GROUP BY user_id ORDER BY total DESC LIMIT ?", (limit,))
        return await cursor.fetchall()

# --- Funções do Sistema de Controle de Caixa ---
async def get_current_balance() -> float:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("SELECT balance_after FROM cash_control ORDER BY id DESC LIMIT 1")
        result = await cursor.fetchone()
        return float(result[0]) if result else 0.0

async def add_cash_transaction(type: str, amount: float, reason: str, image_url: str, balance_before: float, balance_after: float, user_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("INSERT INTO cash_control (type, amount, reason, image_url, balance_before, balance_after, user_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (type, amount, reason, image_url, balance_before, balance_after, user_id, datetime.now().isoformat()))
        await db.commit()

# --- Funções para o Comando de Relatório ---
async def get_farm_report_stats():
    """Retorna estatísticas do sistema de farm para o relatório."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT COUNT(id) as total_deliveries, COUNT(DISTINCT user_id) as unique_farmers FROM farm_deliveries WHERE status = 'aprovado'")
        return await cursor.fetchone()

async def get_cash_control_report_stats():
    """Retorna estatísticas do controle de caixa para o relatório."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                SUM(CASE WHEN type = 'entrada' THEN amount ELSE 0 END) as total_in,
                SUM(CASE WHEN type = 'saida' THEN amount ELSE 0 END) as total_out,
                COUNT(id) as total_transactions
            FROM cash_control
            """
        )
        return await cursor.fetchone()