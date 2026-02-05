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
    ahora = ahora_bogota()
    h = ahora.hour
    if 7 <= h < 13: return 'MAÑANA'
    if 13 <= h < 19: return 'TARDE'
    return 'NOCHE'
        
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

    # ... dentro de la función crear() ...
    if request.method == 'POST':
        # 1. Definimos las variables básicas primero (para que no den error de 'not defined')
        historia_id = request.form.get('historia_clinica_id')
        turno_form = (request.form.get('turno') or turno_real).upper()

        # 2. Validación de turno (tu lógica original)
        if turno_form != turno_real:
            flash(f'No puede registrar turno {turno_form} fuera de su horario.', 'warning')
            return redirect(url_for('enfermeria.crear', paciente_id=paciente_id))

        # 3. Procesamiento de la HORA (La nueva mejora)
        hora_str = (request.form.get('hora_sv') or 
                    request.form.get('hora_inicial') or 
                    request.form.get('hora_eliminado'))
        
        ahora = ahora_bogota()
        fecha_registro_final = ahora 

        if hora_str:
            try:
                # Usamos datetime.strptime y luego datetime.combine
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

@enfermeria_bp.route('/insumo/<int:insumo_paciente_id>/eliminar', methods=['POST'])
@login_required
def eliminar_insumo_paciente(insumo_paciente_id):
    # Buscamos el registro del insumo usado por el paciente
    insumo_p = InsumoPaciente.query.get_or_404(insumo_paciente_id)
    paciente_id = insumo_p.paciente_id

    try:
        # Opcional: Si manejas stock global, aquí podrías devolver la cantidad
        # insumo_p.insumo.stock += insumo_p.cantidad_usada
        
        db.session.delete(insumo_p)
        db.session.commit()
        flash('✅ Uso de insumo eliminado correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('❌ Error al eliminar el insumo.', 'danger')

    return redirect(url_for('enfermeria.registros_paciente', paciente_id=paciente_id))

# ---------- 5) ADMINISTRAR MEDICAMENTOS POR REGISTRO ----------
@enfermeria_bp.route('/registro/<int:registro_id>/medicamentos', methods=['GET', 'POST'])
@login_required
def administrar_medicamentos(registro_id):
    registro = RegistroEnfermeria.query.get_or_404(registro_id)
    paciente = Paciente.query.get(registro.paciente_id)
    
    # ========== PROCESAR GUARDADO (POST) ==========
    if request.method == 'POST' and 'codigo_medicamento' in request.form:
        codigo = request.form.get('codigo_medicamento')
        cantidad = request.form.get('cantidad')
                # Ajuste para el nuevo selector de hora HH:MM
        hora_input = request.form.get('hora_administracion')
        unidad = request.form.get('unidad', 'tab')
        via = request.form.get('via', 'VO')
        observaciones = request.form.get('observaciones', '')
        
        try:
            cantidad_dec = Decimal(cantidad)
            med = Medicamento.query.filter_by(codigo=codigo).first()
            
            ahora = ahora_bogota()
            if hora_input:
                h, m = map(int, hora_input.split(':'))
                hora_admin = datetime.combine(ahora.date(), time(h, m))
            else:
                hora_admin = ahora

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
            flash(f'✅ {med.nombre} registrado correctamente', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error al registrar: {str(e)}', 'danger')
        
        return redirect(url_for('enfermeria.administrar_medicamentos', registro_id=registro_id))

    # ========== CARGAR DATOS (GET) ==========
    medicamentos_formulados = []
    if registro.historia_clinica_id:
        historia_id = registro.historia_clinica_id
        todos_medicamentos = []
        
        # Cargar de Historia y Órdenes
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
        
       # --- LÓGICA DE PRODUCCIÓN: EXTRACCIÓN Y PERSISTENCIA ---
        meds_por_codigo = {}
        
        for med in todos_medicamentos:
            codigo = med.get('codigo') or med.get('codigo_medicamento')
            if not codigo: continue

            # 1. Si es la primera vez que vemos este código, inicializamos el contenedor
            if codigo not in meds_por_codigo:
                med_bd = Medicamento.query.filter_by(codigo=codigo).first()
                meds_por_codigo[codigo] = {
                    'total': 0,
                    'detalle': {
                        'nombre': med_bd.nombre if med_bd else (med.get('medicamento') or med.get('nombre')),
                        'dosis': '',
                        'frecuencia': '--',
                        'via': 'VO',
                        'unidad_inventario': med.get('unidad_inventario') or (med_bd.unidad_inventario if med_bd else 'und')
                    }
                }

            # 2. Sumar cantidades (Siempre acumulando)
            try:
                cantidad = float(med.get('cantidad') or med.get('cantidad_solicitada') or 0)
                meds_por_codigo[codigo]['total'] += cantidad
            except:
                pass

            # 3. Rescate de datos del registro actual
            dosis_actual = str(med.get('dosis') or '').strip()
            frec_actual = str(med.get('frecuencia') or med.get('periodicidad') or '').strip()
            via_actual = med.get('via') or med.get('via_administracion') or 'VO'

            # 4. REGLA DE PERSISTENCIA: Solo guardamos si el dato actual aporta más que lo que ya teníamos
            
            # Guardar Dosis si existe
            if dosis_actual and not meds_por_codigo[codigo]['detalle']['dosis']:
                meds_por_codigo[codigo]['detalle']['dosis'] = dosis_actual

            # Guardar Vía si es diferente a la genérica
            if via_actual and via_actual != 'VO':
                meds_por_codigo[codigo]['detalle']['via'] = via_actual

            # --- LÓGICA MAESTRA DE FRECUENCIA ---
            frec_final = frec_actual
            # Si no hay frecuencia, intentamos sacarla de la dosis
            if not frec_final or frec_final.lower() in ['none', '--', '', 'nan']:
                if 'CADA' in dosis_actual.upper():
                    frec_final = "Cada " + dosis_actual.upper().split('CADA')[-1].strip()

            # Solo actualizamos la frecuencia si encontramos algo real y lo que había era un "--"
            if frec_final and frec_final not in ['--', 'None', '']:
                meds_por_codigo[codigo]['detalle']['frecuencia'] = frec_final

        # CONSTRUIR LISTA FINAL (Claves idénticas a tu HTML original)
        for codigo, data in meds_por_codigo.items():
            formulada = Decimal(str(data['total']))
            admin_total = db.session.query(
                db.func.coalesce(db.func.sum(AdministracionMedicamento.cantidad), 0)
            ).join(Medicamento).filter(
                AdministracionMedicamento.registro_enfermeria_id == registro.id,
                Medicamento.codigo == codigo
            ).scalar() or 0
            
            admin_total = Decimal(str(admin_total))
            pendiente = max(formulada - admin_total, Decimal('0'))
            
            medicamentos_formulados.append({
                'codigo': codigo,
                'nombre': data['detalle'].get('nombre'),
                'dosis': data['detalle'].get('dosis'),
                'frecuencia': data['detalle'].get('frecuencia'),
                'via': data['detalle'].get('via'),
                'cantidad_formulada': formulada,
                'cantidad_administrada': admin_total,
                'pendiente': pendiente,
                'unidad_inventario': data['detalle'].get('unidad_inventario')
            })

    # Historial y otros datos para el template
    administraciones = AdministracionMedicamento.query.filter_by(
        registro_enfermeria_id=registro.id
    ).outerjoin(Medicamento).order_by(AdministracionMedicamento.hora_administracion.desc()).all()
    
    codigos_formulados = [m['codigo'] for m in medicamentos_formulados]
    medicamentos_dropdown = Medicamento.query.filter(Medicamento.codigo.in_(codigos_formulados)).all() if codigos_formulados else []
    
    # Hora actual formateada para el selector simple HH:MM
    hora_actual = ahora_bogota().strftime('%H:%M')
    
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


# ---------- 9) CREAR NOTA (AJUSTADA PARA PERMANECER EN EL MENÚ) ----------

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
        fecha_final = datetime.now()

        if hora_nota_str:
            try:
                h, m = map(int, hora_nota_str.split(':'))
                fecha_final = datetime.combine(fecha_final.date(), time(h, m))
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
    def puede_editar_turno_template(r):
        if not r or isinstance(r, str):
            return False
            
        try:
            ahora = ahora_bogota().replace(tzinfo=None)
            
            # Buscamos la fecha en CUALQUIER campo posible del objeto
            fecha_ref = None
            for campo in ['fecha_registro', 'hora_administracion', 'fecha_uso', 'fecha']:
                if hasattr(r, campo):
                    fecha_ref = getattr(r, campo)
                    break
            
            # SI NO HAY FECHA, NO PODEMOS CALCULAR; LO DEJAMOS EDITAR POR SI ACASO
            if not fecha_ref:
                return True 

            fecha_ref_sin_tz = fecha_ref.replace(tzinfo=None)
            diferencia = ahora - fecha_ref_sin_tz
            minutos_transcurridos = diferencia.total_seconds() / 60

            # --- REGLA DE ORO: SI TIENE MENOS DE 2 HORAS, SIEMPRE EDITABLE ---
            if 0 <= minutos_transcurridos < 120:
                return True

            # Si ya pasó el tiempo, verificamos el turno
            turno_registro = str(getattr(r, 'turno', '')).strip().upper()
            turno_actual = obtener_turno_actual().strip().upper()
            
            es_mismo_dia = fecha_ref_sin_tz.date() == ahora.date()
            es_mismo_turno = (turno_registro == turno_actual)
            
            # Si es el mismo turno y mismo día, permitir aunque pasen las 2 horas
            return es_mismo_dia and es_mismo_turno
            
        except Exception as e:
            # Si algo falla internamente, permitimos editar para no bloquear al usuario
            return True

    return dict(
        puede_editar_turno_template=puede_editar_turno_template
    )

