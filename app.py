import telebot
from flask import Flask, render_template, request, redirect, session, flash
import threading
import sqlite3
import hashlib
import uuid
import schedule
import time
from datetime import datetime
import pytz

# Настройки бота
bot = telebot.TeleBot('8064604462:AAHG4VH59Fy7KUPN6eogD_MJ-XvxQdug1Cg')

# Настройки веб-приложения
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Функции для работы с базой данных
def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()

def add_user(username, password, chat_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (username, password, chat_id) VALUES (?, ?, ?)', 
                      (username, hash_password(password), chat_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def check_user(username, password):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
                  (username, hash_password(password)))
    user = cursor.fetchone()
    conn.close()
    return user is not None

# Обработчики бота
@bot.message_handler(commands=['start'])
def start_message(message):
    bot.send_message(message.chat.id, 'Привет! Я бот для управления кафе!')

@bot.message_handler(commands=['get_chat_id'])
def get_chat_id(message):
    chat_type = "личный чат" if message.chat.type == 'private' else "группа"
    bot.send_message(message.chat.id, f'ID этого чата: `{message.chat.id}`\nТип: {chat_type}', parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('done_'))
def handle_task_completion(call):
    # Извлекаем данные из callback (теперь формат: done_task_id_username)
    data_parts = call.data.split('_')
    task_id = data_parts[1]
    username = data_parts[2]
    
    # Сохраняем в отчёт
    completed_by = call.from_user.username or call.from_user.first_name
    task_text = call.message.text.replace('🔔 Напоминание: ', '')
    
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO task_completions (task_id, username, task_text, completed_by) VALUES (?, ?, ?, ?)', 
                  (task_id, username, task_text, completed_by))
    conn.commit()
    conn.close()
    
    # Отвечаем пользователю
    bot.answer_callback_query(call.id, f'✅ Задача отмечена как выполненная!')
    
    # Обновляем сообщение
    bot.edit_message_text(
        text=call.message.text + f'\n\n✅ Выполнено: @{completed_by}',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )

# Веб-маршруты
@app.route('/')
def home():
    if 'username' in session:
        tasks = get_user_tasks(session['username'])
        return render_template('dashboard.html', username=session['username'], tasks=tasks)
    return render_template('login.html')
def get_chat_id_by_username(username):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM users WHERE username = ?', (username,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def check_and_send_notifications():
    # Украинское время (Киев)
    ukraine_tz = pytz.timezone('Europe/Kiev')
    current_time = datetime.now(ukraine_tz).strftime('%H:%M')
    current_date = datetime.now(ukraine_tz).strftime('%Y-%m-%d')
    
    print(f'Проверяем время: {current_time} (Киев)')
    
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Получаем задачи для отправки
    cursor.execute('''
        SELECT id, username, task_text, repeat_daily FROM tasks 
        WHERE task_time = ? AND is_active = 1 
        AND (
            repeat_daily = 0 
            OR (repeat_daily = 1 AND id NOT IN (
                SELECT DISTINCT task_id FROM task_completions 
                WHERE DATE(completed_at) = ? AND task_id IS NOT NULL
            ))
        )
    ''', (current_time, current_date))
    tasks_to_send = cursor.fetchall()
    
    for task in tasks_to_send:
        task_id, username, task_text, repeat_daily = task
        chat_id = get_chat_id_by_username(username)
        if chat_id:
            try:
                # Отправляем уведомление с кнопкой
                repeat_text = " (ежедневно)" if repeat_daily else ""
                markup = telebot.types.InlineKeyboardMarkup()
                btn = telebot.types.InlineKeyboardButton('✅ Выполнено', callback_data=f'done_{task_id}_{username}')
                markup.add(btn)
                
                bot.send_message(chat_id, f'🔔 Напоминание: {task_text}{repeat_text}', reply_markup=markup)
                print(f'Отправлено уведомление: {task_text} в чат {chat_id}')
                
                # Помечаем как неактивную только разовые задачи
                if repeat_daily == 0:
                    cursor.execute('UPDATE tasks SET is_active = 0 WHERE id = ?', (task_id,))
                    conn.commit()
                
            except Exception as e:
                print(f'Ошибка отправки: {e}')
    
    conn.close()

@app.route('/register_page')
def register_page():
    return render_template('register.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    password = request.form['password']
    chat_id = request.form['chat_id']
    
    if add_user(username, password, chat_id):
        return '<h1>Регистрация успешна!</h1><a href="/">Войти</a>'
    else:
        return '<h1>Ошибка! Пользователь уже существует</h1><a href="/register_page">Назад</a>'

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    
    if check_user(username, password):
        session['username'] = username
        return redirect('/')
    else:
        return '<h1>Неверный логин или пароль</h1><a href="/">Назад</a>'

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

def save_task(username, task_time, task_text, repeat_daily=0):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tasks (username, task_time, task_text, repeat_daily) VALUES (?, ?, ?, ?)', 
                  (username, task_time, task_text, repeat_daily))
    conn.commit()
    conn.close()

def get_user_tasks(username):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, task_time, task_text, created_at, repeat_daily FROM tasks WHERE username = ? AND is_active = 1 ORDER BY task_time', 
                  (username,))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def get_user_reports(username):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT task_text, completed_by, completed_at 
        FROM task_completions 
        WHERE username = ? 
        ORDER BY completed_at DESC
    ''', (username,))
    reports = cursor.fetchall()
    conn.close()
    return reports

@app.route('/delete_task/<int:task_id>')
def delete_task(task_id):
    if 'username' not in session:
        return redirect('/')
    
    # Проверяем что задача принадлежит пользователю
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT username FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()
    
    if task and task[0] == session['username']:
        cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        conn.commit()
        conn.close()
        return redirect('/')
    else:
        conn.close()
        return '<h1>Ошибка: задача не найдена</h1><a href="/">Назад</a>'

@app.route('/edit_task/<int:task_id>')
def edit_task(task_id):
    if 'username' not in session:
        return redirect('/')
    
    # Получаем данные задачи
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, task_time, task_text, username, repeat_daily FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()
    conn.close()
    
    if task and task[3] == session['username']:
        return render_template('edit_task.html', task=task)
    else:
        return '<h1>Ошибка: задача не найдена</h1><a href="/">Назад</a>'

@app.route('/update_task/<int:task_id>', methods=['POST'])
def update_task(task_id):
    if 'username' not in session:
        return redirect('/')
    
    task_time = request.form['task_time']
    task_text = request.form['task_text']
    repeat_daily = 1 if 'repeat_daily' in request.form else 0
    
    # Обновляем задачу
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET task_time = ?, task_text = ?, repeat_daily = ? WHERE id = ? AND username = ?', 
                  (task_time, task_text, repeat_daily, task_id, session['username']))
    conn.commit()
    conn.close()
    
    return redirect('/')

@app.route('/add_task', methods=['POST'])
def add_task():
    if 'username' not in session:
        return redirect('/')
    
    task_time = request.form['task_time']
    task_text = request.form['task_text']
    repeat_daily = 1 if 'repeat_daily' in request.form else 0
    username = session['username']
    
    save_task(username, task_time, task_text, repeat_daily)
    return redirect('/')

@app.route('/update_chat_id', methods=['POST'])
def update_chat_id():
    if 'username' not in session:
        return redirect('/')
    
    new_chat_id = request.form['chat_id']
    username = session['username']
    
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET chat_id = ? WHERE username = ?', (new_chat_id, username))
    conn.commit()
    conn.close()
    
    return '<h1>ID чата обновлён!</h1><a href="/">Назад в кабинет</a>'

@app.route('/reports')
def reports():
    if 'username' not in session:
        return redirect('/')
    
    reports = get_user_reports(session['username'])
    return render_template('reports.html', username=session['username'], reports=reports)

# Запуск бота
def run_bot():
    # Настраиваем планировщик - проверяем каждую минуту
    schedule.every().minute.do(check_and_send_notifications)
    
    def schedule_checker():
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    # Запускаем планировщик в отдельном потоке
    scheduler_thread = threading.Thread(target=schedule_checker, daemon=True)
    scheduler_thread.start()
    
    # Запускаем бота
    bot.polling()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)