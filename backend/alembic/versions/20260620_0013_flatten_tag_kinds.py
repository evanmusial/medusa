from __future__ import annotations

from alembic import op


revision = "20260620_0013"
down_revision = "20260619_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE tags SET kind = 'tag' WHERE kind <> 'tag'")


def downgrade() -> None:
    # Tag kinds were intentionally flattened; the prior keyword/topic distinction
    # cannot be recovered once normalized.
    pass
