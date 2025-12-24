from flask import Blueprint

enfermeria_bp = Blueprint('enfermeria', __name__, url_prefix='/enfermeria')

from app.enfermeria import routes  # Importar rutas para registrar con blueprint
