# -*- coding: utf-8 -*-

"""
Utilitários de classificação de páginas para o TRF5 Scraper.

Funções robustas para detectar tipos de página: detalhe, lista ou erro.
Essencial para o fluxo de processamento correto conforme PRD.
"""

import re
from typing import Union


def is_detail(html_text: Union[str, bytes]) -> bool:
    """
    Detecta se a página é um detalhe de processo.

    Verifica presença simultânea de indicadores específicos:
    - 'PROCESSO Nº' ou variações
    - 'RELATOR' ou variações
    - Seções de envolvidos (tabelas com papéis)
    - Seções de movimentações (cronologia de eventos)

    Args:
        html_text: Conteúdo HTML da página

    Returns:
        True se for página de detalhe, False caso contrário
    """
    if not html_text:
        return False

    # Converte para string se necessário
    if isinstance(html_text, bytes):
        html_text = html_text.decode('utf-8', 'ignore')

    text = str(html_text).upper()

    # Verifica indicadores de página de detalhe
    has_processo = bool(re.search(r'PROCESSO\s+N[°ºo]', text, re.IGNORECASE))
    has_relator = bool(re.search(r'RELATOR', text, re.IGNORECASE))

    # Verifica seção de envolvidos (procura por papéis típicos)
    envolvidos_patterns = [
        r'APT[EO]',           # APTE/APTO (Apelante)
        r'APD[AO]',           # APDA/APDO (Apelado)
        r'AUTOR',             # Autor
        r'R[EÉ]U',            # Réu
        r'ADVOGAD[AO]',       # Advogado
        r'PROCURADOR',        # Procurador
        r'PART[EI]',          # Parte
    ]
    has_envolvidos = any(re.search(pattern, text, re.IGNORECASE) for pattern in envolvidos_patterns)

    # Verifica seção de movimentações (procura por indicadores temporais)
    movimentacoes_patterns = [
        r'MOVIMENTA[ÇC][ÃA]O',     # Movimentação
        r'MOVIMENTOS?',             # Movimento(s)
        r'ANDAMENTOS?',             # Andamento(s)
        r'\d{1,2}/\d{1,2}/\d{4}',   # Padrão de data dd/mm/aaaa
        r'PETICIONAMENTO',          # Peticionamento
        r'JUNTADA',                 # Juntada
        r'PUBLICA[ÇC][ÃA]O',        # Publicação
    ]
    has_movimentacoes = any(re.search(pattern, text, re.IGNORECASE) for pattern in movimentacoes_patterns)

    # Página de detalhe deve ter TODOS os indicadores principais
    return has_processo and has_relator and has_envolvidos and has_movimentacoes


def is_list(html_text: Union[str, bytes]) -> bool:
    """
    Detecta se a página é uma lista de resultados.

    Verifica presença de indicadores típicos de listagem:
    - Texto 'Total:' seguido de número
    - Barra de paginação com links
    - Tabelas com múltiplos processos
    - Links de navegação (próxima, última, etc.)

    Args:
        html_text: Conteúdo HTML da página

    Returns:
        True se for página de lista, False caso contrário
    """
    if not html_text:
        return False

    # Converte para string se necessário
    if isinstance(html_text, bytes):
        html_text = html_text.decode('utf-8', 'ignore')

    text = str(html_text)

    # Verifica padrão "Total: N" (Modo A de paginação)
    has_total = bool(re.search(r'Total:\s*\d+', text, re.IGNORECASE))

    # Verifica barra de paginação (Modo B)
    pagination_patterns = [
        r'pr[óo]xima',              # próxima
        r'[úu]ltima',               # última
        r'primeira',                # primeira
        r'anterior',                # anterior
        r'p[áa]gina\s*\d+',         # página N
        r'>\s*\d+\s*<',             # >N< (link de página)
    ]
    has_pagination = any(re.search(pattern, text, re.IGNORECASE) for pattern in pagination_patterns)

    # Verifica tabela com múltiplos processos
    # Procura por múltiplas ocorrências de números de processo
    processo_pattern = r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}'
    processo_matches = re.findall(processo_pattern, text)
    has_multiple_processes = len(processo_matches) > 1

    # Verifica estrutura de tabela típica de listagem
    table_indicators = [
        r'<table[^>]*>.*?</table>',     # Tags de tabela
        r'<tbody[^>]*>.*?</tbody>',     # Corpo de tabela
        r'<tr[^>]*>.*?</tr>',           # Linhas de tabela
    ]
    has_table_structure = any(re.search(pattern, text, re.IGNORECASE | re.DOTALL) for pattern in table_indicators)

    # Página de lista deve ter pelo menos um indicador forte
    return has_total or has_pagination or (has_multiple_processes and has_table_structure)


def is_error(html_text: Union[str, bytes]) -> bool:
    """
    Detecta se a página indica erro ou ausência de resultados.

    Verifica presença de mensagens típicas de erro:
    - "Nenhum resultado encontrado"
    - "Não foram encontrados processos"
    - Páginas de erro HTTP
    - Redirecionamentos inesperados
    - Estrutura incompleta ou corrompida

    Args:
        html_text: Conteúdo HTML da página

    Returns:
        True se for página de erro, False caso contrário
    """
    if not html_text:
        return True  # Conteúdo vazio é considerado erro

    # Converte para string se necessário
    if isinstance(html_text, bytes):
        html_text = html_text.decode('utf-8', 'ignore')

    text = str(html_text).upper()

    # Mensagens explícitas de erro ou ausência de resultados
    error_patterns = [
        r'NENHUM\s+RESULTADO',              # Nenhum resultado
        r'N[ÃA]O\s+FORAM?\s+ENCONTRADOS?',  # Não foram encontrados
        r'RESULTADO\s+N[ÃA]O\s+ENCONTRADO', # Resultado não encontrado
        r'SEM\s+RESULTADOS?',               # Sem resultado(s)
        r'BUSCA\s+SEM\s+RETORNO',          # Busca sem retorno
        r'CONSULTA\s+SEM\s+RESULTADO',     # Consulta sem resultado
        r'ERRO\s+\d+',                     # Erro HTTP (500, 404, etc.)
        r'P[ÁA]GINA\s+N[ÃA]O\s+ENCONTRADA', # Página não encontrada
        r'ACESSO\s+NEGADO',                # Acesso negado
        r'SERVI[ÇC]O\s+INDISPON[ÍI]VEL',   # Serviço indisponível
        r'SISTEMA\s+FORA\s+DO\s+AR',       # Sistema fora do ar
        r'MANUTEN[ÇC][ÃA]O',               # Manutenção
    ]

    has_error_message = any(re.search(pattern, text, re.IGNORECASE) for pattern in error_patterns)

    # Verifica se página tem estrutura mínima esperada
    # Páginas válidas do TRF5 devem ter elementos básicos
    has_basic_structure = bool(re.search(r'<html', text, re.IGNORECASE))
    has_body = bool(re.search(r'<body', text, re.IGNORECASE))

    # Conteúdo muito pequeno pode indicar erro
    is_too_short = len(text.strip()) < 100

    # Verifica se não é nem detalhe nem lista (estrutura inesperada)
    is_not_detail = not is_detail(html_text)
    is_not_list = not is_list(html_text)
    has_unexpected_structure = is_not_detail and is_not_list and has_basic_structure

    # É erro se tiver mensagem explícita OU estrutura problemática
    return (has_error_message or
            is_too_short or
            not has_basic_structure or
            not has_body or
            has_unexpected_structure)