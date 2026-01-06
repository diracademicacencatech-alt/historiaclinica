from app.extensions import db, login_manager
from sqlalchemy.orm import backref
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime
from decimal import Decimal
import json
from app.utils.fechas import ahora_bogota

class User(db.Model, UserMixin):
    __tablename__ = 'usuarios'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class Paciente(db.Model):
    __tablename__ = 'pacientes'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    numero = db.Column(db.String(50), nullable=False, unique=True)
    cama = db.Column(db.String(50))

    registros_enfermeria = db.relationship(
        'RegistroEnfermeria',
        back_populates='paciente',
        cascade='all, delete-orphan',
        lazy=True
    )
    historias_clinicas = db.relationship(
        'HistoriaClinica',
        back_populates='paciente',
        cascade='all, delete-orphan',
        foreign_keys='HistoriaClinica.paciente_id'
    )
    insumos_paciente = db.relationship(
        'InsumoPaciente', 
        back_populates='paciente', 
        cascade='all, delete-orphan',
        lazy=True
    )

class HistoriaClinica(db.Model):
    __tablename__ = 'historias_clinicas'

    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey('pacientes.id'), nullable=False)
    historia_base_id = db.Column(db.Integer, db.ForeignKey('historias_clinicas.id'), nullable=True)

    # servicio libre que ya usas
    servicio = db.Column(db.String(150))

    # NUEVOS CAMPOS
    cie10_principal = db.Column(db.String(10))          # código CIE‑10 principal
    servicio_hospitalario = db.Column(db.String(50))    # ginecologia, uci_adultos, etc.
    medicamentos_json = db.Column(db.Text)              # lista de medicamentos en JSON

    historia_base = db.relationship(
        'HistoriaClinica',
        remote_side=[id],
        backref=backref('historias_vinculadas', cascade='save-update, merge')
    )

    paciente = db.relationship(
        'Paciente',
        back_populates='historias_clinicas',
        foreign_keys=[paciente_id]
    )

    tipo_historia = db.Column(db.String(50), nullable=False)

    numero_historia = db.Column(db.String(50))
    numero_ingreso = db.Column(db.String(50))
    nombre_paciente = db.Column(db.String(200))
    fecha_nacimiento = db.Column(db.Date)
    edad = db.Column(db.Integer)
    direccion = db.Column(db.String(250))
    procedencia = db.Column(db.String(250))
    sexo = db.Column(db.String(20))
    ocupacion = db.Column(db.String(150))
    telefono = db.Column(db.String(50))
    regimen = db.Column(db.String(50))
    estrato = db.Column(db.Integer)
    plan_beneficios = db.Column(db.String(150))
    acudiente_responsable = db.Column(db.String(150))
    telefono_responsable = db.Column(db.String(50))
    direccion_responsable = db.Column(db.String(250))
    nombre_padre = db.Column(db.String(150))
    nombre_madre = db.Column(db.String(150))
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    subjetivos = db.Column(db.Text)
    objetivos = db.Column(db.Text)
    analisis = db.Column(db.Text)
    plan = db.Column(db.Text)

    signos_vitales = db.relationship(
        'SignosVitales',
        back_populates='historia_clinica',
        uselist=False
    )
    ordenes_medicas = db.relationship(
        'OrdenMedica',
        back_populates='historia',
        cascade='all, delete-orphan'
    )
    evolucion = db.relationship(
        'Evolucion',
        back_populates='historia',
        uselist=False
    )
    diagnosticos = db.relationship(
        'Diagnostico',
        back_populates='historia'
    )


class OrdenMedica(db.Model):
    __tablename__ = 'ordenes_medicas'

    id = db.Column(db.Integer, primary_key=True)
    historia_id = db.Column(db.Integer, db.ForeignKey('historias_clinicas.id'), nullable=False)
    indicaciones_medicas = db.Column(db.Text, nullable=True)
    medicacion_texto = db.Column(db.Text, nullable=True)
    medicamentos_json = db.Column(db.Text, nullable=True)  # lista de {codigo, dosis, frecuencia, via, horario}

    historia = db.relationship('HistoriaClinica', back_populates='ordenes_medicas')
    examenes_lab = db.relationship(
        'OrdenLaboratorioItem',
        back_populates='orden',
        cascade='all, delete-orphan'
    )

class Medico(db.Model):
    __tablename__ = 'medicos'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    especialidad = db.Column(db.String(100))


class SignosVitales(db.Model):
    __tablename__ = 'signos_vitales'

    id = db.Column(db.Integer, primary_key=True)
    historia_id = db.Column(db.Integer, db.ForeignKey('historias_clinicas.id'), nullable=False)
    tension_arterial = db.Column(db.String(20))
    frecuencia_cardiaca = db.Column(db.String(20))
    frecuencia_respiratoria = db.Column(db.String(20))
    temperatura = db.Column(db.String(20))
    saturometria = db.Column(db.String(10))
    escala_dolor = db.Column(db.String(10))
    fi02 = db.Column(db.String(10))
    estado_consciencia = db.Column(db.String(100))
    glucometria = db.Column(db.String(20))
    peso = db.Column(db.String(20))
    talla = db.Column(db.String(20))
    imc = db.Column(db.String(20))

    historia_clinica = db.relationship('HistoriaClinica', back_populates='signos_vitales')


class Evolucion(db.Model):
    __tablename__ = 'evoluciones'

    id = db.Column(db.Integer, primary_key=True)
    historia_id = db.Column(db.Integer, db.ForeignKey('historias_clinicas.id'), nullable=False)

    historia = db.relationship('HistoriaClinica', back_populates='evolucion')

    subjetivos = db.Column(db.Text)
    objetivos = db.Column(db.Text)
    analisis = db.Column(db.Text)
    plan = db.Column(db.Text)
    indicaciones_medicas = db.Column(db.Text)


class Diagnostico(db.Model):
    __tablename__ = 'diagnosticos'

    id = db.Column(db.Integer, primary_key=True)
    historia_id = db.Column(db.Integer, db.ForeignKey('historias_clinicas.id'), nullable=False)

    historia = db.relationship('HistoriaClinica', back_populates='diagnosticos')

    cie10_codigo = db.Column(db.String(10))
    descripcion = db.Column(db.String(250))


class CIE10(db.Model):
    __tablename__ = 'cie10'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    descripcion = db.Column(db.String(255), nullable=False)


class RegistroEnfermeria(db.Model):
    __tablename__ = 'registro_enfermeria'

    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey('pacientes.id'), nullable=False)
    historia_clinica_id = db.Column(db.Integer, db.ForeignKey('historias_clinicas.id'), nullable=True)
    fecha_registro = db.Column(db.DateTime, default=ahora_bogota)
    signos_vitales = db.Column(db.Text)       # JSON
    balance_liquidos = db.Column(db.Text)     # JSON
    control_glicemia = db.Column(db.String(50))
    observaciones = db.Column(db.Text)
    tipo_nota = db.Column(db.String(20), nullable=True)   # ingreso, egreso, intermedia, recibo, entrega
    texto_nota = db.Column(db.Text, nullable=True)
    turno = db.Column(db.String(10), default='mañana')  # Agregar este campo
    paciente = db.relationship('Paciente', back_populates='registros_enfermeria')
    historia = db.relationship('HistoriaClinica')


class AyudaDiagnostica(db.Model):
    __tablename__ = 'ayuda_diagnostica'

    id = db.Column(db.Integer, primary_key=True)
    historia_id = db.Column(db.Integer, db.ForeignKey('historias_clinicas.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # 'laboratorio', 'imagen', 'biopsia'
    nombre_examen = db.Column(db.String(255), nullable=False)
    fecha_resultado = db.Column(db.DateTime, nullable=True)
    archivo = db.Column(db.String(255), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)

    historia = db.relationship('HistoriaClinica', backref='ayudas_diagnosticas')


class CatLaboratorioExamen(db.Model):
    __tablename__ = 'cat_laboratorio_examen'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(255), nullable=False)
    grupo = db.Column(db.String(255))
    activo = db.Column(db.Boolean, default=True, nullable=False)

    parametros = db.relationship('CatLaboratorioParametro', backref='examen', lazy='dynamic')


class CatLaboratorioParametro(db.Model):
    __tablename__ = 'cat_laboratorio_parametro'

    id = db.Column(db.Integer, primary_key=True)
    examen_id = db.Column(db.Integer, db.ForeignKey('cat_laboratorio_examen.id'), nullable=False)
    nombre = db.Column(db.String(255), nullable=False)
    unidad = db.Column(db.String(50), nullable=True)
    valor_ref_min = db.Column(db.Float, nullable=True)
    valor_ref_max = db.Column(db.Float, nullable=True)


class LabSolicitud(db.Model):
    __tablename__ = 'lab_solicitud'

    id = db.Column(db.Integer, primary_key=True)

    historia_id = db.Column(
        db.Integer,
        db.ForeignKey('historias_clinicas.id'),
        nullable=False
    )
    fecha_solicitud = db.Column(db.DateTime, nullable=False, default=ahora_bogota)
    fecha_muestra = db.Column(db.DateTime, nullable=True)
    fecha_resultado = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.String(30), nullable=False, default='pendiente')
    laboratorio_nombre = db.Column(db.String(100), nullable=True)

    historia = db.relationship('HistoriaClinica', backref='lab_solicitudes')


class LabResultado(db.Model):
    __tablename__ = 'lab_resultado'

    id = db.Column(db.Integer, primary_key=True)

    solicitud_id = db.Column(
        db.Integer,
        db.ForeignKey('lab_solicitud.id'),
        nullable=False
    )

    examen_id = db.Column(
        db.Integer,
        db.ForeignKey('cat_laboratorio_examen.id'),
        nullable=False
    )
    parametro_id = db.Column(
        db.Integer,
        db.ForeignKey('cat_laboratorio_parametro.id'),
        nullable=False
    )

    valor = db.Column(db.String(100), nullable=True)
    unidad = db.Column(db.String(50), nullable=True)
    flag_fuera_rango = db.Column(db.Boolean, default=False)
    interpretacion = db.Column(db.String(255), nullable=True)

    solicitud = db.relationship('LabSolicitud', backref='resultados')
    parametro = db.relationship('CatLaboratorioParametro')
    examen = db.relationship('CatLaboratorioExamen')

class DiagnosticoCIE10(db.Model):
    __tablename__ = 'diagnosticos_cie10'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), index=True, nullable=False)
    nombre = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)
    habilitado = db.Column(db.Boolean, default=True)


class Medicamento(db.Model):
    __tablename__ = 'medicamentos'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, index=True, nullable=False)
    nombre = db.Column(db.String(255), nullable=False)
    forma_farmaceutica = db.Column(db.String(100), nullable=True)
    presentacion = db.Column(db.String(100), nullable=True)

    # inventario total disponible (permite decimales)
    cantidad_disponible = db.Column(db.Numeric(precision=12, scale=3), default=0)

    # opcional: unidad de inventario (ampolla, ml, mg, etc.)
    unidad_inventario = db.Column(db.String(50), nullable=True)
    # relaciones hacia AdministracionMedicamento se crean por backref


class AdministracionMedicamento(db.Model):
    __tablename__ = 'administracion_medicamento'

    id = db.Column(db.Integer, primary_key=True)

    registro_enfermeria_id = db.Column(
        db.Integer,
        db.ForeignKey('registro_enfermeria.id'),
        nullable=False
    )
    medicamento_id = db.Column(
        db.Integer,
        db.ForeignKey('medicamentos.id'),
        nullable=False
    )

    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    unidad = db.Column(db.String(50))
    via = db.Column(db.String(50))
    observaciones = db.Column(db.String(255))
    hora_administracion = db.Column(db.DateTime, default=ahora_bogota)

    # relaciones
    registro = db.relationship('RegistroEnfermeria', backref='administraciones')
    medicamento = db.relationship('Medicamento', backref='administraciones')

class InsumoMedico(db.Model):
    __tablename__ = 'insumos_medicos'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, index=True, nullable=False)
    nombre = db.Column(db.String(255), nullable=False)
    stock_actual = db.Column(db.Numeric(12, 3), default=0)
    unidad = db.Column(db.String(50), default='uni')
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=ahora_bogota)
    
    # Relaciones
    solicitudes = db.relationship('SolicitudInsumo', backref='insumo_medico')

class SolicitudInsumo(db.Model):
    __tablename__ = 'solicitudes_insumos'
    
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey('pacientes.id'), nullable=False)
    insumo_medico_id = db.Column(db.Integer, db.ForeignKey('insumos_medicos.id'), nullable=False)
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    unidad = db.Column(db.String(50))
    observaciones = db.Column(db.String(255))
    fecha_solicitud = db.Column(db.DateTime, default=ahora_bogota)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, aprobado, entregado
    enfermero_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    
    # Relaciones
    paciente = db.relationship('Paciente', backref='solicitudes_insumos')
    # enfermero enfermero = db.relationship('Usuario', foreign_keys=[enfermero_id]) # temporal 

class InsumoPaciente(db.Model):
    __tablename__ = 'insumos_paciente'
    
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey('pacientes.id'), nullable=False)
    insumo_id = db.Column(db.Integer, db.ForeignKey('insumos_medicos.id'), nullable=False)
    cantidad = db.Column(db.Float, nullable=False)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    cantidad_usada = db.Column(db.Integer, default=0)  # ← NUEVO
    fecha_uso = db.Column(db.DateTime)  # ← NUEVO
    stock_actual = db.Column(db.Float, default=0)
    observaciones = db.Column(db.Text, default='')
    # Relaciones SIMPLES
    paciente = db.relationship('Paciente', back_populates='insumos_paciente')
    insumo = db.relationship('InsumoMedico')

class OrdenLaboratorioItem(db.Model):
    __tablename__ = 'orden_laboratorio_items'

    id = db.Column(db.Integer, primary_key=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('ordenes_medicas.id'), nullable=False)
    examen_id = db.Column(db.Integer, db.ForeignKey('cat_laboratorio_examen.id'), nullable=False)
    estado = db.Column(db.String(20), default='solicitado')  # solicitado, procesado, etc.

    orden = db.relationship('OrdenMedica', back_populates='examenes_lab')
    examen = db.relationship('CatLaboratorioExamen')

