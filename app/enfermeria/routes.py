from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, make_response
)
from flask_login import login_required
from datetime import datetime
from weasyprint import HTML
from decimal import Decimal
import json

from app.enfermeria import enfermeria_bp
from app.extensions import db
from app.models import (
    RegistroEnfermeria, Paciente, HistoriaClinica,
    AdministracionMedicamento, Medicamento
)
from datetime import datetime, timedelta
from app.utils.fechas import ahora_bogota

# 1) PANTALLA INICIAL: BUSCAR PACIENTE
@enfermeria_bp.route('/', methods=['GET', 'POST'])
@login_required
def inicio_enfermeria():
    if request.method == 'POST':
        criterio = request.form.get('criterio', '').strip()
        if not criterio:
            flash('Ingrese un nombre, documento o número de ingreso.', 'warning')
            return redirect(url_for('enfermeria.inicio_enfermeria'))

        ids_validos = [h.paciente_id for h in HistoriaClinica.query.all()]
        pacientes = (
            Paciente.query
            .filter(Paciente.id.in_(ids_validos))
            .filter(
                (Paciente.numero.ilike(f"%{criterio}%")) |
                (Paciente.nombre.ilike(f"%{criterio}%"))
            )
            .order_by(Paciente.nombre.asc())
            .all()
        )

        if not pacientes:
            flash('No se encontraron pacientes con ese criterio.', 'info')
            return redirect(url_for('enfermeria.inicio_enfermeria'))

        if len(pacientes) == 1:
            return redirect(url_for('enfermeria.menu_paciente',
                                    paciente_id=pacientes[0].id))

        return render_template(
            'enfermeria/inicio_enfermeria.html',
            pacientes=pacientes,
            criterio=criterio
        )

    return render_template('enfermeria/buscar_paciente.html')


# 2) AUTOCOMPLETE
@enfermeria_bp.route('/autocomplete', methods=['GET'])
@login_required
def autocomplete_pacientes():
    termino = request.args.get('q', '').strip()
    if not termino:
        return jsonify([])

    ids_validos = [h.paciente_id for h in HistoriaClinica.query.all()]

    pacientes = (
        Paciente.query
        .filter(Paciente.id.in_(ids_validos))
        .filter(
            (Paciente.nombre.ilike(f"%{termino}%")) |
            (Paciente.numero.ilike(f"%{termino}%"))
        )
        .order_by(Paciente.nombre.asc())
        .limit(10)
        .all()
    )

    datos = [
        {"id": p.id, "nombre": p.nombre, "numero": p.numero}
        for p in pacientes
    ]
    return jsonify(datos)


# 3) DETALLE REGISTROS
@enfermeria_bp.route('/detalle/<int:paciente_id>')
@login_required
def detalle(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)

    registros = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .all()
    )

    for r in registros:
        try:
            sv = json.loads(r.signos_vitales or '{}')
            if not isinstance(sv, dict):
                sv = {}
        except Exception:
            sv = {}
        r.signos_vitales_dict = sv

        try:
            bl = json.loads(r.balance_liquidos or '{}')
            if not isinstance(bl, dict):
                bl = {}
        except Exception:
            bl = {}

        bl.setdefault('administrados', {})
        bl.setdefault('eliminados', {})
        r.balance_liquidos_dict = bl

    notas = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .filter(RegistroEnfermeria.tipo_nota.isnot(None))
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .limit(5)
        .all()
    )

    return render_template(
        'enfermeria/registro_detalle.html',
        paciente=paciente,
        registros=registros,
        notas=notas
    )


# 4) CREAR REGISTRO
@enfermeria_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    paciente_id = request.args.get('paciente_id')
    if not paciente_id:
        flash('Debe seleccionar un paciente válido.', 'error')
        return redirect(url_for('enfermeria.inicio_enfermeria'))

    # Historias clínicas del paciente
    historias = (
        HistoriaClinica.query
        .filter_by(paciente_id=paciente_id)
        .order_by(HistoriaClinica.fecha_registro.desc())
        .all()
    )

    # Registros previos
    registros = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .all()
    )

    # Descomponer JSON y acumular balance
    total_admin = 0.0
    total_elim = 0.0

    for r in registros:
        # signos vitales
        try:
            sv = json.loads(r.signos_vitales or '{}')
            if not isinstance(sv, dict):
                sv = {}
        except Exception:
            sv = {}
        r.sv = sv

        # balance de líquidos
        try:
            bl = json.loads(r.balance_liquidos or '{}')
            if not isinstance(bl, dict):
                bl = {}
        except Exception:
            bl = {}
        r.bl_admin = bl.get("administrados", {}) or {}
        r.bl_elim = bl.get("eliminados", {}) or {}

        # acumular administrados
        try:
            cant_a = float(r.bl_admin.get("cantidad") or 0)
            total_admin += cant_a
        except Exception:
            pass

        # acumular eliminados
        try:
            cant_e = float(r.bl_elim.get("cantidad") or 0)
            total_elim += cant_e
        except Exception:
            pass

    balance_total = total_admin - total_elim

    if request.method == 'POST':
        historia_id = request.form.get('historia_clinica_id')

        signos_vitales_data = {
            "ta": request.form.get('ta'),
            "fc": request.form.get('fc'),
            "fr": request.form.get('fr'),
            "temp": request.form.get('temp'),
            "so2": request.form.get('so2')
        }

        balance_liquidos_data = {
            "administrados": {
                "hora_inicial": request.form.get('hora_inicial'),
                "hora_final": request.form.get('hora_final'),
                "liquido": request.form.get('liquido_admin'),
                "via": request.form.get('via_admin'),
                "cantidad": request.form.get('cantidad_admin')
            },
            "eliminados": {
                "hora_eliminado": request.form.get('hora_eliminado'),
                "tipo_liquido": request.form.get('tipo_liquido'),
                "via_eliminacion": request.form.get('via_eliminacion'),
                "cantidad": request.form.get('cantidad_elim'),
                "obs": request.form.get('obs_eliminado')
            }
        }

        registro = RegistroEnfermeria(
            paciente_id=paciente_id,
            historia_clinica_id=historia_id,
            signos_vitales=json.dumps(signos_vitales_data),
            balance_liquidos=json.dumps(balance_liquidos_data),
            control_glicemia=request.form.get('control_glicemia'),
            observaciones=request.form.get('observaciones'),
        )
        db.session.add(registro)
        db.session.commit()
        flash('Registro creado correctamente.', 'success')
        return redirect(url_for('enfermeria.menu_paciente',
                                paciente_id=paciente_id))

    return render_template(
        'enfermeria/crear.html',
        historias=historias,
        paciente_id=paciente_id,
        registros=registros,
        total_admin=total_admin,
        total_elim=total_elim,
        balance_total=balance_total
    )

@enfermeria_bp.route('/registro/<int:registro_id>/eliminar', methods=['POST'])
@login_required
def eliminar_registro_enfermeria(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    paciente_id = registro.paciente_id

    db.session.delete(registro)
    db.session.commit()
    flash('Registro de enfermería eliminado.', 'success')

    return redirect(url_for('enfermeria.crear', paciente_id=paciente_id))

# 5) ADMINISTRAR MEDICAMENTOS POR REGISTRO
@enfermeria_bp.route('/registro/<int:registro_id>/medicamentos', methods=['GET', 'POST'])
@login_required
def administrar_medicamentos(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)

    # POST: registrar nueva administración
    if request.method == 'POST' and 'codigo_medicamento' in request.form:
        codigo = request.form.get('codigo_medicamento')
        cantidad = request.form.get('cantidad')
        unidad = request.form.get('unidad')
        via = request.form.get('via')
        observaciones = request.form.get('observaciones')

        if not codigo or not cantidad:
            flash('Debe seleccionar un medicamento y una cantidad.', 'danger')
            return redirect(url_for('enfermeria.administrar_medicamentos',
                                    registro_id=registro_id))

        try:
            cantidad_decimal = Decimal(str(cantidad))
        except Exception:
            flash('Cantidad inválida.', 'danger')
            return redirect(url_for('enfermeria.administrar_medicamentos',
                                    registro_id=registro_id))

        try:
            registrar_administracion_enfermeria(
                registro_enfermeria_id=registro.id,
                codigo_medicamento=codigo,
                cantidad=cantidad_decimal,
                unidad=unidad,
                via=via,
                observaciones=observaciones
            )
            flash('Administración registrada.', 'success')
        except ValueError as e:
            flash(str(e), 'danger')

        return redirect(url_for('enfermeria.administrar_medicamentos',
                                registro_id=registro_id))

    # GET: cargar historia y medicamentos
    historia = None
    medicamentos_formulados = []

    if registro.historia_clinica_id:
        historia = HistoriaClinica.query.get(registro.historia_clinica_id)
        if historia and getattr(historia, 'medicamentos_json', None):
            try:
                bruto = json.loads(historia.medicamentos_json)
                if isinstance(bruto, list):
                    for item in bruto:
                        codigo = item.get("codigo") or ""
                        cantidad_formulada = Decimal(str(item.get("cantidad_solicitada") or 0))

                        med_model = Medicamento.query.filter_by(codigo=codigo).first()
                        admins_q = AdministracionMedicamento.query
                        if med_model:
                            admins_q = admins_q.filter_by(
                                registro_enfermeria_id=registro.id,
                                medicamento_id=med_model.id
                            )
                            total_admin = sum((a.cantidad for a in admins_q.all()), Decimal('0'))
                        else:
                            total_admin = Decimal('0')

                        pendiente = cantidad_formulada - total_admin
                        if pendiente < 0:
                            pendiente = Decimal('0')

                        medicamentos_formulados.append({
                            "codigo": codigo,
                            "dosis": item.get("dosis") or "",
                            "frecuencia": item.get("frecuencia") or "",
                            "cantidad_formulada": cantidad_formulada,
                            "cantidad_administrada": total_admin,
                            "pendiente": pendiente,
                            "unidad": item.get("unidad_inventario") or "",
                        })
            except Exception:
                medicamentos_formulados = []

    administraciones = (
        AdministracionMedicamento.query
        .filter_by(registro_enfermeria_id=registro.id)
        .order_by(AdministracionMedicamento.hora_administracion.desc())
        .limit(20)
        .all()
    )

    edit_id = request.args.get('edit_id', type=int)

    return render_template(
        'enfermeria/administrar_medicamentos.html',
        registro=registro,
        historia=historia,
        medicamentos_formulados=medicamentos_formulados,
        administraciones=administraciones,
        edit_id=edit_id
    )

# 5.bis) DESDE MENÚ PACIENTE -> ÚLTIMO REGISTRO PARA MEDICAMENTOS
@enfermeria_bp.route('/paciente/<int:paciente_id>/medicamentos')
@login_required
def administrar_medicamentos_paciente(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)

    registro = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .first()
    )

    if not registro:
        historia = (
            HistoriaClinica.query
            .filter_by(paciente_id=paciente_id)
            .order_by(HistoriaClinica.fecha_registro.desc())
            .first()
        )

        registro = RegistroEnfermeria(
            paciente_id=paciente_id,
            historia_clinica_id=historia.id if historia else None,
            fecha_registro=datetime.now(),
            signos_vitales=json.dumps({}),
            balance_liquidos=json.dumps({}),
            control_glicemia=None,
            observaciones=None,
        )
        db.session.add(registro)
        db.session.commit()

    return redirect(url_for('enfermeria.administrar_medicamentos',
                            registro_id=registro.id))

# 6) BUSCAR PACIENTE JSON
@enfermeria_bp.route('/buscar_paciente_json/<identificacion>')
@login_required
def buscar_paciente_json(identificacion):
    paciente = Paciente.query.filter_by(numero=identificacion).first()
    if paciente:
        return jsonify({
            'nombre': paciente.nombre,
            'apellido': getattr(paciente, 'apellido', ''),
            'paciente_id': paciente.id
        })
    return jsonify({'error': 'Paciente no encontrado'}), 404


# 7) EXPORTAR PDF
@enfermeria_bp.route('/pdf/<int:paciente_id>')
@login_required
def exportar_pdf(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    registros = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .all()
    )

    for r in registros:
        try:
            sv = json.loads(r.signos_vitales or '{}')
            if not isinstance(sv, dict):
                sv = {}
        except Exception:
            sv = {}
        r.signos_vitales_dict = {
            "ta": sv.get("ta") or "N/A",
            "fc": sv.get("fc") or "N/A",
            "fr": sv.get("fr") or "N/A",
            "temp": sv.get("temp") or "N/A",
            "so2": sv.get("so2") or "N/A"
        }

        try:
            bl = json.loads(r.balance_liquidos or '{}')
            if not isinstance(bl, dict):
                bl = {"administrados": {}, "eliminados": {}}
        except Exception:
            bl = {"administrados": {}, "eliminados": {}}
        r.balance_liquidos_dict = bl

    html = render_template(
        'enfermeria/pdf_enfermeria.html',
        paciente=paciente,
        registros=registros
    )
    pdf = HTML(string=html).write_pdf()

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = (
        f'inline; filename=registro_enfermeria_{paciente_id}.pdf'
    )
    return response


# 8) API INFO PACIENTE
@enfermeria_bp.route('/api/buscar_info_paciente', methods=['GET'])
@login_required
def buscar_info_paciente():
    q = request.args.get('q')
    paciente = Paciente.query.filter(
        (Paciente.numero == q) |
        (Paciente.nombre.ilike(f"%{q}%"))
    ).first()
    if not paciente:
        historia = (
            HistoriaClinica.query
            .filter_by(numero_ingreso=q)
            .order_by(HistoriaClinica.fecha_registro.desc())
            .first()
        )
        if historia:
            paciente = historia.paciente
        else:
            return jsonify({'error': 'No encontrado'}), 404

    historia = (
        HistoriaClinica.query
        .filter_by(paciente_id=paciente.id)
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


# 9) CREAR NOTA
@enfermeria_bp.route('/nota/crear', methods=['GET', 'POST'])
@login_required
def crear_nota():
    paciente_id = request.args.get('paciente_id')
    if not paciente_id:
        flash('Debe seleccionar un paciente válido.', 'error')
        return redirect(url_for('enfermeria.inicio_enfermeria'))

    paciente = Paciente.query.get(paciente_id)

    historias = (
        HistoriaClinica.query
        .filter_by(paciente_id=paciente_id)
        .order_by(HistoriaClinica.fecha_registro.desc())
        .all()
    )

    if request.method == 'POST':
        tipo_nota = request.form.get('tipo_nota') or None
        texto_nota = request.form.get('nota') or None
        historia_id_raw = request.form.get('historia_clinica_id')
        historia_id = int(historia_id_raw) if historia_id_raw else None

        if not tipo_nota or not texto_nota:
            flash('Debe seleccionar un tipo de nota y escribir el contenido.', 'error')
            return redirect(url_for('enfermeria.crear_nota',
                                    paciente_id=paciente_id))

        registro = RegistroEnfermeria(
            paciente_id=int(paciente_id),
            historia_clinica_id=historia_id,
            fecha_registro=datetime.now(),
            signos_vitales=json.dumps({}),
            balance_liquidos=json.dumps({}),
            control_glicemia=None,
            observaciones=None,
            tipo_nota=tipo_nota,
            texto_nota=texto_nota,
        )

        db.session.add(registro)
        db.session.commit()
        flash('Nota de enfermería creada correctamente.', 'success')
        return redirect(url_for('enfermeria.menu_paciente',
                                paciente_id=paciente_id))

    return render_template(
        'enfermeria/crear_nota.html',
        paciente=paciente,
        historias=historias
    )


# 10) MENÚ PACIENTE
@enfermeria_bp.route('/paciente/<int:paciente_id>/menu')
@login_required
def menu_paciente(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)

    notas = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .filter(RegistroEnfermeria.tipo_nota.isnot(None))
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .limit(5)
        .all()
    )

    return render_template(
        'enfermeria/menu_paciente.html',
        paciente=paciente,
        notas=notas
    )


# FUNCIÓN AUXILIAR: REGISTRAR ADMINISTRACIÓN
def registrar_administracion_enfermeria(registro_enfermeria_id, codigo_medicamento,
                                        cantidad, unidad, via, observaciones=None):
    med = Medicamento.query.filter_by(codigo=codigo_medicamento).first()
    if not med:
        raise ValueError(f"Medicamento {codigo_medicamento} no encontrado")

    admin = AdministracionMedicamento(
        registro_enfermeria_id=registro_enfermeria_id,
        medicamento_id=med.id,
        cantidad=cantidad,
        unidad=unidad,
        via=via,
        observaciones=observaciones,
        hora_administracion=datetime.now(ahora_bogota),
    )
    db.session.add(admin)

    med.cantidad_disponible = (med.cantidad_disponible or 0) - Decimal(str(cantidad))
    if med.cantidad_disponible < 0:
        med.cantidad_disponible = 0

    db.session.commit()

@enfermeria_bp.route('/administracion/<int:admin_id>/eliminar', methods=['POST'])
@login_required
def eliminar_administracion_medicamento(admin_id):
    admin = AdministracionMedicamento.query.get_or_404(admin_id)
    registro_id = admin.registro_enfermeria_id

    if admin.medicamento:
        admin.medicamento.cantidad_disponible = (
            (admin.medicamento.cantidad_disponible or 0) + admin.cantidad
        )

    db.session.delete(admin)
    db.session.commit()
    flash('Administración eliminada.', 'success')
    return redirect(url_for('enfermeria.administrar_medicamentos',
                            registro_id=registro_id))

@enfermeria_bp.route('/administracion/<int:admin_id>/editar', methods=['POST'])
@login_required
def editar_administracion_medicamento(admin_id):
    admin = AdministracionMedicamento.query.get_or_404(admin_id)
    registro_id = admin.registro_enfermeria_id

    nueva_cantidad = request.form.get('cantidad')
    nueva_unidad = request.form.get('unidad')
    nueva_via = request.form.get('via')
    nuevas_obs = request.form.get('observaciones')

    try:
        nueva_cantidad_dec = Decimal(str(nueva_cantidad))
    except Exception:
        flash('Cantidad inválida al editar.', 'danger')
        return redirect(url_for('enfermeria.administrar_medicamentos',
                                registro_id=registro_id))

    # ajustar inventario: revertir la cantidad anterior y aplicar la nueva
    if admin.medicamento:
        diff = nueva_cantidad_dec - admin.cantidad  # si positivo: se descuenta más
        admin.medicamento.cantidad_disponible = (
            (admin.medicamento.cantidad_disponible or 0) - diff
        )
        if admin.medicamento.cantidad_disponible < 0:
            admin.medicamento.cantidad_disponible = 0

    admin.cantidad = nueva_cantidad_dec
    admin.unidad = nueva_unidad
    admin.via = nueva_via
    admin.observaciones = nuevas_obs

    db.session.commit()
    flash('Administración modificada.', 'success')
    return redirect(url_for('enfermeria.administrar_medicamentos',
                            registro_id=registro_id))

@enfermeria_bp.route('/paciente/<int:paciente_id>/registros')
def registros_paciente(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    registros = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .all()
    )
    return render_template(
        'enfermeria/registros_paciente.html',
        paciente=paciente,
        registros=registros
    )