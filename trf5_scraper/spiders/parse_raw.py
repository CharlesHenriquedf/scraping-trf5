# -*- coding: utf-8 -*-

"""
Spider Parse Raw para reprocessamento offline de páginas salvas.

Lê páginas HTML armazenadas na coleção raw_pages do MongoDB e reprocessa
os dados estruturados, útil para ajustes nos extractors sem refazer requests.
"""

import scrapy
from typing import Dict, Any, Optional, Generator, List
from pymongo import MongoClient

from ..utils.normalize import (
    normalize_npu_hyphenated,
    parse_date_to_iso,
    clean_text,
    normalize_relator
)
from ..utils.classify import is_detail, is_list, is_error


class ParseRawSpider(scrapy.Spider):
    """
    Spider para reprocessamento offline de páginas HTML salvas.

    Útil para:
    - Testar novos extractors sem refazer requisições
    - Reprocessar dados após mudanças nos algoritmos
    - Auditoria e debugging de dados extraídos
    - Recuperação de dados após falhas no pipeline
    """

    name = "parse_raw"

    def __init__(self, limit=None, skip=None, tipo=None, busca=None, *args, **kwargs):
        """
        Inicializa spider para reprocessamento offline.

        Args:
            limit: Máximo de documentos a processar (padrão: 10)
            skip: Documentos a pular no início (padrão: 0)
            tipo: Filtro por tipo ('detalhe', 'lista', 'form')
            busca: Filtro por tipo de busca ('numero', 'cnpj')
        """
        super().__init__(*args, **kwargs)

        self.limit = int(limit) if limit else 10
        self.skip = int(skip) if skip else 0
        self.tipo_filter = tipo
        self.busca_filter = busca

        # Controles de estado
        self.processed_count = 0
        self.success_count = 0
        self.error_count = 0

        self.mongo = None  # Será definido pelo pipeline

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        """
        Lê páginas HTML do MongoDB e gera requests simulados para reprocessamento.
        """
        self.logger.info(
            "Iniciando reprocessamento offline (limit=%d, skip=%d, tipo=%s, busca=%s)",
            self.limit, self.skip, self.tipo_filter, self.busca_filter
        )

        # Obtém conexão MongoDB diretamente das configurações
        mongo_uri = self.settings.get("MONGO_URI", "mongodb://localhost:27017")
        mongo_db_name = self.settings.get("MONGO_DB", "trf5")

        try:
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            db = client[mongo_db_name]
            raw_pages = db["raw_pages"]

            # Constrói filtros baseados nos parâmetros
            query_filter = self._build_query_filter()

            self.logger.info("Consultando MongoDB com filtro: %s", query_filter)

            # Busca documentos com ordenação por data mais recente
            cursor = raw_pages.find(query_filter).sort("fetched_at", -1)

            if self.skip > 0:
                cursor = cursor.skip(self.skip)

            if self.limit > 0:
                cursor = cursor.limit(self.limit)

            total_found = raw_pages.count_documents(query_filter)
            self.logger.info("Encontrados %d documentos para reprocessamento", total_found)

            # Processa cada documento encontrado
            for doc in cursor:
                if self.processed_count >= self.limit:
                    break

                # Cria request simulado a partir do documento
                yield self._create_simulated_request(doc)
                self.processed_count += 1

            client.close()

        except Exception as e:
            self.logger.error("Erro ao conectar no MongoDB: %s", e)
            return

    def _build_query_filter(self) -> Dict[str, Any]:
        """
        Constrói filtro de consulta MongoDB baseado nos parâmetros.
        """
        query_filter = {}

        # Filtro por tipo de página
        if self.tipo_filter:
            query_filter["context.tipo"] = self.tipo_filter

        # Filtro por tipo de busca
        if self.busca_filter:
            query_filter["context.busca"] = self.busca_filter

        # Garante que há HTML para processar
        query_filter["html"] = {"$exists": True, "$ne": "", "$ne": None}

        return query_filter

    def _create_simulated_request(self, doc: Dict[str, Any]) -> scrapy.Request:
        """
        Cria request simulado a partir do documento MongoDB.
        """
        # Extrai dados básicos do documento
        url = doc.get('url', 'http://simulated-request/')
        html = doc.get('html', '')
        context = doc.get('context', {})

        # Classifica automaticamente o tipo se não especificado no context
        if not context.get('tipo'):
            context['tipo'] = self._auto_classify_page(html)

        # Enriquece context com metadados do documento
        context['reprocessed'] = True
        context['original_fetch_time'] = doc.get('fetched_at')
        context['document_id'] = str(doc.get('_id'))

        # Determina callback baseado no tipo de página
        callback = self._get_callback_for_type(context.get('tipo'))

        # Cria request com HTML simulado
        request = scrapy.Request(
            url=url,
            callback=callback,
            meta={'context': context},
            dont_filter=True
        )

        # Anexa HTML diretamente ao request para simulação
        request.meta['simulated_html'] = html
        request.meta['original_status'] = doc.get('status')

        return request

    def _auto_classify_page(self, html: str) -> str:
        """
        Classifica automaticamente o tipo de página baseado no HTML.
        """
        if is_detail(html):
            return 'detalhe'
        elif is_list(html):
            return 'lista'
        elif is_error(html):
            return 'erro'
        else:
            return 'unknown'

    def _get_callback_for_type(self, page_type: str) -> callable:
        """
        Retorna callback apropriado baseado no tipo de página.
        """
        if page_type == 'detalhe':
            return self.parse_detail_offline
        elif page_type == 'lista':
            return self.parse_list_offline
        else:
            return self.parse_generic_offline

    def parse_detail_offline(self, response: scrapy.http.Response) -> Optional[Dict[str, Any]]:
        """
        Reprocessa página de detalhe salva.
        """
        context = response.meta['context']
        html = response.meta.get('simulated_html', response.text)

        self.logger.info(
            "Reprocessando detalhe offline (doc_id=%s, url=%s)",
            context.get('document_id'), response.url
        )

        try:
            # Cria response simulado com HTML salvo
            simulated_response = self._create_simulated_response(response, html)

            # Extrai dados estruturados
            item = self._extract_processo_data_offline(simulated_response, context)

            if item and self.mongo:
                # Persiste dados reprocessados
                result = self.mongo.upsert_processo(item)
                self.success_count += 1

                self.logger.info(
                    "Processo reprocessado com sucesso: %s (doc_id=%s)",
                    item.get('numero_processo'), context.get('document_id')
                )

                return result
            else:
                self.error_count += 1
                self.logger.warning(
                    "Falha ao extrair dados do processo (doc_id=%s)",
                    context.get('document_id')
                )

        except Exception as e:
            self.error_count += 1
            self.logger.error(
                "Erro no reprocessamento (doc_id=%s): %s",
                context.get('document_id'), e
            )

        return None

    def parse_list_offline(self, response: scrapy.http.Response) -> None:
        """
        Reprocessa página de lista salva.
        """
        context = response.meta['context']

        self.logger.info(
            "Reprocessando lista offline (doc_id=%s, url=%s)",
            context.get('document_id'), response.url
        )

        # Para listas, apenas registra a reprocessamento
        # Links não são seguidos em modo offline
        self.success_count += 1

    def parse_generic_offline(self, response: scrapy.http.Response) -> None:
        """
        Reprocessa página genérica salva.
        """
        context = response.meta['context']

        self.logger.info(
            "Reprocessando página genérica offline (doc_id=%s, tipo=%s, url=%s)",
            context.get('document_id'), context.get('tipo'), response.url
        )

        self.success_count += 1

    def _create_simulated_response(self, original_response: scrapy.http.Response, html: str) -> scrapy.http.Response:
        """
        Cria response simulado com HTML salvo para extração.
        """
        # Usa classe interna do Scrapy para simular response
        from scrapy.http import HtmlResponse

        return HtmlResponse(
            url=original_response.url,
            body=html.encode('utf-8'),
            encoding='utf-8',
            request=original_response.request
        )

    def _extract_processo_data_offline(self, response: scrapy.http.Response, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extrai dados estruturados em modo offline.
        Reutiliza lógica do spider principal com adaptações.
        """
        try:
            # Inicializa estrutura de dados
            item = {
                'fonte_url': response.url,
                'reprocessed_at': context.get('original_fetch_time'),
                'reprocessed_from_doc': context.get('document_id')
            }

            # Extrai número do processo
            numero_processo = self._extract_numero_processo_offline(response)
            if not numero_processo:
                self.logger.warning("Número do processo não encontrado no reprocessamento")
                return None

            # Usa NPU como _id para idempotência
            item['_id'] = normalize_npu_hyphenated(numero_processo)
            item['numero_processo'] = item['_id']

            # Extrai campos adicionais
            item['numero_legado'] = self._extract_numero_legado_offline(response)

            # Se numero_processo está vazio, usa numero_legado
            if not item['numero_processo'] and item['numero_legado']:
                item['numero_processo'] = item['numero_legado']

            # Extrai demais campos
            item['data_autuacao'] = self._extract_data_autuacao_offline(response)
            item['relator'] = self._extract_relator_offline(response)
            item['envolvidos'] = self._extract_envolvidos_offline(response)
            item['movimentacoes'] = self._extract_movimentacoes_offline(response)

            return item

        except Exception as e:
            self.logger.error("Erro ao extrair dados no reprocessamento: %s", e)
            return None

    def _extract_numero_processo_offline(self, response: scrapy.http.Response) -> Optional[str]:
        """
        Extrai número do processo em modo offline.
        """
        import re

        text = response.text

        # Padrão NPU completo
        npu_pattern = r'(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})'
        match = re.search(npu_pattern, text)
        if match:
            return normalize_npu_hyphenated(match.group(1))

        # Busca em elementos específicos
        selectors = [
            '//text()[contains(., "PROCESSO") and contains(., "Nº")]',
            '//text()[contains(., "Processo:")]'
        ]

        for selector in selectors:
            elements = response.xpath(selector)
            for element in elements:
                text_content = element.get().strip()
                match = re.search(npu_pattern, text_content)
                if match:
                    return normalize_npu_hyphenated(match.group(1))

        return None

    def _extract_numero_legado_offline(self, response: scrapy.http.Response) -> Optional[str]:
        """
        Extrai número legado em modo offline.
        """
        # Implementação específica para estrutura real do TRF5
        return None

    def _extract_data_autuacao_offline(self, response: scrapy.http.Response) -> Optional[str]:
        """
        Extrai data de autuação em modo offline.
        """
        import re

        selectors = [
            '//text()[contains(., "Autuação") or contains(., "Data:")]'
        ]

        for selector in selectors:
            elements = response.xpath(selector)
            for element in elements:
                text_content = element.get().strip()
                date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', text_content)
                if date_match:
                    return parse_date_to_iso(date_match.group(1))

        return None

    def _extract_relator_offline(self, response: scrapy.http.Response) -> Optional[str]:
        """
        Extrai relator em modo offline.
        """
        import re

        selectors = [
            '//text()[contains(., "RELATOR")]'
        ]

        for selector in selectors:
            elements = response.xpath(selector)
            for element in elements:
                text_content = clean_text(element.get())
                if 'relator' in text_content.lower():
                    match = re.search(r'relator:?\s*(.+)', text_content, re.IGNORECASE)
                    if match:
                        return normalize_relator(match.group(1))

        return None

    def _extract_envolvidos_offline(self, response: scrapy.http.Response) -> List[Dict[str, str]]:
        """
        Extrai envolvidos em modo offline.
        """
        envolvidos = []

        tables = response.css('table')
        for table in tables:
            rows = table.css('tr')
            for row in rows:
                cells = row.css('td')
                if len(cells) >= 2:
                    papel = clean_text(cells[0].css('::text').get() or '')
                    nome = clean_text(cells[1].css('::text').get() or '')

                    if papel and nome:
                        envolvidos.append({
                            'papel': papel,
                            'nome': nome
                        })

        return envolvidos

    def _extract_movimentacoes_offline(self, response: scrapy.http.Response) -> List[Dict[str, str]]:
        """
        Extrai movimentações em modo offline.
        """
        movimentacoes = []

        movs_section = response.css('.movimentacoes, .andamentos, .timeline')

        for section in movs_section:
            items = section.css('.movimento, .andamento, .item')
            for item in items:
                data_text = item.css('.data::text, .timestamp::text').get()
                texto = clean_text(item.css('.texto::text, .descricao::text').get() or '')

                if data_text and texto:
                    data_iso = parse_date_to_iso(data_text.strip())
                    if data_iso:
                        movimentacoes.append({
                            'data': data_iso,
                            'texto': texto
                        })

        return movimentacoes

    def closed(self, reason):
        """
        Relatório final do reprocessamento.
        """
        self.logger.info(
            "Reprocessamento concluído: %d processados, %d sucessos, %d erros (motivo: %s)",
            self.processed_count, self.success_count, self.error_count, reason
        )