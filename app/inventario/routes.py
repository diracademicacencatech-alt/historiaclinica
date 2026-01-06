from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.extensions import db
from app.models import InsumoMedico

inventario_bp = Blueprint('inventario', __name__, url_prefix='/inventario')

# LISTAR INSUMOS
@inventario_bp.route('/insumos')
@login_required
def listar_insumos():
    q = request.args.get('q', '').strip()

    query = InsumoMedico.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                InsumoMedico.nombre.ilike(like),
                InsumoMedico.codigo.ilike(like)
            )
        )

    insumos = query.order_by(InsumoMedico.nombre).all()
    return render_template('inventario/insumos_list.html',
                           insumos=insumos,
                           q=q)

# CREAR NUEVO
@inventario_bp.route('/insumos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_insumo():
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip()
        nombre = request.form.get('nombre', '').strip()
        stock = request.form.get('stock_actual', '0').strip()
        unidad = request.form.get('unidad', '').strip() or 'Unidad'
        activo = 1 if request.form.get('activo') == 'on' else 0

        if not codigo or not nombre:
            flash('Código y nombre son obligatorios', 'danger')
            return redirect(url_for('inventario.nuevo_insumo'))

        ins = InsumoMedico(
            codigo=codigo,
            nombre=nombre,
            stock_actual=float(stock or 0),
            unidad=unidad,
            activo=activo
        )
        db.session.add(ins)
        db.session.commit()
        flash('Insumo creado correctamente', 'success')
        return redirect(url_for('inventario.listar_insumos'))

    return render_template('inventario/insumo_form.html', insumo=None)

# ELIMINAR INDIVIDUAL
@inventario_bp.route('/insumos/<int:insumo_id>/eliminar', methods=['POST'])
@login_required
def eliminar_insumo(insumo_id):
    ins = InsumoMedico.query.get_or_404(insumo_id)
    db.session.delete(ins)
    db.session.commit()
    flash('Insumo eliminado', 'warning')
    return redirect(url_for('inventario.listar_insumos'))

# ELIMINAR VARIOS SELECCIONADOS
@inventario_bp.route('/insumos/eliminar_seleccionados', methods=['POST'])
@login_required
def eliminar_insumos_seleccionados():
    ids = request.form.getlist('insumo_ids')  # lista de strings
    if not ids:
        flash('No se seleccionó ningún insumo.', 'warning')
        return redirect(url_for('inventario.listar_insumos'))

    deleted = (
        InsumoMedico.query
        .filter(InsumoMedico.id.in_([int(i) for i in ids]))
        .delete(synchronize_session=False)
    )
    db.session.commit()
    flash(f'{deleted} insumos eliminados.', 'success')
    return redirect(url_for('inventario.listar_insumos'))
