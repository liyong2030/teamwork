"""sso auth source

Revision ID: 49eaab6013e1
Revises: bca61813731b
Create Date: 2026-10-19 12:14:47.733624+08:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '49eaab6013e1'
down_revision: str | None = 'bca61813731b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 注意：存量表加非空列必须带 server_default，否则 PostgreSQL 直接拒绝。
    # 这里先用 'local' 回填全部存量账号，再去掉默认值（后续由 SQLAlchemy 层的
    # python default 负责赋值，避免依赖数据库默认值）。
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'auth_source',
                sa.String(length=16),
                nullable=False,
                server_default='local',
            )
        )
        batch_op.add_column(sa.Column('external_id', sa.String(length=128), nullable=True))
        batch_op.alter_column('hashed_password',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)
        batch_op.create_index(batch_op.f('ix_users_auth_source'), ['auth_source'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_external_id'), ['external_id'], unique=False)
        batch_op.create_unique_constraint('uq_users_auth_source_external_id', ['auth_source', 'external_id'])

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('auth_source', existing_type=sa.String(length=16),
                              nullable=False, server_default=None)


def downgrade() -> None:
    # SSO 账号没有本地口令，回滚前必须先把 NULL 填成不可登录的占位串，
    # 否则把列改回 NOT NULL 时会因存量数据违规而失败。
    op.execute(
        "UPDATE users SET hashed_password = '!sso-migrated' "
        "WHERE hashed_password IS NULL"
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_auth_source_external_id', type_='unique')
        batch_op.drop_index(batch_op.f('ix_users_external_id'))
        batch_op.drop_index(batch_op.f('ix_users_auth_source'))
        batch_op.alter_column('hashed_password',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
        batch_op.drop_column('external_id')
        batch_op.drop_column('auth_source')
