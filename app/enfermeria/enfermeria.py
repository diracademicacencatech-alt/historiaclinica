from ..decorators import roles_requeridos
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from ..models import RegistroEnfermeria, HistoriaClinica, Paciente
from .. import db
from sqlalchemy import or_
from datetime import datetime
import json
from app.utils.fechas import ahora_bogota

enfermeria_bp = Blueprint('enfermeria', __name__)
print("DEBUG rutas enfermeria:", __name__)

@enfermeria_bp.route('/', methods=['GET'])
@login_required
@roles_requeridos('admin', 'medico', 'enfermero')
def listar():
    pacientes = Paciente.query.all()
    historias = HistoriaClinica.query.all()
    return render_template('enfermeria.inicio_enfermeria.html', pacientes=pacientes, historias=historias)


@enfermeria_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    paciente_id = request.args.get('paciente_id')
    if not paciente_id:
        flash('Debe seleccionar un paciente válido.', 'error')
        return redirect(url_for('enfermeria.inicio_enfermeria'))

    historias = (
        HistoriaClinica.query
        .filter_by(paciente_id=paciente_id)
        .order_by(HistoriaClinica.fecha_registro.desc())
        .all()
    )

    if request.method == 'POST':
        # Historia clínica (opcional)
        historia_id_raw = request.form.get('historia_clinica_id')
        historia_id = int(historia_id_raw) if historia_id_raw else None

        # Signos vitales
        signos_vitales_data = {
            "ta": request.form.get('ta') or None,
            "fc": request.form.get('fc') or None,
            "fr": request.form.get('fr') or None,
            "temp": request.form.get('temp') or None,
            "so2": request.form.get('so2') or None,
        }
        signos_vitales_data = {
            k: v for k, v in signos_vitales_data.items() if v not in (None, '')
        }

        # Balance de líquidos
        balance_liquidos_data = {
            "administrados": {
                "hora_inicial": request.form.get('hora_inicial') or None,
                "hora_final": request.form.get('hora_final') or None,
                "liquido": request.form.get('liquido_admin') or None,
                "via": request.form.get('via_admin') or None,
                "cantidad": request.form.get('cantidad_admin') or None,
            },
            "eliminados": {
                "hora_eliminado": request.form.get('hora_eliminado') or None,
                "tipo_liquido": request.form.get('tipo_liquido') or None,
                "via_eliminacion": request.form.get('via_eliminacion') or None,
                "cantidad": request.form.get('cantidad_elim') or None,
                "obs": request.form.get('obs_eliminado') or None,
            },
        }

        for key in ("administrados", "eliminados"):
            balance_liquidos_data[key] = {
                k: v
                for k, v in balance_liquidos_data[key].items()
                if v not in (None, '')
            }

        # Control de glicemia
        cg_raw = request.form.get('control_glicemia')
        if cg_raw in (None, ''):
            cg_value = None
        else:
            try:
                cg_value = float(cg_raw)
            except ValueError:
                cg_value = None

        # Observaciones
        observaciones = request.form.get('observaciones') or None

        # Crear registro
        registro = RegistroEnfermeria(
            paciente_id=int(paciente_id),
            historia_clinica_id=historia_id,
            fecha_registro=ahora_bogota(),
            signos_vitales=json.dumps(signos_vitales_data),
            balance_liquidos=json.dumps(balance_liquidos_data),
            control_glicemia=cg_value,
            observaciones=observaciones,
        )

        db.session.add(registro)
        db.session.commit()
        flash('Registro de enfermería creado correctamente.', 'success')
        return redirect(url_for('enfermeria.inicio_enfermeria'))

    return render_template('enfermeria/crear.html', historias=historias, paciente_id=paciente_id)


@enfermeria_bp.route('/nota/crear', methods=['GET', 'POST'])
@login_required
def crear_nota():
    paciente_id = request.args.get('paciente_id')
    if not paciente_id:
        flash('Debe seleccionar un paciente válido.', 'error')
        return redirect(url_for('enfermeria.inicio_enfermeria'))

    paciente = Paciente.query.get(paciente_id)

    if request.method == 'POST':
        texto = request.form.get('nota') or ''
        flash('Nota de enfermería guardada (pendiente de guardar en BD).', 'success')
        return redirect(url_for('enfermeria.inicio_enfermeria'))

    return render_template('enfermeria/crear_nota.html', paciente=paciente)

print("DEBUG endpoint crear_nota registrado")


@enfermeria_bp.route('/api/buscar_info_paciente', methods=['GET'])
@login_required
def buscar_info_paciente():
    q = request.args.get('q')
    paciente = Paciente.query.filter(
        or_(
            Paciente.numero == q,
            Paciente.nombre.ilike(f"%{q}%"),
            Paciente.id == q,
        )
    ).first()
    if not paciente:
        historia = (
            HistoriaClinica.query.filter_by(numero_ingreso=q)
            .order_by(HistoriaClinica.fecha_registro.desc())
            .first()
        )
        if historia:
            paciente = historia.paciente
        else:
            return jsonify({'error': 'No encontrado'}), 404

    historia = (
        HistoriaClinica.query.filter_by(paciente_id=paciente.id)
        .order_by(HistoriaClinica.fecha_registro.desc())
        .first()
    )

    return jsonify({
        'paciente_id': paciente.id,
        'nombre': paciente.nombre,
        'documento': paciente.numero,
        'cama': paciente.cama or '',
        'ingreso': historia.numero_ingreso if historia else '',
        'fecha_ingreso': (
            historia.fecha_registro.strftime('%Y-%m-%d')
            if historia and historia.fecha_registro else ''
        ),
    })
