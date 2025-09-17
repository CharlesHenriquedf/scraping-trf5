# -*- coding: utf-8 -*-

"""
Spider TRF5 para coleta de dados de processos jurídicos.

Implementa dois modos de operação:
- modo=numero: busca por NPU via formulário oficial
- modo=cnpj: descoberta via rota estável GET (novo: /processo/cpf/porData/ativos/{CNPJ}/{PAGINA})

URL base: https://www5.trf5.jus.br/cp/

NOTA: Compatível com Scrapy 2.13+ (implementa start() além de start_requests()).
Mudança principal: fluxo CNPJ não usa mais POST para cp.do (dependência de sessão),
agora usa rota estável que não requer estado.

Seletores-chave para rota estável CNPJ:
- Lista válida: .consulta_resultados OU <th>CNPJ:</th>
- Total: .consulta_paginas .texto_consulta
- Links: a.linkar[href^="/processo/"]
- Paginação: URLs sequenciais .../CNPJ/0, .../CNPJ/1, etc.

Campos frágeis (dependem da estrutura HTML do TRF5):
- Relator: busca por células de tabela com "RELATOR"
- Data: padrão "AUTUADO EM DD/MM/AAAA"
- Movimentações: links <a name="mov_X"> seguidos de texto
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

    Racional da mudança CNPJ:
    - Antes: POST para cp.do (dependência de sessão/estado)
    - Agora: GET para /processo/cpf/porData/ativos/{CNPJ}/{PAGINA} (rota estável)

    Vantagens da rota estável:
    - Não depende de estado de sessão
    - URLs previsíveis e sequenciais
    - Menor chance de erro por timeout/validação
    - Paginação mais robusta
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

        # Armazenar parâmetros sem validação (validação será feita em start_requests)
        self.modo = modo
        self.valor = str(valor).strip() if valor else None

        limits = compute_limits(
            int(max_pages) if max_pages else None,
            int(max_details_per_page) if max_details_per_page else None
        )
        self.max_pages = limits['max_pages']
        self.max_details_per_page = limits['max_details_per_page']

        # Normalização defensiva (pode resultar em None se inválido)
        self.valor_normalizado = None
        if self.modo == 'numero' and self.valor:
            self.valor_normalizado = normalize_npu_hyphenated(self.valor)
        elif self.modo == 'cnpj' and self.valor:
            self.valor_normalizado = normalize_cnpj_digits(self.valor)

        self.cnpj_pages_processed = 0
        self.cnpj_details_collected = 0

        self.mongo = None  # setado pela pipeline

    async def start(self):
        """
        Método moderno para Scrapy 2.13+ (substitui start_requests).
        Gera requests diretamente sem dependência de start_requests.
        """
        for request in self.start_requests():
            yield request

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        """
        Método legado para compatibilidade com Scrapy < 2.13.
        A partir do Scrapy 2.13, preferência é dada ao método start().
        """
        # Validação com logs informativos e encerramento silencioso
        if not self.modo or not self.valor:
            self.logger.error("Parâmetros 'modo' e 'valor' são obrigatórios")
            self.logger.info("Uso: scrapy crawl trf5 -a modo=numero -a valor='0015648-78.1999.4.05.0000'")
            return

        if self.modo not in ['numero', 'cnpj']:
            self.logger.error(f"Modo inválido: '{self.modo}'. Deve ser 'numero' ou 'cnpj'")
            return

        if self.modo == 'numero':
            if not self.valor_normalizado or len(normalize_npu_digits(self.valor)) != 20:
                self.logger.error(f"NPU inválido: {self.valor}. NPU deve ter 20 dígitos.")
                return
        else:
            if not self.valor_normalizado or len(self.valor_normalizado) != 14:
                self.logger.error(f"CNPJ inválido: {self.valor}. CNPJ deve ter 14 dígitos.")
                return

        self.logger.info(
            "Iniciando coleta TRF5 (modo=%s, valor=%s, max_pages=%d, max_details=%d)",
            self.modo, self.valor_normalizado, self.max_pages, self.max_details_per_page
        )

        if self.modo == 'numero':
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
            # Extrai links de processo de forma robusta, evitando links de movimentação
            melhor = self._extract_npu_detail_link(response, self.valor_normalizado)

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
        """
        CNPJ via rota estável GET (rota direta sem dependência de sessão).

        Mudança: Em vez de usar formulário POST para cp.do (que retornava erro),
        agora usamos a rota estável: /processo/cpf/porData/ativos/{DOC14}/{PAGINA}

        Esta rota é mais confiável pois não depende de estado de sessão.
        """
        # Validação robusta: CNPJ deve ter exatamente 14 dígitos
        if len(self.valor_normalizado) != 14:
            self.logger.warning(
                "[cnpj] CNPJ inválido: %s (deve ter 14 dígitos). Encerrando fluxo.",
                self.valor_normalizado
            )
            return

        # Construir URL da rota estável
        stable_url = f"https://cp.trf5.jus.br/processo/cpf/porData/ativos/{self.valor_normalizado}/0"

        context = {
            "tipo": "lista",
            "busca": "cnpj",
            "cnpj": self.valor_normalizado,
            "page_idx": 0,
            "endpoint": "stable_route"
        }

        self.logger.info(
            "[cnpj] acessando rota estável: %s (CNPJ=%s)",
            stable_url, self.valor_normalizado
        )

        # Incluir cabeçalhos básicos conforme especificação
        headers = {
            'Referer': 'https://www5.trf5.jus.br/cp/',
            'User-Agent': self.settings.get('USER_AGENT', 'trf5_scraper (+http://www.yourdomain.com)')
        }

        yield scrapy.Request(
            url=stable_url,
            callback=self.parse_result_list_stable,
            meta={'context': context},
            headers=headers,
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
    def parse_result_list_stable(self, response: scrapy.http.Response) -> Generator[scrapy.Request, None, None]:
        """
        Processa resposta da rota estável CNPJ com nova heurística de detecção.

        Nova lógica de classificação:
        - Lista válida: existe .consulta_resultados OU parâmetros CNPJ
        - Erro: texto "O Número do Processo informado não é válido" OU estrutura ausente
        """
        context = response.meta['context']
        if self.mongo:
            self.mongo.save_raw_page(response, context)

        html = response.text
        page_type = self._classify_page_cnpj_stable(html)

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

        # Extrair total de registros
        total_info = self._extract_total_from_stable_page(response)
        if total_info:
            self.logger.info(
                "[cnpj] Total de registros detectado: %d (CNPJ=%s)",
                total_info, context.get('cnpj')
            )

        # Extrair links de detalhe
        yield from self._extract_detail_links_stable(response)

        # Controlar paginação
        self.cnpj_pages_processed += 1
        if self.cnpj_pages_processed < self.max_pages:
            yield from self._handle_pagination_stable(response)

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

        page_type = self._classify_page_unified(response.text)

        if page_type == 'error':
            self.logger.warning("Erro ao acessar processo: %s", response.url)
            return None

        if page_type != 'detail':
            self.logger.warning(
                "Página não é detalhe conforme esperado (tipo=%s): %s",
                page_type, response.url
            )
            # Log adicional para debug - mostra indicadores presentes
            self._debug_page_content(response.text, response.url)
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
    def _classify_page_cnpj_stable(self, html: str) -> str:
        """
        Heurística específica para a rota estável CNPJ.

        Lista válida quando:
        - existe tabela .consulta_resultados, OU
        - existe bloco "Parâmetros da Pesquisa" com <th>CNPJ:</th>

        Erro quando:
        - texto "O Número do Processo informado não é válido", OU
        - não existe .consulta_resultados e nem parâmetros visíveis
        """
        if not html:
            return 'error'

        text_upper = html.upper()

        # Verificar erro explícito
        if "O NÚMERO DO PROCESSO INFORMADO NÃO É VÁLIDO" in text_upper:
            return 'error'

        # Verificar lista válida por indicadores específicos
        has_consulta_resultados = '.consulta_resultados' in html or 'consulta_resultados' in html
        has_cnpj_params = bool(
            re.search(r'<th[^>]*>\s*CNPJ\s*:?\s*</th>', html, re.IGNORECASE)
        )

        if has_consulta_resultados or has_cnpj_params:
            return 'list'

        # Se não tem indicadores de lista nem de erro explícito, assumir erro
        return 'error'

    def _classify_page(self, html: str) -> str:
        """
        Classificação unificada de páginas com critérios ampliados.

        Usado tanto online quanto offline para garantir consistência.
        """
        return self._classify_page_unified(html)

    def _classify_page_unified(self, html: str) -> str:
        """
        Classificação unificada com critérios ampliados para detectar detalhes.

        Critérios para detalhe (mais permissivos):
        - Contém NPU formatado E (relator OU envolvidos OU movimentações)
        - OU indicadores clássicos do is_detail() original
        """
        if not html:
            return 'error'

        # Primeiro tenta a classificação original (mais restritiva)
        if is_detail(html):
            return 'detail'

        # Classificação ampliada para capturar mais casos de detalhe
        text_upper = html.upper()

        # Verifica se há NPU formatado (indicador forte de detalhe)
        has_npu = bool(re.search(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', html))

        if has_npu:
            # Indicadores de conteúdo de detalhe
            has_relator_info = any(re.search(pattern, text_upper) for pattern in [
                r'RELATOR',
                r'DESEMBARGADOR',
                r'JUIZ(A)?\s+FEDERAL'
            ])

            has_parties_info = any(re.search(pattern, text_upper) for pattern in [
                r'APT[EO]',     # APTE/APTO
                r'APD[AO]',     # APDA/APDO
                r'AUTOR',
                r'R[EÉ]U',
                r'ADVOGAD[AO]',
                r'PROCURADOR',
                r'PART[EI]',
                r'ENVOLVIDOS?'
            ])

            has_timeline_info = any(re.search(pattern, text_upper) for pattern in [
                r'MOVIMENTA[ÇC][ÃA]O',
                r'MOVIMENTOS?',
                r'ANDAMENTOS?',
                r'PETICIONAMENTO',
                r'JUNTADA',
                r'PUBLICA[ÇC][ÃA]O',
                r'\d{1,2}/\d{1,2}/\d{4}',  # Datas
                r'AUTUAD[AO]\s+EM'
            ])

            # Se tem NPU + pelo menos um indicador de conteúdo, considera detalhe
            if has_relator_info or has_parties_info or has_timeline_info:
                return 'detail'

        # Se não é detalhe, tenta outras classificações
        if is_list(html):
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
        """
        Extrai relator com múltiplas estratégias para diferentes layouts do TRF5.

        Tenta múltiplas abordagens para maximizar cobertura de casos.
        """
        # Estratégia 1: Tabelas estruturadas (padrão clássico)
        relator = self._extract_relator_from_table(response)
        if relator:
            return relator

        # Estratégia 2: Texto estruturado (divs, spans, etc.)
        relator = self._extract_relator_from_text(response)
        if relator:
            return relator

        # Estratégia 3: Busca ampla por padrões textuais
        relator = self._extract_relator_from_patterns(response)
        if relator:
            return relator

        # Estratégia 4: XPath genérico para casos edge
        relator = self._extract_relator_xpath_fallback(response)
        if relator:
            return relator

        return None

    def _extract_relator_from_table(self, response: scrapy.http.Response) -> Optional[str]:
        """Extrai relator de estruturas de tabela."""
        rows = response.css('table tr')
        for row in rows:
            cells = row.css('td')
            if len(cells) >= 2:
                first_cell = clean_text(cells[0].css('::text').get() or '')
                if 'relator' in first_cell.lower():
                    # Busca texto em diferentes elementos da segunda célula
                    second_cell_selectors = ['::text', 'b::text', 'strong::text', 'span::text']
                    for sel in second_cell_selectors:
                        second_cell = clean_text(cells[1].css(sel).get() or '')
                        if second_cell:
                            # Remove prefixos comuns
                            relator_name = re.sub(r'^\s*[:;]\s*', '', second_cell)
                            if relator_name:
                                return normalize_relator(relator_name)
        return None

    def _extract_relator_from_text(self, response: scrapy.http.Response) -> Optional[str]:
        """Extrai relator de elementos de texto estruturados."""
        # Seletores específicos para diferentes layouts
        selectors = [
            '.relator::text',
            '.magistrado::text',
            '.juiz::text',
            '.desembargador::text',
            'div:contains("RELATOR") + div::text',
            'span:contains("RELATOR")::text',
            'p:contains("RELATOR")::text',
            '.info-relator::text',
            '.dados-relator::text'
        ]

        for selector in selectors:
            elements = response.css(selector)
            for element in elements:
                text_content = clean_text(element.get() or '')
                if text_content:
                    # Se já contém "relator", remove o prefixo
                    if 'relator' in text_content.lower():
                        match = re.search(r'relator:?\s*(.+)', text_content, re.IGNORECASE)
                        if match:
                            return normalize_relator(match.group(1))
                    else:
                        # Se não contém "relator", mas está em seletor específico, use direto
                        return normalize_relator(text_content)
        return None

    def _extract_relator_from_patterns(self, response: scrapy.http.Response) -> Optional[str]:
        """Extrai relator usando padrões textuais amplos."""
        # Busca por padrões textuais em todo o HTML
        text_patterns = [
            r'RELATOR:?\s*([^\n\r<]+)',
            r'Relator:?\s*([^\n\r<]+)',
            r'DESEMBARGADOR(?:\s+FEDERAL)?:?\s*([^\n\r<]+)',
            r'JUIZ(?:A)?\s+FEDERAL:?\s*([^\n\r<]+)',
            r'(?:RELATOR|RELATORA)\s*-\s*([^\n\r<]+)'
        ]

        full_text = response.text
        for pattern in text_patterns:
            matches = re.finditer(pattern, full_text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                relator_text = clean_text(match.group(1))
                if relator_text and len(relator_text) > 3:  # Filtro mínimo de tamanho
                    return normalize_relator(relator_text)
        return None

    def _extract_relator_xpath_fallback(self, response: scrapy.http.Response) -> Optional[str]:
        """Busca genérica com XPath como último recurso."""
        xpath_selectors = [
            '//text()[contains(upper-case(.), "RELATOR")]',
            '//td[contains(upper-case(.), "RELATOR")]/following-sibling::td[1]//text()',
            '//th[contains(upper-case(.), "RELATOR")]/following-sibling::td[1]//text()',
            '//*[contains(upper-case(@class), "relator")]//text()',
            '//*[contains(upper-case(@id), "relator")]//text()'
        ]

        for xpath in xpath_selectors:
            try:
                elements = response.xpath(xpath)
                for element in elements:
                    text_content = clean_text(element.get() or '')
                    if text_content and 'relator' in text_content.lower():
                        # Extrai apenas a parte do nome, removendo "RELATOR:"
                        match = re.search(r'relator:?\s*(.+)', text_content, re.IGNORECASE)
                        if match:
                            candidate = clean_text(match.group(1))
                            if candidate and len(candidate) > 3:
                                return normalize_relator(candidate)
            except Exception:
                continue  # XPath pode falhar em HTML malformado
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

    # ----------------------------- HELPERS NPU ----------------------------- #
    def _extract_npu_detail_link(self, response: scrapy.http.Response, target_npu: str) -> Optional[str]:
        """
        Extrai link de detalhe específico para NPU de forma robusta.

        Evita capturar HTML completo e filtra links de movimentação interna.
        Prioriza links que contenham o NPU alvo exato.
        """
        # Seletores específicos para links de processo, evitando movimentação
        selectors = [
            'a.linkar[href^="/processo/"]:not([href*="/movimentacao/"])',
            'a[href^="/cp/processo/"]:not([href*="/movimentacao/"])',
            'a[href*="/processo/"]:not([href*="/movimentacao/"]):not([href*="/movimento/"])',
            'a[href*="processo"]:not([href*="movimentacao"]):not([href*="movimento"])'
        ]

        npu_regex = r'(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})'
        melhor_link = None
        melhor_score = 0

        for selector in selectors:
            links = response.css(selector)

            for link in links:
                href = link.attrib.get('href')
                if not href:
                    continue

                # Ignora fragmentos, javascript e links relativos problemáticos
                if href.startswith('#') or href.startswith('javascript:') or href == '/':
                    continue

                # Score baseado em relevância
                score = 0

                # Score máximo se contém o NPU exato
                if target_npu in href:
                    score += 100

                # Score por padrão NPU válido
                if re.search(npu_regex, href):
                    score += 50

                # Score por estrutura típica de detalhe
                if '/processo/' in href and not any(x in href for x in ['/movimentacao/', '/movimento/', '/lista']):
                    score += 25

                # Prioriza links mais específicos (sem parâmetros extras)
                if href.count('?') == 0 and href.count('&') == 0:
                    score += 10

                # Atualiza melhor link se score é maior
                if score > melhor_score:
                    melhor_score = score
                    melhor_link = href

                    # Se encontrou NPU exato, pode parar a busca
                    if target_npu in href:
                        break

            # Se já encontrou um link com NPU exato, não precisa tentar outros seletores
            if melhor_score >= 100:
                break

        if melhor_link:
            self.logger.info(
                "[numero] Link de detalhe selecionado (score=%d): %s",
                melhor_score, melhor_link
            )

        return melhor_link

    def _debug_page_content(self, html: str, url: str) -> None:
        """
        Gera log de debug mostrando indicadores presentes na página.
        Útil para entender por que uma página não foi classificada como detalhe.
        """
        if not html:
            self.logger.debug("[debug] Página vazia: %s", url)
            return

        text_upper = html.upper()
        indicators = {
            'npu': bool(re.search(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', html)),
            'processo_ref': 'PROCESSO' in text_upper,
            'relator': 'RELATOR' in text_upper,
            'desembargador': 'DESEMBARGADOR' in text_upper,
            'envolvidos': any(x in text_upper for x in ['AUTOR', 'REU', 'RÉU', 'ADVOGADO']),
            'movimentacao': any(x in text_upper for x in ['MOVIMENTAÇÃO', 'ANDAMENTO', 'JUNTADA']),
            'data_formato': bool(re.search(r'\d{1,2}/\d{1,2}/\d{4}', html)),
            'autuacao': 'AUTUADO' in text_upper
        }

        present_indicators = [k for k, v in indicators.items() if v]

        self.logger.debug(
            "[debug] Indicadores presentes em %s: %s",
            url, ', '.join(present_indicators) if present_indicators else 'nenhum'
        )

        # Se tem NPU mas não foi classificado como detalhe, mostra mais detalhes
        if indicators['npu']:
            self.logger.debug(
                "[debug] Página tem NPU mas não foi classificada como detalhe. "
                "Tamanho HTML: %d chars", len(html)
            )

    # ----------------------------- HELPERS ROTA ESTÁVEL CNPJ ----------------------------- #
    def _extract_total_from_stable_page(self, response: scrapy.http.Response) -> Optional[int]:
        """
        Extrai total de registros de .consulta_paginas .texto_consulta.
        Padrão esperado: "Total: 125" ou similar.
        """
        # Seletor específico da rota estável
        total_selectors = [
            '.consulta_paginas .texto_consulta::text',
            '.texto_consulta::text',
            '//text()[contains(., "Total:")]'
        ]

        for selector in total_selectors:
            if selector.startswith('//'):
                elements = response.xpath(selector)
            else:
                elements = response.css(selector)

            for element in elements:
                text = element.get().strip() if element else ''
                # Procura por "Total: N"
                match = re.search(r'Total:\s*(\d+)', text, re.IGNORECASE)
                if match:
                    return int(match.group(1))

        return None

    def _extract_detail_links_stable(self, response: scrapy.http.Response) -> Generator[scrapy.Request, None, None]:
        """
        Extrai links de processo da tabela .consulta_resultados.
        Seletores específicos para a rota estável CNPJ.
        """
        context = response.meta['context']

        # Seletores mais específicos para a rota estável
        link_selectors = [
            'a.linkar[href^="/processo/"]',
            'a[href*="/processo/"]',
            'a[href*="processo"]'
        ]

        processo_links = []
        for selector in link_selectors:
            links = response.css(selector)
            if links:
                processo_links = links
                break

        details_this_page = 0
        itens_listados_por_pagina = 0

        for link in processo_links:
            if (self.cnpj_details_collected >= (self.max_pages * self.max_details_per_page) or
                details_this_page >= self.max_details_per_page):
                break

            href = link.attrib.get('href')
            if not href:
                continue

            # Extrair NPU do href
            npu_match = re.search(r'(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})', href)
            processo_npu = npu_match.group(1) if npu_match else None

            # Construir URL absoluta
            detail_url = urljoin(response.url, href)
            # Forçar HTTPS se necessário
            if detail_url.startswith('http://cp.trf5.jus.br'):
                detail_url = detail_url.replace('http://', 'https://')

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
            itens_listados_por_pagina += 1
            self.cnpj_details_collected += 1

        self.logger.info(
            "[cnpj] itens_listados_por_pagina=%d, detalhes_enfileirados=%d, total_coletado=%d",
            itens_listados_por_pagina, details_this_page, self.cnpj_details_collected
        )

    def _handle_pagination_stable(self, response: scrapy.http.Response) -> Generator[scrapy.Request, None, None]:
        """
        Paginação para rota estável: URLs sequenciais .../CNPJ/0, .../CNPJ/1, .../CNPJ/2, etc.
        Detecta links de paginação em .consulta_paginas a.
        """
        context = response.meta['context']
        current_page = context.get('page_idx', 0)
        cnpj = context.get('cnpj')

        # Verificar se existe próxima página
        pagination_links = response.css('.consulta_paginas a')
        has_next = False

        for link in pagination_links:
            link_text = (link.css('::text').get() or '').strip().lower()
            if 'próxima' in link_text or 'next' in link_text or 'seguinte' in link_text:
                has_next = True
                break

        # Se não encontrou links explícitos, tentar página seguinte mesmo assim
        # (a rota estável pode não ter links mas aceitar URLs sequenciais)
        if not has_next and current_page < 5:  # limite de segurança
            has_next = True

        if has_next and current_page + 1 < self.max_pages:
            next_page = current_page + 1
            next_url = f"https://cp.trf5.jus.br/processo/cpf/porData/ativos/{cnpj}/{next_page}"

            next_context = dict(context)
            next_context['page_idx'] = next_page

            self.logger.info(
                "[cnpj] Seguindo para página %d: %s",
                next_page, next_url
            )

            # Manter cabeçalhos
            headers = {
                'Referer': response.url,
                'User-Agent': self.settings.get('USER_AGENT', 'trf5_scraper (+http://www.yourdomain.com)')
            }

            yield scrapy.Request(
                url=next_url,
                callback=self.parse_result_list_stable,
                meta={'context': next_context},
                headers=headers,
                dont_filter=True
            )
