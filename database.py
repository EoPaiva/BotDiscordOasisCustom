# database.py
import aiosqlite
from datetime import datetime

# Usaremos um único arquivo de banco de dados para todos os sistemas.
DATABASE_FILE = "oasis_custom_data.db"

async def init_db():
    """Inicializa o banco de dados e cria todas as tabelas necessárias se não existirem."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('PRAGMA journal_mode=WAL;') # Melhora o desempenho

        # Tabela para o Sistema de Ausência
        await db.execute('''
            CREATE TABLE IF NOT EXISTS absences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                return_date TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        ''')

        # Tabela para os tickets de farm abertos
        await db.execute('''
            CREATE TABLE IF NOT EXISTS farm_tickets (
                user_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL
            )
        ''')

        # Tabela para as entregas de farm
        await db.execute('''
            CREATE TABLE IF NOT EXISTS farm_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                item_quantity INTEGER NOT NULL,
                image_url TEXT,
                private_message_id INTEGER,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pendente' -- pendente, aprovado, negado
            )
        ''')
        await db.commit()
    print("Banco de dados consolidado inicializado com sucesso.")

# --- Funções do Sistema de Ausência ---
async def add_absence(user_id: int, reason: str, return_date: str):
    """Adiciona um novo pedido de ausência ao banco de dados."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            "INSERT INTO absences (user_id, reason, return_date, submitted_at) VALUES (?, ?, ?, ?)",
            (user_id, reason, return_date, datetime.now().isoformat())
        )
        await db.commit()

async def get_expired_absences():
    """Busca todas as ausências ativas cuja data de retorno já passou."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            "SELECT id, user_id FROM absences WHERE return_date <= ? AND is_active = 1",
            (today_str,)
        )
        rows = await cursor.fetchall()
        return rows

async def deactivate_absence(absence_id: int):
    """Marca uma ausência como inativa para não ser processada novamente."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            "UPDATE absences SET is_active = 0 WHERE id = ?",
            (absence_id,)
        )
        await db.commit()

# --- Funções do Sistema de Farm ---
async def get_user_ticket(user_id: int):
    """Verifica se um usuário já possui um ticket de farm aberto."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("SELECT channel_id FROM farm_tickets WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()

async def create_farm_ticket(user_id: int, channel_id: int):
    """Registra um novo ticket de farm no banco de dados."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("INSERT INTO farm_tickets (user_id, channel_id) VALUES (?, ?)", (user_id, channel_id))
        await db.commit()

async def delete_farm_ticket(user_id: int):
    """Remove um ticket de farm do banco de dados."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("DELETE FROM farm_tickets WHERE user_id = ?", (user_id,))
        await db.commit()

async def add_farm_delivery(user_id: int, item_name: str, quantity: int, image_url: str):
    """Adiciona uma nova entrega e retorna o ID da linha criada."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            "INSERT INTO farm_deliveries (user_id, item_name, item_quantity, image_url, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, item_name, quantity, image_url, datetime.now().isoformat())
        )
        await db.commit()
        return cursor.lastrowid

async def set_private_message_id(delivery_id: int, message_id: int):
    """Salva o ID da mensagem de confirmação no ticket privado."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            "UPDATE farm_deliveries SET private_message_id = ? WHERE id = ?",
            (message_id, delivery_id)
        )
        await db.commit()

async def get_delivery_info(delivery_id: int):
    """Busca todas as informações de uma entrega, incluindo o ID da mensagem privada."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row # Retorna os resultados como dicionários
        cursor = await db.execute("SELECT user_id, private_message_id FROM farm_deliveries WHERE id = ?", (delivery_id,))
        return await cursor.fetchone()

async def update_delivery_status(delivery_id: int, new_status: str):
    """Atualiza o status de uma entrega (aprovado ou negado)."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            "UPDATE farm_deliveries SET status = ? WHERE id = ?",
            (new_status, delivery_id)
        )
        await db.commit()

async def get_user_deliveries(user_id: int, limit: int = 10):
    """Busca as últimas entregas de um usuário, incluindo a imagem e o status."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            "SELECT item_name, item_quantity, image_url, status, timestamp FROM farm_deliveries WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        )
        return await cursor.fetchall()

async def get_farm_ranking(limit: int = 10):
    """Calcula o ranking geral de farm, somando apenas as entregas APROVADAS."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            """
            SELECT user_id, SUM(item_quantity) as total
            FROM farm_deliveries
            WHERE status = 'aprovado'
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT ?
            """,
            (limit,)
        )
        return await cursor.fetchall()