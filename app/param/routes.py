from flask import Blueprint, render_template, request, redirect, url_for, flash 
from flask_login import login_required
from app.models import Medicamento, DiagnosticoCIE10, CatLaboratorioExamen
from app.extensions import db

param_bp = Blueprint('param', __name__, url_prefix='/param')

# 💊 Lista de medicamentos
@param_bp.route('/medicamentos')
@login_required
def medicamentos():
    q = request.args.get('q', '').strip()

    query = Medicamento.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Medicamento.nombre.ilike(like),
                Medicamento.codigo.ilike(like)
            )
        )

    meds = query.order_by(Medicamento.nombre).all()
    return render_template('param/medicamentos_list.html',
                           medicamentos=meds,
                           q=q)

# 💊 CREAR NUEVO
@param_bp.route('/medicamentos/nuevo', methods=['GET', 'POST'])
@login_required
def medicamento_nuevo():
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip()
        nombre = request.form.get('nombre', '').strip()
        forma = request.form.get('forma_farmaceutica', '').strip()
        presentacion = request.form.get('presentacion', '').strip()
        cantidad = request.form.get('cantidad_disponible', '0').strip()
        unidad = request.form.get('unidad_inventario', '').strip()

        if not codigo or not nombre:
            flash('Código y nombre son obligatorios', 'danger')
            return redirect(url_for('param.medicamento_nuevo'))

        med = Medicamento(
            codigo=codigo,
            nombre=nombre,
            forma_farmaceutica=forma or None,
            presentacion=presentacion or None,
            cantidad_disponible=cantidad or 0,
            unidad_inventario=unidad or None
        )
        db.session.add(med)
        db.session.commit()
        flash('Medicamento creado correctamente', 'success')
        return redirect(url_for('param.medicamentos'))

    return render_template('param/medicamento_form.html', medicamento=None)

# 💊 ELIMINAR INDIVIDUAL
@param_bp.route('/medicamentos/<int:med_id>/eliminar', methods=['POST'])
@login_required
def medicamento_eliminar(med_id):
    med = Medicamento.query.get_or_404(med_id)
    db.session.delete(med)
    db.session.commit()
    flash('Medicamento eliminado', 'warning')
    return redirect(url_for('param.medicamentos'))

# 💊 ELIMINAR SELECCIONADOS
@param_bp.route('/medicamentos/eliminar_seleccionados', methods=['POST'])
@login_required
def medicamentos_eliminar_seleccionados():
    ids = request.form.getlist('med_ids')
    if not ids:
        flash('No se seleccionó ningún medicamento.', 'warning')
        return redirect(url_for('param.medicamentos'))

    deleted = (
        Medicamento.query
        .filter(Medicamento.id.in_([int(i) for i in ids]))
        .delete(synchronize_session=False)
    )
    db.session.commit()
    flash(f'{deleted} medicamentos eliminados.', 'success')
    return redirect(url_for('param.medicamentos'))

# 📚 Lista CIE-10
@param_bp.route('/cie10')
@login_required
def cie10():
    from app.extensions import db

    q = request.args.get('q', '').strip()

    query = DiagnosticoCIE10.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                DiagnosticoCIE10.codigo.ilike(like),
                DiagnosticoCIE10.nombre.ilike(like)
            )
        )

    cie = query.order_by(DiagnosticoCIE10.codigo).all()
    return render_template('param/cie10_list.html', cie10=cie, q=q)

@param_bp.route('/cie10/<int:cie_id>/toggle', methods=['POST'])
@login_required
def cie10_toggle(cie_id):
    d = DiagnosticoCIE10.query.get_or_404(cie_id)
    d.habilitado = not d.habilitado
    db.session.commit()
    return redirect(url_for('param.cie10'))

# 🧪 Lista de exámenes de laboratorio
from app.models import CatLaboratorioExamen, CatLaboratorioParametro
from app.extensions import db

@param_bp.route('/laboratorios')
@login_required
def laboratorios():
    q = request.args.get('q', '').strip()

    query = CatLaboratorioExamen.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                CatLaboratorioExamen.nombre.ilike(like),
                CatLaboratorioExamen.grupo.ilike(like)
            )
        )

    examenes = query.order_by(CatLaboratorioExamen.grupo, CatLaboratorioExamen.nombre).all()
    return render_template('param/lab_examenes_list.html',
                           examenes=examenes,
                           q=q)

@param_bp.route('/laboratorios/<int:examen_id>/toggle', methods=['POST'])
@login_required
def laboratorio_toggle(examen_id):
    ex = CatLaboratorioExamen.query.get_or_404(examen_id)
    ex.activo = not ex.activo
    db.session.commit()
    return redirect(url_for('param.laboratorios'))

@param_bp.route('/laboratorios/<int:examen_id>', methods=['GET', 'POST'])
@login_required
def laboratorio_detalle(examen_id):
    ex = CatLaboratorioExamen.query.get_or_404(examen_id)

    if request.method == 'POST':
        # crear o actualizar parámetro
        nombre = request.form.get('nombre', '').strip()
        unidad = request.form.get('unidad', '').strip()
        vr_min = request.form.get('valor_ref_min', '').strip()
        vr_max = request.form.get('valor_ref_max', '').strip()

        if not nombre:
            flash('El nombre del parámetro es obligatorio.', 'danger')
        else:
            param = CatLaboratorioParametro(
                examen_id=ex.id,
                nombre=nombre,
                unidad=unidad or None,
                valor_ref_min=float(vr_min) if vr_min else None,
                valor_ref_max=float(vr_max) if vr_max else None,
            )
            db.session.add(param)
            db.session.commit()
            flash('Parámetro agregado correctamente.', 'success')

        return redirect(url_for('param.laboratorio_detalle', examen_id=ex.id))

    parametros = CatLaboratorioParametro.query.filter_by(examen_id=ex.id).order_by(CatLaboratorioParametro.id).all()
    return render_template('param/lab_examen_detalle.html',
                           examen=ex,
                           parametros=parametros)

@param_bp.route('/laboratorios/<int:examen_id>/eliminar', methods=['POST'])
@login_required
def laboratorio_eliminar(examen_id):
    ex = CatLaboratorioExamen.query.get_or_404(examen_id)
    # También se borran sus parámetros por la FK (si no tienes cascade, los borramos explícitos)
    CatLaboratorioParametro.query.filter_by(examen_id=ex.id).delete()
    db.session.delete(ex)
    db.session.commit()
    flash('Examen de laboratorio eliminado.', 'warning')
    return redirect(url_for('param.laboratorios'))

# EDITAR PARÁMETRO
@param_bp.route('/laboratorios/parametro/<int:param_id>/editar', methods=['POST'])
@login_required
def laboratorio_parametro_editar(param_id):
    p = CatLaboratorioParametro.query.get_or_404(param_id)
    ex_id = p.examen_id

    nombre = request.form.get('nombre', '').strip()
    unidad = request.form.get('unidad', '').strip()
    vr_min = request.form.get('valor_ref_min', '').strip()
    vr_max = request.form.get('valor_ref_max', '').strip()

    if not nombre:
        flash('El nombre del parámetro es obligatorio.', 'danger')
        return redirect(url_for('param.laboratorio_detalle', examen_id=ex_id))

    p.nombre = nombre
    p.unidad = unidad or None
    p.valor_ref_min = float(vr_min) if vr_min else None
    p.valor_ref_max = float(vr_max) if vr_max else None

    db.session.commit()
    flash('Parámetro actualizado.', 'success')
    return redirect(url_for('param.laboratorio_detalle', examen_id=ex_id))

# ELIMINAR PARÁMETRO
@param_bp.route('/laboratorios/parametro/<int:param_id>/eliminar', methods=['POST'])
@login_required
def laboratorio_parametro_eliminar(param_id):
    p = CatLaboratorioParametro.query.get_or_404(param_id)
    ex_id = p.examen_id
    db.session.delete(p)
    db.session.commit()
    flash('Parámetro eliminado.', 'warning')
    return redirect(url_for('param.laboratorio_detalle', examen_id=ex_id))
