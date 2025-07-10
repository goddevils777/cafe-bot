import telebot
from flask import Flask, render_template, request, redirect, session, flash
import threading
import sqlite3
import hashlib
import uuid
import schedule
import time
from datetime import datetime, timedelta
import pytz

def format_ukrainian_time(utc_timestamp):
    try:
        from datetime import datetime
        import pytz
        
        # Парсим UTC время из базы
        utc_time = datetime.strptime(utc_timestamp, '%Y-%m-%d %H:%M:%S')
        utc_time = pytz.utc.localize(utc_time)
        
        # Конвертируем в украинское время
        ukraine_tz = pytz.timezone('Europe/Kiev')
        ukraine_time = utc_time.astimezone(ukraine_tz)
        
        return ukraine_time.strftime('%d.%m.%Y %H:%M')
    except:
        return utc_timestamp

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

@bot.message_handler(commands=['setup'])
def setup_chat(message):
    chat_id = message.chat.id
    chat_type = message.chat.type
    
    if chat_type in ['group', 'supergroup']:
        bot.send_message(chat_id, 
                        f'🔧 *Настройка группы*\n\n'
                        f'ID этой группы: `{chat_id}`\n\n'
                        f'📋 *Что делать дальше:*\n'
                        f'1. Скопируйте ID: `{chat_id}`\n'
                        f'2. Войдите в веб-интерфейс\n'
                        f'3. Вставьте ID в настройки\n'
                        f'4. Создавайте задачи!\n\n'
                        f'✅ После настройки уведомления будут приходить в эту группу', 
                        parse_mode='Markdown')
    else:
        bot.send_message(chat_id, 'Эта команда работает только в группах!')

# Добавим глобальный список для отслеживания фото-запросов
pending_photo_requests = []

@bot.callback_query_handler(func=lambda call: call.data.startswith('done_'))
def handle_task_completion(call):
    try:
        print(f'DEBUG: Получен callback: {call.data}')
        
        # Извлекаем данные из callback
        data_parts = call.data.split('_')
        task_id = data_parts[1]
        username = data_parts[2]
        require_photo = int(data_parts[3]) if len(data_parts) > 3 else 0
        allow_multiple = int(data_parts[4]) if len(data_parts) > 4 else 0
        
        completed_by = call.from_user.username or call.from_user.first_name
        task_text = call.message.text.replace('🔔 Напоминание: ', '').replace(' (ежедневно)', '').replace(' 📸', '')
        
        print(f'DEBUG: Выполнил: {completed_by}, allow_multiple: {allow_multiple}')
        
        # Подключаемся к базе
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        
        # Для групповых задач - проверяем не выполнял ли уже этот пользователь
        if allow_multiple:
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            
            cursor.execute('''
                SELECT COUNT(*) FROM task_completions 
                WHERE task_id = ? AND completed_by = ? AND DATE(completed_at) = ?
            ''', (task_id, completed_by, today))
            
            already_completed = cursor.fetchone()[0] > 0
            
            if already_completed:
                bot.answer_callback_query(call.id, f'❌ Вы уже отметили выполнение этой задачи сегодня!')
                conn.close()
                return
        
        # Сохраняем выполнение
        cursor.execute('INSERT INTO task_completions (task_id, username, task_text, completed_by) VALUES (?, ?, ?, ?)', 
                      (task_id, username, task_text, completed_by))
        conn.commit()
        
        # Для обычных задач - деактивируем
        if not allow_multiple:
            cursor.execute('SELECT repeat_daily, repeat_weekly, repeat_monthly FROM tasks WHERE id = ?', (task_id,))
            task_info = cursor.fetchone()
            if task_info and task_info[0] == 0 and task_info[1] == 0 and task_info[2] == 0:
                cursor.execute('UPDATE tasks SET is_active = 0 WHERE id = ?', (task_id,))
                conn.commit()
        
        # Получаем всех кто выполнил задачу сегодня (для групповых)
        if allow_multiple:
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT completed_by FROM task_completions 
                WHERE task_id = ? AND DATE(completed_at) = ?
                ORDER BY completed_at
            ''', (task_id, today))
            all_completed = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        
        # Ответ пользователю
        if allow_multiple:
            bot.answer_callback_query(call.id, f'✅ Задача отмечена! (Групповая)')
        else:
            bot.answer_callback_query(call.id, f'✅ Задача отмечена!')
        
        # Обновляем сообщение
        if allow_multiple:
            # Для групповых - показываем список всех выполнивших
            completed_list = '\n'.join([f'@{user}' for user in all_completed])
            original_text = call.message.text.split('\n\n✅')[0]  # Убираем старый список
            new_text = original_text + f'\n\n✅ Выполнили:\n{completed_list}'
            
            bot.edit_message_text(
                text=new_text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=call.message.reply_markup  # Кнопка остается
            )
        else:
            # Для обычных - убираем кнопку
            bot.edit_message_text(
                text=call.message.text + f'\n\n✅ Выполнено: @{completed_by}',
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        
    except Exception as e:
        print(f'ОШИБКА: {e}')
        bot.answer_callback_query(call.id, f'❌ Ошибка: {e}')

@bot.callback_query_handler(func=lambda call: call.data.startswith('escalation_'))
def handle_escalation_response(call):
    # Извлекаем данные из callback (escalation_yes_task_id_username)
    data_parts = call.data.split('_')
    task_id = data_parts[2]
    username = data_parts[3]
    
    completed_by = call.from_user.username or call.from_user.first_name
    task_text = call.message.text.split('Задача: ')[1].split('\n')[0]
    
    # Сотрудник подтвердил выполнение
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO task_completions (task_id, username, task_text, completed_by) VALUES (?, ?, ?, ?)', 
                  (task_id, username, task_text, completed_by))
    
    # Деактивируем разовые задачи после подтверждения эскалации
    cursor.execute('SELECT repeat_daily, repeat_weekly FROM tasks WHERE id = ?', (task_id,))
    task_info = cursor.fetchone()
    if task_info and task_info[0] == 0 and task_info[1] == 0:  # Если разовая задача
        cursor.execute('UPDATE tasks SET is_active = 0 WHERE id = ?', (task_id,))
    conn.commit()    
    conn.close()
    
    bot.answer_callback_query(call.id, f'✅ Спасибо за подтверждение!')
    bot.edit_message_text(
        text=call.message.text + f'\n\n✅ Подтверждено: @{completed_by}',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )

# Веб-маршруты
@app.route('/')
def home():
    if 'username' in session:
        active_tasks, _ = get_user_tasks(session['username'])  # Не нужны completed_tasks
        
        # Форматируем время для активных задач
        formatted_active = []
        for task in active_tasks:
            task_list = list(task)
            task_list[3] = format_ukrainian_time(task[3])
            formatted_active.append(tuple(task_list))
        
        # Получаем использованные никнеймы для автозаполнения
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT nickname FROM used_usernames WHERE username = ? ORDER BY created_at DESC', (session['username'],))
        used_usernames = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        return render_template('dashboard.html', 
                             username=session['username'], 
                             active_tasks=formatted_active,
                             used_usernames=used_usernames)
    return render_template('login.html')

def get_chat_id_by_username(username):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM users WHERE username = ?', (username,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_chat_info(chat_id):
    """Получает информацию о чате/группе"""
    if not chat_id:
        return None
    
    try:
        chat = bot.get_chat(chat_id)
        return {
            'id': chat_id,
            'title': chat.title or 'Личный чат',
            'type': chat.type
        }
    except Exception as e:
        print(f'Ошибка получения информации о чате {chat_id}: {e}')
        return None

def get_chat_members(chat_id):
    """Получает список всех участников группы"""
    if not chat_id:
        return []
    
    try:
        members = []
        
        # Получаем количество участников
        chat_member_count = bot.get_chat_member_count(chat_id)
        
        # Для малых групп (до 200 человек) можем получить список всех
        if chat_member_count <= 200:
            try:
                # Пытаемся получить всех участников через админов и обычных пользователей
                admins = bot.get_chat_administrators(chat_id)
                for admin in admins:
                    user = admin.user
                    username = f"@{user.username}" if user.username else "Нет username"
                    members.append({
                        'id': user.id,
                        'name': user.first_name + (f" {user.last_name}" if user.last_name else ""),
                        'username': username,
                        'status': admin.status,
                        'is_admin': True
                    })
            except:
                pass
        
        # Если не удалось получить всех, показываем только админов
        if not members:
            admins = bot.get_chat_administrators(chat_id)
            for admin in admins:
                user = admin.user
                username = f"@{user.username}" if user.username else "Нет username"
                members.append({
                    'id': user.id,
                    'name': user.first_name + (f" {user.last_name}" if user.last_name else ""),
                    'username': username,
                    'status': admin.status,
                    'is_admin': True
                })
        
        return members
    except Exception as e:
        print(f'Ошибка получения участников чата {chat_id}: {e}')
        return []

def send_task_notification(task_data):
    """Отправляет уведомление для одной задачи"""
    print(f'DEBUG: send_task_notification received: {task_data}, length: {len(task_data)}')
    
    task_id = task_data[0]
    username = task_data[1] 
    task_text = task_data[2]
    repeat_daily = task_data[3]
    require_photo = task_data[4]
    repeat_weekly = task_data[5]
    week_day = task_data[6]
    assigned_to = task_data[7] if len(task_data) > 7 else None
    allow_multiple = task_data[8] if len(task_data) > 8 else 0
    
    print(f'DEBUG: assigned_to in function = "{assigned_to}"')
    
    chat_id = get_chat_id_by_username(username)
    
    if chat_id:
        try:
            repeat_text = ""
            if repeat_daily:
                repeat_text = " (ежедневно)"
            elif repeat_weekly:
                days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
                repeat_text = f" (еженедельно {days[week_day]})"
            
            photo_text = " 📸" if require_photo else ""
            
            # Формируем сообщение с упоминанием
            if assigned_to:
                if assigned_to.startswith('@'):
                    message_text = f'🔔 Задача для {assigned_to}: {task_text}{repeat_text}{photo_text}'
                else:
                    message_text = f'🔔 Задача для @{assigned_to}: {task_text}{repeat_text}{photo_text}'
            else:
                message_text = f'🔔 Напоминание: {task_text}{repeat_text}{photo_text}'
            
            markup = telebot.types.InlineKeyboardMarkup()
            btn = telebot.types.InlineKeyboardButton('✅ Выполнено', 
                                                callback_data=f'done_{task_id}_{username}_{require_photo}_{allow_multiple}')
            markup.add(btn)
            
            bot.send_message(chat_id, message_text, reply_markup=markup)
            print(f'Отправлено уведомление: {message_text}')
            
            return True
        except Exception as e:
            print(f'Ошибка отправки: {e}')
            return False
    
    return False        

def check_and_send_notifications():
    global pending_photo_requests
    
    # Украинское время (Киев)
    ukraine_tz = pytz.timezone('Europe/Kiev')
    now = datetime.now(ukraine_tz)
    current_time = now.strftime('%H:%M')
    current_date = now.strftime('%Y-%m-%d')
    current_weekday = now.weekday()  # 0=понедельник, 6=воскресенье
    
    print(f'Проверяем время: {current_time} (Киев), день недели: {current_weekday}')

    print(f'Ищем задачи на время: {current_time}')
    
    # 1. Проверяем обычные задачи
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Сначала покажем все активные задачи
    cursor.execute('SELECT id, username, task_time, task_text, is_active, repeat_daily, repeat_weekly, week_day, require_photo, assigned_to FROM tasks WHERE is_active = 1')
    all_active = cursor.fetchall()
    print(f'Все активные задачи: {all_active}')
    
    cursor.execute('''
        SELECT id, username, task_text, repeat_daily, require_photo, repeat_weekly, week_day, assigned_to, allow_multiple FROM tasks 
        WHERE task_time = ? AND is_active = 1 
        AND (
            (repeat_daily = 0 AND repeat_weekly = 0 AND repeat_monthly = 0 AND (task_date IS NULL OR task_date = ?)) OR
            (repeat_daily = 1 AND id NOT IN (
                SELECT DISTINCT task_id FROM task_completions 
                WHERE DATE(completed_at) = ? AND task_id IS NOT NULL
            )) OR
            (repeat_weekly = 1 AND week_day = ? AND id NOT IN (
                SELECT DISTINCT task_id FROM task_completions 
                WHERE DATE(completed_at) = ? AND task_id IS NOT NULL
            )) OR
            (repeat_monthly = 1 AND CAST(strftime('%d', 'now', 'localtime') AS INTEGER) = month_day AND id NOT IN (
                SELECT DISTINCT task_id FROM task_completions 
                WHERE DATE(completed_at) = ? AND task_id IS NOT NULL
            ))
        )
    ''', (current_time, current_date, current_date, current_weekday, current_date, current_date))
    tasks_to_send = cursor.fetchall()

    print(f'Задачи для отправки: {tasks_to_send}')
    print(f'DEBUG: SQL columns returned: {[desc[0] for desc in cursor.description]}')
    for i, task in enumerate(tasks_to_send):
        print(f'DEBUG: Task {i}: {task}, length: {len(task)}')
    
    for task_data in tasks_to_send:
        print(f'DEBUG: Processing task_data: {task_data}')
        
        # Отправляем уведомление через изолированную функцию
        if send_task_notification(task_data):
            # Записываем отправленную задачу для эскалации
            task_id = task_data[0]
            username = task_data[1]
            task_text = task_data[2]
            repeat_daily = task_data[3]
            repeat_weekly = task_data[5]
            
            # Сохраняем время в украинском часовом поясе
            ukraine_tz = pytz.timezone('Europe/Kiev')
            current_ukraine_time = datetime.now(ukraine_tz).strftime('%Y-%m-%d %H:%M:%S')
            allow_multiple = task_data[8] if len(task_data) > 8 else 0

            cursor.execute('INSERT INTO sent_tasks (task_id, username, task_text, sent_at, allow_multiple, message_id, chat_id) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                (task_id, username, task_text, current_ukraine_time, allow_multiple, None, None))
            conn.commit()
            print(f'DEBUG: Записали в sent_tasks: task_id={task_id}, username={username}, text={task_text}')

            # Проверяем групповые задачи старше 2 часов и деактивируем их
            two_hours_ago = datetime.now(ukraine_tz) - timedelta(hours=2)
            cursor.execute('''
                SELECT DISTINCT st.task_id, st.username FROM sent_tasks st
                WHERE st.allow_multiple = 1 
                AND datetime(st.sent_at) <= datetime(?)
                AND st.buttons_removed = 0
            ''', (two_hours_ago.strftime('%Y-%m-%d %H:%M:%S'),))

            expired_group_tasks = cursor.fetchall()

            for task_id, task_username in expired_group_tasks:
                try:
                    # Деактивируем разовые групповые задачи
                    cursor.execute('SELECT repeat_daily, repeat_weekly, repeat_monthly FROM tasks WHERE id = ?', (task_id,))
                    task_info = cursor.fetchone()
                    if task_info and task_info[0] == 0 and task_info[1] == 0 and task_info[2] == 0:
                        cursor.execute('UPDATE tasks SET is_active = 0 WHERE id = ?', (task_id,))
                        print(f'Групповая задача {task_id} деактивирована через 2 часа')
                    
                    # Помечаем как обработанные
                    cursor.execute('UPDATE sent_tasks SET buttons_removed = 1 WHERE task_id = ? AND allow_multiple = 1', (task_id,))
                    conn.commit()
                    print(f'Кнопки убраны для групповой задачи {task_id}')
                except Exception as e:
                    print(f'Ошибка удаления кнопок: {e}')

    conn.close()
    
    # 2. Проверяем фото-запросы
    for i, photo_request in enumerate(pending_photo_requests[:]):
        if photo_request['time'] == current_time and photo_request['date'] == current_date:
            try:
                bot.send_message(photo_request['chat_id'], 
                               f'📸 Время для фото-отчёта!\n\n'
                               f'Задача: {photo_request["task_text"]}\n'
                               f'Выполнил: @{photo_request["completed_by"]}\n\n'
                               f'Пожалуйста, пришлите фото или видео результата выполнения задачи.')
                print(f'Отправлен запрос фото для задачи: {photo_request["task_text"]}')
                pending_photo_requests.remove(photo_request)
            except Exception as e:
                print(f'Ошибка запроса фото: {e}')

    # Эскалация - проверяем задачи отправленные больше 2 минут назад
    escalation_time_threshold = datetime.now(ukraine_tz) - timedelta(minutes=5)
    print(f'DEBUG: Ищем задачи отправленные раньше: {escalation_time_threshold.strftime("%H:%M:%S")}')
    
    # Создаём новое соединение для эскалации
    escalation_conn = sqlite3.connect('bot_database.db')
    escalation_cursor = escalation_conn.cursor()
    
    escalation_cursor.execute('SELECT * FROM sent_tasks WHERE escalation_sent = 0')
    all_sent = escalation_cursor.fetchall()
    print(f'DEBUG: Все неэскалированные задачи в sent_tasks: {all_sent}')

    escalation_cursor.execute('''
        SELECT st.id, st.task_id, st.username, st.task_text, st.sent_at 
        FROM sent_tasks st
        WHERE datetime(st.sent_at) <= datetime(?)
        AND st.escalation_sent = 0
        AND st.task_id NOT IN (
            SELECT DISTINCT task_id FROM task_completions 
            WHERE task_id = st.task_id AND DATE(completed_at) = ?
        )
    ''', (escalation_time_threshold.strftime('%Y-%m-%d %H:%M:%S'), current_date))
    
    overdue_tasks = escalation_cursor.fetchall()

    print(f'DEBUG: Проверяем эскалацию, ищем задачи старше: {escalation_time_threshold.strftime("%H:%M:%S")}')
    print(f'DEBUG: Найдено просроченных задач: {len(overdue_tasks)}')
    
    for overdue in overdue_tasks:
        sent_task_id, task_id, username, task_text, sent_at = overdue
        chat_id = get_chat_id_by_username(username)
        if chat_id:
            try:
                markup = telebot.types.InlineKeyboardMarkup()
                btn_yes = telebot.types.InlineKeyboardButton('✅ Да, выполнил', 
                                                           callback_data=f'escalation_yes_{task_id}_{username}')
                markup.add(btn_yes)
                
                bot.send_message(chat_id, 
                               f'❗ Проверка выполнения\n\n'
                               f'Задача: {task_text}\n'
                               f'Время: {sent_at}\n\n'
                               f'Вы выполнили это задание?', 
                               reply_markup=markup)
                
                # Помечаем что эскалация отправлена
                escalation_cursor.execute('UPDATE sent_tasks SET escalation_sent = 1 WHERE id = ?', (sent_task_id,))
                escalation_conn.commit()
                
                print(f'Отправлена эскалация для задачи: {task_text}')
                
            except Exception as e:
                print(f'Ошибка эскалации: {e}')
    
    escalation_conn.close()

@app.route('/register_page')
def register_page():
    return render_template('register.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    password = request.form['password']
    
    if add_user(username, password, ''):  # Пустой chat_id
        return '<h1>Регистрация успешна!</h1><p>Теперь добавьте бота в группу и настройте ID чата в личном кабинете.</p><a href="/">Войти</a>'
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

def save_task(username, task_time, task_text, repeat_daily=0, repeat_weekly=0, week_day=0, require_photo=0, assigned_to=None, task_date=None, repeat_monthly=0, month_day=1, allow_multiple=0):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    cursor.execute('INSERT INTO tasks (username, task_time, task_text, task_date, assigned_to, repeat_daily, repeat_weekly, week_day, require_photo, repeat_monthly, month_day, allow_multiple) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', 
              (username, task_time, task_text, task_date, assigned_to, repeat_daily, repeat_weekly, week_day, require_photo, repeat_monthly, month_day, allow_multiple))
    
    # Если указан исполнитель, сохраняем его в список использованных никнеймов
    if assigned_to:
        try:
            cursor.execute('INSERT INTO tasks (username, task_time, task_text, task_date, assigned_to, repeat_daily, repeat_weekly, week_day, require_photo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', 
              (username, task_time, task_text, task_date, assigned_to, repeat_daily, repeat_weekly, week_day, require_photo))
        except:
            pass  # Игнорируем если никнейм уже есть
    
    conn.commit()
    conn.close()

def get_user_tasks(username):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Получаем активные задачи с исполнителями
    cursor.execute('SELECT id, task_time, task_text, created_at, repeat_daily, require_photo, repeat_weekly, week_day, assigned_to, task_date, repeat_monthly, month_day, allow_multiple FROM tasks WHERE username = ? AND is_active = 1 ORDER BY created_at DESC', 
                (username,))
    active_tasks = cursor.fetchall()
    
    # Получаем выполненные разовые задачи с группировкой выполнений
    cursor.execute('''
        SELECT t.id, t.task_time, t.task_text, t.created_at, t.repeat_daily, t.require_photo, 
            t.repeat_weekly, t.week_day, t.assigned_to, t.task_date, t.repeat_monthly, t.month_day,
            t.allow_multiple,
            MIN(tc.completed_at) as first_completed_at,
            GROUP_CONCAT(tc.completed_by, ', ') as all_completed_by
        FROM tasks t
        LEFT JOIN task_completions tc ON t.id = tc.task_id
        WHERE t.username = ? AND t.is_active = 0 AND t.repeat_daily = 0 AND t.repeat_weekly = 0 AND t.repeat_monthly = 0 
        GROUP BY t.id
        ORDER BY MIN(tc.completed_at) DESC
    ''', (username,))
    completed_tasks = cursor.fetchall()

    conn.close()
    return active_tasks, completed_tasks

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
    cursor.execute('SELECT id, task_time, task_text, username, repeat_daily, require_photo, repeat_weekly, week_day, assigned_to, task_date, repeat_monthly, month_day FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()
    
    # Получаем использованные никнеймы для автозаполнения
    cursor.execute('SELECT DISTINCT nickname FROM used_usernames WHERE username = ? ORDER BY created_at DESC', (session['username'],))
    used_usernames = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    if task and task[3] == session['username']:
        return render_template('edit_task.html', task=task, used_usernames=used_usernames)
    else:
        return '<h1>Ошибка: задача не найдена</h1><a href="/">Назад</a>'

@app.route('/update_task/<int:task_id>', methods=['POST'])
def update_task(task_id):
    if 'username' not in session:
        return redirect('/')
    
    task_time = request.form['task_time']
    task_text = request.form['task_text']
    repeat_type = request.form['repeat_type']
    week_day = int(request.form.get('week_day', 0))
    require_photo = 1 if 'require_photo' in request.form else 0
    allow_multiple = 1 if 'allow_multiple' in request.form else 0
    assigned_to = request.form.get('assigned_to', '').strip() or None
    task_date = request.form.get('task_date', '').strip() or None
    month_day = int(request.form.get('month_day', 1))
    
    # Определяем тип повторения
    repeat_daily = 1 if repeat_type == 'daily' else 0
    repeat_weekly = 1 if repeat_type == 'weekly' else 0
    repeat_monthly = 1 if repeat_type == 'monthly' else 0

    # Обновляем задачу
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET task_time = ?, task_text = ?, repeat_daily = ?, repeat_weekly = ?, week_day = ?, require_photo = ?, assigned_to = ?, task_date = ?, repeat_monthly = ?, month_day = ?, allow_multiple = ? WHERE id = ? AND username = ?', 
                (task_time, task_text, repeat_daily, repeat_weekly, week_day, require_photo, assigned_to, task_date, repeat_monthly, month_day, allow_multiple, task_id, session['username']))
    
    # Если указан новый исполнитель, сохраняем его в список использованных никнеймов
    if assigned_to:
        try:
            cursor.execute('INSERT OR IGNORE INTO used_usernames (username, nickname) VALUES (?, ?)', 
                          (session['username'], assigned_to))
        except:
            pass  # Игнорируем если никнейм уже есть
    
    conn.commit()
    conn.close()
    
    return redirect('/')

@app.route('/restart_task/<int:task_id>')
def restart_task(task_id):
    if 'username' not in session:
        return redirect('/')
    
    # Проверяем что задача принадлежит пользователю и неактивна
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT username, is_active, repeat_daily FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()
    
    if task and task[0] == session['username'] and task[1] == 0 and task[2] == 0:
        # Активируем задачу обратно
        cursor.execute('UPDATE tasks SET is_active = 1 WHERE id = ?', (task_id,))
        conn.commit()
        conn.close()
        return redirect('/')
    else:
        conn.close()
        return '<h1>Ошибка: задачу нельзя перезапустить</h1><a href="/">Назад</a>'

@app.route('/add_task', methods=['POST'])
def add_task():
    if 'username' not in session:
        return redirect('/')
    
    task_time = request.form['task_time']
    task_text = request.form['task_text']
    repeat_type = request.form['repeat_type']
    week_day = int(request.form.get('week_day', 0))
    require_photo = 1 if 'require_photo' in request.form else 0
    allow_multiple = 1 if 'allow_multiple' in request.form else 0
    assigned_to = request.form.get('assigned_to', '').strip() or None
    task_date = request.form.get('task_date', '').strip() or None
    month_day = int(request.form.get('month_day', 1))
    username = session['username']
    
    # Определяем тип повторения
    repeat_daily = 1 if repeat_type == 'daily' else 0
    repeat_weekly = 1 if repeat_type == 'weekly' else 0
    repeat_monthly = 1 if repeat_type == 'monthly' else 0

    save_task(username, task_time, task_text, repeat_daily, repeat_weekly, week_day, require_photo, assigned_to, task_date, repeat_monthly, month_day, allow_multiple)
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
    # Форматируем время для каждого отчёта
    formatted_reports = []
    for report in reports:
        report_list = list(report)
        report_list[2] = format_ukrainian_time(report[2])  # Форматируем время выполнения
        formatted_reports.append(tuple(report_list))
    
    return render_template('reports.html', username=session['username'], reports=formatted_reports)

@app.route('/completed_tasks')
def completed_tasks():
    if 'username' not in session:
        return redirect('/')
    
    # Получаем только выполненные задачи
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT t.id, t.task_time, t.task_text, t.created_at, t.repeat_daily, t.require_photo, 
               t.repeat_weekly, t.week_day, t.assigned_to, t.task_date, t.repeat_monthly, t.month_day,
               t.allow_multiple,
               MIN(tc.completed_at) as first_completed_at,
               GROUP_CONCAT(tc.completed_by, ', ') as all_completed_by
        FROM tasks t
        LEFT JOIN task_completions tc ON t.id = tc.task_id
        WHERE t.username = ? AND t.is_active = 0 AND t.repeat_daily = 0 AND t.repeat_weekly = 0 AND t.repeat_monthly = 0 
        GROUP BY t.id
        ORDER BY MIN(tc.completed_at) DESC
    ''', (session['username'],))
    completed_tasks = cursor.fetchall()
    
    conn.close()
    
    # Форматируем время для выполненных задач
    formatted_completed = []
    for task in completed_tasks:
        task_list = list(task)
        task_list[3] = format_ukrainian_time(task[3])  # Время создания
        if task[13]:  # Если есть время выполнения
            task_list[13] = format_ukrainian_time(task[13])  # Время выполнения
        formatted_completed.append(tuple(task_list))
    
    return render_template('completed_tasks.html', 
                         username=session['username'], 
                         completed_tasks=formatted_completed)

@app.route('/settings')
def settings():
    if 'username' not in session:
        return redirect('/')
    
    # Получаем текущий chat_id пользователя
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM users WHERE username = ?', (session['username'],))
    result = cursor.fetchone()
    conn.close()
    
    current_chat_id = result[0] if result and result[0] else None
    current_chat_info = None
    chat_members = []
    
    # Если chat_id есть, получаем информацию о группе и участниках
    if current_chat_id:
        current_chat_info = get_chat_info(current_chat_id)
        chat_members = get_chat_members(current_chat_id)
    
    return render_template('settings.html', 
                         username=session['username'], 
                         current_chat_id=current_chat_id,
                         current_chat_info=current_chat_info,
                         chat_members=chat_members)

@app.route('/delete_multiple_tasks', methods=['POST'])
def delete_multiple_tasks():
    if 'username' not in session:
        return {'success': False, 'error': 'Не авторизован'}, 401
    
    try:
        import json
        data = request.get_json()
        task_ids = data.get('task_ids', [])
        task_type = data.get('type', '')
        
        if not task_ids:
            return {'success': False, 'error': 'Не выбраны задачи'}
        
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        
        # Проверяем что все задачи принадлежат пользователю
        placeholders = ','.join(['?' for _ in task_ids])
        cursor.execute(f'SELECT id FROM tasks WHERE id IN ({placeholders}) AND username = ?', 
                      task_ids + [session['username']])
        
        valid_tasks = [row[0] for row in cursor.fetchall()]
        
        if len(valid_tasks) != len(task_ids):
            conn.close()
            return {'success': False, 'error': 'Некоторые задачи не найдены'}
        
        # Удаляем задачи и связанные данные
        for task_id in valid_tasks:
            # Удаляем выполнения задач
            cursor.execute('DELETE FROM task_completions WHERE task_id = ?', (task_id,))
            # Удаляем отправленные уведомления
            cursor.execute('DELETE FROM sent_tasks WHERE task_id = ?', (task_id,))
            # Удаляем саму задачу
            cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        
        conn.commit()
        conn.close()
        
        return {'success': True, 'deleted_count': len(valid_tasks)}
        
    except Exception as e:
        return {'success': False, 'error': str(e)}, 500

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
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)