from decimal import Decimal
from datetime import datetime, timedelta

import json
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, make_response, send_file
)
from flask_login import login_required

from app.enfermeria import enfermeria_bp
from app.extensions import db
from app.models import (
    RegistroEnfermeria, Paciente, HistoriaClinica,
    AdministracionMedicamento, Medicamento, OrdenMedica,
)
from app.utils.fechas import ahora_bogota
from sqlalchemy import func, text
from collections import defaultdict
from weasyprint import HTML
from io import BytesIO

TURNOS_DISPONIBLES = ['MAÑANA', 'TARDE', 'NOCHE']

def parse_json_seguro(data_str, default=None):
    """Parse JSON seguro con fallback"""
    if not data_str:
        return default or {}
    try:
        data = json.loads(data_str)
        return data if isinstance(data, dict) else default or {}
    except:
        return default or {}

# ---------- AUXILIAR ----------

def obtener_turno_actual():
    """Turnos: Mañana(7-13), Tarde(13-19), Noche(19-6)."""
    ahora = ahora_bogota()
    hora = ahora.hour

    if 7 <= hora < 13:
        return 'mañana'
    elif 13 <= hora < 19:
        return 'tarde'
    else:
        return 'noche'


# ---------- 1) PANTALLA INICIAL: BUSCAR PACIENTE ----------

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


# ---------- 2) AUTOCOMPLETE ----------

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


# ---------- 3) DETALLE REGISTROS DEL DÍA / TURNO ----------

@enfermeria_bp.route('/detalle/<int:paciente_id>')
@login_required
def detalle(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)

    turno_actual = obtener_turno_actual()
    fecha_hoy = ahora_bogota().date()

    registros = (
        RegistroEnfermeria.query
        .filter(
            RegistroEnfermeria.paciente_id == paciente_id,
            db.func.date(RegistroEnfermeria.fecha_registro) == fecha_hoy,
            RegistroEnfermeria.turno == turno_actual
        )
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
        notas=notas,
        turno_actual=turno_actual
    )


# ---------- 4) CREAR REGISTRO SIGNOS / BALANCE ----------

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

    fecha_hoy = ahora_bogota().date()
    turno_real = obtener_turno_actual().upper()
    turno_actual = turno_real

    registros = (
        RegistroEnfermeria.query
        .filter(
            RegistroEnfermeria.paciente_id == paciente_id,
            db.func.date(RegistroEnfermeria.fecha_registro) == fecha_hoy,
            RegistroEnfermeria.turno == turno_actual
        )
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .all()
    )

    total_admin = 0.0
    total_elim = 0.0

    for r in registros:
        # signos
        try:
            sv = json.loads(r.signos_vitales or '{}')
            if not isinstance(sv, dict):
                sv = {}
        except Exception:
            sv = {}
        r.sv = sv

        # balance
        try:
            bl = json.loads(r.balance_liquidos or '{}')
            if not isinstance(bl, dict):
                bl = {}
        except Exception:
            bl = {}
        r.bl_admin = bl.get("administrados", {}) or {}
        r.bl_elim = bl.get("eliminados", {}) or {}

        # totales balance
        try:
            cant_a = float(r.bl_admin.get("cantidad") or 0)
            total_admin += cant_a
        except Exception:
            pass

        try:
            cant_e = float(r.bl_elim.get("cantidad") or 0)
            total_elim += cant_e
        except Exception:
            pass

    balance_total = total_admin - total_elim

    if request.method == 'POST':
        historia_id = request.form.get('historia_clinica_id')
        turno_form = (request.form.get('turno') or turno_real).upper()

        if turno_form != turno_real:
            flash(
                f'No puede registrar turno {turno_form} fuera de su horario. '
                f'El turno válido en este momento es {turno_real}.',
                'warning'
            )
            return redirect(url_for('enfermeria.crear', paciente_id=paciente_id))

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
            turno=turno_form,
            signos_vitales=json.dumps(signos_vitales_data),
            balance_liquidos=json.dumps(balance_liquidos_data),
            control_glicemia=request.form.get('control_glicemia'),
            observaciones=request.form.get('observaciones'),
        )
        db.session.add(registro)
        db.session.commit()
        flash('Registro creado correctamente.', 'success')
        return redirect(url_for('enfermeria.crear', paciente_id=paciente_id))

    return render_template(
        'enfermeria/crear.html',
        historias=historias,
        paciente_id=paciente_id,
        registros=registros,
        total_admin=total_admin,
        total_elim=total_elim,
        balance_total=balance_total,
        turno_actual=turno_actual,
        turnos=TURNOS_DISPONIBLES,
        fecha_hoy=fecha_hoy
    )


# ---------- 4.b) ELIMINAR REGISTRO COMPLETO ----------

@enfermeria_bp.route('/registro/<int:registro_id>/eliminar', methods=['POST'])
@login_required
def eliminar_registro_enfermeria(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    paciente_id = registro.paciente_id

    db.session.delete(registro)
    db.session.commit()
    flash('Registro de enfermería eliminado.', 'success')

    return redirect(url_for('enfermeria.registros_paciente', paciente_id=paciente_id))


@enfermeria_bp.route('/registro/<int:registro_id>/eliminar_signos', methods=['POST'])
@login_required
def eliminar_signos_enfermeria(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    paciente_id = registro.paciente_id

    registro.signos_vitales = json.dumps({})
    registro.control_glicemia = None

    db.session.commit()
    flash('Signos vitales eliminados del registro.', 'success')
    return redirect(url_for('enfermeria.registros_paciente', paciente_id=paciente_id))


@enfermeria_bp.route('/registro/<int:registro_id>/eliminar_balance', methods=['POST'])
@login_required
def eliminar_balance_enfermeria(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    paciente_id = registro.paciente_id

    registro.balance_liquidos = json.dumps({})

    db.session.commit()
    flash('Balance de líquidos eliminado del registro.', 'success')
    return redirect(url_for('enfermeria.registros_paciente', paciente_id=paciente_id))


@enfermeria_bp.route('/registro/<int:registro_id>/eliminar_nota', methods=['POST'])
@login_required
def eliminar_nota_enfermeria(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    paciente_id = registro.paciente_id

    registro.tipo_nota = None
    registro.texto_nota = None

    db.session.commit()
    flash('Nota de enfermería eliminada del registro.', 'success')
    return redirect(url_for('enfermeria.registros_paciente', paciente_id=paciente_id))


# ---------- 5) ADMINISTRAR MEDICAMENTOS POR REGISTRO ----------

@enfermeria_bp.route('/registro/<int:registro_id>/medicamentos', methods=['GET', 'POST'])
@login_required
def administrar_medicamentos(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)

    # --- POST: GUARDAR con HORA EDITABLE ---
    if request.method == 'POST' and 'codigo_medicamento' in request.form:
        codigo = request.form['codigo_medicamento']
        cantidad = request.form['cantidad']
        hora_str = request.form.get('hora_administracion', '') or ahora_bogota().strftime('%Y-%m-%dT%H:%M')
        unidad = request.form.get('unidad', 'tab')
        via = request.form.get('via', 'VO')
        observaciones = request.form.get('observaciones', '')

        try:
            cantidad_dec = Decimal(cantidad)
            med = Medicamento.query.filter_by(codigo=codigo).first()
            if not med:
                flash('❌ Medicamento no encontrado', 'danger')
                return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))

            # HORA EDITABLE o actual
            if hora_str:
                hora_admin = datetime.strptime(hora_str, '%Y-%m-%dT%H:%M')
            else:
                hora_admin = ahora_bogota()

            admin = AdministracionMedicamento(
                registro_enfermeria_id=registro.id,
                medicamento_id=med.id,
                cantidad=cantidad_dec,
                unidad=unidad,
                via=via,
                observaciones=observaciones,
                hora_administracion=hora_admin
            )
            db.session.add(admin)
            db.session.commit()
            flash(f'✅ {codigo} x{cantidad_dec} a las {hora_admin.strftime("%H:%M")}', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error: {str(e)}', 'danger')

        return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))

    # --- GET: TODO IGUAL QUE FUNCIONABA ---
    medicamentos_formulados = []
    if registro.historia_clinica_id:
        historia_id = registro.historia_clinica_id
        todos_medicamentos = []
        
        # Historia
        historia = HistoriaClinica.query.get(historia_id)
        if historia and historia.medicamentos_json:
            try:
                bruto = json.loads(historia.medicamentos_json)
                if isinstance(bruto, list):
                    todos_medicamentos.extend(bruto)
            except:
                pass
        
        # Órdenes
        ordenes = OrdenMedica.query.filter_by(historia_id=historia_id).all()
        for orden in ordenes:
            if orden.medicamentos_json:
                try:
                    meds = json.loads(orden.medicamentos_json)
                    if isinstance(meds, list):
                        todos_medicamentos.extend(meds)
                except:
                    pass
        
        # Agrupar por código
        meds_por_codigo = defaultdict(lambda: {'total': 0, 'detalle': {}})
        for med in todos_medicamentos:
            codigo = med.get('codigo', '')
            if codigo:
                meds_por_codigo[codigo]['total'] += float(med.get('cantidad_solicitada', 0))
                meds_por_codigo[codigo]['detalle'].update({
                    'dosis': med.get('dosis', ''),
                    'frecuencia': med.get('frecuencia', ''),
                    'unidad_inventario': med.get('unidad_inventario', 'tab')
                })
        
        # Calcular pendientes
        for codigo, data in meds_por_codigo.items():
            formulada = Decimal(str(data['total']))
            
            admin_total = db.session.query(
                db.func.coalesce(db.func.sum(AdministracionMedicamento.cantidad), 0)
            ).join(Medicamento).filter(
                AdministracionMedicamento.registro_enfermeria_id == registro.id,
                Medicamento.codigo == codigo
            ).scalar()
            
            admin_total = Decimal(str(admin_total))
            pendiente = max(formulada - admin_total, Decimal('0'))
            
            medicamentos_formulados.append({
                'codigo': codigo,
                'dosis': data['detalle'].get('dosis', ''),
                'frecuencia': data['detalle'].get('frecuencia', ''),
                'cantidad_formulada': formulada,
                'cantidad_administrada': admin_total,
                'pendiente': pendiente,
                'unidad': data['detalle'].get('unidad_inventario', 'tab')
            })

    # Administraciones
    administraciones = AdministracionMedicamento.query.filter_by(
        registro_enfermeria_id=registro.id
    ).outerjoin(Medicamento).order_by(
        AdministracionMedicamento.hora_administracion.desc()
    ).limit(20).all()

    # HORA ACTUAL para formulario
    hora_actual = ahora_bogota().strftime('%Y-%m-%dT%H:%M')

    return render_template('enfermeria/administrar_medicamentos.html',
                         registro=registro,
                         medicamentos_formulados=medicamentos_formulados,
                         administraciones=administraciones,
                         hora_actual=hora_actual)

# ---------- 5.bis) DESDE MENÚ PACIENTE -> ÚLTIMO REGISTRO PARA MEDICAMENTOS ----------

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


# ---------- 6) BUSCAR PACIENTE JSON ----------

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


# ---------- 7) EXPORTAR PDF ----------
@enfermeria_bp.route('/paciente/<int:paciente_id>/exportar_pdf', methods=['GET'])
@login_required
def exportar_pdf(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    
    registros = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .all()
    )

    # 🔥 TU CÓDIGO ORIGINAL - Signos vitales
    for r in registros:
        try:
            sv = json.loads(r.signos_vitales or '{}')
            if not isinstance(sv, dict):
                sv = {}
        except Exception:
            sv = {}
        r.signos_vitales_dict = {
            "ta": sv.get("ta") or "",
            "fc": sv.get("fc") or "",
            "fr": sv.get("fr") or "",
            "temp": sv.get("temp") or "",
            "so2": sv.get("so2") or ""
        }

        # 🔥 TU CÓDIGO ORIGINAL - Balance líquidos
        try:
            bl = json.loads(r.balance_liquidos or '{}')
            if not isinstance(bl, dict):
                bl = {"administrados": {}, "eliminados": {}}
        except Exception:
            bl = {"administrados": {}, "eliminados": {}}
        r.balance_liquidos_dict = bl

    # 🔥 TU CÓDIGO ORIGINAL - Medicamentos
    medicamentos = []
    if registros:
        registro_ids = [r.id for r in registros]
        medicamentos = db.session.query(AdministracionMedicamento).filter(
            AdministracionMedicamento.registro.has(RegistroEnfermeria.id.in_(registro_ids))
        ).order_by(
            AdministracionMedicamento.hora_administracion.desc()
        ).limit(50).all()

    data = {
        'paciente': paciente,
        'registros': registros,
        'medicamentos': medicamentos,
        'fecha_generacion': datetime.now().strftime('%d/%m/%Y %H:%M')
    }
    
    html_string = render_template('enfermeria/pdf_enfermeria_limpio.html', **data)
    
    from weasyprint import HTML
    from io import BytesIO
    
    pdf_file = BytesIO()
    HTML(string=html_string).write_pdf(pdf_file)
    pdf_file.seek(0)
    
    return send_file(
        pdf_file,
        as_attachment=True,
        download_name=f"Registros_Enfermeria_{paciente.numero}.pdf",
        mimetype='application/pdf'
    )

# ---------- 8) API INFO PACIENTE ----------

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


# ---------- 9) CREAR NOTA ----------

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


# ---------- 10) MENÚ PACIENTE ----------

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


# ---------- 11) ADMINISTRACIÓN DE MEDICAMENTOS: CRUD ----------

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
        hora_administracion=ahora_bogota(),
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

    if admin.medicamento:
        diff = nueva_cantidad_dec - admin.cantidad
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


# ---------- 12) LISTADO DE REGISTROS POR PACIENTE ----------

@enfermeria_bp.route('/paciente/<int:paciente_id>/registros')
@login_required
def registros_paciente(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    registros = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .all()
    )

    # TU CÓDIGO ORIGINAL - Signos vitales
    for r in registros:
        try:
            sv = json.loads(r.signos_vitales or '{}')
            if not isinstance(sv, dict):
                sv = {}
        except Exception:
            sv = {}
        r.signos_vitales_dict = {
            "ta": sv.get("ta") or "",
            "fc": sv.get("fc") or "",
            "fr": sv.get("fr") or "",
            "temp": sv.get("temp") or "",
            "so2": sv.get("so2") or ""
        }

        # TU CÓDIGO ORIGINAL - Balance líquidos
        try:
            bl = json.loads(r.balance_liquidos or '{}')
            if not isinstance(bl, dict):
                bl = {"administrados": {}, "eliminados": {}}
        except Exception:
            bl = {"administrados": {}, "eliminados": {}}
        r.balance_liquidos_dict = bl

    # CORREGIDO: Medicamentos administrados
    medicamentos = []
    if registros:
        registro_ids = [r.id for r in registros]
        medicamentos = db.session.query(AdministracionMedicamento).filter(
            AdministracionMedicamento.registro.has(RegistroEnfermeria.id.in_(registro_ids))
        ).order_by(
            AdministracionMedicamento.hora_administracion.desc()
        ).limit(50).all()

    return render_template(
        'enfermeria/registros_paciente.html',
        paciente=paciente,
        registros=registros,
        medicamentos=medicamentos
    )

@enfermeria_bp.route('/debug/ordenes/<int:historia_id>')
@login_required
def debug_ordenes(historia_id):
    ordenes = OrdenMedica.query.filter_by(historia_id=historia_id).all()
    lineas = [f"Total órdenes: {len(ordenes)}"]
    for o in ordenes:
        lineas.append(f"---- ORDEN {o.id} ----")
        lineas.append(f"indicaciones_medicas: {o.indicaciones_medicas}")
        lineas.append(f"medicacion_texto: {o.medicacion_texto}")
        lineas.append(f"medicamentos_json: {o.medicamentos_json}")
    return "<br>".join(lineas)

def obtener_medicamentos_ordenes(historia_id):
    """Devuelve una lista de dicts con medicamentos provenientes de OrdenMedica.medicamentos_json."""
    resultados = []

    ordenes = OrdenMedica.query.filter_by(historia_id=historia_id).order_by(OrdenMedica.id.asc()).all()
    for orden in ordenes:
        if not orden.medicamentos_json:
            continue
        try:
            bruto = json.loads(orden.medicamentos_json)
        except Exception:
            continue

        # Aquí asumimos que bruto es una lista de medicamentos; si no, se ajusta luego
        if isinstance(bruto, list):
            for item in bruto:
                resultados.append(item)
        elif isinstance(bruto, dict):
            # Si el JSON tuviera una clave tipo {"medicamentos":[...]}
            meds = bruto.get("medicamentos") or []
            if isinstance(meds, list):
                resultados.extend(meds)

    return resultados

def administrar_medicamentos(historia_id):
    """
    Carga medicamentos de órdenes médicas en AdministracionMedicamento.
    """
    # 1. OBTENER medicamentos de TODAS las órdenes
    ordenes = OrdenMedica.query.filter_by(historia_id=historia_id).all()
    medicamentos_ordenes = []
    
    for orden in ordenes:
        if orden.medicamentos_json:
            try:
                meds_json = json.loads(orden.medicamentos_json)
                medicamentos_ordenes.extend(meds_json)
            except json.JSONDecodeError:
                print(f"⚠️ JSON inválido en orden {orden.id}")
    
    # 2. ELIMINAR administraciones anteriores de órdenes para esta historia
    # Buscar registros de enfermería de esta historia
    registros_historia = RegistroEnfermeria.query.filter_by(historia_clinica_id=historia_id).all()
    registro_ids = [r.id for r in registros_historia]
    
    if registro_ids:
        eliminados = AdministracionMedicamento.query.filter(
            AdministracionMedicamento.registro_enfermeria_id.in_(registro_ids)
        ).delete()
        print(f"🗑️ Eliminados {eliminados} administraciones anteriores")
    
    # 3. Crear un registro enfermería temporal para las órdenes
    # Buscar paciente de la historia
    historia = HistoriaClinica.query.get(historia_id)
    if not historia or not historia.paciente_id:
        print("❌ No se encontró historia o paciente válido")
        return {'error': 'Historia no válida'}
    
    registro_temp = RegistroEnfermeria(
        paciente_id=historia.paciente_id,
        historia_clinica_id=historia_id,
        fecha_registro=ahora_bogota(),
        turno='ÓRDENES_MEDICAS'
    )
    db.session.add(registro_temp)
    db.session.flush()  # Obtener ID
    
    # 4. INSERTAR medicamentos como administraciones
    insertados = 0
    for med in medicamentos_ordenes:
        codigo = med.get('codigo', '')
        med_obj = Medicamento.query.filter_by(codigo=codigo).first()
        if med_obj:
            admin = AdministracionMedicamento(
                registro_enfermeria_id=registro_temp.id,
                medicamento_id=med_obj.id,
                cantidad=Decimal('0'),  # Pendiente de administrar
                unidad=med.get('unidad_inventario', 'tab'),
                via=med.get('via_administracion', 'VO'),
                observaciones=f"{med.get('dosis', '')} - {med.get('frecuencia', '')}",
                hora_administracion=ahora_bogota()
            )
            db.session.add(admin)
            insertados += 1
    
    db.session.commit()
    
    print(f"✅ Historia {historia_id}: {insertados}/{len(medicamentos_ordenes)} medicamentos cargados")
    
    return {
        'ordenes': len(medicamentos_ordenes),
        'insertados': insertados,
        'registro_id': registro_temp.id
    }
def cargar_medicamentos_ordenes(historia_id):
    """
    Carga medicamentos de órdenes médicas como administraciones PENDIENTES.
    NO borra nada existente.
    """
    # Obtener historia y paciente
    historia = HistoriaClinica.query.get(historia_id)
    if not historia:
        print("❌ Historia no encontrada")
        return {'error': 'Historia no existe'}
    
    # Obtener medicamentos de TODAS las órdenes
    ordenes = OrdenMedica.query.filter_by(historia_id=historia_id).all()
    medicamentos_ordenes = []
    
    for orden in ordenes:
        if orden.medicamentos_json:
            try:
                meds = json.loads(orden.medicamentos_json)
                medicamentos_ordenes.extend(meds)
            except:
                continue
    
    if not medicamentos_ordenes:
        print("❌ No hay medicamentos en órdenes")
        return {'error': 'Sin medicamentos en órdenes'}
    
    # Crear registro temporal
    registro = RegistroEnfermeria(
        paciente_id=historia.paciente_id,
        historia_clinica_id=historia_id,
        fecha_registro=ahora_bogota(),
        turno='ÓRDENES'
    )
    db.session.add(registro)
    db.session.flush()
    
    # Agregar cada medicamento
    count = 0
    for med in medicamentos_ordenes:
        medicamento = Medicamento.query.filter_by(codigo=med.get('codigo')).first()
        if medicamento:
            admin = AdministracionMedicamento(
                registro_enfermeria_id=registro.id,
                medicamento_id=medicamento.id,
                cantidad=Decimal('0'),  # Pendiente
                unidad=med.get('unidad_inventario', 'tab'),
                via=med.get('via_administracion', 'VO'),
                observaciones=f"{med.get('dosis')} {med.get('frecuencia')}"
            )
            db.session.add(admin)
            count += 1
    
    db.session.commit()
    
    print(f"✅ {count} medicamentos cargados en registro {registro.id}")
    return {'exito': count, 'registro_id': registro.id}

@enfermeria_bp.route('/debug/cargar_ordenes/<int:historia_id>')
@login_required
def debug_cargar_ordenes(historia_id):
    resultado = cargar_medicamentos_ordenes(historia_id)
    flash(f'Cargados {resultado.get("exito", 0)} medicamentos de órdenes médicas', 'success')
    # Redirigir al paciente
    historia = HistoriaClinica.query.get(historia_id)
    if historia:
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=historia.paciente_id))
    return "Historia no encontrada"


