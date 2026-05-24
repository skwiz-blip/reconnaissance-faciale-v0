"""Contrôle d'accès intelligent: zones + politiques RBAC + journalisation."""
from access.policy_engine import (
    AccessDecision, AccessRequest, AccessResult,
    evaluate_access, evaluate_access_for_identity,
)

__all__ = [
    "AccessDecision", "AccessRequest", "AccessResult",
    "evaluate_access", "evaluate_access_for_identity",
]
