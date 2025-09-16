# -*- coding: utf-8 -*-

"""
Utilitários de normalização para o TRF5 Scraper.

Funções para normalizar NPUs, CNPJs, datas e texto conforme especificações
do PRD. Garante consistência e padronização dos dados coletados.
"""

import re
from datetime import datetime
from typing import Optional


def normalize_npu_hyphenated(npu: str) -> str:
    """
    Normaliza NPU para formato com hífens (formato humano/canônico).

    Usado para URLs canônicas e como _id nos documentos MongoDB.
    Formato: NNNNNNN-DD.AAAA.J.TR.OOOO

    Args:
        npu: NPU com ou sem formatação

    Returns:
        NPU normalizado com hífens

    Examples:
        >>> normalize_npu_hyphenated("00156487819994050000")
        "0015648-78.1999.4.05.0000"
        >>> normalize_npu_hyphenated("0015648-78.1999.4.05.0000")
        "0015648-78.1999.4.05.0000"
    """
    if not npu:
        return ""

    # Remove todos os caracteres não numéricos
    digits = re.sub(r'\D', '', str(npu).strip())

    # NPU deve ter exatamente 20 dígitos
    if len(digits) != 20:
        return npu  # Retorna original se não for válido

    # Aplica formatação: NNNNNNN-DD.AAAA.J.TR.OOOO
    formatted = f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13:14]}.{digits[14:16]}.{digits[16:20]}"
    return formatted


def normalize_npu_digits(npu: str) -> str:
    """
    Normaliza NPU para formato apenas dígitos.

    Remove toda formatação, mantendo apenas os 20 dígitos do NPU.

    Args:
        npu: NPU com ou sem formatação

    Returns:
        NPU normalizado apenas com dígitos

    Examples:
        >>> normalize_npu_digits("0015648-78.1999.4.05.0000")
        "00156487819994050000"
        >>> normalize_npu_digits("00156487819994050000")
        "00156487819994050000"
    """
    if not npu:
        return ""

    # Remove todos os caracteres não numéricos
    digits = re.sub(r'\D', '', str(npu).strip())
    return digits


def normalize_cnpj_digits(cnpj: str) -> str:
    """
    Normaliza CNPJ para formato apenas dígitos.

    Remove toda formatação (pontos, barras, hífens), mantendo apenas números.

    Args:
        cnpj: CNPJ com ou sem formatação

    Returns:
        CNPJ normalizado apenas com dígitos

    Examples:
        >>> normalize_cnpj_digits("00.000.000/0001-91")
        "00000000000191"
        >>> normalize_cnpj_digits("00000000000191")
        "00000000000191"
    """
    if not cnpj:
        return ""

    # Remove todos os caracteres não numéricos
    digits = re.sub(r'\D', '', str(cnpj).strip())
    return digits


def parse_date_to_iso(date_str: str) -> Optional[str]:
    """
    Converte data brasileira para formato ISO-8601.

    Aceita formatos 'dd/mm/aaaa' ou 'dd/mm/aaaa HH:MM' e converte para ISO-8601.
    Timezone é indefinida conforme especificação do PRD.

    Args:
        date_str: Data no formato brasileiro

    Returns:
        Data no formato ISO-8601 ou None se inválida

    Examples:
        >>> parse_date_to_iso("15/04/2000")
        "2000-04-15"
        >>> parse_date_to_iso("06/10/2020 03:13")
        "2020-10-06T03:13:00"
    """
    if not date_str:
        return None

    date_str = str(date_str).strip()

    # Formato com hora: dd/mm/aaaa HH:MM
    match_with_time = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{1,2})', date_str)
    if match_with_time:
        day, month, year, hour, minute = match_with_time.groups()
        try:
            dt = datetime(int(year), int(month), int(day), int(hour), int(minute))
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None

    # Formato apenas data: dd/mm/aaaa
    match_date_only = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_str)
    if match_date_only:
        day, month, year = match_date_only.groups()
        try:
            dt = datetime(int(year), int(month), int(day))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None

    return None


def clean_text(text: str) -> str:
    """
    Limpa e normaliza texto.

    Remove espaços em excesso, quebras de linha e normaliza espaçamento.
    Preserva acentuação e caracteres especiais do português.

    Args:
        text: Texto a ser limpo

    Returns:
        Texto normalizado

    Examples:
        >>> clean_text("  Texto   com    espaços   ")
        "Texto com espaços"
        >>> clean_text("Linha 1\\n\\n  Linha 2")
        "Linha 1 Linha 2"
    """
    if not text:
        return ""

    # Converte para string e remove espaços das extremidades
    text = str(text).strip()

    # Substitui quebras de linha por espaços
    text = re.sub(r'[\r\n]+', ' ', text)

    # Colapsa múltiplos espaços em um único espaço
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def normalize_relator(relator: str) -> str:
    """
    Normaliza nome do relator removendo títulos e cargos.

    Remove prefixos como "Des.", "DESEMBARGADOR FEDERAL", "JUIZ FEDERAL", etc.
    Mantém apenas o nome próprio conforme exigido pelo PRD.

    Args:
        relator: Nome do relator com possíveis títulos

    Returns:
        Nome do relator sem títulos

    Examples:
        >>> normalize_relator("DESEMBARGADOR FEDERAL JOÃO DA SILVA")
        "JOÃO DA SILVA"
        >>> normalize_relator("Des. Maria Santos")
        "Maria Santos"
        >>> normalize_relator("JUÍZA FEDERAL ANA OLIVEIRA")
        "ANA OLIVEIRA"
    """
    if not relator:
        return ""

    relator = clean_text(relator)

    # Padrões de títulos a serem removidos
    # Regex case-insensitive para capturar variações
    patterns = [
        r'^\s*Des\.?\s+',                           # Des. ou Des
        r'^\s*DESEMBARGADOR(A)?\s+FEDERAL\s+',      # DESEMBARGADOR(A) FEDERAL
        r'^\s*DESEMBARGADOR(A)?\s+',                # DESEMBARGADOR(A)
        r'^\s*JUIZ(A)?\s+FEDERAL\s+',               # JUIZ(A) FEDERAL
        r'^\s*JUIZ(A)?\s+',                         # JUIZ(A)
        r'^\s*DR\.?\s+',                            # DR. ou DR
        r'^\s*DRA\.?\s+',                           # DRA. ou DRA
    ]

    for pattern in patterns:
        relator = re.sub(pattern, '', relator, flags=re.IGNORECASE)

    return clean_text(relator)