from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return '<h1>Управление ботом</h1><p>Бот работает!</p>'

if __name__ == '__main__':
    app.run(debug=True)