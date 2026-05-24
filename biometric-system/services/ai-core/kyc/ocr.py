"""
Extraction OCR sur documents d'identité.

Stratégie en cascade:
    1. Pré-traitement (deskew, binarisation adaptative, denoising)
    2. Tesseract (rapide, install système requis)
    3. EasyOCR (fallback, plus robuste sur images dégradées)

Les deux moteurs sont importés à la demande pour éviter de charger 2GB
d'EasyOCR si seul Tesseract est utilisé.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
from loguru import logger


# ============================================================
# Résultat
# ============================================================

@dataclass(slots=True)
class OCRResult:
    full_text:   str
    fields:      dict[str, str] = field(default_factory=dict)
    confidence:  float = 0.0
    engine:      str = ""
    raw_lines:   list[str] = field(default_factory=list)


# ============================================================
# Moteur
# ============================================================

class OCREngine:
    """Wrapper unifié Tesseract / EasyOCR."""

    def __init__(self, lang: str = "fra+eng", prefer: str = "tesseract"):
        self.lang = lang
        self.prefer = prefer
        self._easyocr_reader = None  # lazy

    def extract(self, img: np.ndarray) -> OCRResult:
        pre = self._preprocess(img)

        if self.prefer == "tesseract":
            try:
                return self._tesseract(pre)
            except Exception as e:
                logger.warning(f"Tesseract échec ({e}) → bascule EasyOCR")
                try:
                    return self._easyocr(pre)
                except Exception as ee:
                    logger.error(f"EasyOCR échec aussi: {ee}")
                    return OCRResult("", engine="none")
        else:
            try:
                return self._easyocr(pre)
            except Exception as e:
                logger.warning(f"EasyOCR échec ({e}) → bascule Tesseract")
                try:
                    return self._tesseract(pre)
                except Exception as ee:
                    logger.error(f"Tesseract échec aussi: {ee}")
                    return OCRResult("", engine="none")

    # ----------------- prétraitement -----------------

    @staticmethod
    def _preprocess(img: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        # Resize si trop petit (OCR fonctionne mieux à 300dpi équivalent)
        h, w = gray.shape
        if max(h, w) < 1200:
            scale = 1200 / max(h, w)
            gray = cv2.resize(gray, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC)
        # Denoising léger
        gray = cv2.bilateralFilter(gray, 7, 50, 50)
        # Binarisation adaptative (mieux que Otsu sur les docs avec ombres)
        bw = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 10
        )
        return bw

    # ----------------- tesseract -----------------

    def _tesseract(self, img: np.ndarray) -> OCRResult:
        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(
            img, lang=self.lang, output_type=Output.DICT,
            config="--oem 3 --psm 6",
        )
        lines: list[str] = []
        confidences: list[float] = []
        cur_line: list[str] = []
        cur_block = -1
        cur_par = -1
        cur_line_id = -1
        for i, text in enumerate(data["text"]):
            if not text.strip():
                continue
            block = data["block_num"][i]
            par = data["par_num"][i]
            line = data["line_num"][i]
            if (block, par, line) != (cur_block, cur_par, cur_line_id):
                if cur_line:
                    lines.append(" ".join(cur_line))
                cur_line = [text]
                cur_block, cur_par, cur_line_id = block, par, line
            else:
                cur_line.append(text)
            try:
                c = float(data["conf"][i])
                if c >= 0:
                    confidences.append(c)
            except (ValueError, TypeError):
                pass
        if cur_line:
            lines.append(" ".join(cur_line))

        full = "\n".join(lines)
        conf = float(np.mean(confidences)) / 100.0 if confidences else 0.0
        return OCRResult(
            full_text=full,
            confidence=round(conf, 3),
            engine="tesseract",
            raw_lines=lines,
        )

    # ----------------- easyocr -----------------

    def _easyocr(self, img: np.ndarray) -> OCRResult:
        if self._easyocr_reader is None:
            import easyocr
            # Langs EasyOCR: ["fr", "en"] (pas le format "fra+eng" de tesseract)
            langs = self._tesseract_to_easyocr_langs(self.lang)
            self._easyocr_reader = easyocr.Reader(langs, gpu=False)

        # EasyOCR prend RGB
        rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB) if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self._easyocr_reader.readtext(rgb, detail=1, paragraph=False)
        lines = [r[1] for r in results]
        confs = [float(r[2]) for r in results]
        full = "\n".join(lines)
        conf = float(np.mean(confs)) if confs else 0.0
        return OCRResult(
            full_text=full,
            confidence=round(conf, 3),
            engine="easyocr",
            raw_lines=lines,
        )

    @staticmethod
    def _tesseract_to_easyocr_langs(tess_lang: str) -> list[str]:
        mapping = {"fra": "fr", "eng": "en", "deu": "de", "spa": "es",
                   "ita": "it", "por": "pt"}
        return [mapping.get(c, c) for c in tess_lang.split("+")]


# ============================================================
# Extraction de champs structurés
# ============================================================

DATE_RE = re.compile(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b")
NAME_KEYWORDS = ("nom", "name", "surname", "apellido", "nachname")
GIVEN_NAME_KEYWORDS = ("prénom", "prenom", "given", "nombre", "vorname")
BIRTH_KEYWORDS = ("né", "born", "naiss", "date de naissance", "fecha de nacimiento")
DOC_NUMBER_RE = re.compile(r"\b[A-Z0-9]{6,12}\b")


def extract_fields_from_text(text: str) -> dict[str, str]:
    """Heuristiques regex pour extraire les champs courants."""
    fields: dict[str, str] = {}
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Dates
    dates = DATE_RE.findall(text)
    if dates:
        fields["birth_date_candidate"] = dates[0]
        if len(dates) > 1:
            fields["expiry_date_candidate"] = dates[-1]

    # Numéro de document
    for line in lines:
        m = DOC_NUMBER_RE.search(line.upper())
        if m and not m.group().isdigit():  # éviter dates pures
            fields.setdefault("document_number_candidate", m.group())

    # Nom / prénom (par mot-clé)
    for line in lines:
        low = line.lower()
        if any(k in low for k in NAME_KEYWORDS) and "surname" in fields == False:
            after = line.split(":", 1)[-1].strip()
            if after and after != line:
                fields.setdefault("surname", after)
        if any(k in low for k in GIVEN_NAME_KEYWORDS):
            after = line.split(":", 1)[-1].strip()
            if after and after != line:
                fields.setdefault("given_name", after)
        if any(k in low for k in BIRTH_KEYWORDS):
            ds = DATE_RE.search(line)
            if ds:
                fields["birth_date"] = ds.group(1)

    return fields


def extract_text(img: np.ndarray, lang: str = "fra+eng") -> OCRResult:
    """Helper haut niveau: OCR + extraction de champs."""
    engine = OCREngine(lang=lang)
    result = engine.extract(img)
    result.fields = extract_fields_from_text(result.full_text)
    return result
