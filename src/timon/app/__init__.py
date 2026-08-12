from flask import Flask
from flask_socketio import SocketIO
from .config import Config

socketio = SocketIO()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    socketio.init_app(app)

    with app.app_context():
        from . import routes, events
    return app
