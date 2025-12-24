"""Fix historia_id nullable and text fields nullable in ordenes_medicas

Revision ID: xxxxxxxx1234
Revises: d62fbdee40c2
Create Date: 2025-09-25 11:40:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'xxxxxxxx1234'
down_revision = 'd62fbdee40c2'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('ordenes_medicas', schema=None) as batch_op:
        batch_op.alter_column('historia_id',
           existing_type=sa.Integer(),
           nullable=False)
        batch_op.alter_column('indicaciones_medicas',
           existing_type=sa.Text(),
           nullable=True)
        batch_op.alter_column('medicacion_texto',
           existing_type=sa.Text(),
           nullable=True)

def downgrade():
    with op.batch_alter_table('ordenes_medicas', schema=None) as batch_op:
        batch_op.alter_column('historia_id',
           existing_type=sa.Integer(),
           nullable=True)
        batch_op.alter_column('indicaciones_medicas',
           existing_type=sa.Text(),
           nullable=False)
        batch_op.alter_column('medicacion_texto',
           existing_type=sa.Text(),
           nullable=False)
