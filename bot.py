import telebot

bot = telebot.TeleBot('8064604462:AAHG4VH59Fy7KUPN6eogD_MJ-XvxQdug1Cg')

@bot.message_handler(commands=['start'])
def start_message(message):
    bot.send_message(message.chat.id, 'Привет! Я твой первый бот!')

@bot.message_handler(content_types=['text'])
def get_text_messages(message):
    bot.send_message(message.chat.id, f'Ты написал: {message.text}')

bot.polling()