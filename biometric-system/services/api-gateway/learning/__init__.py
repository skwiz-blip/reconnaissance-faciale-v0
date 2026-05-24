"""Active learning + drift detection + auto-update des embeddings."""
from learning.active_learning import (
    queue_correction_candidate, list_pending_corrections,
    apply_correction, CorrectionType,
)
from learning.drift import (
    DriftReport, compute_identity_drift, schedule_re_enrollment,
)

__all__ = [
    "queue_correction_candidate", "list_pending_corrections",
    "apply_correction", "CorrectionType",
    "DriftReport", "compute_identity_drift", "schedule_re_enrollment",
]
