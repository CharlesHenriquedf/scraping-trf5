# -*- coding: utf-8 -*-

"""
Utilitários de paginação para o TRF5 Scraper.

Funções para extrair informações de paginação e calcular limites operacionais.
Suporta dois modos: Total:N (Modo A) e barra de páginas (Modo B).
"""

import re
import math
from typing import Optional, Dict, List, Tuple, Any, Union


def extract_total_and_last_page(html_text: Union[str, bytes], page_size: int = 10) -> Dict[str, Optional[int]]:
    """
    Extrai total de resultados e calcula última página (Modo A).

    Procura por padrão "Total: N" no HTML e calcula o número de páginas
    baseado no page_size fornecido (padrão 10 conforme especificação).

    Args:
        html_text: Conteúdo HTML da página
        page_size: Número de itens por página (padrão 10)

    Returns:
        Dict com 'total', 'page_size', 'last_page' ou None se não encontrado

    Examples:
        >>> extract_total_and_last_page("Resultados: Total: 157 processos")
        {'total': 157, 'page_size': 10, 'last_page': 15}
        >>> extract_total_and_last_page("Nenhum resultado", 10)
        {'total': None, 'page_size': 10, 'last_page': None}
    """
    if not html_text:
        return {'total': None, 'page_size': page_size, 'last_page': None}

    # Converte para string se necessário
    if isinstance(html_text, bytes):
        html_text = html_text.decode('utf-8', 'ignore')

    text = str(html_text)

    # Padrões para capturar "Total: N" ou variações
    total_patterns = [
        r'Total:\s*(\d+)',              # Total: 157
        r'Total\s+de\s+(\d+)',          # Total de 157
        r'(\d+)\s+resultados?',         # 157 resultado(s)
        r'(\d+)\s+processos?',          # 157 processo(s)
        r'Encontrados?\s+(\d+)',        # Encontrado(s) 157
        r'Localizado[s]?\s+(\d+)',      # Localizados 157
    ]

    total = None
    for pattern in total_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            total = int(match.group(1))
            break

    # Calcula última página se total foi encontrado
    last_page = None
    if total is not None and page_size > 0:
        # Página baseada em 0 (0, 1, 2, ..., last_page)
        last_page = math.ceil(total / page_size) - 1
        if last_page < 0:
            last_page = 0

    return {
        'total': total,
        'page_size': page_size,
        'last_page': last_page
    }


def extract_bar_links(html_text: Union[str, bytes]) -> Dict[str, Any]:
    """
    Extrai links de navegação da barra de paginação (Modo B).

    Procura por links de navegação típicos: próxima, última, primeira, anterior
    e números de página. Útil quando o total não está disponível.

    Args:
        html_text: Conteúdo HTML da página

    Returns:
        Dict com informações dos links encontrados

    Examples:
        >>> extract_bar_links('<a href="?page=1">Próxima</a> <a href="?page=10">Última</a>')
        {'next_page': 1, 'last_page': 10, 'has_next': True, 'has_last': True}
    """
    if not html_text:
        return {
            'next_page': None,
            'last_page': None,
            'first_page': None,
            'prev_page': None,
            'page_numbers': [],
            'has_next': False,
            'has_prev': False,
            'has_last': False,
            'has_first': False
        }

    # Converte para string se necessário
    if isinstance(html_text, bytes):
        html_text = html_text.decode('utf-8', 'ignore')

    text = str(html_text)

    result = {
        'next_page': None,
        'last_page': None,
        'first_page': None,
        'prev_page': None,
        'page_numbers': [],
        'has_next': False,
        'has_prev': False,
        'has_last': False,
        'has_first': False
    }

    # Padrões para links de navegação
    # Procura por href com parâmetros de página
    link_patterns = {
        'next': [
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*pr[óo]xima?\s*</a>',
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*seguinte\s*</a>',
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*>\s*</a>',
        ],
        'last': [
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*[úu]ltima?\s*</a>',
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*fim\s*</a>',
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*>>\s*</a>',
        ],
        'first': [
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*primeira?\s*</a>',
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*in[íi]cio\s*</a>',
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*<<\s*</a>',
        ],
        'prev': [
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*anterior\s*</a>',
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>\s*<\s*</a>',
        ]
    }

    # Extrai links de navegação
    for link_type, patterns in link_patterns.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                href = match.group(1)
                # Extrai número da página do href
                page_match = re.search(r'page[=](\d+)', href, re.IGNORECASE)
                if page_match:
                    page_num = int(page_match.group(1))
                    result[f'{link_type}_page'] = page_num
                    result[f'has_{link_type}'] = True
                break

    # Procura por links numerados de página
    number_pattern = r'<a[^>]*href=["\']([^"\']*page[=](\d+)[^"\']*)["\'][^>]*>\s*(\d+)\s*</a>'
    number_matches = re.findall(number_pattern, text, re.IGNORECASE)

    page_numbers = []
    for href, page_param, page_text in number_matches:
        page_num = int(page_text)
        page_numbers.append(page_num)

    result['page_numbers'] = sorted(list(set(page_numbers)))

    # Se encontrou números de página, usa o maior como possível última página
    if page_numbers and not result['last_page']:
        result['last_page'] = max(page_numbers)
        result['has_last'] = True

    return result


def compute_limits(max_pages: Optional[int] = None, max_details_per_page: Optional[int] = None) -> Dict[str, int]:
    """
    Calcula limites operacionais para evitar sobrecarga do sistema.

    Define valores padrão seguros e valida os limites fornecidos.
    Essencial para o modo CNPJ que pode gerar muitas requisições.

    Args:
        max_pages: Máximo de páginas de lista a processar
        max_details_per_page: Máximo de detalhes por página a seguir

    Returns:
        Dict com limites validados e valores padrão

    Examples:
        >>> compute_limits(2, 5)
        {'max_pages': 2, 'max_details_per_page': 5, 'max_total_details': 10}
        >>> compute_limits()
        {'max_pages': 5, 'max_details_per_page': 10, 'max_total_details': 50}
    """
    # Valores padrão seguros para evitar sobrecarga
    default_max_pages = 5
    default_max_details_per_page = 10

    # Valida e aplica limites
    if max_pages is None or max_pages <= 0:
        max_pages = default_max_pages
    else:
        # Limita a um máximo absoluto para segurança
        max_pages = min(max_pages, 20)

    if max_details_per_page is None or max_details_per_page <= 0:
        max_details_per_page = default_max_details_per_page
    else:
        # Limita a um máximo absoluto para segurança
        max_details_per_page = min(max_details_per_page, 50)

    # Calcula total máximo de detalhes que serão processados
    max_total_details = max_pages * max_details_per_page

    return {
        'max_pages': max_pages,
        'max_details_per_page': max_details_per_page,
        'max_total_details': max_total_details
    }


def get_page_range(current_page: int, last_page: int, max_pages: int) -> List[int]:
    """
    Calcula range de páginas a serem processadas respeitando limites.

    Utilitário para determinar quais páginas processar baseado na página
    atual, última página disponível e limite máximo configurado.

    Args:
        current_page: Página atual (geralmente 0)
        last_page: Última página disponível
        max_pages: Máximo de páginas a processar

    Returns:
        Lista de números de página a serem processadas

    Examples:
        >>> get_page_range(0, 10, 3)
        [0, 1, 2]
        >>> get_page_range(0, 1, 5)
        [0, 1]
    """
    if last_page is None or last_page < 0:
        return [current_page] if current_page >= 0 else [0]

    # Calcula range limitado pelo max_pages
    end_page = min(current_page + max_pages - 1, last_page)

    # Garante que não temos páginas negativas
    start_page = max(current_page, 0)
    end_page = max(end_page, start_page)

    return list(range(start_page, end_page + 1))