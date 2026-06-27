"""normalize concordance composition statuses

Revision ID: 20260627_0028
Revises: 20260627_0027
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "20260627_0028"
down_revision = "20260627_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE document_composition_records
        SET status = CASE
            WHEN status IN ('failed', 'error') THEN 'failed'
            WHEN status LIKE 'rejected_%' THEN 'warning'
            WHEN status IN (
                'already_sorted',
                'disabled_by_preset',
                'empty',
                'model_no_op',
                'no_formulas',
                'not_found',
                'not_needed',
                'skipped_existing_bibliography',
                'skipped_large_bibliography',
                'unconfigured'
            ) THEN 'skipped'
            ELSE 'complete'
        END
        WHERE record_kind = 'concordance'
          AND status NOT IN ('complete', 'skipped', 'warning', 'failed')
        """
    )


def downgrade() -> None:
    pass
