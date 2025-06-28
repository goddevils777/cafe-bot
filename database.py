import sqlite3

conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Таблица пользователей
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE,
    password TEXT,
    chat_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

# Таблица задач с датой выполнения
cursor.execute('''
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    username TEXT,
    task_time TEXT,
    task_date TEXT,
    task_text TEXT,
    assigned_to TEXT,
    is_active INTEGER DEFAULT 1,
    repeat_daily INTEGER DEFAULT 0,
    repeat_weekly INTEGER DEFAULT 0,
    week_day INTEGER DEFAULT 0,
    require_photo INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

# Таблица выполнения задач
cursor.execute('''
CREATE TABLE IF NOT EXISTS task_completions (
    id INTEGER PRIMARY KEY,
    task_id INTEGER,
    username TEXT,
    task_text TEXT,
    completed_by TEXT,
    photo_path TEXT,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

# Таблица отправленных задач
cursor.execute('''
CREATE TABLE IF NOT EXISTS sent_tasks (
    id INTEGER PRIMARY KEY,
    task_id INTEGER,
    username TEXT,
    task_text TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    escalation_sent INTEGER DEFAULT 0
)
''')

# Таблица использованных никнеймов
cursor.execute('''
CREATE TABLE IF NOT EXISTS used_usernames (
    id INTEGER PRIMARY KEY,
    username TEXT,
    nickname TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

conn.commit()
conn.close()
print("База данных с датами задач создана!")