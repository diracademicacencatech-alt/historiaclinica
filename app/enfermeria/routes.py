from decimal import Decimal
from datetime import datetime, timedelta, time

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
from sqlalchemy import func, text, or_
from collections import defaultdict
from weasyprint import HTML
from io import BytesIO
from app import db  # ← db.session 

def parse_json_seguro(data_str, default=None):
    """Convierte string JSON a diccionario de forma segura"""
    if not data_str:
        return default or {}
    try:
        data = json.loads(data_str)
        return data if isinstance(data, dict) else default or {}
    except:
        return default or {}
    
TURNOS_DISPONIBLES = ['MAÑANA', 'TARDE', 'NOCHE']

def obtener_turno_actual():
    ahora = ahora_bogota() # Asegúrate de que esta función devuelva la hora de Colombia
    h = ahora.hour
    
    # Mañana: 07:00 a 12:59
    if 7 <= h < 13:
        return 'MAÑANA'
    # Tarde: 13:00 a 18:59
    elif 13 <= h < 19:
        return 'TARDE'
    # Noche: 19:00 a 06:59
    else:
        return 'NOCHE'

def validar_turno_estricto(registro_obj):
    # 1. Los administradores saltan la regla
    user_rol = getattr(current_user, 'rol', getattr(current_user, 'role', None))
    if user_rol == 'ADMIN': 
        return True, "OK"

    ahora = ahora_bogota().replace(tzinfo=None)
    turno_actual = obtener_turno_actual()
    
    # 2. Obtener el turno guardado
    turno_guardado = str(getattr(registro_obj, 'turno', '')).strip().upper()

    # 3. Obtener la fecha del registro
    fecha_reg = getattr(registro_obj, 'fecha_registro', ahora)
    if fecha_reg:
        fecha_reg = fecha_reg.replace(tzinfo=None)
        # Si el registro tiene menos de 180 minutos (3 horas), 
        # permitimos editar/eliminar sin importar el nombre del turno.
        if (ahora - fecha_reg).total_seconds() / 60 < 180:
            return True, "OK"

    # 4. Si pasó mucho tiempo, validamos que el turno coincida
    if turno_guardado == turno_actual:
        return True, "OK"
    
    return False, f"Acción denegada: Registro de turno {turno_guardado} no modificable en turno {turno_actual}."

def validar_acceso_visual(r):
    """Para BOTONES: Permite ver botones hasta 120 min después del registro."""
    # Intentamos obtener el rol de forma segura
    user_rol = getattr(current_user, 'rol', getattr(current_user, 'role', None))
    if user_rol == 'ADMIN': 
        return True
        
    ahora = ahora_bogota()
    fecha_ref = getattr(r, 'fecha_registro', getattr(r, 'hora_administracion', None))
    if not fecha_ref: return False
    
    diferencia = ahora.replace(tzinfo=None) - fecha_ref.replace(tzinfo=None)
    minutos = diferencia.total_seconds() / 60
    
    if 0 <= minutos < 120: 
        return True
        
    return str(getattr(r, 'turno', '')).strip().upper() == obtener_turno_actual()

@enfermeria_bp.context_processor
def inyectar_utilidades():
    return dict(
        puede_editar_turno_template=validar_turno_estricto,
        validar_acceso_visual=validar_acceso_visual
    )
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

    # Traemos todos los registros del paciente sin filtrar por hoy para el historial
    registros = (
        RegistroEnfermeria.query
        .filter(RegistroEnfermeria.paciente_id == paciente_id)
        .order_by(RegistroEnfermeria.fecha_registro.desc())
        .all()
    )

    for r in registros:
        # Usamos la función parse_json_seguro que ya tienes arriba
        r.signos_vitales_dict = parse_json_seguro(r.signos_vitales)
        r.balance_liquidos_dict = parse_json_seguro(r.balance_liquidos, {'administrados': {}, 'eliminados': {}})

    # Notas para el resumen lateral
    notas = [r for r in registros if r.tipo_nota]

    return render_template(
        'enfermeria/registro_detalle.html',
        paciente=paciente,
        registros=registros,
        notas=notas[:5], # Solo las últimas 5 notas
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

    # ... dentro de la función crear() ...
    if request.method == 'POST':
        # 1. Definimos las variables básicas primero (para que no den error de 'not defined')
        historia_id = request.form.get('historia_clinica_id')
        turno_form = (request.form.get('turno') or turno_real).upper()
        hora_str = (request.form.get('hora_sv') or 
                    request.form.get('hora_inicial') or 
                    request.form.get('hora_eliminado'))
               
        # 2. Validación de turno ESTRICTA
        # turno_real viene de obtener_turno_actual() al principio de la función
        if turno_form != turno_real:
            flash(f'⚠️ ERROR DE SEGURIDAD: Usted está en el turno {turno_real}. '
                  f'No se permite crear registros para el turno {turno_form}.', 'danger')
            return redirect(url_for('enfermeria.crear', paciente_id=paciente_id))
        
        # 3. Procesamiento de la HORA e integridad de turno
        # Capturamos las 3 horas por separado para validarlas todas
        h_sv = request.form.get('hora_sv')
        h_admin = request.form.get('hora_inicial')
        h_elim = request.form.get('hora_eliminado')
        
        # Consolidamos para la fecha del registro (usamos la primera que aparezca)
        hora_str = h_sv or h_admin or h_elim
        
        ahora = ahora_bogota()
        turno_actual_sistema = obtener_turno_actual().upper()
        fecha_registro_final = ahora 

        # --- FUNCIÓN INTERNA DE BLOQUEO ---
        def validar_hora_turno(valor_hora, nombre_campo):
            if valor_hora:
                try:
                    obj = datetime.strptime(valor_hora, '%H:%M').time()
                    h = obj.hour
                    t_calc = 'MAÑANA' if 7 <= h < 13 else 'TARDE' if 13 <= h < 19 else 'NOCHE'
                    
                    if t_calc != turno_actual_sistema:
                        return False, f"❌ ERROR en {nombre_campo}: La hora {valor_hora} es del turno {t_calc}. Usted está en {turno_actual_sistema}."
                except:
                    pass
            return True, ""

        # Validamos las 3 posibles horas del formulario
        v_sv, m_sv = validar_hora_turno(h_sv, "Signos Vitales")
        if not v_sv:
            flash(m_sv, 'danger')
            return redirect(url_for('enfermeria.crear', paciente_id=paciente_id))

        v_ad, m_ad = validar_hora_turno(h_admin, "Líquidos Admin")
        if not v_ad:
            flash(m_ad, 'danger')
            return redirect(url_for('enfermeria.crear', paciente_id=paciente_id))

        v_el, m_el = validar_hora_turno(h_elim, "Líquidos Elim")
        if not v_el:
            flash(m_el, 'danger')
            return redirect(url_for('enfermeria.crear', paciente_id=paciente_id))

        # Configuración de la fecha final para la base de datos
        if hora_str:
            try:
                hora_obj = datetime.strptime(hora_str, '%H:%M').time()
                fecha_registro_final = datetime.combine(ahora.date(), hora_obj)
                
                if fecha_registro_final > ahora:
                    flash('No se pueden realizar registros con horas futuras.', 'error')
                    return redirect(url_for('enfermeria.crear', paciente_id=paciente_id))
            except Exception as e:
                print(f"Error procesando hora: {e}")

        # 4. Empaquetado de datos (Tus JSON originales)
        signos_vitales_data = {
            "hora_sv": request.form.get('hora_sv'),
            "ta": request.form.get('ta'),
            "fc": request.form.get('fc'),
            "fr": request.form.get('fr'),
            "temp": request.form.get('temp'),
            "so2": request.form.get('so2')
        }

        balance_liquidos_data = {
            "administrados": {
                "hora_inicial": request.form.get('hora_inicial'),
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

        # 5. Creación del registro con la fecha final calculada
        registro = RegistroEnfermeria(
            paciente_id=paciente_id,
            historia_clinica_id=historia_id, # Ahora sí está definido
            turno=turno_form,                # Ahora sí está definido
            fecha_registro=fecha_registro_final,
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

    permitido, mensaje = validar_turno_estricto(registro)
    if not permitido:
        flash(mensaje, "danger")
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=registro.paciente_id))
    
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

@enfermeria_bp.route('/insumo_paciente/<int:ip_id>/eliminar', methods=['POST'])
@login_required
def eliminar_insumo_paciente(ip_id):
    ip = InsumoPaciente.query.get_or_404(ip_id)
    
    # Buscamos el registro de enfermería asociado al insumo
    registro = RegistroEnfermeria.query.get(ip.registro_enfermeria_id)
    if registro:
        permitido, mensaje = validar_turno_estricto(registro)
        if not permitido:
            flash(mensaje, "danger")
            return redirect(request.referrer)

    db.session.delete(ip)
    db.session.commit()
    flash('Insumo eliminado.', 'success')
    return redirect(request.referrer)

# ---------- 5) ADMINISTRAR MEDICAMENTOS POR REGISTRO ----------
@enfermeria_bp.route('/registro/<int:registro_id>/medicamentos', methods=['GET', 'POST'])
@login_required
def administrar_medicamentos(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    paciente = Paciente.query.get(registro.paciente_id)
    
    # 1. Inicializar variables del GET al principio para evitar errores de Pylance
    medicamentos_formulados = []
    administraciones = []
    medicamentos_dropdown = []
    hora_actual = ahora_bogota().strftime('%H:%M')

    # ========== PROCESAR GUARDADO (POST) ==========
    if request.method == 'POST' and 'codigo_medicamento' in request.form:
        # ACTUALIZACIÓN DINÁMICA DE TURNO
        turno_real_reloj = obtener_turno_actual().upper()
        if registro.turno != turno_real_reloj:
            registro.turno = turno_real_reloj
            registro.fecha_registro = ahora_bogota()

        codigo = request.form.get('codigo_medicamento')
        cantidad = request.form.get('cantidad')
        hora_input = request.form.get('hora_administracion')
        via_form = request.form.get('via')
        observaciones = request.form.get('observaciones')
        
        if hora_input:
            try:
                h, m = map(int, hora_input.split(':'))
                # Determinar turno de la hora ingresada
                if 7 <= h < 13: t_calc = 'MAÑANA'
                elif 13 <= h < 19: t_calc = 'TARDE'
                else: t_calc = 'NOCHE'
                
                turno_actual_sistema = obtener_turno_actual().upper()
                
                if t_calc != turno_actual_sistema:
                    flash(f"Acción bloqueada: La hora {hora_input} es del turno {t_calc}. Su turno actual es {turno_actual_sistema}.", 'danger')
                    return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))
                
                med_bd = Medicamento.query.filter_by(codigo=codigo).first()
                if med_bd and cantidad:
                    nueva_admin = AdministracionMedicamento(
                        registro_enfermeria_id=registro.id,
                        medicamento_id=med_bd.id,
                        cantidad=float(cantidad),
                        via=via_form or 'VO',
                        hora_administracion=datetime.combine(ahora_bogota().date(), time(h, m)),
                        observaciones=observaciones,
                        unidad=med_bd.unidad_inventario or 'UND'
                    )
                    db.session.add(nueva_admin)
                    db.session.commit()
                    flash('✅ Medicamento administrado correctamente.', 'success')
                else:
                    flash('❌ Error: Datos incompletos.', 'danger')

                return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))

            except Exception as e:
                db.session.rollback()
                flash(f'Error al procesar: {str(e)}', 'danger')
                return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))

    # ========== CARGAR DATOS (GET) ==========
    # Esta parte se ejecuta siempre que no haya un 'return' previo en el POST
    if registro.historia_clinica_id:
        historia_id = registro.historia_clinica_id
        todos_medicamentos = []
        
        historia = HistoriaClinica.query.get(historia_id)
        if historia and historia.medicamentos_json:
            try:
                bruto = json.loads(historia.medicamentos_json)
                if isinstance(bruto, list): todos_medicamentos.extend(bruto)
            except: pass
            
        ordenes = OrdenMedica.query.filter_by(historia_id=historia_id).all()
        for orden in ordenes:
            if orden.medicamentos_json:
                try:
                    meds = json.loads(orden.medicamentos_json)
                    if isinstance(meds, list): todos_medicamentos.extend(meds)
                except: pass
        
        meds_por_codigo = {}
        for med in todos_medicamentos:
            codigo_m = med.get('codigo') or med.get('codigo_medicamento')
            if not codigo_m: continue
            if codigo_m not in meds_por_codigo:
                med_bd_query = Medicamento.query.filter_by(codigo=codigo_m).first()
                meds_por_codigo[codigo_m] = {
                    'total': 0,
                    'detalle': {
                        'nombre': med_bd_query.nombre if med_bd_query else (med.get('medicamento') or med.get('nombre')),
                        'dosis': med.get('dosis', ''),
                        'frecuencia': med.get('frecuencia', '--'),
                        'via': med.get('via', 'VO'),
                        'unidad_inventario': med.get('unidad_inventario') or (med_bd_query.unidad_inventario if med_bd_query else 'und')
                    }
                }
            try:
                meds_por_codigo[codigo_m]['total'] += float(med.get('cantidad') or 0)
            except: pass

        for c, d in meds_por_codigo.items():
            admin_total = db.session.query(db.func.coalesce(db.func.sum(AdministracionMedicamento.cantidad), 0))\
                .filter(AdministracionMedicamento.registro_enfermeria_id == registro.id, AdministracionMedicamento.medicamento.has(codigo=c)).scalar() or 0
            
            medicamentos_formulados.append({
                'codigo': c,
                'nombre': d['detalle']['nombre'],
                'dosis': d['detalle']['dosis'],
                'frecuencia': d['detalle']['frecuencia'],
                'via': d['detalle']['via'],
                'cantidad_formulada': Decimal(str(d['total'])),
                'cantidad_administrada': Decimal(str(admin_total)),
                'pendiente': max(Decimal(str(d['total'])) - Decimal(str(admin_total)), Decimal('0')),
                'unidad_inventario': d['detalle']['unidad_inventario']
            })

    # Consultas finales para la vista
    administraciones = AdministracionMedicamento.query.filter_by(registro_enfermeria_id=registro.id)\
        .order_by(AdministracionMedicamento.hora_administracion.desc()).all()
    
    codigos_f = [m['codigo'] for m in medicamentos_formulados]
    medicamentos_dropdown = Medicamento.query.filter(Medicamento.codigo.in_(codigos_f)).all() if codigos_f else []

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
            # MODIFICACIÓN AQUÍ: Consolidar la vía
            'via': med.get('via') or med.get('via_administracion') or 'VO',
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
                
                # --- AJUSTE AQUÍ: ENVIAMOS LA VÍA AL JSON FINAL ---
                medicamentos_formulados.append({
                    'codigo': codigo,
                    'nombre': data['detalle'].get('nombre', codigo), # Asegurar que el nombre pase si existe
                    'dosis': data['detalle'].get('dosis', ''),
                    'frecuencia': data['detalle'].get('frecuencia', ''),
                    'via_administracion': data['detalle'].get('via_administracion', ''),
                    'via': data['detalle'].get('via', ''),
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
                # Primer filtro: que pertenezca a los registros (Relación)
                AdministracionMedicamento.registro_enfermeria_id.in_(registro_ids), 
                # Segundo filtro: que la cantidad sea mayor a 0 (Atributo directo)
                AdministracionMedicamento.cantidad > 0 
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
                'observaciones': getattr(ip, 'observaciones', '') or 'Sin observaciones',
                'registro_obj': r
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


# ---------- 9) CREAR NOTA  ----------

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
        
        # Lógica de hora
        hora_nota_str = request.form.get('hora_nota')
        ahora = ahora_bogota() # Usamos tu utilidad de fecha
        fecha_final = ahora
        
        if hora_nota_str:
            try:
                h, m = map(int, hora_nota_str.split(':'))
                fecha_final = datetime.combine(ahora.date(), time(h, m))

                # --- EL BLOQUEO DE SEGURIDAD AQUÍ ---
                # A. Calculamos el turno de la hora escrita
                if 7 <= h < 13: t_calc = 'MAÑANA'
                elif 13 <= h < 19: t_calc = 'TARDE'
                else: t_calc = 'NOCHE'
                
                # B. Obtenemos el turno actual del sistema
                turno_actual_sistema = obtener_turno_actual().upper()

                # C. Si no coinciden, rebotamos inmediatamente
                if t_calc != turno_actual_sistema:
                    flash(f'❌ ERROR: La hora {hora_nota_str} pertenece al turno {t_calc}. '
                          f'Usted está en el turno {turno_actual_sistema}.', 'danger')
                    return redirect(url_for('enfermeria.crear_nota', paciente_id=paciente_id))
                # ------------------------------------

                if fecha_final > ahora:
                    flash('No se pueden realizar notas con horas futuras.', 'error')
                    return redirect(url_for('enfermeria.crear_nota', paciente_id=paciente_id))

            except Exception as e:
                print(f"Error procesando hora: {e}")

        if not tipo_nota or not texto_nota:
            flash('Debe seleccionar un tipo de nota y escribir el contenido.', 'error')
            return redirect(url_for('enfermeria.crear_nota', paciente_id=paciente_id))

        registro = RegistroEnfermeria(
            paciente_id=int(paciente_id),
            historia_clinica_id=historia_id,
            fecha_registro=fecha_final,
            signos_vitales=json.dumps({}),
            balance_liquidos=json.dumps({}),
            control_glicemia=None,
            observaciones=None,
            tipo_nota=tipo_nota,
            texto_nota=texto_nota,
        )

        db.session.add(registro)
        db.session.commit()
        
        # MENSAJE DE ÉXITO
        flash('Nota de enfermería guardada. Puede redactar otra.', 'success')
        
        # --- CAMBIO AQUÍ: Redirige a la misma función en lugar de salir al menú ---
        return redirect(url_for('enfermeria.crear_nota', paciente_id=paciente_id))

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
                                        cantidad, unidad, via, observaciones=None, hora_manual=None):
    med = Medicamento.query.filter_by(codigo=codigo_medicamento).first()
    if not med:
        raise ValueError(f"Medicamento {codigo_medicamento} no encontrado")
    
    ahora = ahora_bogota()
    fecha_final = hora_manual if hora_manual else ahora

    admin = AdministracionMedicamento(
        registro_enfermeria_id=registro_enfermeria_id,
        medicamento_id=med.id,
        cantidad=cantidad,
        unidad=unidad,
        via=via,
        observaciones=observaciones,
        hora_administracion=fecha_final,
    )
    db.session.add(admin)

    med.cantidad_disponible = (med.cantidad_disponible or 0) - Decimal(str(cantidad))
    if med.cantidad_disponible < 0:
        med.cantidad_disponible = 0

    db.session.commit()


# --- FUNCIÓN DE EDICIÓN ACTUALIZADA ---
@enfermeria_bp.route('/administracion/<int:admin_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_administracion_medicamento(admin_id):
    admin = AdministracionMedicamento.query.get_or_404(admin_id)
    registro_id = admin.registro_enfermeria_id

    # VALIDACIÓN DE TURNO (Ahora también en Editar)
    permitido, mensaje = validar_turno_estricto(admin.registro)
    if not permitido:
        flash(mensaje, "danger")
        return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))

    if request.method == 'GET':
        return render_template('enfermeria/editar_medicamento.html', admin=admin)

    # ... (resto de tu lógica de guardado de edición que ya tenías)
    nueva_cantidad = request.form.get('cantidad')
    # ... (procesar cambios y db.session.commit())
    return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))


# --- FUNCIÓN DE ELIMINACIÓN ACTUALIZADA ---
@enfermeria_bp.route('/administracion/<int:admin_id>/eliminar', methods=['POST'])
@login_required
def eliminar_administracion_medicamento(admin_id):
    admin = AdministracionMedicamento.query.get_or_404(admin_id)
    registro_id = admin.registro_enfermeria_id

    # VALIDACIÓN DE TURNO
    permitido, mensaje = validar_turno_estricto(admin.registro)
    if not permitido:
        flash(mensaje, "danger")
        return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))

    try:
        if admin.medicamento:
            admin.medicamento.cantidad_disponible += Decimal(str(admin.cantidad))
        db.session.delete(admin)
        db.session.commit()
        flash('✅ Eliminado correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error: {str(e)}', 'danger')

    return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))


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
                # Primer filtro: que pertenezca a los registros (Relación)
                AdministracionMedicamento.registro_enfermeria_id.in_(registro_ids), 
                # Segundo filtro: que la cantidad sea mayor a 0 (Atributo directo)
                AdministracionMedicamento.cantidad > 0 
            )
            .order_by(AdministracionMedicamento.hora_administracion.desc())
            .limit(50)
            .all()
        )

    # 🧴 INSUMOS: usados y pendientes para este paciente
    insumos_paciente = InsumoPaciente.query.filter_by(paciente_id=paciente_id).all()

    insumos_registrados = []  # usados > 0
    insumos_pendientes = []   # usados == 0
    hoy_str = ahora_bogota().strftime('%Y-%m-%d')

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
                'observaciones': getattr(ip, 'observaciones', '') or 'Sin observaciones',
                'registro_obj': r
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
        insumos_pendientes=insumos_pendientes,
        fecha_hoy=hoy_str,
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
            cantidad=Decimal('0'), 
            unidad=med.get('unidad_inventario', 'tab'),
            # MODIFICACIÓN AQUÍ: Mismo orden de prioridad
            via=med.get('via') or med.get('via_administracion') or 'VO',
            observaciones=f"{med.get('dosis')} {med.get('frecuencia')}"
        )
            db.session.add(admin)
            count += 1
    
    db.session.commit()
    
    print(f"✅ {count} medicamentos cargados en registro {registro.id}")
    return {'exito': count, 'registro_id': registro.id}

@enfermeria_bp.route('/enfermeria/paciente/<int:paciente_id>/solicitar_insumos', methods=['GET', 'POST'])
@login_required
def solicitar_insumos(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    
    # 1. PROCESAR LA SOLICITUD (POST)
    if request.method == 'POST':
        insumo_id = request.form.get('insumo_id')
        cantidad = request.form.get('cantidad')
        
        if insumo_id and cantidad:
            try:
                # Verificar stock en bodega
                insumo_medico = InsumoMedico.query.get(insumo_id)
                cant_pedida = int(cantidad)
                
                if insumo_medico and insumo_medico.stock_actual >= cant_pedida:
                    # Crear el registro de insumo para el paciente
                    nueva_solicitud = InsumoPaciente(
                        paciente_id=paciente_id,
                        insumo_id=insumo_id,
                        cantidad=cant_pedida,
                        cantidad_usada=0,
                        fecha_solicitud=ahora_bogota(),
                        usuario_id=current_user.id  # Para saber quién lo pidió
                    )
                    
                    db.session.add(nueva_solicitud)
                    db.session.commit()
                    flash(f'✅ Se han solicitado {cant_pedida} unidades de {insumo_medico.nombre}', 'success')
                else:
                    flash('❌ No hay suficiente stock en bodega para esta solicitud.', 'danger')
                    
            except Exception as e:
                db.session.rollback()
                flash(f'Error al procesar solicitud: {str(e)}', 'danger')
        
        return redirect(url_for('enfermeria.solicitar_insumos', paciente_id=paciente_id))

@enfermeria_bp.route('/enfermeria/paciente/<int:paciente_id>/insumos/limpiar', methods=['POST'])
@login_required
def limpiar_insumos_solicitados(paciente_id):
    InsumoPaciente.query.filter_by(paciente_id=paciente_id, cantidad_usada=0).delete()
    db.session.commit()
    flash('🧹 Pendientes limpiados.', 'info')
    return redirect(url_for('enfermeria.solicitar_insumos', paciente_id=paciente_id))

@enfermeria_bp.route('/enfermeria/paciente/<int:paciente_id>/insumos/eliminar_uno/<int:insumo_paciente_id>', methods=['POST'])
@login_required
def eliminar_insumo_individual(paciente_id, insumo_paciente_id):
    insumo = InsumoPaciente.query.get_or_404(insumo_paciente_id)
    if insumo.paciente_id == paciente_id:
        db.session.delete(insumo)
        db.session.commit()
        flash('🗑️ Eliminado.', 'success')
    return redirect(url_for('enfermeria.solicitar_insumos', paciente_id=paciente_id))

@enfermeria_bp.route('/enfermeria/paciente/<int:paciente_id>/insumos/reset', methods=['POST'])
@login_required
def reset_insumos_paciente(paciente_id):
    InsumoPaciente.query.filter_by(paciente_id=paciente_id).delete()
    db.session.commit()
    flash('⚠️ Historial reiniciado.', 'warning')
    return redirect(url_for('enfermeria.solicitar_insumos', paciente_id=paciente_id))
# ---------- RUTAS DE EDICIÓN COMPLETAS ----------
@enfermeria_bp.route('/registro/<int:registro_id>/editar_signos', methods=['GET', 'POST'])
@login_required
def editar_signos(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    
    # 1. Obtener la hora actual en Bogotá
    ahora = ahora_bogota()
    hora_actual = ahora.hour
    
    # 2. Validación basada en el TURNO del registro (Margen ±1 hora)
    # Convertimos a mayúsculas para asegurar coincidencia
    turno = registro.turno.upper() if registro.turno else ""
    puede_editar = False

    if turno == 'MAÑANA':
        # Turno 7-13 | Permitido editar de 6am a 2pm (14:00)
        if 6 <= hora_actual < 14:
            puede_editar = True
    elif turno == 'TARDE':
        # Turno 13-19 | Permitido editar de 12pm a 8pm (20:00)
        if 12 <= hora_actual < 20:
            puede_editar = True
    elif turno == 'NOCHE':
        # Turno 19-07 | Permitido editar de 6pm a 8am (Cruza medianoche)
        if hora_actual >= 18 or hora_actual < 8:
            puede_editar = True

    # 3. Bloqueo si está fuera de rango
    if not puede_editar:
        flash(f'🚫 No se puede editar: El turno {turno} ya no está vigente para cambios (Margen ±1h agotado).', 'danger')
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=registro.paciente_id))

    # 4. Procesamiento del Formulario (POST)
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
        
        try:
            db.session.commit()
            flash('✅ Signos vitales actualizados correctamente.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error al guardar: {str(e)}', 'danger')
            
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=registro.paciente_id))
    
    # 5. Carga de datos para el Template (GET)
    sv = parse_json_seguro(registro.signos_vitales)
    return render_template('enfermeria/editar_signos.html', registro=registro, sv=sv)
@enfermeria_bp.route('/enfermeria/paciente/<int:paciente_id>/registrar_insumos', methods=['GET', 'POST'])
@login_required
def registrar_insumos(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    
    if request.method == 'POST':
        # Obtenemos la lista de IDs de los insumos que el enfermero seleccionó en los checkboxes
        insumos_ids = request.form.getlist('insumos_reg[]')
        
        try:
            for i_id in insumos_ids:
                # 1. Obtener el registro de la asignación del paciente
                insumo_p = InsumoPaciente.query.get(i_id)
                # 2. Obtener la cantidad que el enfermero escribió en el input
                cantidad_usada = float(request.form.get(f'cant_{i_id}', 0))
                observaciones = request.form.get(f'obs_{i_id}', '')

                if insumo_p and cantidad_usada > 0:
                    # Actualizar lo usado en la tabla del paciente
                    insumo_p.cantidad_usada = (insumo_p.cantidad_usada or 0) + cantidad_usada
                    insumo_p.observaciones = observaciones
                    
                    # 3. DESCONTAR DEL STOCK REAL (Bodega Central)
                    insumo_medico = InsumoMedico.query.get(insumo_p.insumo_id)
                    if insumo_medico:
                        insumo_medico.stock_actual -= cantidad_usada

            db.session.commit()
            flash('✅ Uso de insumos registrado y descontado de bodega.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error al registrar: {str(e)}', 'danger')
            
        return redirect(url_for('enfermeria.solicitar_insumos', paciente_id=paciente_id))

    # Si entran por GET (directo a la tabla de registro)
    insumos = InsumoPaciente.query.filter(
        InsumoPaciente.paciente_id == paciente_id,
        (InsumoPaciente.cantidad - InsumoPaciente.cantidad_usada) > 0
    ).all()
    
    # Preparar datos para que el HTML los lea fácil
    lista_final = []
    for item in insumos:
        m = InsumoMedico.query.get(item.insumo_id)
        lista_final.append({
            'id': item.id,
            'nombre': m.nombre if m else "Desconocido",
            'solicitado': item.cantidad,
            'usado': item.cantidad_usada or 0,
            'observaciones': item.observaciones or ''
        })

    return render_template('enfermeria/registrar_insumos.html', paciente=paciente, insumos=lista_final)

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
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=registro.paciente_id))

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
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=registro.paciente_id))
    
    # Preparar datos para el formulario
    bl = json.loads(registro.balance_liquidos or '{"administrados":{}, "eliminados":{}}')
    return render_template('enfermeria/editar_balance.html', registro=registro, bl=bl)

@enfermeria_bp.route('/registro/<int:registro_id>/editar_nota', methods=['GET', 'POST'])
@login_required
def editar_nota(registro_id):
    # 1. Obtener el objeto (aquí se llama 'registro')
    registro = RegistroEnfermeria.query.get_or_404(registro_id)

    # 2. VALIDACIÓN: Usamos 'registro' directamente
    permitido, mensaje = validar_turno_estricto(registro)
    if not permitido:
        flash(mensaje, "danger")
        # Redirigimos al detalle del paciente o donde prefieras
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=registro.paciente_id))

    # 3. Manejo de zonas horarias
    ahora = ahora_bogota()
    fecha_reg = registro.fecha_registro
    if fecha_reg.tzinfo is None:
        fecha_reg = fecha_reg.replace(tzinfo=ahora.tzinfo)
    
    # 2. Cálculo de diferencia de tiempo
    diff_horas = (ahora - fecha_reg).total_seconds() / 3600
    
    # 3. Validación de las 2 horas
    if abs(diff_horas) > 2:
        flash(f'No es posible editar la nota. Han pasado {round(abs(diff_horas), 1)} horas.', 'danger')
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=registro.paciente_id))

    if request.method == 'POST':
        # Actualizamos los campos de la nota
        registro.tipo_nota = request.form.get('tipo_nota')
        registro.texto_nota = request.form.get('texto_nota')
        
        db.session.commit()
        flash('✅ Nota de enfermería actualizada con éxito.', 'success')
        # Redirigir al detalle del paciente
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=registro.paciente_id))
    
    return render_template('enfermeria/editar_nota.html', registro=registro)

@enfermeria_bp.route('/medicamento/<int:admin_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_administracion_med(admin_id):
    # Buscamos el registro de administración específico
    admin = AdministracionMedicamento.query.get_or_404(admin_id)
    registro = RegistroEnfermeria.query.get(admin.registro_enfermeria_id)
    permitido, mensaje = validar_turno_estricto(registro)
    if not permitido:
        flash(mensaje, "danger")
        return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=admin.registro_enfermeria_id))
    # Validación de tiempo (2 horas)
    ahora = ahora_bogota()
    fecha_admin = admin.hora_administracion
    if fecha_admin.tzinfo is None:
        fecha_admin = fecha_admin.replace(tzinfo=ahora.tzinfo)
    
    diff_horas = (ahora - fecha_admin).total_seconds() / 3600
    if abs(diff_horas) > 2:
        flash('No se puede editar la administración de medicamento después de 2 horas.', 'danger')
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=registro.paciente_id))

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
            
        return redirect(url_for('enfermeria.registros_paciente', paciente_id=registro.paciente_id))

    return render_template('enfermeria/editar_medicamento.html', admin=admin, registro=registro)

@enfermeria_bp.route('/insumo/<int:insumo_paciente_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_insumo_paciente(insumo_paciente_id):
    insumo_p = InsumoPaciente.query.get_or_404(insumo_paciente_id)
    registro = RegistroEnfermeria.query.get(insumo_p.registro_enfermeria_id)
    if registro:
        permitido, mensaje = validar_turno_estricto(registro)
        if not permitido:
            flash(mensaje, "danger")
            return redirect(request.referrer)

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

@enfermeria_bp.app_context_processor
def inject_permissions():
    def puede_editar(objeto):
        if not objeto: return False
        reg = getattr(objeto, 'registro', objeto)
        # USA LA VISUAL (Con margen de 2 horas)
        return validar_acceso_visual(reg)
    return dict(puede_editar=puede_editar)



