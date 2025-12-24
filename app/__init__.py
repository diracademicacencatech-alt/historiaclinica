from flask import Flask, redirect, url_for
from flask_migrate import Migrate

from app.extensions import db, login_manager
from app.utils.fechas import tz_bogota
# Blueprints
from app.auth import auth_bp
from app.pacientes import pacientes_bp
from app.ayudas import ayudas_bp
from app.enfermeria import enfermeria_bp
from app.menu import menu_bp
from app.utils.fechas import ahora_bogota

migrate = Migrate()


def create_app():
    app = Flask(__name__, template_folder='templates')

    # Configuración básica
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///historia_clinica.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'tu_clave_secreta_aqui'

    # Extensiones
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # Registro de blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(pacientes_bp, url_prefix='/pacientes')
    app.register_blueprint(ayudas_bp, url_prefix='/ayudas')
    app.register_blueprint(enfermeria_bp, url_prefix='/enfermeria')
    app.register_blueprint(menu_bp, url_prefix='/menu')

    # Ruta raíz
    @app.route('/')
    def index():
        return redirect(url_for('menu.inicio'))

    return app


# User loader
from app.models import User  # noqa: E402


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Decorador de roles
from functools import wraps  # noqa: E402
from flask_login import current_user  # noqa: E402
from flask import abort  # noqa: E402


def roles_requeridos(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or getattr(current_user, 'rol', None) not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator
