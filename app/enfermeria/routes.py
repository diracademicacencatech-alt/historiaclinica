from decimal import Decimal
from datetime import datetime, timedelta

import json
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, make_response, send_file, session
)
from flask_login import login_required, current_user

from app.enfermeria import enfermeria_bp
from app.extensions import db
from app.models import (
    RegistroEnfermeria, Paciente, HistoriaClinica,
    AdministracionMedicamento, Medicamento, OrdenMedica, InsumoMedico, InsumoPaciente,
)
from app.utils.fechas import ahora_bogota
from sqlalchemy import func, text
from collections import defaultdict
from weasyprint import HTML
from io import BytesIO
from app import db  # ← db.session 

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
    """
    Gestiona la administración de medicamentos para un registro de enfermería.
    
    GET: Muestra medicamentos formulados, formulario y historial
    POST: Guarda la administración del medicamento
    """
    
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    paciente = Paciente.query.get(registro.paciente_id)
    
    # ========== MANEJO DE POST (GUARDAR ADMINISTRACIÓN) ==========
    if request.method == 'POST' and 'codigo_medicamento' in request.form:
        codigo = request.form.get('codigo_medicamento')
        cantidad = request.form.get('cantidad')
        hora_str = request.form.get('hora_administracion', '') or ahora_bogota().strftime('%Y-%m-%dT%H:%M')
        unidad = request.form.get('unidad', 'tab')
        via = request.form.get('via', 'VO')
        observaciones = request.form.get('observaciones', '')
        
        try:
            cantidad_dec = Decimal(cantidad)
            
            # Buscar medicamento
            med = Medicamento.query.filter_by(codigo=codigo).first()
            if not med:
                flash(f'❌ Medicamento {codigo} no encontrado', 'danger')
                return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))
            
            # Parsear hora
            if hora_str:
                hora_admin = datetime.strptime(hora_str, '%Y-%m-%dT%H:%M')
            else:
                hora_admin = ahora_bogota()
            
            # Crear registro de administración
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
            
            flash(f'✅ {med.nombre} x{cantidad_dec} {unidad} a las {hora_admin.strftime("%H:%M")}', 'success')
        
        except ValueError as e:
            db.session.rollback()
            flash(f'❌ Error en los datos: {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error: {str(e)}', 'danger')
        
        return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))
    
    
    # ========== MANEJO DE GET (MOSTRAR FORMULARIO) ==========
    
    medicamentos_formulados = []
    
    if registro.historia_clinica_id:
        historia_id = registro.historia_clinica_id
        todos_medicamentos = []
        
        # Obtener medicamentos de la Historia Clínica
        historia = HistoriaClinica.query.get(historia_id)
        if historia and historia.medicamentos_json:
            try:
                bruto = json.loads(historia.medicamentos_json)
                if isinstance(bruto, list):
                    todos_medicamentos.extend(bruto)
            except json.JSONDecodeError:
                pass
        
        # Obtener medicamentos de las Órdenes Médicas
        ordenes = OrdenMedica.query.filter_by(historia_id=historia_id).all()
        for orden in ordenes:
            if orden.medicamentos_json:
                try:
                    meds = json.loads(orden.medicamentos_json)
                    if isinstance(meds, list):
                        todos_medicamentos.extend(meds)
                except json.JSONDecodeError:
                    pass
        
        # Agrupar por código de medicamento
        meds_por_codigo = defaultdict(lambda: {'total': 0, 'detalle': {}, 'medicamento_bd': None})
        
        for med in todos_medicamentos:
            codigo = med.get('codigo', '')
            if codigo:
                # Buscar medicamento en BD para obtener nombre completo
                med_bd = Medicamento.query.filter_by(codigo=codigo).first()
                
                meds_por_codigo[codigo]['total'] += float(med.get('cantidad_solicitada', 0))
                meds_por_codigo[codigo]['medicamento_bd'] = med_bd
                meds_por_codigo[codigo]['detalle'].update({
                    'nombre': med_bd.nombre if med_bd else med.get('nombre', 'Sin nombre'),
                    'dosis': med.get('dosis', ''),
                    'frecuencia': med.get('frecuencia', ''),
                    'unidad_inventario': med.get('unidad_inventario', 'tab'),
                    'via': med.get('via', 'VO')
                })
        
        # Calcular pendientes
        for codigo, data in meds_por_codigo.items():
            formulada = Decimal(str(data['total']))
            
            # Sumar cantidad administrada
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
                'nombre': data['detalle'].get('nombre', 'Sin nombre'),
                'dosis': data['detalle'].get('dosis', ''),
                'frecuencia': data['detalle'].get('frecuencia', ''),
                'via': data['detalle'].get('via', 'VO'),
                'cantidad_formulada': formulada,
                'cantidad_administrada': admin_total,
                'pendiente': pendiente,
                'unidad': data['detalle'].get('unidad_inventario', 'tab')
            })
    
    # Obtener historial de administraciones
    administraciones = AdministracionMedicamento.query.filter_by(
        registro_enfermeria_id=registro.id
    ).outerjoin(Medicamento).order_by(
        AdministracionMedicamento.hora_administracion.desc()
    ).limit(50).all()
    
    # Hora actual para auto-llenar formulario
    hora_actual = ahora_bogota().strftime('%Y-%m-%dT%H:%M')
    
    # Obtener todos los medicamentos para dropdown
           # ========== DROPDOWN: SOLO MEDICAMENTOS FORMULADOS ==========
    medicamentos_dropdown = []
        
        # Extraer códigos únicos de medicamentos formulados
    codigos_formulados = []
    for med in medicamentos_formulados:
        codigos_formulados.append(med['codigo'])
        
        # Buscar solo esos medicamentos en BD
        if codigos_formulados:
            medicamentos_dropdown = Medicamento.query.filter(
                Medicamento.codigo.in_(codigos_formulados)
            ).all()
        else:
            # Fallback si no hay formulados
            medicamentos_dropdown = Medicamento.query.limit(10).all()
        
        # Hora actual para formulario
        hora_actual = ahora_bogota().strftime('%Y-%m-%dT%H:%M')
        
        # Renderizar template
        return render_template(
            'enfermeria/administrar_medicamentos.html',
            registro=registro,
            paciente=paciente,
            medicamentos_formulados=medicamentos_formulados,
            administraciones=administraciones,
            hora_actual=hora_actual,
            medicamentos=medicamentos_dropdown
        )


# ============================================================
# 2) ADMINISTRAR MEDICAMENTOS DESDE MENÚ PACIENTE
# ============================================================

@enfermeria_bp.route('/paciente/<int:paciente_id>/medicamentos')
@login_required
def administrar_medicamentos_paciente(paciente_id):
    """
    Ruta de acceso rápido desde el menú de paciente.
    Obtiene o crea el último registro de enfermería y redirige.
    """
    
    paciente = Paciente.query.get_or_404(paciente_id)
    
    # Buscar último registro de enfermería
    registro = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .first()
    )
    
    # Si no existe, crear uno nuevo
    if not registro:
        # Buscar última historia clínica
        historia = (
            HistoriaClinica.query
            .filter_by(paciente_id=paciente_id)
            .order_by(HistoriaClinica.fecha_registro.desc())
            .first()
        )
        
        # Crear nuevo registro
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
    
    return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro.id))


# ============================================================
# 3) API AUXILIAR: OBTENER MEDICAMENTOS POR REGISTRO (OPCIONAL)
# ============================================================

@enfermeria_bp.route('/api/registro/<int:registro_id>/medicamentos-formulados')
@login_required
def api_medicamentos_formulados(registro_id):
    """
    API para obtener medicamentos formulados de un registro (AJAX).
    Retorna JSON con medicamentos y sus detalles.
    """
    
    try:
        registro = RegistroEnfermeria.query.get_or_404(registro_id)
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
                except json.JSONDecodeError:
                    pass
            
            # Órdenes
            ordenes = OrdenMedica.query.filter_by(historia_id=historia_id).all()
            for orden in ordenes:
                if orden.medicamentos_json:
                    try:
                        meds = json.loads(orden.medicamentos_json)
                        if isinstance(meds, list):
                            todos_medicamentos.extend(meds)
                    except json.JSONDecodeError:
                        pass
            
            # Agrupar
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
                    'cantidad_formulada': float(formulada),
                    'cantidad_administrada': float(admin_total),
                    'pendiente': float(pendiente),
                    'unidad': data['detalle'].get('unidad_inventario', 'tab')
                })
        
        return jsonify({
            'success': True,
            'medicamentos': medicamentos_formulados
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    
# ---------- 6) BUSCAR PACIENTE JSON ----------

@enfermeria_bp.route('/paciente/<int:paciente_id>/exportar_pdf', methods=['GET'])
@login_required
def exportar_pdf(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    
    # 📌 Registros de enfermería
    registros = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .all()
    )

    # 🔥 Signos vitales
    for r in registros:
        try:
            sv = json.loads(r.signos_vitales or '{}')
            if not isinstance(sv, dict):
                sv = {}
        except Exception:
            sv = {}

        r.signos_vitales_dict = {
            "ta":   sv.get("ta")   or "",
            "fc":   sv.get("fc")   or "",
            "fr":   sv.get("fr")   or "",
            "temp": sv.get("temp") or "",
            "so2":  sv.get("so2")  or ""
        }

        # 💧 Balance de líquidos
        try:
            bl = json.loads(r.balance_liquidos or '{}')
            if not isinstance(bl, dict):
                bl = {"administrados": {}, "eliminados": {}}
        except Exception:
            bl = {"administrados": {}, "eliminados": {}}
        r.balance_liquidos_dict = bl

    # 💊 Medicamentos administrados
    medicamentos = []
    if registros:
        registro_ids = [r.id for r in registros]
        medicamentos = (
            db.session.query(AdministracionMedicamento)
            .filter(
                AdministracionMedicamento.registro.has(
                    RegistroEnfermeria.id.in_(registro_ids)
                )
            )
            .order_by(AdministracionMedicamento.hora_administracion.desc())
            .limit(50)
            .all()
        )

    # 🧴 INSUMOS: mismos datos que usas en registros_paciente
    insumos_paciente = InsumoPaciente.query.filter_by(paciente_id=paciente_id).all()

    insumos_registrados = []
    for ip in insumos_paciente:
        insumo = InsumoMedico.query.get(ip.insumo_id)
        if not insumo:
            continue

        usado = ip.cantidad_usada or 0
        pendiente = (ip.cantidad or 0) - usado

        if usado > 0:
            insumos_registrados.append({
                'nombre': insumo.nombre,
                'solicitado': ip.cantidad,
                'usado': usado,
                'pendiente': pendiente,
                'fecha_uso': ip.fecha_uso.strftime('%d/%m %H:%M')
                            if getattr(ip, 'fecha_uso', None) else 'Sin fecha',
                'observaciones': getattr(ip, 'observaciones', '') or 'Sin observaciones'
            })

    data = {
        'paciente': paciente,
        'registros': registros,
        'medicamentos': medicamentos,
        'insumos_registrados': insumos_registrados,  # ← NUEVO
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

    # 📌 Registros de enfermería
    registros = (
        RegistroEnfermeria.query
        .filter_by(paciente_id=paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .all()
    )

    # 🔥 Signos vitales (dict seguro)
    for r in registros:
        try:
            sv = json.loads(r.signos_vitales or '{}')
            if not isinstance(sv, dict):
                sv = {}
        except Exception:
            sv = {}

        r.signos_vitales_dict = {
            "ta":   sv.get("ta")   or "",
            "fc":   sv.get("fc")   or "",
            "fr":   sv.get("fr")   or "",
            "temp": sv.get("temp") or "",
            "so2":  sv.get("so2")  or ""
        }

        # 💧 Balance de líquidos (dict seguro)
        try:
            bl = json.loads(r.balance_liquidos or '{}')
            if not isinstance(bl, dict):
                bl = {"administrados": {}, "eliminados": {}}
        except Exception:
            bl = {"administrados": {}, "eliminados": {}}

        r.balance_liquidos_dict = bl

    # 💊 Medicamentos administrados ligados a estos registros
    medicamentos = []
    if registros:
        registro_ids = [r.id for r in registros]
        medicamentos = (
            db.session.query(AdministracionMedicamento)
            .filter(
                AdministracionMedicamento.registro.has(
                    RegistroEnfermeria.id.in_(registro_ids)
                )
            )
            .order_by(AdministracionMedicamento.hora_administracion.desc())
            .limit(50)
            .all()
        )

    # 🧴 INSUMOS: usados y pendientes para este paciente
    insumos_paciente = InsumoPaciente.query.filter_by(paciente_id=paciente_id).all()

    insumos_registrados = []  # usados > 0
    insumos_pendientes = []   # usados == 0

    for ip in insumos_paciente:
        insumo = InsumoMedico.query.get(ip.insumo_id)
        if not insumo:
            continue

        usado = ip.cantidad_usada or 0
        pendiente = (ip.cantidad or 0) - usado

        if usado > 0:
            insumos_registrados.append({
                'nombre': insumo.nombre,
                'solicitado': ip.cantidad,
                'usado': usado,
                'pendiente': pendiente,
                'fecha_uso': ip.fecha_uso.strftime('%d/%m %H:%M') if getattr(ip, 'fecha_uso', None) else 'Sin fecha',
                'observaciones': getattr(ip, 'observaciones', '') or 'Sin observaciones'
            })
        else:
            insumos_pendientes.append({
                'nombre': insumo.nombre,
                'solicitado': ip.cantidad,
                'pendiente': pendiente,
                'fecha_solicitud': 'Pendiente'
            })

    return render_template(
        'enfermeria/registros_paciente.html',
        paciente=paciente,
        registros=registros,
        medicamentos=medicamentos,
        insumos_registrados=insumos_registrados,
        insumos_pendientes=insumos_pendientes
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

@enfermeria_bp.route('/enfermeria/paciente/<int:paciente_id>/solicitar_insumos', methods=['GET', 'POST'])
@login_required 
def solicitar_insumos(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    
    if request.method == 'POST':
        insumo_id_str = request.form.get('insumo_id', '').strip()
        cantidad_str = request.form.get('cantidad', '0').strip()
        
        if not insumo_id_str:
            flash('❌ Selecciona un insumo', 'danger')
        else:
            try:
                insumo_id = int(insumo_id_str)
                cantidad = max(1, int(cantidad_str))
                
                insumo = InsumoMedico.query.get(insumo_id)
                if insumo and (insumo.stock_actual or 0) >= cantidad:
                    insumo_paciente = InsumoPaciente(
                        paciente_id=paciente_id,
                        insumo_id=insumo_id,
                        cantidad=cantidad,
                        cantidad_usada=0
                    )
                    db.session.add(insumo_paciente)
                    db.session.commit()
                    flash(f'✅ {insumo.nombre} SOLICITADO ({cantidad} uds)', 'success')
                else:
                    flash('❌ Stock insuficiente', 'danger')
            except Exception as e:
                flash(f'❌ Error: {str(e)[:50]}', 'danger')
        return redirect(url_for('enfermeria.solicitar_insumos', paciente_id=paciente_id))
    
    insumos_json = InsumoMedico.query.filter(
        InsumoMedico.stock_actual > 0
    ).limit(50).all()
    
    # QUERY AGRUPADA
    insumos_agrupados = db.session.query(
        InsumoPaciente.insumo_id,
        InsumoMedico.nombre,
        func.sum(InsumoPaciente.cantidad).label('total_solicitado'),
        func.coalesce(func.sum(InsumoPaciente.cantidad_usada), 0).label('total_usado'),
        func.max(InsumoPaciente.id).label('ultimo_id'),
        func.count(InsumoPaciente.id).label('num_solicitudes')
    ).outerjoin(InsumoMedico, InsumoPaciente.insumo_id == InsumoMedico.id)\
     .filter(InsumoPaciente.paciente_id == paciente_id)\
     .group_by(InsumoPaciente.insumo_id, InsumoMedico.nombre)\
     .having(func.coalesce(func.sum(InsumoPaciente.cantidad_usada), 0) < func.sum(InsumoPaciente.cantidad))\
     .order_by(func.max(InsumoPaciente.id).desc()).all()
    
    insumos_solicitados = []
    for row in insumos_agrupados:
        insumos_solicitados.append({
            'nombre': row.nombre,
            'total_solicitado': float(row.total_solicitado),
            'total_usado': float(row.total_usado),
            'pendiente': float(row.total_solicitado - row.total_usado),
            'ultimo_id': row.ultimo_id,  # ← Solo ID
            'num_solicitudes': int(row.num_solicitudes)
        })
    
    return render_template(
        'enfermeria/solicitar_insumos.html',
        paciente=paciente,
        insumos_json=insumos_json,
        insumos_solicitados=insumos_solicitados
    )

@enfermeria_bp.route('/enfermeria/paciente/<int:paciente_id>/registrar_insumos', methods=['GET', 'POST'])
@login_required
def registrar_insumos(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    
    if request.method == 'POST':
        ids_raw = request.form.getlist('insumos_reg[]')
        if not ids_raw:
            flash('Selecciona al menos un insumo para registrar.', 'warning')
            return redirect(url_for('enfermeria.registrar_insumos', paciente_id=paciente_id))
        
        procesados = 0
        for ip_id_str in ids_raw:
            try:
                ip_id = int(ip_id_str)
                ip = InsumoPaciente.query.get(ip_id)
                if not ip or ip.paciente_id != paciente_id:
                    continue

                # CANTIDAD ESPECÍFICA POR INSUMO
                cantidad_str = request.form.get(f'cant_{ip_id}', '1')
                cantidad = min(int(cantidad_str), ip.cantidad - (ip.cantidad_usada or 0))
                if cantidad <= 0:
                    continue

                # OBSERVACIONES
                obs = request.form.get(f'obs_{ip_id}', '').strip()
                ip.observaciones = obs if obs else None

                # ACTUALIZAR USO
                usado_actual = ip.cantidad_usada or 0
                ip.cantidad_usada = usado_actual + cantidad
                ip.fecha_uso = datetime.now()

                # Descontar stock físico
                insumo = InsumoMedico.query.get(ip.insumo_id)
                if insumo:
                    insumo.stock_actual = max(0, (insumo.stock_actual or 0) - cantidad)

                procesados += 1
                
            except Exception as e:
                print(f"Error procesando {ip_id_str}: {e}")
                continue  # Salta errores individuales
        
        db.session.commit()
        if procesados > 0:
            flash(f'✅ {procesados} insumo(s) registrados correctamente', 'success')
        else:
            flash('No se pudo registrar ningún insumo.', 'warning')
        
        return redirect(url_for('enfermeria.registrar_insumos', paciente_id=paciente_id))
    
    # SOLO INSUMOS PENDIENTES (no completos)
    insumos_paciente = InsumoPaciente.query.filter(
        InsumoPaciente.paciente_id == paciente_id,
        InsumoPaciente.cantidad_usada < InsumoPaciente.cantidad
    ).order_by(InsumoPaciente.id.desc()).all()
    
    insumos_reg = []
    for ip in insumos_paciente:
        insumo = InsumoMedico.query.get(ip.insumo_id)
        if insumo:
            insumos_reg.append({
                'id': ip.id,
                'nombre': insumo.nombre,
                'solicitado': ip.cantidad,
                'usado': ip.cantidad_usada or 0,
                'observaciones': ip.observaciones or ''
            })
    
    return render_template(
        'enfermeria/registrar_insumos.html',
        paciente=paciente,
        insumos=insumos_reg
    )

# ✅ 1. LIMPIAR TODOS pendientes
@enfermeria_bp.route('/enfermeria/paciente/<int:paciente_id>/limpiar_insumos', methods=['POST'])
@login_required
def limpiar_insumos_solicitados(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    eliminados = InsumoPaciente.query.filter(
        InsumoPaciente.paciente_id == paciente_id,
        InsumoPaciente.cantidad_usada < InsumoPaciente.cantidad
    ).delete()
    db.session.commit()
    flash(f'🗑️ {eliminados} insumos eliminados', 'success')
    return redirect(url_for('enfermeria.solicitar_insumos', paciente_id=paciente_id))

# ✅ 2. ELIMINAR UNO (usa insumo_paciente_id real de BD)
@enfermeria_bp.route('/enfermeria/paciente/<int:paciente_id>/eliminar_insumo/<int:insumo_paciente_id>', methods=['POST'])
@login_required
def eliminar_insumo_individual(paciente_id, insumo_paciente_id):
    ip = InsumoPaciente.query.get_or_404(insumo_paciente_id)
    if ip.paciente_id != paciente_id or ip.cantidad_usada > 0:
        flash('❌ No autorizado o ya usado', 'danger')
        return redirect(url_for('enfermeria.solicitar_insumos', paciente_id=paciente_id))
    
    nombre = InsumoMedico.query.get(ip.insumo_id).nombre
    db.session.delete(ip)
    db.session.commit()
    flash(f'🗑️ {nombre} eliminado', 'success')
    return redirect(url_for('enfermeria.solicitar_insumos', paciente_id=paciente_id))

@enfermeria_bp.route('/enfermeria/paciente/<int:paciente_id>/reset_insumos', methods=['POST'])
@login_required
def reset_insumos_paciente(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)

    eliminados = InsumoPaciente.query.filter(
        InsumoPaciente.paciente_id == paciente_id
    ).delete()  # ← sin filtrar por cantidad_usada

    db.session.commit()
    flash(f'🧹 {eliminados} solicitudes de insumos eliminadas (HARD RESET)', 'warning')
    return redirect(url_for('enfermeria.solicitar_insumos', paciente_id=paciente_id))

# ---------- RUTAS DE EDICIÓN COMPLETAS ----------
@enfermeria_bp.route('/registro/<int:registro_id>/editar_signos', methods=['GET', 'POST'])
@login_required
def editar_signos(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    
    # 1. Unificar fechas para evitar el error de "offset-naive vs offset-aware"
    ahora = ahora_bogota()
    # Si la fecha de la base de datos no tiene zona horaria, le asignamos la de Bogotá para comparar
    fecha_reg = registro.fecha_registro
    if fecha_reg.tzinfo is None:
        fecha_reg = fecha_reg.replace(tzinfo=ahora.tzinfo)
    
    # 2. Definir la variable ANTES de usarla
    diff_horas = (ahora - fecha_reg).total_seconds() / 3600
    
    # 3. Validación de las 2 horas
    if abs(diff_horas) > 2:
        flash(f'El tiempo límite de edición ha expirado ({round(abs(diff_horas), 1)}h transcurridas).', 'danger')
        return redirect(url_for('enfermeria.detalle', paciente_id=registro.paciente_id))

    if request.method == 'POST':
        signos_data = {
            "ta": request.form.get('ta'),
            "fc": request.form.get('fc'),
            "fr": request.form.get('fr'),
            "temp": request.form.get('temp'),
            "so2": request.form.get('so2')
        }
        registro.signos_vitales = json.dumps(signos_data)
        registro.control_glicemia = request.form.get('control_glicemia')
        registro.observaciones = request.form.get('observaciones')
        
        db.session.commit()
        flash('✅ Signos vitales actualizados.', 'success')
        return redirect(url_for('enfermeria.detalle', paciente_id=registro.paciente_id))
    
    sv = json.loads(registro.signos_vitales or '{}')
    return render_template('enfermeria/editar_signos.html', registro=registro, sv=sv)
@enfermeria_bp.route('/registro/<int:registro_id>/editar_balance', methods=['GET', 'POST'])
@login_required
def editar_balance(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    
    # Manejo de zonas horarias para evitar el TypeError
    ahora = ahora_bogota()
    fecha_reg = registro.fecha_registro
    if fecha_reg.tzinfo is None:
        fecha_reg = fecha_reg.replace(tzinfo=ahora.tzinfo)
    
    # Cálculo de diferencia
    diff_horas = (ahora - fecha_reg).total_seconds() / 3600
    
    if abs(diff_horas) > 2:
        flash('El tiempo límite de 2 horas para editar el balance ha expirado.', 'danger')
        return redirect(url_for('enfermeria.detalle', paciente_id=registro.paciente_id))

    if request.method == 'POST':
        # Recolectamos los datos del formulario (deben coincidir con los "name" del HTML)
        balance_data = {
            "administrados": {
                "liquido": request.form.get('liquido_admin'),
                "cantidad": request.form.get('cantidad_admin'),
                "via": request.form.get('via_admin')
            },
            "eliminados": {
                "tipo_liquido": request.form.get('tipo_liquido'),
                "cantidad": request.form.get('cantidad_elim'),
                "via_eliminacion": request.form.get('via_eliminacion')
            }
        }
        registro.balance_liquidos = json.dumps(balance_data)
        db.session.commit()
        flash('✅ Balance de líquidos actualizado con éxito.', 'success')
        return redirect(url_for('enfermeria.detalle', paciente_id=registro.paciente_id))
    
    # Preparar datos para el formulario
    bl = json.loads(registro.balance_liquidos or '{"administrados":{}, "eliminados":{}}')
    return render_template('enfermeria/editar_balance.html', registro=registro, bl=bl)

@enfermeria_bp.route('/registro/<int:registro_id>/editar_nota', methods=['GET', 'POST'])
@login_required
def editar_nota(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    
    # 1. Manejo de zonas horarias para evitar el TypeError
    ahora = ahora_bogota()
    fecha_reg = registro.fecha_registro
    if fecha_reg.tzinfo is None:
        fecha_reg = fecha_reg.replace(tzinfo=ahora.tzinfo)
    
    # 2. Cálculo de diferencia de tiempo
    diff_horas = (ahora - fecha_reg).total_seconds() / 3600
    
    # 3. Validación de las 2 horas
    if abs(diff_horas) > 2:
        flash(f'No es posible editar la nota. Han pasado {round(abs(diff_horas), 1)} horas.', 'danger')
        return redirect(url_for('enfermeria.detalle', paciente_id=registro.paciente_id))

    if request.method == 'POST':
        # Actualizamos los campos de la nota
        registro.tipo_nota = request.form.get('tipo_nota')
        registro.texto_nota = request.form.get('texto_nota')
        
        db.session.commit()
        flash('✅ Nota de enfermería actualizada con éxito.', 'success')
        # Redirigir al detalle del paciente
        return redirect(url_for('enfermeria.detalle', paciente_id=registro.paciente_id))
    
    return render_template('enfermeria/editar_nota.html', registro=registro)

@enfermeria_bp.route('/medicamento/<int:admin_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_administracion_med(admin_id):
    # Buscamos el registro de administración específico
    admin = AdministracionMedicamento.query.get_or_404(admin_id)
    registro = RegistroEnfermeria.query.get(admin.registro_enfermeria_id)
    
    # Validación de tiempo (2 horas)
    ahora = ahora_bogota()
    fecha_admin = admin.hora_administracion
    if fecha_admin.tzinfo is None:
        fecha_admin = fecha_admin.replace(tzinfo=ahora.tzinfo)
    
    diff_horas = (ahora - fecha_admin).total_seconds() / 3600
    if abs(diff_horas) > 2:
        flash('No se puede editar la administración de medicamento después de 2 horas.', 'danger')
        return redirect(url_for('enfermeria.detalle', paciente_id=registro.paciente_id))

    if request.method == 'POST':
        try:
            admin.cantidad = Decimal(request.form.get('cantidad'))
            admin.unidad = request.form.get('unidad')
            admin.via = request.form.get('via')
            admin.observaciones = request.form.get('observaciones')
            
            # Actualizar hora si se proporcionó una nueva
            nueva_hora = request.form.get('hora_administracion')
            if nueva_hora:
                admin.hora_administracion = datetime.strptime(nueva_hora, '%Y-%m-%dT%H:%M')
            
            db.session.commit()
            flash('✅ Administración de medicamento actualizada.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error al actualizar: {str(e)}', 'danger')
            
        return redirect(url_for('enfermeria.detalle', paciente_id=registro.paciente_id))

    return render_template('enfermeria/editar_medicamento.html', admin=admin, registro=registro)

@enfermeria_bp.route('/insumo/<int:insumo_paciente_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_insumo_paciente(insumo_paciente_id):
    insumo_p = InsumoPaciente.query.get_or_404(insumo_paciente_id)
    
    if request.method == 'POST':
        try:
            insumo_p.cantidad = float(request.form.get('cantidad'))
            insumo_p.observaciones = request.form.get('observaciones')
            
            db.session.commit()
            flash('✅ Registro de insumo actualizado.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error: {str(e)}', 'danger')
            
        return redirect(url_for('enfermeria.detalle', paciente_id=insumo_p.paciente_id))

    return render_template('enfermeria/editar_insumo.html', insumo_p=insumo_p)