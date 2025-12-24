from flask import Blueprint

ayudas_bp = Blueprint('ayudas', __name__, template_folder='templates')
from .routes import *
