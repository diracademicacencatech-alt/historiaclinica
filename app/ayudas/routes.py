from flask import (
    render_template, request, redirect, url_for,
    flash, jsonify, current_app, send_from_directory, send_file
)
from flask_login import current_user, login_required
from app.ayudas import ayudas_bp
from app.models import (
    Paciente, HistoriaClinica, AyudaDiagnostica,
    CatLaboratorioExamen, CatLaboratorioParametro,
    LabSolicitud, LabResultado
)
from app.extensions import db
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from io import BytesIO
from app.utils.fechas import ahora_bogota
from app.ayudas import ayudas_bp
from app.services.pplx_client import pplx_chat

UPLOAD_SUBFOLDER = os.path.join('uploads', 'ayudas')  # carpeta relativa

def guardar_archivo_ayuda(historia_id: int, tipo: str, file_storage):
    """
    Guarda un archivo para una ayuda diagnóstica y devuelve la ruta RELATIVA
    desde la raíz del proyecto (para guardar en BD).
    """
    if not file_storage or not file_storage.filename:
        return None

    nombre_seguro = secure_filename(file_storage.filename)

    # <root>/uploads/ayudas/<tipo>/<historia_id>/
    base_dir = os.path.join(current_app.root_path, UPLOAD_SUBFOLDER, tipo, str(historia_id))
    os.makedirs(base_dir, exist_ok=True)

    ruta_absoluta = os.path.join(base_dir, nombre_seguro)
    file_storage.save(ruta_absoluta)

    # ruta relativa, ej: uploads/ayudas/imagenes/10/archivo.png
    ruta_relativa = os.path.relpath(ruta_absoluta, current_app.root_path)
    return ruta_relativa

@ayudas_bp.route('/')
@login_required
def inicio_ayudas():
    """Pantalla principal del módulo: formulario de búsqueda de paciente."""
    return render_template(
        'ayudas/buscar_paciente.html',
        current_user=current_user
    )

@ayudas_bp.route('/buscar', methods=['POST'])
@login_required
def buscar_paciente():
    """Procesa el formulario de búsqueda y muestra resultados."""
    criterio = request.form.get('criterio', '').strip()

    if not criterio:
        flash('Ingrese un criterio de búsqueda (nombre o número de historia/paciente).', 'warning')
        return redirect(url_for('ayudas.inicio_ayudas'))

    pacientes = (
        Paciente.query
        .filter(
            (Paciente.nombre.ilike(f"%{criterio}%")) |
            (Paciente.numero.ilike(f"%{criterio}%"))
        )
        .all()
    )

    if not pacientes:
        flash('No se encontraron pacientes con ese criterio.', 'info')
        return redirect(url_for('ayudas.inicio_ayudas'))

    if len(pacientes) == 1:
        paciente_unico = pacientes[0]
        return redirect(url_for('ayudas.seleccionar_historia',
                                paciente_id=paciente_unico.id))

    return render_template(
        'ayudas/buscar_resultados.html',
        pacientes=pacientes,
        criterio=criterio,
        current_user=current_user
    )

@ayudas_bp.route('/paciente/<int:paciente_id>/historias')
@login_required
def seleccionar_historia(paciente_id):
    """Lista las historias clínicas de un paciente para seleccionar una."""
    paciente = Paciente.query.get_or_404(paciente_id)
    historias = (
        HistoriaClinica.query
        .filter_by(paciente_id=paciente.id)
        .order_by(HistoriaClinica.fecha_registro.desc())
        .all()
    )

    if not historias:
        flash('Este paciente no tiene historias clínicas registradas.', 'info')
        return redirect(url_for('ayudas.inicio_ayudas'))

    return render_template(
        'ayudas/seleccionar_historia.html',
        paciente=paciente,
        historias=historias,
        current_user=current_user
    )

@ayudas_bp.route('/historia/<int:historia_id>/ayudas')
@login_required
def menu_ayudas_historia(historia_id):
    """Menú principal de ayudas diagnósticas para una historia."""
    historia = HistoriaClinica.query.get_or_404(historia_id)
    paciente = historia.paciente

    return render_template(
        'ayudas/menu_ayudas_historia.html',
        paciente=paciente,
        historia=historia,
        current_user=current_user
    )

# ------- SUBMÓDULO: IMÁGENES (sin carga masiva, con observaciones) -------

@ayudas_bp.route('/historia/<int:historia_id>/imagenes', methods=['GET', 'POST'])
@login_required
def ayudas_imagenes(historia_id):
    historia = HistoriaClinica.query.get_or_404(historia_id)
    paciente = historia.paciente

    if request.method == 'POST':
        # Crear nuevo estudio con observaciones
        if 'nombre_examen' in request.form:
            nombre = request.form.get('nombre_examen', '').strip()
            fecha_str = request.form.get('fecha_resultado', '').strip()
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d') if fecha_str else None
            observaciones = request.form.get('observaciones', '').strip()
            archivo_rel = guardar_archivo_ayuda(historia_id, 'imagenes', request.files.get('archivo'))

            if nombre:
                ayuda = AyudaDiagnostica(
                    historia_id=historia.id,
                    tipo='imagen',
                    nombre_examen=nombre,
                    fecha_resultado=fecha,
                    archivo=archivo_rel,
                    observaciones=observaciones
                )
                db.session.add(ayuda)
                db.session.commit()
                flash('Estudio de imágenes registrado correctamente.', 'success')
            else:
                flash('El nombre del examen es obligatorio.', 'warning')

        # Actualizar solo observaciones de un registro existente
        elif 'ayuda_id' in request.form:
            ayuda_id = request.form.get('ayuda_id', type=int)
            ayuda = AyudaDiagnostica.query.get_or_404(ayuda_id)
            ayuda.observaciones = request.form.get('observaciones', '').strip()
            db.session.commit()
            flash('Observaciones actualizadas.', 'success')

    examenes = (
        AyudaDiagnostica.query
        .filter_by(historia_id=historia.id, tipo='imagen')
        .order_by(AyudaDiagnostica.fecha_resultado.desc().nullslast())
        .all()
    )

    return render_template(
        'ayudas/imagenes_listar.html',
        paciente=paciente,
        historia=historia,
        examenes=examenes,
        current_user=current_user
    )

# ------- SUBMÓDULO: LABORATORIOS AVANZADO -------

@ayudas_bp.route('/historia/<int:historia_id>/laboratorios', methods=['GET'])
@login_required
def ayudas_laboratorios(historia_id):
    """Lista las solicitudes de laboratorio de una historia clínica."""
    historia = HistoriaClinica.query.get_or_404(historia_id)
    paciente = historia.paciente

    solicitudes = (
        LabSolicitud.query
        .filter_by(historia_id=historia.id)
        .order_by(LabSolicitud.fecha_solicitud.desc())
        .all()
    )

    return render_template(
        'laboratorio/solicitudes_listar.html',
        paciente=paciente,
        historia=historia,
        solicitudes=solicitudes,
        current_user=current_user
    )

@ayudas_bp.route('/historia/<int:historia_id>/laboratorios/nueva', methods=['GET', 'POST'])
@login_required
def nueva_solicitud_laboratorio(historia_id):
    """Crear una nueva solicitud de laboratorio usando el catálogo."""
    historia = HistoriaClinica.query.get_or_404(historia_id)
    paciente = historia.paciente

    examenes = CatLaboratorioExamen.query.order_by(
        CatLaboratorioExamen.grupo, CatLaboratorioExamen.nombre
    ).all()

    if request.method == 'POST':
        examen_id = request.form.get('examen_id', type=int)
        if not examen_id:
            flash('Debe seleccionar un examen de laboratorio.', 'warning')
            return redirect(url_for('ayudas.nueva_solicitud_laboratorio', historia_id=historia_id))

        examen = CatLaboratorioExamen.query.get_or_404(examen_id)

        # encabezado
        solicitud = LabSolicitud(
            historia_id=historia.id,
            fecha_solicitud = ahora_bogota(),
            estado='pendiente'
        )
        db.session.add(solicitud)
        db.session.flush()  # para solicitud.id

        # resultados vacíos por cada parámetro
        for param in examen.parametros:
            resultado = LabResultado(
                solicitud_id=solicitud.id,
                examen_id=examen.id,
                parametro_id=param.id,
                unidad=param.unidad
            )
            db.session.add(resultado)

        db.session.commit()
        flash('Solicitud de laboratorio creada.', 'success')
        return redirect(url_for('ayudas.ver_solicitud_laboratorio', solicitud_id=solicitud.id))

    return render_template(
        'laboratorio/nueva_solicitud.html',
        paciente=paciente,
        historia=historia,
        examenes=examenes,
        current_user=current_user
    )

@ayudas_bp.route('/laboratorio/solicitud/<int:solicitud_id>', methods=['GET', 'POST'])
@login_required
def ver_solicitud_laboratorio(solicitud_id):
    """Vista maestro-detalle para capturar y ver resultados de una solicitud."""
    solicitud = LabSolicitud.query.get_or_404(solicitud_id)
    historia = solicitud.historia
    paciente = historia.paciente

    # Guardar valores de parámetros
    if request.method == 'POST':
        for res in solicitud.resultados:
            campo_valor = f"valor_{res.id}"
            campo_interp = f"interp_{res.id}"

            if campo_valor in request.form:
                nuevo_valor = request.form.get(campo_valor, '').strip()
                res.valor = nuevo_valor

                # marcar fuera de rango si hay referencia y valor numérico
                try:
                    v = float(nuevo_valor.replace(',', '.'))
                    p = res.parametro
                    if p.valor_ref_min is not None and p.valor_ref_max is not None:
                        res.flag_fuera_rango = not (p.valor_ref_min <= v <= p.valor_ref_max)
                except ValueError:
                    res.flag_fuera_rango = False

            if campo_interp in request.form:
                res.interpretacion = request.form.get(campo_interp, '').strip()

        solicitud.fecha_resultado = ahora_bogota()
        solicitud.estado = 'interpretado'
        db.session.commit()
        flash('Resultados de laboratorio actualizados.', 'success')
        return redirect(url_for('ayudas.ver_solicitud_laboratorio', solicitud_id=solicitud.id))

    # listado de solicitudes de esta historia (para la columna izquierda)
    solicitudes_historia = (
        LabSolicitud.query
        .filter_by(historia_id=historia.id)
        .order_by(LabSolicitud.fecha_solicitud.desc())
        .all()
    )

    return render_template(
        'laboratorio/solicitud_detalle.html',
        solicitud=solicitud,
        solicitudes_historia=solicitudes_historia,
        historia=historia,
        paciente=paciente,
        current_user=current_user
    )

# ------- CARGA MASIVA LABORATORIOS + PLANTILLA -------

@ayudas_bp.route('/laboratorios/descargar-plantilla', methods=['GET'])
@login_required
def descargar_plantilla_laboratorios():
    """Descarga una plantilla Excel para carga masiva de exámenes, 
    prellenada con pacientes y con catálogos de exámenes/parámetros."""

    wb = openpyxl.Workbook()

    # =========================
    # HOJA PRINCIPAL: EXÁMENES
    # =========================
    ws = wb.active
    ws.title = "Examenes"

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    headers = [
        'NUMERO_PACIENTE',
        'EXAMEN',
        'PARAMETRO',
        'VALOR',
        'FECHA_RESULTADO',
        'LABORATORIO'
    ]

    # Encabezados
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.value = header
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = thin_border

    # Pacientes existentes prellenados
    pacientes = Paciente.query.order_by(Paciente.numero).all()
    row_num = 2
    for p in pacientes:
        # Columna A: NUMERO_PACIENTE
        cell = ws.cell(row=row_num, column=1)
        cell.value = p.numero
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="left", vertical="center")

        # Otras columnas vacías pero formateadas
        for col_num in range(2, len(headers) + 1):
            c = ws.cell(row=row_num, column=col_num)
            c.border = thin_border
            c.alignment = Alignment(horizontal="left", vertical="center")

        row_num += 1

    # Ancho de columnas
    ws.column_dimensions['A'].width = 18  # NUMERO_PACIENTE
    ws.column_dimensions['B'].width = 25  # EXAMEN
    ws.column_dimensions['C'].width = 25  # PARAMETRO
    ws.column_dimensions['D'].width = 15  # VALOR
    ws.column_dimensions['E'].width = 20  # FECHA_RESULTADO
    ws.column_dimensions['F'].width = 20  # LABORATORIO

    # =======================
    # HOJA DE INSTRUCCIONES
    # =======================
    ws_instruc = wb.create_sheet("Instrucciones", 0)
    ws_instruc.column_dimensions['A'].width = 90

    instruc = [
        "INSTRUCCIONES DE CARGA MASIVA DE EXÁMENES DE LABORATORIO",
        "",
        "1. Hoja \"Examenes\":",
        "   - La columna NUMERO_PACIENTE ya viene prellenada con los pacientes existentes.",
        "   - NO modifique estos números. Si no va a registrar exámenes para un paciente,",
        "     simplemente deje su fila en blanco.",
        "",
        "2. COLUMNAS OBLIGATORIAS POR CADA FILA CON DATOS:",
        "   - NUMERO_PACIENTE: Ya viene prellenado.",
        "   - EXAMEN: Nombre exacto del examen en el sistema.",
        "   - PARAMETRO: Nombre exacto del parámetro del examen.",
        "   - VALOR: Valor del resultado.",
        "   - FECHA_RESULTADO: Fecha en formato DD/MM/YYYY.",
        "   - LABORATORIO: Nombre del laboratorio que realizó el examen.",
        "",
        "3. REGLAS:",
        "   - Puede dejar filas sin exámenes si no va a cargar nada para ese paciente.",
        "   - No cambie ni elimine los números de pacientes prellenados.",
        "   - No agregue filas intermedias vacías entre filas que sí tengan datos.",
        "",
        "4. HOJA \"Catalogos\":",
        "   - Contiene la lista de exámenes y parámetros válidos.",
        "   - Copie y pegue desde allí los valores de EXAMEN y PARAMETRO para evitar errores",
        "     de escritura.",
        "",
        "5. DESPUÉS DE LLENAR:",
        "   - Guardar el archivo como Excel (.xlsx).",
        "   - Ir a Módulo Ayudas > Laboratorios > Carga masiva.",
        "   - Seleccionar este archivo.",
        "   - Hacer clic en \"Procesar carga masiva\".",
    ]

    for idx, linea in enumerate(instruc, 1):
        cell = ws_instruc.cell(row=idx, column=1)
        cell.value = linea
        if idx == 1:
            cell.font = Font(bold=True, size=12)

    # ==========================
    # HOJA DE CATÁLOGOS
    # ==========================
    ws_cat = wb.create_sheet("Catalogos", 2)

    ws_cat['A1'] = "EXAMEN_ID"
    ws_cat['B1'] = "EXAMEN_NOMBRE"
    ws_cat['C1'] = "GRUPO"
    ws_cat['D1'] = "PARAMETRO_NOMBRE"
    ws_cat['E1'] = "UNIDAD"
    ws_cat['F1'] = "VALOR_REF_MIN"
    ws_cat['G1'] = "VALOR_REF_MAX"

    for col in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
        ws_cat.column_dimensions[col].width = 22

    header_cat_font = Font(bold=True)
    for col in range(1, 8):
        ws_cat.cell(row=1, column=col).font = header_cat_font

    examenes = CatLaboratorioExamen.query.order_by(
        CatLaboratorioExamen.grupo, CatLaboratorioExamen.nombre
    ).all()

    row = 2
    for ex in examenes:
        if ex.parametros:
            for p in ex.parametros:
                ws_cat.cell(row=row, column=1, value=ex.id)
                ws_cat.cell(row=row, column=2, value=ex.nombre)
                ws_cat.cell(row=row, column=3, value=ex.grupo or "")
                ws_cat.cell(row=row, column=4, value=p.nombre)
                ws_cat.cell(row=row, column=5, value=p.unidad or "")
                ws_cat.cell(row=row, column=6, value=p.valor_ref_min)
                ws_cat.cell(row=row, column=7, value=p.valor_ref_max)
                row += 1
        else:
            ws_cat.cell(row=row, column=1, value=ex.id)
            ws_cat.cell(row=row, column=2, value=ex.nombre)
            ws_cat.cell(row=row, column=3, value=ex.grupo or "")
            row += 1

    # ==========================
    # DEVOLVER ARCHIVO
    # ==========================
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='Plantilla_Carga_Masiva_Laboratorios.xlsx'
    )

@ayudas_bp.route('/laboratorios/carga_masiva', methods=['GET', 'POST'])
@login_required
def carga_masiva_laboratorios():
    if request.method == 'POST':
        file = request.files.get('archivo_masivo')
        if not file or file.filename == '':
            flash('Debe seleccionar un archivo.', 'warning')
            return redirect(url_for('ayudas.carga_masiva_laboratorios'))

        try:
            if file.filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file, sheet_name='Examenes')
            else:
                df = pd.read_csv(file)

            columnas_req = [
                'NUMERO_PACIENTE', 'EXAMEN', 'PARAMETRO',
                'VALOR', 'FECHA_RESULTADO', 'LABORATORIO'
            ]
            faltantes = [c for c in columnas_req if c not in df.columns]
            if faltantes:
                flash(f'Columnas faltantes: {", ".join(faltantes)}', 'danger')
                return redirect(url_for('ayudas.carga_masiva_laboratorios'))

            creados = 0
            errores = []
            
            for idx, row in df.iterrows():
                try:
                    num_pac = str(row['NUMERO_PACIENTE']).strip()
                    nombre_exam = str(row['EXAMEN']).strip()
                    nombre_param = str(row['PARAMETRO']).strip()
                    valor = str(row['VALOR']).strip()
                    lab_nombre = str(row.get('LABORATORIO') or '').strip()
                    
                    fecha_res = None
                    if pd.notna(row.get('FECHA_RESULTADO')):
                        try:
                            # Soportar DD/MM/YYYY
                            fecha_res = pd.to_datetime(row['FECHA_RESULTADO'], format='%d/%m/%Y').to_pydatetime()
                        except Exception:
                            try:
                                fecha_res = pd.to_datetime(row['FECHA_RESULTADO']).to_pydatetime()
                            except Exception as e:
                                errores.append(f"Fila {idx+2}: Fecha inválida")
                                continue

                    if not (num_pac and nombre_exam and nombre_param):
                        errores.append(f"Fila {idx+2}: Falta información obligatoria")
                        continue

                    paciente = Paciente.query.filter_by(numero=num_pac).first()
                    if not paciente:
                        errores.append(f"Fila {idx+2}: Paciente {num_pac} no encontrado")
                        continue

                    historia = (
                        HistoriaClinica.query
                        .filter_by(paciente_id=paciente.id)
                        .order_by(HistoriaClinica.fecha_registro.desc())
                        .first()
                    )
                    if not historia:
                        errores.append(f"Fila {idx+2}: Paciente {num_pac} sin historia clínica")
                        continue

                    examen = CatLaboratorioExamen.query.filter_by(nombre=nombre_exam).first()
                    if not examen:
                        errores.append(f"Fila {idx+2}: Examen '{nombre_exam}' no encontrado")
                        continue

                    param = CatLaboratorioParametro.query.filter_by(
                        examen_id=examen.id,
                        nombre=nombre_param
                    ).first()
                    if not param:
                        errores.append(f"Fila {idx+2}: Parámetro '{nombre_param}' no encontrado")
                        continue

                    # Buscar solicitud existente
                    solicitud = None
                    if fecha_res:
                        solicitud = (
                            LabSolicitud.query
                            .filter_by(
                                historia_id=historia.id,
                                laboratorio_nombre=lab_nombre
                            )
                            .filter(db.func.date(LabSolicitud.fecha_solicitud) == fecha_res.date())
                            .first()
                        )
                    
                    if not solicitud:
                        solicitud = LabSolicitud(
                            historia_id=historia.id,
                            fecha_solicitud=fecha_res or ahora_bogota(),
                            estado='completado',
                            laboratorio_nombre=lab_nombre
                        )
                        db.session.add(solicitud)
                        db.session.flush()

                    resultado = LabResultado(
                        solicitud_id=solicitud.id,
                        examen_id=examen.id,
                        parametro_id=param.id,
                        valor=valor,
                        unidad=param.unidad
                    )
                    db.session.add(resultado)
                    creados += 1

                except Exception as e:
                    errores.append(f"Fila {idx+2}: {str(e)}")
                    continue

            db.session.commit()
            
            msg = f'Se cargaron {creados} resultados de laboratorio.'
            if errores:
                msg += f' Se encontraron {len(errores)} errores.'
                flash(msg, 'warning')
                for error in errores[:10]:  # Mostrar máximo 10 errores
                    flash(f"  • {error}", 'warning')
            else:
                flash(msg, 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'Error procesando archivo: {e}', 'danger')

        return redirect(url_for('ayudas.carga_masiva_laboratorios'))

    return render_template('laboratorio/carga_masiva.html', current_user=current_user)

# ------- AUTOCOMPLETE PACIENTES -------

@ayudas_bp.route('/autocomplete')
@login_required
def autocomplete_pacientes():
    termino = request.args.get('q', '').strip()

    if not termino:
        return jsonify([])

    pacientes = (
        Paciente.query
        .filter(Paciente.nombre.ilike(f"%{termino}%"))
        .order_by(Paciente.nombre.asc())
        .limit(10)
        .all()
    )

    datos = [
        {"id": p.id, "nombre": p.nombre, "numero": p.numero}
        for p in pacientes
    ]
    return jsonify(datos)

# ------- VER ARCHIVO DE AYUDA -------

@ayudas_bp.route('/archivo/<int:ayuda_id>')
@login_required
def ver_archivo_ayuda(ayuda_id):
    ayuda = AyudaDiagnostica.query.get_or_404(ayuda_id)
    if not ayuda.archivo:
        flash('Este examen no tiene archivo asociado.', 'warning')
        if ayuda.tipo == 'imagen':
            return redirect(url_for('ayudas.ayudas_imagenes', historia_id=ayuda.historia_id))
        # cualquier otro tipo vuelve a laboratorios
        return redirect(url_for('ayudas.ayudas_laboratorios', historia_id=ayuda.historia_id))

    ruta_absoluta = os.path.join(current_app.root_path, ayuda.archivo)
    directorio, nombre = os.path.split(ruta_absoluta)

    return send_from_directory(directorio, nombre)

# ------- ELIMINAR AYUDA -------

@ayudas_bp.route('/eliminar/<int:ayuda_id>', methods=['POST'])
@login_required
def eliminar_ayuda(ayuda_id):
    ayuda = AyudaDiagnostica.query.get_or_404(ayuda_id)
    historia_id = ayuda.historia_id
    tipo = ayuda.tipo

    # Si tiene archivo, borrar también del disco (opcional)
    if ayuda.archivo:
        ruta_abs = os.path.join(current_app.root_path, ayuda.archivo)
        if os.path.exists(ruta_abs):
            try:
                os.remove(ruta_abs)
            except OSError:
                pass

    db.session.delete(ayuda)
    db.session.commit()
    flash('La ayuda diagnóstica se eliminó correctamente.', 'success')

    if tipo == 'imagen':
        return redirect(url_for('ayudas.ayudas_imagenes', historia_id=historia_id))
    return redirect(url_for('ayudas.ayudas_laboratorios', historia_id=historia_id))

@ayudas_bp.route('/laboratorios/gestion-catalogo', methods=['GET', 'POST'])
@login_required
def gestion_catalogo_laboratorios():
    """Ver y gestionar el catálogo de exámenes de laboratorio."""
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        grupo = request.form.get('grupo', '').strip()
        if not nombre:
            flash('El nombre del examen es obligatorio.', 'warning')
            return redirect(url_for('ayudas.gestion_catalogo_laboratorios'))

        examen = CatLaboratorioExamen(
            nombre=nombre,
            grupo=grupo or None,
            activo=True
        )
        db.session.add(examen)
        db.session.commit()
        flash('Examen agregado al catálogo.', 'success')
        return redirect(url_for('ayudas.gestion_catalogo_laboratorios'))

    examenes = (
        CatLaboratorioExamen.query
        .order_by(CatLaboratorioExamen.grupo, CatLaboratorioExamen.nombre)
        .all()
    )
    return render_template(
        'ayudas/gestion_catalogo_laboratorios.html',
        examenes=examenes,
        current_user=current_user
    )

@ayudas_bp.route('/laboratorios/catalogo/<int:examen_id>/toggle', methods=['POST'])
@login_required
def toggle_examen_catalogo(examen_id):
    """Activa o desactiva un examen del catálogo."""
    examen = CatLaboratorioExamen.query.get_or_404(examen_id)
    examen.activo = not bool(examen.activo)
    db.session.commit()
    flash('Estado del examen actualizado.', 'success')
    return redirect(url_for('ayudas.gestion_catalogo_laboratorios'))

@ayudas_bp.route('/laboratorios/cargar-catalogo', methods=['POST'])
@login_required
def cargar_catalogo_laboratorios():
    """Carga masiva del catálogo de exámenes (EXAMEN/GRUPO/PARAMETRO/UNIDAD/RANGOS)."""
    file = request.files.get('archivo_catalogo')
    if not file or file.filename == '':
        flash('Debe seleccionar un archivo de catálogo.', 'warning')
        return redirect(url_for('ayudas.gestion_catalogo_laboratorios'))

    try:
        # Leer Excel o CSV
        if file.filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file)
        else:
            df = pd.read_csv(file)

        columnas_req = ['EXAMEN', 'GRUPO', 'PARAMETRO', 'UNIDAD', 'VALOR_REF_MIN', 'VALOR_REF_MAX', 'TIPO']
        faltantes = [c for c in columnas_req if c not in df.columns]
        if faltantes:
            flash(f'Columnas faltantes en catálogo: {", ".join(faltantes)}', 'danger')
            return redirect(url_for('ayudas.gestion_catalogo_laboratorios'))

        # Opcional: borrar catálogo anterior
        # CatLaboratorioParametro.query.delete()
        # CatLaboratorioExamen.query.delete()
        # db.session.commit()

        creados_examenes = 0
        creados_parametros = 0

        for _, row in df.iterrows():
            nombre_exam = str(row['EXAMEN']).strip()
            grupo = str(row['GRUPO']).strip() if not pd.isna(row['GRUPO']) else None
            nombre_param = str(row['PARAMETRO']).strip()
            unidad = str(row['UNIDAD']).strip() if not pd.isna(row['UNIDAD']) else None
            ref_min = row['VALOR_REF_MIN'] if not pd.isna(row['VALOR_REF_MIN']) else None
            ref_max = row['VALOR_REF_MAX'] if not pd.isna(row['VALOR_REF_MAX']) else None

            if not nombre_exam:
                continue

            # Buscar o crear examen
            examen = CatLaboratorioExamen.query.filter_by(nombre=nombre_exam).first()
            if not examen:
                examen = CatLaboratorioExamen(
                    nombre=nombre_exam,
                    grupo=grupo,
                    activo=True
                )
                db.session.add(examen)
                db.session.flush()
                creados_examenes += 1
            else:
                # Actualizar grupo si cambió
                examen.grupo = grupo

            # Parámetro (puede haber filas sin parámetro)
            if nombre_param and nombre_param.lower() != 'nan':
                param = CatLaboratorioParametro.query.filter_by(
                    examen_id=examen.id,
                    nombre=nombre_param
                ).first()
                if not param:
                    param = CatLaboratorioParametro(
                        examen_id=examen.id,
                        nombre=nombre_param,
                        unidad=unidad,
                        valor_ref_min=ref_min,
                        valor_ref_max=ref_max
                    )
                    db.session.add(param)
                    creados_parametros += 1
                else:
                    param.unidad = unidad
                    param.valor_ref_min = ref_min
                    param.valor_ref_max = ref_max

        db.session.commit()
        flash(f'Catálogo actualizado. Exámenes nuevos: {creados_examenes}, parámetros nuevos: {creados_parametros}.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error procesando catálogo: {e}', 'danger')

    return redirect(url_for('ayudas.gestion_catalogo_laboratorios'))


@ayudas_bp.route('/laboratorios/descargar-catalogo-template', methods=['GET'])
@login_required
def descargar_catalogo_template():
    """Genera y descarga el catálogo completo de laboratorios."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Catalogo"

    # Estilos
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center")
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    # Encabezados
    headers = ['EXAMEN', 'GRUPO', 'PARAMETRO', 'UNIDAD', 'VALOR_REF_MIN', 'VALOR_REF_MAX', 'TIPO']
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = thin_border

    # Datos del catálogo (41 parámetros comunes)
    catalogo = [
        # HEMOGRAMA
        ('Hemograma Completo', 'Hematología', 'Hemoglobina', 'g/dL', 12.0, 16.0, 'Numérico'),
        ('Hemograma Completo', 'Hematología', 'Hematocrito', '%', 36.0, 46.0, 'Numérico'),
        ('Hemograma Completo', 'Hematología', 'Glóbulos Rojos', 'x10^6/µL', 4.2, 5.4, 'Numérico'),
        ('Hemograma Completo', 'Hematología', 'Glóbulos Blancos', 'x10^3/µL', 4.5, 11.0, 'Numérico'),
        ('Hemograma Completo', 'Hematología', 'Plaquetas', 'x10^3/µL', 150, 400, 'Numérico'),
        # GLUCOSA
        ('Glucosa en Ayunas', 'Química Sanguínea', 'Glucosa', 'mg/dL', 70.0, 100.0, 'Numérico'),
        # LIPIDOGRAMA
        ('Lipidograma', 'Química Sanguínea', 'Colesterol Total', 'mg/dL', None, 200.0, 'Numérico'),
        ('Lipidograma', 'Química Sanguínea', 'LDL', 'mg/dL', None, 130.0, 'Numérico'),
        ('Lipidograma', 'Química Sanguínea', 'HDL', 'mg/dL', 40.0, None, 'Numérico'),
        ('Lipidograma', 'Química Sanguínea', 'Triglicéridos', 'mg/dL', None, 150.0, 'Numérico'),
        # HEPÁTICO
        ('Función Hepática', 'Química Sanguínea', 'AST', 'U/L', 10.0, 40.0, 'Numérico'),
        ('Función Hepática', 'Química Sanguínea', 'ALT', 'U/L', 7.0, 56.0, 'Numérico'),
        ('Función Hepática', 'Química Sanguínea', 'Bilirrubina Total', 'mg/dL', 0.1, 1.2, 'Numérico'),
        # RENAL
        ('Función Renal', 'Química Sanguínea', 'Creatinina', 'mg/dL', 0.7, 1.3, 'Numérico'),
        ('Función Renal', 'Química Sanguínea', 'Urea', 'mg/dL', 7.0, 20.0, 'Numérico'),
        # ORINA
        ('Parcial de Orina', 'Uroanálisis', 'Color', None, None, None, 'Cualitativo'),
        ('Parcial de Orina', 'Uroanálisis', 'Aspecto', None, None, None, 'Cualitativo'),
        ('Parcial de Orina', 'Uroanálisis', 'Densidad', 'g/mL', 1.005, 1.030, 'Numérico'),
        ('Parcial de Orina', 'Uroanálisis', 'pH', None, 5.0, 9.0, 'Numérico'),
        ('Parcial de Orina', 'Uroanálisis', 'Nitritos', None, None, None, 'Cualitativo'),
        ('Parcial de Orina', 'Uroanálisis', 'Leucocitos', 'Leuco/µL', 0, 5, 'Numérico'),
        ('Parcial de Orina', 'Uroanálisis', 'Proteínas', 'mg/dL', None, 10.0, 'Numérico'),
        ('Parcial de Orina', 'Uroanálisis', 'Glucosa', 'mg/dL', None, 10.0, 'Numérico'),
        ('Parcial de Orina', 'Uroanálisis', 'Cetonas', None, None, None, 'Cualitativo'),
        ('Parcial de Orina', 'Uroanálisis', 'Sangre', 'Ery/µL', 0, 5, 'Numérico'),
        ('Parcial de Orina', 'Uroanálisis', 'Sedimento', None, None, None, 'Cualitativo'),
        # COAGULACIÓN
        ('Coagulación', 'Coagulación', 'PT', 'seg', 11.0, 13.5, 'Numérico'),
        ('Coagulación', 'Coagulación', 'INR', None, 0.8, 1.1, 'Numérico'),
        # TIROIDES
        ('Perfil Tiroideo', 'Endocrinología', 'TSH', 'mIU/L', 0.4, 4.0, 'Numérico'),
        ('Perfil Tiroideo', 'Endocrinología', 'T4 Libre', 'ng/dL', 0.8, 1.8, 'Numérico'),
    ]

    row = 2
    for examen, grupo, parametro, unidad, ref_min, ref_max, tipo in catalogo:
        ws.cell(row=row, column=1, value=examen).border = thin_border
        ws.cell(row=row, column=1).alignment = left_align
        ws.cell(row=row, column=2, value=grupo).border = thin_border
        ws.cell(row=row, column=2).alignment = left_align
        ws.cell(row=row, column=3, value=parametro).border = thin_border
        ws.cell(row=row, column=3).alignment = left_align
        ws.cell(row=row, column=4, value=unidad).border = thin_border
        ws.cell(row=row, column=4).alignment = left_align
        if ref_min: ws.cell(row=row, column=5, value=ref_min).border = thin_border
        if ref_max: ws.cell(row=row, column=6, value=ref_max).border = thin_border
        ws.cell(row=row, column=7, value=tipo).border = thin_border
        row += 1

    # Anchos
    for col, width in zip('ABCDEFG', [25,18,28,15,15,15,12]):
        ws.column_dimensions[col].width = width

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='Catalogo_Laboratorios.xlsx')

@ayudas_bp.post("/ia")
def ayudas_ia():
    prompt = request.json.get("prompt", "")
    if not prompt:
        return jsonify({"error": "Falta 'prompt'"}), 400

    respuesta = pplx_chat(prompt)
    return jsonify({"respuesta": respuesta})