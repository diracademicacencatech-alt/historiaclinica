from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app.extensions import db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('menu.inicio'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not username or not email or not password or not confirm_password:
            flash('Por favor completa todos los campos.', 'warning')
            return render_template('auth/register.html')

        if password != confirm_password:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('auth/register.html')

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('Usuario o email ya registrado.', 'danger')
            return render_template('auth/register.html')

        nuevo_usuario = User(username=username, email=email)
        nuevo_usuario.set_password(password)
        db.session.add(nuevo_usuario)
        db.session.commit()
        flash('Registro exitoso. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('menu.inicio'))

    if request.method == 'POST':
        username_or_email = request.form.get('username_or_email', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter((User.username == username_or_email) | (User.email == username_or_email)).first()

        if user and user.check_password(password):
            login_user(user)
            flash('Inicio de sesión exitoso.', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('menu.inicio'))
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('auth.login'))
