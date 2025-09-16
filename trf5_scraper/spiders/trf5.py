# -*- coding: utf-8 -*-

"""
Spider TRF5 para coleta de dados de processos jurídicos.

Implementa dois modos de operação:
- modo=numero: busca por NPU via formulário oficial
- modo=cnpj: descoberta via formulário de busca

URL base: https://www5.trf5.jus.br/cp/
"""

import scrapy
import re
from typing import Dict, Any, Optional, Generator, List
from urllib.parse import urljoin

from ..utils.normalize import (
    normalize_npu_hyphenated,
    normalize_npu_digits,
    normalize_cnpj_digits,
    parse_date_to_iso,
    clean_text,
    normalize_relator
)
from ..utils.classify import is_detail, is_list, is_error
from ..utils.pagination import (
    extract_total_and_last_page,
    extract_bar_links,
    compute_limits,
    get_page_range
)


class Trf5Spider(scrapy.Spider):
    """
    Spider principal para extração de processos do TRF5.
    """

    name = "trf5"
    # ALTERAÇÃO: aceitar subdomínios (ex.: www5.trf5.jus.br) sem barrar pelo Offsite
    allowed_domains = ["trf5.jus.br"]  # antes: ["www5.trf5.jus.br"]
    # ALTERAÇÃO: usar https para evitar 302
    start_urls = ["https://www5.trf5.jus.br/cp/"]

    # Configurações do sistema TRF5
    # ALTERAÇÃO: http -> https
    BASE_URL = "https://www5.trf5.jus.br/cp/"
    FORM_URL = "https://www5.trf5.jus.br/cp/"
    PAGE_SIZE = 10

    def __init__(self, modo=None, valor=None, max_pages=None, max_details_per_page=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not modo or not valor:
            raise ValueError("Parâmetros 'modo' e 'valor' são obrigatórios")
        if modo not in ['numero', 'cnpj']:
            raise ValueError("Modo deve ser 'numero' ou 'cnpj'")

        self.modo = modo
        self.valor = str(valor).strip()

        limits = compute_limits(
            int(max_pages) if max_pages else None,
            int(max_details_per_page) if max_details_per_page else None
        )
        self.max_pages = limits['max_pages']
        self.max_details_per_page = limits['max_details_per_page']

        if self.modo == 'numero':
            self.valor_normalizado = normalize_npu_hyphenated(self.valor)
            if not self.valor_normalizado or len(normalize_npu_digits(self.valor)) != 20:
                raise ValueError(f"NPU inválido: {self.valor}")
        else:
            self.valor_normalizado = normalize_cnpj_digits(self.valor)
            if not self.valor_normalizado or len(self.valor_normalizado) != 14:
                raise ValueError(f"CNPJ inválido: {self.valor}")

        self.cnpj_pages_processed = 0
        self.cnpj_details_collected = 0

        self.mongo = None  # setado pela pipeline

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        self.logger.info(
            "Iniciando coleta TRF5 (modo=%s, valor=%s, max_pages=%d, max_details=%d)",
            self.modo, self.valor_normalizado, self.max_pages, self.max_details_per_page
        )

        if self.modo == 'numero':
            # ALTERAÇÃO: em vez de tentar /cp/processo/<NPU>, use o formulário oficial
            yield from self._start_requests_numero()
        else:
            yield from self._start_requests_cnpj()

    # ----------------------------- MODO NPU ----------------------------- #
    def _start_requests_numero(self) -> Generator[scrapy.Request, None, None]:
        """
        NPU via formulário (mais resiliente que supor um endpoint direto).
        """
        context = {
            "tipo": "form",
            "busca": "numero",
            "numero": self.valor_normalizado,
            "endpoint": "form"
        }
        self.logger.info("[numero] carregando formulário: %s", self.FORM_URL)
        yield scrapy.Request(
            url=self.FORM_URL,
            callback=self.parse_form_page_numero,  # ALTERAÇÃO: novo callback
            meta={'context': context},
            dont_filter=True
        )

    def parse_form_page_numero(self, response: scrapy.http.Response) -> Generator[scrapy.Request, None, None]:
        """
        Submete o formulário para busca por NPU.
        """
        context = response.meta['context']
        if self.mongo:
            self.mongo.save_raw_page(response, context)

        form_data = self._extract_form_data(response)

        # Definir campos específicos para busca por número de processo
        # O TRF5 usa radio buttons para selecionar o tipo de busca
        # e um campo principal "filtro" para inserir o valor
        form_data["tipo"] = "xmlproc"  # N° do processo
        form_data["filtro"] = self.valor_normalizado

        self.logger.info("[numero] submetendo formulário tipo=xmlproc com filtro=%s", self.valor_normalizado)

        # Resultado esperado: página de detalhe OU uma lista com 1 item
        context_result = {
            "tipo": "lista",  # pode virar 'detalhe' na classificação
            "busca": "numero",
            "numero": self.valor_normalizado,
            "page_idx": 0,
            "endpoint": "form"
        }

        yield scrapy.FormRequest.from_response(
            response,
            formdata=form_data,
            callback=self.parse_result_numero,  # ALTERAÇÃO: novo callback
            meta={'context': context_result},
            dont_filter=True
        )

    def parse_result_numero(self, response: scrapy.http.Response) -> Generator[scrapy.Request, None, None]:
        """
        Trata o retorno da busca por NPU: pode vir diretamente a página de detalhe
        ou uma lista intermediária com link para o detalhe.
        """
        context = response.meta['context']
        if self.mongo:
            self.mongo.save_raw_page(response, context)

        page_type = self._classify_page(response.text)
        self.logger.info("[numero] retorno classificado como: %s (%s)", page_type, response.url)

        if page_type == 'detail':
            # Reaproveita a lógica de detalhe
            yield from self._process_detail_response(response)
            return

        if page_type == 'list':
            # Tenta extrair o primeiro link que contenha o NPU solicitado
            links = response.css('a[href*="processo"], a[href*="Processo"], a[href*="detalhe"]::attr(href)').getall()
            # procurar o NPU alvo na página para construir/filtrar o link correto
            npu_regex = r'(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})'
            alvo = self.valor_normalizado
            melhor = None
            for href in links:
                if not href:
                    continue
                if alvo in href:
                    melhor = href
                    break
                # fallback: se o alvo não está no href, mas o href parece detalhe, ainda tentar
                if re.search(npu_regex, href):
                    melhor = href

            if not melhor:
                self.logger.warning("[numero] lista retornada, mas nenhum link de detalhe encontrado.")
                return

            detail_url = urljoin(response.url, melhor)
            detail_context = {
                "tipo": "detalhe",
                "busca": "numero",
                "numero": self.valor_normalizado,
                "endpoint": "detalhe"
            }
            self.logger.info("[numero] seguindo para detalhe: %s", detail_url)
            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_processo_detail,
                meta={'context': detail_context},
                dont_filter=True
            )
            return

        if page_type == 'error':
            self.logger.warning("[numero] página de erro após submissão: %s", response.url)
            return

        self.logger.warning("[numero] tipo de página desconhecido: %s", response.url)

    # ----------------------------- MODO CNPJ ----------------------------- #
    def _start_requests_cnpj(self) -> Generator[scrapy.Request, None, None]:
        context = {
            "tipo": "form",
            "busca": "cnpj",
            "cnpj": self.valor_normalizado,
            "endpoint": "form"
        }
        self.logger.info("[cnpj] carregando formulário: %s", self.FORM_URL)
        yield scrapy.Request(
            url=self.FORM_URL,
            callback=self.parse_form_page,
            meta={'context': context},
            dont_filter=True
        )

    def parse_form_page(self, response: scrapy.http.Response) -> Generator[scrapy.Request, None, None]:
        context = response.meta['context']
        if self.mongo:
            self.mongo.save_raw_page(response, context)

        form_data = self._extract_form_data(response)

        # Definir campos específicos para busca por CNPJ
        # O TRF5 usa radio buttons para selecionar o tipo de busca
        form_data["tipo"] = "xmlcpf"  # CPF/CNPJ
        form_data["filtro"] = self.valor_normalizado

        context_list = {
            "tipo": "lista",
            "busca": "cnpj",
            "cnpj": self.valor_normalizado,
            "page_idx": 0,
            "endpoint": "form"
        }

        self.logger.info("[cnpj] submetendo formulário tipo=xmlcpf com filtro=%s", self.valor_normalizado)
        yield scrapy.FormRequest.from_response(
            response,
            formdata=form_data,
            callback=self.parse_result_list,
            meta={'context': context_list},
            dont_filter=True
        )

    # ----------------------------- LISTA / DETALHE ----------------------------- #
    def parse_result_list(self, response: scrapy.http.Response) -> Generator[scrapy.Request, None, None]:
        context = response.meta['context']
        if self.mongo:
            self.mongo.save_raw_page(response, context)

        html = response.text
        page_type = self._classify_page(html)

        self.logger.info(
            "Página de lista processada (page=%d, tipo=%s, url=%s)",
            context.get('page_idx', 0), page_type, response.url
        )

        if page_type == 'error':
            self.logger.warning("Página de erro detectada: %s", response.url)
            return

        if page_type != 'list':
            self.logger.warning("Página não é lista conforme esperado: %s", response.url)
            return

        yield from self._extract_detail_links(response)

        self.cnpj_pages_processed += 1
        if self.cnpj_pages_processed < self.max_pages:
            yield from self._handle_pagination(response)

    def parse_processo_detail(self, response: scrapy.http.Response) -> Optional[Dict[str, Any]]:
        # Salvar HTML sempre
        context = response.meta['context']
        if self.mongo:
            self.mongo.save_raw_page(response, context)

        page_type = self._classify_page(response.text)

        if page_type == 'error':
            self.logger.warning("Erro ao acessar processo: %s", response.url)
            return None

        if page_type != 'detail':
            self.logger.warning("Página não é detalhe conforme esperado: %s", response.url)
            return None

        # Processar de fato o detalhe
        yield from self._process_detail_response(response)
        return None

    # ALTERAÇÃO: pequena refatoração para reutilizar no fluxo de numero/lista
    def _process_detail_response(self, response: scrapy.http.Response) -> Generator[None, None, None]:
        try:
            item = self._extract_processo_data(response)
            if item and self.mongo:
                self.mongo.upsert_processo(item)
        except Exception as e:
            self.logger.error("Erro ao extrair dados do processo %s: %s", response.url, e)
        yield  # generator compatível com callbacks do Scrapy

    # ----------------------------- FORM & PAGINAÇÃO HELPERS ----------------------------- #
    def _extract_form_data(self, response: scrapy.http.Response) -> Dict[str, str]:
        """
        Extrai inputs hidden para manter a sessão/validação do formulário.
        (Não define aqui CNPJ/NPU; isso é feito pelos respectivos parse_*_page.)
        """
        form_data: Dict[str, str] = {}
        for hidden in response.css('input[type="hidden"]'):
            name = (hidden.attrib.get('name') or '').strip()
            if not name:
                continue
            value = hidden.attrib.get('value', '')
            form_data[name] = value
        return form_data

    # ALTERAÇÃO: utilitário robusto para localizar o nome do input por palavras-chave
    def _find_input_name(self, response: scrapy.http.Response, keywords: List[str]) -> Optional[str]:
        kw = [k.lower() for k in keywords]
        for inp in response.css('input'):
            name = (inp.attrib.get('name') or '').strip()
            if not name:
                continue
            lname = name.lower()
            if any(k in lname for k in kw):
                return name
        return None

    def _extract_detail_links(self, response: scrapy.http.Response) -> Generator[scrapy.Request, None, None]:
        context = response.meta['context']
        processo_links = response.css('a[href*="processo"]')

        details_this_page = 0
        for link in processo_links:
            if (self.cnpj_details_collected >= (self.max_pages * self.max_details_per_page) or
                details_this_page >= self.max_details_per_page):
                break

            href = link.attrib.get('href')
            if not href:
                continue

            npu_match = re.search(r'(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})', href)
            processo_npu = npu_match.group(1) if npu_match else None

            detail_url = urljoin(response.url, href)

            detail_context = {
                "tipo": "detalhe",
                "busca": "cnpj",
                "cnpj": context.get('cnpj'),
                "numero": processo_npu,
                "endpoint": "detalhe"
            }

            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_processo_detail,
                meta={'context': detail_context},
                dont_filter=True
            )

            details_this_page += 1
            self.cnpj_details_collected += 1

        self.logger.info(
            "Extraídos %d links de detalhe desta página (total coletado: %d)",
            details_this_page, self.cnpj_details_collected
        )

    def _handle_pagination(self, response: scrapy.http.Response) -> Generator[scrapy.Request, None, None]:
        context = response.meta['context']
        current_page = context.get('page_idx', 0)

        pagination_info = extract_total_and_last_page(response.text, self.PAGE_SIZE)
        if pagination_info['total'] is not None:
            last_page = pagination_info['last_page']
            page_range = get_page_range(current_page + 1, last_page, self.max_pages - self.cnpj_pages_processed)

            for page_num in page_range:
                if page_num <= current_page:
                    continue

                next_context = dict(context)
                next_context['page_idx'] = page_num
                next_url = self._build_page_url(response.url, page_num)

                yield scrapy.Request(
                    url=next_url,
                    callback=self.parse_result_list,
                    meta={'context': next_context},
                    dont_filter=True
                )
        else:
            bar_info = extract_bar_links(response.text)
            if bar_info['has_next'] and bar_info['next_page'] is not None:
                next_context = dict(context)
                next_context['page_idx'] = current_page + 1
                next_url = urljoin(response.url, f"?page={bar_info['next_page']}")

                yield scrapy.Request(
                    url=next_url,
                    callback=self.parse_result_list,
                    meta={'context': next_context},
                    dont_filter=True
                )

    def _build_page_url(self, base_url: str, page_num: int) -> str:
        if '?' in base_url:
            return f"{base_url}&page={page_num}"
        else:
            return f"{base_url}?page={page_num}"

    # ----------------------------- CLASSIFICAÇÃO / PARSE DETALHE ----------------------------- #
    def _classify_page(self, html: str) -> str:
        if is_detail(html):
            return 'detail'
        elif is_list(html):
            return 'list'
        elif is_error(html):
            return 'error'
        else:
            return 'unknown'

    def _extract_processo_data(self, response: scrapy.http.Response) -> Optional[Dict[str, Any]]:
        try:
            item = {'fonte_url': response.url}

            numero_processo = self._extract_numero_processo(response)
            if not numero_processo:
                self.logger.warning("Número do processo não encontrado em %s", response.url)
                return None

            item['_id'] = normalize_npu_hyphenated(numero_processo)
            item['numero_processo'] = item['_id']
            item['numero_legado'] = self._extract_numero_legado(response)

            if not item['numero_processo'] and item['numero_legado']:
                item['numero_processo'] = item['numero_legado']

            item['data_autuacao'] = self._extract_data_autuacao(response)
            item['relator'] = self._extract_relator(response)
            item['envolvidos'] = self._extract_envolvidos(response)
            item['movimentacoes'] = self._extract_movimentacoes(response)

            return item
        except Exception as e:
            self.logger.error("Erro ao extrair dados do processo: %s", e)
            return None

    def _extract_numero_processo(self, response: scrapy.http.Response) -> Optional[str]:
        text = response.text
        npu_pattern = r'(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})'
        match = re.search(npu_pattern, text)
        if match:
            return normalize_npu_hyphenated(match.group(1))

        selectors = [
            '//text()[contains(., "PROCESSO") and contains(., "Nº")]',
            '//text()[contains(., "Processo:")]',
            '.processo-numero::text',
            '.numero-processo::text'
        ]
        for selector in selectors:
            elements = response.xpath(selector) if selector.startswith('//') else response.css(selector)
            for element in elements:
                text_content = element.get().strip()
                match = re.search(npu_pattern, text_content)
                if match:
                    return normalize_npu_hyphenated(match.group(1))
        return None

    def _extract_numero_legado(self, response: scrapy.http.Response) -> Optional[str]:
        # Busca padrão "(99.05.15648-8)" ou similar
        text = response.text
        match = re.search(r'\(([0-9]{2}\.[0-9]{2}\.[0-9]+-[0-9])\)', text)
        if match:
            return clean_text(match.group(1))
        return None

    def _extract_data_autuacao(self, response: scrapy.http.Response) -> Optional[str]:
        # Busca padrão "AUTUADO EM DD/MM/AAAA" específico do TRF5
        text = response.text
        match = re.search(r'AUTUADO\s+EM\s+(\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
        if match:
            return parse_date_to_iso(match.group(1))

        # Fallback para outros padrões
        selectors = [
            '//text()[contains(., "Autuação") or contains(., "Data:")]',
            '.data-autuacao::text',
            '.autuacao::text'
        ]
        for selector in selectors:
            elements = response.xpath(selector) if selector.startswith('//') else response.css(selector)
            for element in elements:
                text_content = element.get().strip()
                date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', text_content)
                if date_match:
                    return parse_date_to_iso(date_match.group(1))
        return None

    def _extract_relator(self, response: scrapy.http.Response) -> Optional[str]:
        # Busca em células de tabela específicas do TRF5
        # Estrutura: <td>RELATOR</td><td><b>: DESEMBARGADOR FEDERAL NOME</b></td>
        rows = response.css('table tr')
        for row in rows:
            cells = row.css('td')
            if len(cells) >= 2:
                first_cell = clean_text(cells[0].css('::text').get() or '')
                if 'relator' in first_cell.lower():
                    second_cell = clean_text(cells[1].css('::text').get() or '')
                    # Remove ":" do início se presente
                    relator_name = re.sub(r'^\s*:\s*', '', second_cell)
                    if relator_name:
                        return normalize_relator(relator_name)

        # Fallback para outros padrões
        selectors = [
            '//text()[contains(., "RELATOR")]',
            '.relator::text',
            '.magistrado::text'
        ]
        for selector in selectors:
            elements = response.xpath(selector) if selector.startswith('//') else response.css(selector)
            for element in elements:
                text_content = clean_text(element.get())
                if 'relator' in text_content.lower():
                    match = re.search(r'relator:?\s*(.+)', text_content, re.IGNORECASE)
                    if match:
                        return normalize_relator(match.group(1))
        return None

    def _extract_envolvidos(self, response: scrapy.http.Response) -> list:
        envolvidos = []
        tables = response.css('table')
        for table in tables:
            rows = table.css('tr')
            for row in rows:
                cells = row.css('td')
                if len(cells) >= 2:
                    papel = clean_text(cells[0].css('::text').get() or '')
                    nome_raw = clean_text(cells[1].css('::text').get() or '')

                    # Remove ":" do início do nome se presente
                    nome = re.sub(r'^\s*:\s*', '', nome_raw)

                    # Filtra registros válidos (não vazios, não são apenas ":")
                    if (papel and nome and
                        papel not in ['RELATOR'] and  # relator já é extraído separadamente
                        nome != ':' and
                        len(nome.strip()) > 1):
                        envolvidos.append({'papel': papel, 'nome': nome})
        return envolvidos

    def _extract_movimentacoes(self, response: scrapy.http.Response) -> list:
        movimentacoes = []

        # Estrutura específica do TRF5: <a name="mov_X">Em DD/MM/AAAA HH:MM</a>
        movs_links = response.css('a[name^="mov_"]')
        for link in movs_links:
            data_text = clean_text(link.css('::text').get() or '')
            # Extrai data de "Em 11/09/2021 16:50"
            date_match = re.search(r'Em\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{1,2})', data_text)
            if date_match:
                data_str = f"{date_match.group(1)} {date_match.group(2)}"
                data_iso = parse_date_to_iso(data_str)

                # Busca o texto da movimentação nas células seguintes
                parent_row = link.xpath('./ancestor::tr[1]')
                if parent_row:
                    next_row = parent_row[0].xpath('./following-sibling::tr[1]')
                    if next_row:
                        texto_cell = next_row[0].css('td:nth-child(2)')
                        if texto_cell:
                            texto = clean_text(texto_cell.css('::text').get() or '')
                            # Remove códigos de guia e outros metadados
                            texto = re.sub(r'\[Guia:.*?\].*', '', texto)
                            texto = clean_text(texto)

                            if data_iso and texto and len(texto) > 5:
                                movimentacoes.append({
                                    'data': data_iso,
                                    'texto': texto
                                })

        # Fallback para outros padrões
        if not movimentacoes:
            movs_section = response.css('.movimentacoes, .andamentos, .timeline')
            for section in movs_section:
                items = section.css('.movimento, .andamento, .item')
                for item in items:
                    data_text = item.css('.data::text, .timestamp::text').get()
                    texto = clean_text(item.css('.texto::text, .descricao::text').get() or '')
                    if data_text and texto:
                        data_iso = parse_date_to_iso(data_text.strip())
                        if data_iso:
                            movimentacoes.append({'data': data_iso, 'texto': texto})

        return movimentacoes
