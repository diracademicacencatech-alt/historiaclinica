from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, make_response
from datetime import datetime, date
from app.extensions import db
from app.models import Paciente, RegistroEnfermeria, HistoriaClinica, SignosVitales, OrdenMedica, DiagnosticoCIE10
from flask_login import login_required
import pandas as pd
import io
import json  # para usar json.dumps

from app.models import (
    Paciente,
    HistoriaClinica,
    SignosVitales,
    RegistroEnfermeria,
    DiagnosticoCIE10,
    Medicamento,
    OrdenLaboratorioItem,
    CatLaboratorioExamen,
)
from app.utils.fechas import ahora_bogota
from app.utils.fechas import tz_bogota
from weasyprint import HTML
from datetime import datetime

pacientes_bp = Blueprint('pacientes', __name__, url_prefix='/pacientes')

@pacientes_bp.route('/listar', methods=['GET'], endpoint='listar')
@login_required
def listar():
    """Lista todos los pacientes con paginación"""
    page = request.args.get('page', 1, type=int)
    pacientes = Paciente.query.paginate(page=page, per_page=10)
    
    return render_template(
        'pacientes/listar.html',
        pacientes=pacientes.items,
        pagination=pacientes
    )

@pacientes_bp.route('/crear', methods=['GET', 'POST'], endpoint='crear')
@login_required
def crear():
    if request.method == 'POST':
        try:
            nombre = request.form.get('nombre')
            numero = request.form.get('numero')
            cama = request.form.get('cama')

            if not (nombre and numero):
                flash('Nombre y número son obligatorios', 'warning')
                return redirect(url_for('pacientes.crear'))

            nuevo_paciente = Paciente(nombre=nombre, numero=numero, cama=cama)
            db.session.add(nuevo_paciente)
            db.session.flush()

            registro = RegistroEnfermeria(
                paciente_id=nuevo_paciente.id,
                fecha_registro=ahora_bogota()
            )
            db.session.add(registro)
            db.session.commit()

            flash('Paciente creado correctamente.', 'success')
            return redirect(url_for('pacientes.listar'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear paciente: {e}', 'danger')
            return redirect(url_for('pacientes.crear'))

    return render_template('pacientes/crear_simple.html')

@pacientes_bp.route('/pacientes/nuevo_ingreso', methods=['GET', 'POST'])
def nuevo_ingreso():
    if request.method == 'POST':
        form = request.form

        # ==================== 1. CREAR PACIENTE ====================
        paciente = Paciente(
            nombre=form.get('nombre'),
            numero=form.get('numero'),
            cama=form.get('cama')
        )
        db.session.add(paciente)
        db.session.flush()

        # ==================== 2. PROCESAR MEDICAMENTOS ====================
        medicamentos = []
        idx = 0
        while True:
            prefix = f'medicamentos[{idx}]'
            codigo = form.get(f'{prefix}[codigo]')
            if codigo is None:
                break

            if codigo.strip():
                medicamentos.append({
                    'codigo': codigo.strip(),
                    'dosis': form.get(f'{prefix}[dosis]', '').strip(),
                    'frecuencia': form.get(f'{prefix}[frecuencia]', '').strip(),
                    'cantidad_solicitada': form.get(f'{prefix}[cantidad_solicitada]', '').strip(),
                    'unidad_inventario': form.get(f'{prefix}[unidad_inventario]', '').strip(),
                    'via_administracion': form.get(f'{prefix}[via_administracion]', '').strip()
                })
            idx += 1

        # ==================== 3. CONVERTIR FECHA ====================
        fecha_nac = None
        if form.get('fecha_nacimiento'):
            try:
                fecha_nac = datetime.strptime(
                    form.get('fecha_nacimiento'),
                    '%Y-%m-%d'
                ).date()
            except:
                fecha_nac = None

        # ==================== 4. CREAR HISTORIA CLÍNICA ====================
        historia = HistoriaClinica(
            paciente_id=paciente.id,
            tipo_historia='ingreso',
            numero_historia=form.get('numero_historia'),
            numero_ingreso=form.get('numero_ingreso'),
            nombre_paciente=form.get('nombre'),
            cie10_principal=form.get('cie10_principal'),
            servicio_hospitalario=form.get('servicio_hospitalario'),
            fecha_nacimiento=fecha_nac,
            edad=form.get('edad') or None,
            direccion=form.get('direccion'),
            procedencia=form.get('procedencia'),
            sexo=form.get('sexo'),
            telefono=form.get('telefono'),
            regimen=form.get('regimen'),
            estrato=form.get('estrato') or None,
            plan_beneficios=form.get('plan_beneficios'),
            acudiente_responsable=form.get('acudiente_responsable'),
            telefono_responsable=form.get('telefono_responsable'),
            direccion_responsable=form.get('direccion_responsable'),
            nombre_padre=form.get('nombre_padre'),
            nombre_madre=form.get('nombre_madre'),
            fecha_registro=ahora_bogota().date(),
            subjetivos=form.get('subjetivos'),
            objetivos=form.get('objetivos'),
            analisis=form.get('analisis'),
            plan=form.get('plan'),
            medicamentos_json=json.dumps(medicamentos, ensure_ascii=False),
            
            # ==================== ANTECEDENTES NUEVOS ====================
            antecedentes_medicos=form.get('antecedentes_medicos', '').strip() or None,
            antecedentes_farmacologicos=form.get('antecedentes_farmacologicos', '').strip() or None,
            antecedentes_quirurgicos=form.get('antecedentes_quirurgicos', '').strip() or None,
            antecedentes_toxicos=form.get('antecedentes_toxicos', '').strip() or None,
            antecedentes_alergicos=form.get('antecedentes_alergicos', '').strip() or None,
            antecedentes_ginecobstetricos=form.get('antecedentes_ginecobstetricos', '').strip() or None,
            
            # ==================== RIESGOS NUEVOS ====================
            riesgos_general=form.get('riesgos_general', '').strip() or None,
            riesgo_caidas_dowton=form.get('riesgo_caidas_dowton', '').strip() or None,
            riesgo_upp_braden=form.get('riesgo_upp_braden', '').strip() or None,
            riesgos_evaluacion=form.get('riesgos_evaluacion', '').strip() or None,
            
            # ==================== ALERGIAS NUEVAS ====================
            tiene_alergias=form.get('tiene_alergias', 'no').strip(),
            descripcion_alergias=form.get('descripcion_alergias', '').strip() or None,
        )
        db.session.add(historia)
        db.session.flush()

        # ==================== 5. VALIDAR ALERGIAS ====================
        if historia.tiene_alergias == 'si' and not historia.descripcion_alergias:
            db.session.rollback()
            flash('❌ Debe describir las alergias si marca SÍ tiene alergias.', 'danger')
            diagnosticos_cie10 = DiagnosticoCIE10.query.order_by(DiagnosticoCIE10.codigo).all()
            medicamentos_catalogo = Medicamento.query.order_by(Medicamento.nombre).all()
            return render_template(
                'pacientes/nuevo_ingreso.html',
                diagnosticos_cie10=diagnosticos_cie10,
                medicamentos_catalogo=medicamentos_catalogo,
                form_data=form
            )

        # ==================== 6. SIGNOS VITALES ====================
        sv = SignosVitales(
            historia_id=historia.id,
            tension_arterial=form.get('tension_arterial'),
            frecuencia_cardiaca=form.get('frecuencia_cardiaca'),
            frecuencia_respiratoria=form.get('frecuencia_respiratoria'),
            temperatura=form.get('temperatura'),
            saturometria=form.get('saturometria'),
            fi02=form.get('fi02'),
            escala_dolor=form.get('escala_dolor'),
            glucometria=form.get('glucometria'),
            peso=form.get('peso'),
            talla=form.get('talla'),
            imc=form.get('imc')
        )
        db.session.add(sv)

        db.session.commit()
        flash('✅ Paciente e historia de ingreso creados correctamente con antecedentes, riesgos y alergias', 'success')
        return redirect(url_for('pacientes.listar'))

        # GET: cargar catálogos
    diagnosticos_cie10 = DiagnosticoCIE10.query.order_by(DiagnosticoCIE10.codigo).all()
    medicamentos_catalogo = Medicamento.query.order_by(Medicamento.nombre).all()
    return render_template(
        'pacientes/nuevo_ingreso.html',
        diagnosticos_cie10=diagnosticos_cie10,
        medicamentos_catalogo=medicamentos_catalogo,
        historia=None  # ✅ NUEVA LÍNEA
    )


@pacientes_bp.route('/eliminar/<int:paciente_id>', methods=['POST'], endpoint='eliminar')
@login_required
def eliminar_paciente(paciente_id):
    paciente = Paciente.query.get_or_404(paciente_id)
    try:
        for historia in list(paciente.historias_clinicas):
            if getattr(historia, 'signos_vitales', None):
                db.session.delete(historia.signos_vitales)
            db.session.delete(historia)

        for reg in list(paciente.registros_enfermeria):
            db.session.delete(reg)

        db.session.delete(paciente)
        db.session.commit()
        flash(f'Paciente {paciente.nombre} y todos sus registros fueron eliminados.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar paciente: {e}', 'danger')

    return redirect(url_for('pacientes.listar'))

@pacientes_bp.route('/carga-masiva', methods=['GET', 'POST'], endpoint='carga_masiva')
@login_required
def carga_masiva():
    if request.method == 'POST':
        file = request.files.get('archivo')
        if not file or file.filename == '':
            flash('Debe seleccionar un archivo Excel o CSV.', 'warning')
            return redirect(url_for('pacientes.carga_masiva'))

        try:
            if file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
                df = pd.read_excel(file)
            else:
                df = pd.read_csv(file, sep=';', encoding='utf-8')

            columnas_requeridas = [
                'NOMBRE', 'NUMERO', 'CAMA', 'NUMERO_HC', 'NUMERO_INGRESO',
                'SERVICIO', 'REGIMEN', 'ESTRATO', 'PLAN_BENEFICIOS',
                'ACUDIENTE', 'TEL_ACUDIENTE', 'DIR_ACUDIENTE', 'PADRE', 'MADRE',
                'SUBJETIVOS', 'OBJETIVOS', 'ANALISIS', 'PLAN'
            ]

            columnas_faltantes = [col for col in columnas_requeridas if col not in df.columns]
            if columnas_faltantes:
                flash(f'❌ Columnas faltantes: {", ".join(columnas_faltantes)}', 'danger')
                return redirect(url_for('pacientes.carga_masiva'))

            creados = 0
            errores = []

            for idx, row in df.iterrows():
                try:
                    nombre = str(row['NOMBRE']).strip() if pd.notna(row['NOMBRE']) else ''
                    numero = str(row['NUMERO']).strip() if pd.notna(row['NUMERO']) else ''

                    if not nombre or not numero:
                        errores.append(f"Fila {idx+2}: NOMBRE o NUMERO vacíos")
                        continue

                    paciente_existente = Paciente.query.filter_by(numero=numero).first()
                    if paciente_existente:
                        errores.append(f"Fila {idx+2}: Paciente {numero} ya existe")
                        continue

                    paciente = Paciente(
                        nombre=nombre,
                        numero=numero,
                        cama=str(row.get('CAMA', '') or '').strip()
                    )
                    db.session.add(paciente)
                    db.session.flush()

                    historia = HistoriaClinica(
                        paciente_id=paciente.id,
                        tipo_historia='ingreso',
                        numero_historia=str(row.get('NUMERO_HC', '') or '').strip(),
                        numero_ingreso=str(row.get('NUMERO_INGRESO', '') or '').strip(),
                        nombre_paciente=nombre,
                        servicio=str(row.get('SERVICIO', '') or '').strip(),
                        regimen=str(row.get('REGIMEN', '') or '').strip(),
                        estrato=int(row['ESTRATO']) if pd.notna(row.get('ESTRATO')) and str(row['ESTRATO']).isdigit() else None,
                        plan_beneficios=str(row.get('PLAN_BENEFICIOS', '') or '').strip(),
                        acudiente_responsable=str(row.get('ACUDIENTE', '') or '').strip(),
                        telefono_responsable=str(row.get('TEL_ACUDIENTE', '') or '').strip(),
                        direccion_responsable=str(row.get('DIR_ACUDIENTE', '') or '').strip(),
                        nombre_padre=str(row.get('PADRE', '') or '').strip(),
                        nombre_madre=str(row.get('MADRE', '') or '').strip(),
                        subjetivos=str(row.get('SUBJETIVOS', '') or '').strip(),
                        objetivos=str(row.get('OBJETIVOS', '') or '').strip(),
                        analisis=str(row.get('ANALISIS', '') or '').strip(),
                        plan=str(row.get('PLAN', '') or '').strip(),
                        fecha_registro=ahora_bogota(),
                        
                        # Nuevos campos - ANTECEDENTES (de carga masiva si existen)
                        antecedentes_medicos=str(row.get('ANTECEDENTES_MEDICOS', '') or '').strip() or None,
                        antecedentes_farmacologicos=str(row.get('ANTECEDENTES_FARM', '') or '').strip() or None,
                        antecedentes_quirurgicos=str(row.get('ANTECEDENTES_QUIRURG', '') or '').strip() or None,
                        antecedentes_toxicos=str(row.get('ANTECEDENTES_TOXICOS', '') or '').strip() or None,
                        antecedentes_alergicos=str(row.get('ANTECEDENTES_ALERGICOS', '') or '').strip() or None,
                        antecedentes_ginecobstetricos=str(row.get('ANTECEDENTES_GINEC', '') or '').strip() or None,
                        
                        # Nuevos campos - RIESGOS (de carga masiva si existen)
                        riesgos_general=str(row.get('RIESGOS_GENERAL', '') or '').strip() or None,
                        riesgo_caidas_dowton=str(row.get('RIESGO_CAIDAS', '') or '').strip() or None,
                        riesgo_upp_braden=str(row.get('RIESGO_UPP', '') or '').strip() or None,
                        riesgos_evaluacion=str(row.get('RIESGOS_EVAL', '') or '').strip() or None,
                        
                        # Nuevos campos - ALERGIAS (de carga masiva si existen)
                        tiene_alergias=str(row.get('TIENE_ALERGIAS', 'no') or 'no').strip().lower(),
                        descripcion_alergias=str(row.get('DESC_ALERGIAS', '') or '').strip() or None,
                    )
                    db.session.add(historia)
                    db.session.flush()

                    signos = SignosVitales(
                        historia_id=historia.id,
                        tension_arterial=str(row.get('TENSION_ARTERIAL', '') or '').strip() if 'TENSION_ARTERIAL' in df.columns else None,
                        frecuencia_cardiaca=int(row.get('FC', 0)) if pd.notna(row.get('FC')) and str(row.get('FC', '')).isdigit() and 'FC' in df.columns else None,
                        frecuencia_respiratoria=int(row.get('FR', 0)) if pd.notna(row.get('FR')) and str(row.get('FR', '')).isdigit() and 'FR' in df.columns else None,
                        temperatura=float(row.get('TEMPERATURA', 36.5)) if pd.notna(row.get('TEMPERATURA')) and str(row.get('TEMPERATURA', '')).replace('.', '').replace('-', '').isdigit() and 'TEMPERATURA' in df.columns else None,
                        saturometria=int(row.get('SATUROMETRIA', 95)) if pd.notna(row.get('SATUROMETRIA')) and str(row.get('SATUROMETRIA', '')).isdigit() and 'SATUROMETRIA' in df.columns else None,
                        escala_dolor=int(row.get('ESCALA_DOLOR', 0)) if pd.notna(row.get('ESCALA_DOLOR')) and str(row.get('ESCALA_DOLOR', '')).isdigit() and 'ESCALA_DOLOR' in df.columns else None,
                        fi02=str(row.get('FIO2', '')) if 'FIO2' in df.columns else None,
                        glucometria=int(row.get('GLUCOMETRIA', 0)) if pd.notna(row.get('GLUCOMETRIA')) and str(row.get('GLUCOMETRIA', '')).isdigit() and 'GLUCOMETRIA' in df.columns else None,
                        peso=float(row.get('PESO', 0)) if pd.notna(row.get('PESO')) and str(row.get('PESO', '')).replace('.', '').replace('-', '').isdigit() and 'PESO' in df.columns else None,
                        talla=float(row.get('TALLA', 0)) if pd.notna(row.get('TALLA')) and str(row.get('TALLA', '')).replace('.', '').replace('-', '').isdigit() and 'TALLA' in df.columns else None,
                        imc=float(row.get('IMC', 0)) if pd.notna(row.get('IMC')) and str(row.get('IMC', '')).replace('.', '').replace('-', '').isdigit() and 'IMC' in df.columns else None,
                    )
                    db.session.add(signos)

                    registro = RegistroEnfermeria(
                        paciente_id=paciente.id,
                        fecha_registro=ahora_bogota()
                    )
                    db.session.add(registro)

                    creados += 1

                except Exception as e:
                    errores.append(f"Fila {idx+2}: {str(e)}")

            db.session.commit()

            mensaje = f'✅ Se crearon {creados} pacientes con historia de ingreso.'
            if errores:
                mensaje += f' ⚠️ {len(errores)} error(es): ' + '; '.join(errores[:5])

            flash(mensaje, 'success' if creados > 0 else 'warning')
            return redirect(url_for('pacientes.listar'))

        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error procesando el archivo: {str(e)}', 'danger')
            return redirect(url_for('pacientes.carga_masiva'))

    return render_template('pacientes/carga_masiva.html')

@pacientes_bp.route('/descargar-plantilla', endpoint='descargar_plantilla')
@login_required
def descargar_plantilla():
    try:
        columnas = [
            # Datos básicos
            'NOMBRE', 'NUMERO', 'CAMA', 'NUMERO_HC', 'NUMERO_INGRESO',
            'SERVICIO', 'REGIMEN', 'ESTRATO', 'PLAN_BENEFICIOS',
            'ACUDIENTE', 'TEL_ACUDIENTE', 'DIR_ACUDIENTE', 'PADRE', 'MADRE',
            # SOAP
            'SUBJETIVOS', 'OBJETIVOS', 'ANALISIS', 'PLAN',
            # Signos vitales
            'TENSION_ARTERIAL', 'FC', 'FR', 'TEMPERATURA', 'SATUROMETRIA',
            'ESCALA_DOLOR', 'FIO2', 'GLUCOMETRIA', 'PESO', 'TALLA', 'IMC',
            # NUEVOS - ANTECEDENTES
            'ANTECEDENTES_MEDICOS', 'ANTECEDENTES_FARM', 'ANTECEDENTES_QUIRURG',
            'ANTECEDENTES_TOXICOS', 'ANTECEDENTES_ALERGICOS', 'ANTECEDENTES_GINEC',
            # NUEVOS - RIESGOS
            'RIESGOS_GENERAL', 'RIESGO_CAIDAS', 'RIESGO_UPP', 'RIESGOS_EVAL',
            # NUEVOS - ALERGIAS
            'TIENE_ALERGIAS', 'DESC_ALERGIAS'
        ]

        data = [{
            'NOMBRE': 'Juan Pérez López',
            'NUMERO': '12345',
            'CAMA': '101-A',
            'NUMERO_HC': 'HC-001-2025',
            'NUMERO_INGRESO': 'ING-001-2025',
            'SERVICIO': 'Pediatría',
            'REGIMEN': 'Contributivo',
            'ESTRATO': 3,
            'PLAN_BENEFICIOS': 'POS 2023',
            'ACUDIENTE': 'María González',
            'TEL_ACUDIENTE': '300 123 4567',
            'DIR_ACUDIENTE': 'Cra 10 #20-30 B/45 Bogotá',
            'PADRE': 'Pedro Pérez',
            'MADRE': 'Rosa García',
            'SUBJETIVOS': 'Fiebre hace 3 días tos productiva',
            'OBJETIVOS': 'T 38.2°C TA 110/70 FC 110',
            'ANALISIS': 'Infección respiratoria aguda',
            'PLAN': 'Ceftriaxona 1g IV c/12h reposo',
            'TENSION_ARTERIAL': '110/70',
            'FC': 110,
            'FR': 24,
            'TEMPERATURA': 38.2,
            'SATUROMETRIA': 96,
            'ESCALA_DOLOR': 5,
            'FIO2': 21,
            'GLUCOMETRIA': 120,
            'PESO': 25,
            'TALLA': 1.20,
            'IMC': 17.4,
            # NUEVOS
            'ANTECEDENTES_MEDICOS': 'Diabetes tipo 2, Hipertensión',
            'ANTECEDENTES_FARM': 'Metformina 500mg c/8h, Losartán 50mg c/día',
            'ANTECEDENTES_QUIRURG': 'Apendicectomía 2015',
            'ANTECEDENTES_TOXICOS': 'Tabaco negado, Alcohol negado',
            'ANTECEDENTES_ALERGICOS': 'Penicilina (rash)',
            'ANTECEDENTES_GINEC': 'G2P2C0, ciclos regulares',
            'RIESGOS_GENERAL': 'Riesgo de caídas por edad',
            'RIESGO_CAIDAS': 'Bajo (0-2)',
            'RIESGO_UPP': 'Moderado (15-18)',
            'RIESGOS_EVAL': 'Vigilancia continua, cambios posición',
            'TIENE_ALERGIAS': 'si',
            'DESC_ALERGIAS': 'Penicilina → rash generalizado'
        }]

        df = pd.DataFrame(data, columns=columnas)

        # CSV en memoria con separador ';'
        text_buffer = io.StringIO()
        df.to_csv(text_buffer, sep=';', index=False)
        csv_text = text_buffer.getvalue()

        # Añadir BOM UTF‑8
        bom = '\ufeff'
        csv_bytes = (bom + csv_text).encode('utf-8')

        return send_file(
            io.BytesIO(csv_bytes),
            as_attachment=True,
            download_name='plantilla_carga_pacientes_completa.csv',
            mimetype='text/csv; charset=utf-8'
        )
    except Exception as e:
        flash(f'Error descargando plantilla: {str(e)}', 'danger')
        return redirect(url_for('pacientes.carga_masiva'))

@pacientes_bp.route('/historias_por_paciente', methods=['GET'])
@login_required
def historias_por_paciente():
    paciente_id = request.args.get('paciente_id', type=int)
    if not paciente_id:
        return jsonify({'error': 'paciente_id requerido'}), 400

    historias = (
        HistoriaClinica.query
        .filter_by(paciente_id=paciente_id)
        .order_by(HistoriaClinica.fecha_registro.desc())
        .all()
    )

    datos = []
    for h in historias:
        datos.append({
            'id': h.id,
            'nombre': h.paciente.nombre if h.paciente else '',
            'numero': h.paciente.numero if h.paciente else '',
            'fecha_registro': h.fecha_registro.strftime('%Y-%m-%d %H:%M') if h.fecha_registro else '',
            'regimen': h.regimen or ''
        })

    return jsonify(datos)

@pacientes_bp.route('/autocomplete_cie10')
@login_required
def autocomplete_cie10():
    term = request.args.get('term', '', type=str)

    if not term:
        return jsonify([])

    # Buscar por código que EMPIEZA por term o nombre que contiene term
    query = DiagnosticoCIE10.query.filter(
        db.and_(
            DiagnosticoCIE10.habilitado.is_(True),
            db.or_(
                DiagnosticoCIE10.codigo.ilike(f"{term}%"),
                DiagnosticoCIE10.nombre.ilike(f"%{term}%"),
            )
        )
    ).order_by(DiagnosticoCIE10.codigo).limit(20)

    resultados = [
        {"label": f"{dx.codigo} - {dx.nombre}", "value": dx.codigo}
        for dx in query
    ]
    return jsonify(resultados)

@pacientes_bp.route('/historias/<int:historia_id>/orden_medica', methods=['GET', 'POST'])
@login_required
def orden_medica(historia_id):
    historia = HistoriaClinica.query.get_or_404(historia_id)

    if request.method == 'POST':
        form = request.form

        # ===== Medicamentos (igual que antes) =====
        medicamentos = []
        idx = 0
        while True:
            prefix = f'medicamentos[{idx}]'
            codigo = form.get(f'{prefix}[codigo]')
            if codigo is None:
                break
            if codigo.strip():
                medicamentos.append({
                    'codigo': codigo.strip(),
                    'dosis': form.get(f'{prefix}[dosis]', '').strip(),
                    'frecuencia': form.get(f'{prefix}[frecuencia]', '').strip(),
                    'cantidad_solicitada': form.get(f'{prefix}[cantidad_solicitada]', '').strip(),
                    'unidad_inventario': form.get(f'{prefix}[unidad_inventario]', '').strip(),
                    'via_administracion': form.get(f'{prefix}[via_administracion]', '').strip()
                })
            idx += 1

        # ===== Crear orden médica (igual) =====
        orden = OrdenMedica(
            historia_id=historia.id,
            indicaciones_medicas=form.get('indicaciones_medicas'),
            medicacion_texto=form.get('medicacion_texto'),
            medicamentos_json=json.dumps(medicamentos, ensure_ascii=False)
        )
        db.session.add(orden)
        db.session.flush()   # para tener orden.id sin cerrar la transacción

        # ===== NUEVO: exámenes de laboratorio seleccionados =====
        examenes_seleccionados = request.form.getlist('examenes_lab_ids[]')

        for ex_id in examenes_seleccionados:
            if not ex_id:
                continue
            item = OrdenLaboratorioItem(
                orden_id=orden.id,
                examen_id=int(ex_id),
                estado='solicitado'
            )
            db.session.add(item)

        db.session.commit()
        flash('Orden médica creada correctamente', 'success')
        return redirect(url_for('pacientes.listar'))

    # GET: cargar catálogos
    medicamentos_catalogo = Medicamento.query.order_by(Medicamento.nombre).all()
    examenes_catalogo = CatLaboratorioExamen.query.filter_by(activo=True).order_by(CatLaboratorioExamen.nombre).all()

    return render_template(
        'pacientes/crear_orden_medica.html',
        historia=historia,
        medicamentos_catalogo=medicamentos_catalogo,
        examenes_catalogo=examenes_catalogo
    )

@pacientes_bp.route('/historias/libro/<int:historia_id>/pdf')
@login_required
def pdf_libro_historia(historia_id):
    historia = HistoriaClinica.query.get_or_404(historia_id)
    ordenes = OrdenMedica.query.filter_by(historia_id=historia_id).all()
    fecha_ingreso_local = historia.fecha_registro if historia.fecha_registro else None

    diag_cie10 = None
    if historia.cie10_principal:
        diag_cie10 = DiagnosticoCIE10.query.filter_by(codigo=historia.cie10_principal).first()

    # --- PROCESAR MEDICAMENTOS GENERALES DE LA HISTORIA ---
    medicamentos = []
    if getattr(historia, 'medicamentos_json', None):
        try:
            datos_json = json.loads(historia.medicamentos_json)
            for m in datos_json:
                cod = str(m.get('codigo', '')).strip()
                med_db = Medicamento.query.filter_by(codigo=cod).first()
                m['nombre'] = med_db.nombre if med_db else f"Cod: {cod}"
                medicamentos.append(m)
        except Exception as e:
            print(f"Error procesando medicamentos para el PDF: {e}")

    # --- PROCESAR ÓRDENES (MEDICAMENTOS Y LABORATORIOS) ---
    ordenes_con_todo = []
    for orden in ordenes:
        # 1. Procesar Medicamentos de la Orden (JSON)
        meds_orden = []
        if orden.medicamentos_json:
            try:
                meds_lista_orden = json.loads(orden.medicamentos_json)
                for mo in meds_lista_orden:
                    cod_o = str(mo.get('codigo', '')).strip()
                    med_db_o = Medicamento.query.filter_by(codigo=cod_o).first()
                    mo['nombre'] = med_db_o.nombre if med_db_o else f"Cod: {cod_o}"
                    meds_orden.append(mo)
            except:
                meds_orden = []

        # 2. PROCESAR LABORATORIOS (Relación SQLAlchemy)
        # Según tu modelo, orden.examenes_lab es una lista de OrdenLaboratorioItem
        labs_orden = []
        if orden.examenes_lab:
            for item_lab in orden.examenes_lab:
                # Accedemos al nombre a través de la relación item_lab.examen
                labs_orden.append({
                    'nombre': item_lab.examen.nombre if item_lab.examen else "Examen no encontrado",
                    'estado': item_lab.estado
                })

        ordenes_con_todo.append({
            'orden': orden,
            'medicamentos': meds_orden,
            'laboratorios': labs_orden
        })

    html = render_template(
        'pacientes/pdf_libro.html',
        historia=historia,
        fecha_ingreso_local=fecha_ingreso_local,
        ordenes_con_meds=ordenes_con_todo,
        diag_cie10=diag_cie10,
        medicamentos=medicamentos,
        now=datetime.now(),
    )
    
    pdf = HTML(string=html).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=libro_historia_{historia_id}.pdf'
    return response

@pacientes_bp.route('/historias/libro/<int:historia_id>/ver')
@login_required
def ver_historia(historia_id):
    historia = HistoriaClinica.query.get_or_404(historia_id)
    ordenes = OrdenMedica.query.filter_by(historia_id=historia_id).all()
    fecha_ingreso_local = historia.fecha_registro if historia.fecha_registro else None

    diag_cie10 = None
    if historia.cie10_principal:
        diag_cie10 = DiagnosticoCIE10.query.filter_by(codigo=historia.cie10_principal).first()

    ordenes_con_todo = []
    for orden in ordenes:
        # Medicamentos
        meds_orden = []
        if orden.medicamentos_json:
            try:
                meds_lista = json.loads(orden.medicamentos_json)
                for m in meds_lista:
                    cod = m.get('codigo', '').strip()
                    med_db = Medicamento.query.filter_by(codigo=cod).first()
                    m['nombre'] = med_db.nombre if med_db else f"No encontrado ({cod})"
                    meds_orden.append(m)
            except Exception as e:
                meds_orden = []

        # Laboratorios (Usando la relación definida en el modelo OrdenMedica)
        labs_orden = []
        if orden.examenes_lab:
            for item_lab in orden.examenes_lab:
                labs_orden.append({
                    'nombre': item_lab.examen.nombre if item_lab.examen else "Examen no definido",
                    'estado': item_lab.estado
                })

        ordenes_con_todo.append({
            'orden': orden,
            'medicamentos': meds_orden,
            'laboratorios': labs_orden
        })

    return render_template(
        'pacientes/ver_historia.html',
        historia=historia,
        fecha_ingreso_local=fecha_ingreso_local,
        ordenes_con_meds=ordenes_con_todo,
        diag_cie10=diag_cie10,
    )

@pacientes_bp.route('/api/medicamentos/buscar', methods=['GET'])
@login_required
def buscar_medicamentos():
    """API para buscar medicamentos por nombre o código"""
    q = request.args.get('q', '').lower()
    
    if len(q) < 2:
        return jsonify([])
    
    medicamentos = Medicamento.query.filter(
        db.or_(
            Medicamento.codigo.ilike(f'%{q}%'),
            Medicamento.nombre.ilike(f'%{q}%')
        )
    ).limit(10).all()
    
    return jsonify([{
        'codigo': m.codigo,
        'nombre': m.nombre if m.nombre else f'Medicamento {m.codigo}',
        'dosis': m.dosis,
        'frecuencia': m.frecuencia
    } for m in medicamentos])

