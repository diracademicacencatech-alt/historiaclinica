"""Agregar columna activo a CatLaboratorioExamen

Revision ID: def9d863c34c
Revises: bdf65cb803cf
Create Date: 2025-12-10 16:28:47.027439
"""
from alembic import op
import sqlalchemy as sa


revision = 'def9d863c34c'
down_revision = 'bdf65cb803cf'
branch_labels = None
depends_on = None


def upgrade():
    # Añadir columna 'activo' con default 1 (True) y permitir NULL al crear
    op.add_column(
        'cat_laboratorio_examen',
        sa.Column('activo', sa.Boolean(), nullable=True, server_default=sa.true())
    )

    # Opcional: si quieres cambiar el tamaño de grupo, hazlo aparte si no da problemas
    # con SQLite; si te vuelve a dar problemas, deja grupo como está y no lo toques.


def downgrade():
    # Revertir: eliminar columna 'activo'
    op.drop_column('cat_laboratorio_examen', 'activo')
