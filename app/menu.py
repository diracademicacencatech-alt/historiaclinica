from flask import Blueprint, render_template
from flask_login import login_required

menu_bp = Blueprint('menu', __name__, url_prefix='/menu')

@menu_bp.route('/')
@login_required
def inicio():
    return render_template('menu.html')
