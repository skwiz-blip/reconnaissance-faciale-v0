"""
Parser MRZ (Machine Readable Zone) — ICAO 9303.

Formats supportés:
  - TD1 (3 lignes × 30 caractères) : cartes d'identité européennes
  - TD2 (2 lignes × 36 caractères) : anciennes CI / titres séjour
  - TD3 (2 lignes × 44 caractères) : passeports

Le parser valide les check digits ICAO (modulo 10 sur poids 7-3-1) → toute
incohérence remonte comme un flag de fraude.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


class MRZParseError(Exception):
    pass


@dataclass(slots=True)
class MRZData:
    document_type:   str              # P (passport), I/A/C (CI)
    issuing_country: str
    surname:         str
    given_names:     str
    document_number: str
    nationality:     str
    birth_date:      str              # YYMMDD
    sex:             str              # M / F / X
    expiry_date:     str              # YYMMDD
    personal_number: str = ""
    checks_passed:   dict[str, bool] = field(default_factory=dict)
    raw_lines:       list[str] = field(default_factory=list)

    @property
    def all_checks_ok(self) -> bool:
        return all(self.checks_passed.values()) if self.checks_passed else False


# ============================================================
# Constantes ICAO
# ============================================================

WEIGHTS = [7, 3, 1]
CHAR_VALUES = {chr(c): c - ord("A") + 10 for c in range(ord("A"), ord("Z") + 1)}
CHAR_VALUES.update({str(d): d for d in range(10)})
CHAR_VALUES["<"] = 0


def _check_digit(s: str) -> int:
    total = 0
    for i, c in enumerate(s):
        v = CHAR_VALUES.get(c, 0)
        total += v * WEIGHTS[i % 3]
    return total % 10


def _clean(s: str) -> str:
    return s.replace("<", " ").strip()


def _split_names(field_str: str) -> tuple[str, str]:
    """ICAO: surname puis << puis given names."""
    parts = field_str.split("<<", 1)
    surname = parts[0].replace("<", " ").strip()
    given = parts[1].replace("<", " ").strip() if len(parts) > 1 else ""
    return surname, given


# ============================================================
# Détection du format
# ============================================================

def _detect_format(lines: list[str]) -> str:
    if len(lines) == 2 and all(len(l) == 44 for l in lines):
        return "TD3"
    if len(lines) == 2 and all(len(l) == 36 for l in lines):
        return "TD2"
    if len(lines) == 3 and all(len(l) == 30 for l in lines):
        return "TD1"
    raise MRZParseError(f"Format MRZ inconnu: {len(lines)} lignes × tailles {[len(l) for l in lines]}")


# ============================================================
# Parsers par format
# ============================================================

def _parse_td3(lines: list[str]) -> MRZData:
    l1, l2 = lines
    document_type   = l1[0:2].replace("<", "").strip()
    issuing_country = l1[2:5].replace("<", "")
    surname, given  = _split_names(l1[5:44])

    document_number = l2[0:9].replace("<", "")
    doc_check       = l2[9]
    nationality     = l2[10:13].replace("<", "")
    birth_date      = l2[13:19]
    birth_check     = l2[19]
    sex             = l2[20]
    expiry          = l2[21:27]
    expiry_check    = l2[27]
    personal        = l2[28:42]
    personal_check  = l2[42]
    composite_check = l2[43]

    composite = l2[0:10] + l2[13:20] + l2[21:43]

    checks = {
        "document_number": str(_check_digit(l2[0:9]))  == doc_check,
        "birth_date":      str(_check_digit(birth_date)) == birth_check,
        "expiry_date":     str(_check_digit(expiry))    == expiry_check,
        "personal_number": str(_check_digit(personal))  == personal_check,
        "composite":       str(_check_digit(composite)) == composite_check,
    }
    return MRZData(
        document_type=document_type,
        issuing_country=issuing_country,
        surname=surname,
        given_names=given,
        document_number=document_number,
        nationality=nationality,
        birth_date=birth_date,
        sex=sex,
        expiry_date=expiry,
        personal_number=_clean(personal),
        checks_passed=checks,
        raw_lines=lines,
    )


def _parse_td2(lines: list[str]) -> MRZData:
    l1, l2 = lines
    document_type   = l1[0:2].replace("<", "").strip()
    issuing_country = l1[2:5].replace("<", "")
    surname, given  = _split_names(l1[5:36])

    document_number = l2[0:9].replace("<", "")
    doc_check       = l2[9]
    nationality     = l2[10:13].replace("<", "")
    birth_date      = l2[13:19]
    birth_check     = l2[19]
    sex             = l2[20]
    expiry          = l2[21:27]
    expiry_check    = l2[27]
    optional        = l2[28:35]
    composite_check = l2[35]

    composite = l2[0:10] + l2[13:20] + l2[21:35]
    checks = {
        "document_number": str(_check_digit(l2[0:9])) == doc_check,
        "birth_date":      str(_check_digit(birth_date)) == birth_check,
        "expiry_date":     str(_check_digit(expiry)) == expiry_check,
        "composite":       str(_check_digit(composite)) == composite_check,
    }
    return MRZData(
        document_type=document_type,
        issuing_country=issuing_country,
        surname=surname,
        given_names=given,
        document_number=document_number,
        nationality=nationality,
        birth_date=birth_date,
        sex=sex,
        expiry_date=expiry,
        personal_number=_clean(optional),
        checks_passed=checks,
        raw_lines=lines,
    )


def _parse_td1(lines: list[str]) -> MRZData:
    l1, l2, l3 = lines
    document_type   = l1[0:2].replace("<", "").strip()
    issuing_country = l1[2:5].replace("<", "")
    document_number = l1[5:14].replace("<", "")
    doc_check       = l1[14]
    optional_a      = l1[15:30]

    birth_date      = l2[0:6]
    birth_check     = l2[6]
    sex             = l2[7]
    expiry          = l2[8:14]
    expiry_check    = l2[14]
    nationality     = l2[15:18].replace("<", "")
    optional_b      = l2[18:29]
    composite_check = l2[29]

    surname, given  = _split_names(l3[0:30])

    composite = (l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29])
    checks = {
        "document_number": str(_check_digit(l1[5:14])) == doc_check,
        "birth_date":      str(_check_digit(birth_date)) == birth_check,
        "expiry_date":     str(_check_digit(expiry)) == expiry_check,
        "composite":       str(_check_digit(composite)) == composite_check,
    }
    return MRZData(
        document_type=document_type,
        issuing_country=issuing_country,
        surname=surname,
        given_names=given,
        document_number=document_number,
        nationality=nationality,
        birth_date=birth_date,
        sex=sex,
        expiry_date=expiry,
        personal_number=_clean(optional_a + optional_b),
        checks_passed=checks,
        raw_lines=lines,
    )


# ============================================================
# API publique
# ============================================================

MRZ_LINE_RE = re.compile(r"^[A-Z0-9<]{30,44}$")


def _extract_mrz_lines(text: str) -> list[str]:
    """Récupère les lignes ressemblant à du MRZ depuis un texte OCR brut."""
    candidates: list[str] = []
    for raw in text.splitlines():
        line = "".join(ch for ch in raw.upper() if ch.isalnum() or ch == "<")
        if MRZ_LINE_RE.match(line):
            candidates.append(line)
    # Garder les 2-3 dernières (la MRZ est en bas du document)
    return candidates[-3:] if candidates else []


def parse_mrz(text: str) -> MRZData:
    lines = _extract_mrz_lines(text)
    if not lines:
        raise MRZParseError("Aucune ligne MRZ trouvée")
    fmt = _detect_format(lines)
    if fmt == "TD3":
        return _parse_td3(lines)
    if fmt == "TD2":
        return _parse_td2(lines)
    return _parse_td1(lines)
