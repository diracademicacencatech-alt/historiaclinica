"""Agregar historia_clinica_id a RegistroEnfermeria

Revision ID: ccad232b2b80
Revises: 8ab8cba60ffa
Create Date: 2025-11-07 14:15:46.312455

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ccad232b2b80'
down_revision = '8ab8cba60ffa'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('registro_enfermeria', schema=None) as batch_op:
        batch_op.add_column(sa.Column('historia_clinica_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_registro_historia', 'historias_clinicas', ['historia_clinica_id'], ['id'])

def downgrade():
    with op.batch_alter_table('registro_enfermeria', schema=None) as batch_op:
        batch_op.drop_constraint('fk_registro_historia', type_='foreignkey')
        batch_op.drop_column('historia_clinica_id')
