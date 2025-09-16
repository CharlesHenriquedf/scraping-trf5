# trf5_scraper/pipelines/mongo_pipeline.py
from __future__ import annotations
import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional, Union

# importe IndexModel e OperationFailure
from pymongo import MongoClient, ASCENDING, DESCENDING, IndexModel
from pymongo.errors import OperationFailure
from scrapy.http import Response


def _iso_now() -> str:
    """Gera timestamp ISO-8601 sem microssegundos para logs e persistencia."""
    return datetime.now().replace(microsecond=0).isoformat()


def _sha256(text: str) -> str:
    """Calcula hash SHA-256 do texto para integridade dos dados HTML."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


class MongoPipeline:
    """
    Pipeline do Scrapy para persistência no MongoDB.

    Responsável por salvar HTML bruto em raw_pages e dados estruturados
    em processos conforme especificação do PRD. Implementa idempotência
    através de upserts e mantém auditoria completa.
    """

    def __init__(self, mongo_uri: str, mongo_db: str) -> None:
        self.mongo_uri = mongo_uri
        self.mongo_db_name = mongo_db
        self.client: Optional[MongoClient] = None
        self.db = None
        self.raw_pages = None
        self.processos = None
        self.logger = None

    @classmethod
    def from_crawler(cls, crawler):
        """Factory method para receber configurações do Scrapy."""
        mongo_uri = crawler.settings.get("MONGO_URI", "mongodb://localhost:27017")
        mongo_db = crawler.settings.get("MONGO_DB", "trf5")
        pipe = cls(mongo_uri, mongo_db)
        return pipe

    def open_spider(self, spider) -> None:
        """Conecta ao MongoDB e prepara coleções e índices."""
        self.client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
        self.db = self.client[self.mongo_db_name]
        self.raw_pages = self.db["raw_pages"]
        self.processos = self.db["processos"]

        raw_idx = [
            IndexModel(
                [("context.tipo", ASCENDING), ("fetched_at", DESCENDING)],
                name="idx_tipo_fetched"
            ),
            IndexModel(
                [("url", ASCENDING), ("method", ASCENDING)],
                name="idx_url_method"
            ),
        ]
        proc_idx = [
            IndexModel(
                [("relator", ASCENDING), ("data_autuacao", DESCENDING)],
                name="idx_relator_autuacao"
            )
        ]

        try:
            self.raw_pages.create_indexes(raw_idx)
        except OperationFailure as e:
            if getattr(e, "code", None) != 85:
                raise

        try:
            self.processos.create_indexes(proc_idx)
        except OperationFailure as e:
            if getattr(e, "code", None) != 85:
                raise

        self.logger = getattr(spider, "logger", None)
        # Disponibiliza a pipeline para o spider chamar diretamente
        setattr(spider, "mongo", self)

        if self.logger:
            self.logger.info("[mongo] conectado em %s/%s", self.mongo_uri, self.mongo_db_name)

    def close_spider(self, spider) -> None:
        """Fecha conexão com MongoDB ao finalizar spider."""
        if self.client:
            self.client.close()
            if self.logger:
                self.logger.info("[mongo] conexão encerrada")

    # RAW PAGES
    def save_raw_page(self, response_or_html: Union[Response, str], context: Dict[str, Any]) -> None:
        """
        Salva HTML bruto com metadados e 'context' padronizado pelo PRD.

        Aceita Response do Scrapy ou string HTML diretamente. Extrai metadados
        da requisição quando disponível e calcula hash SHA-256 para integridade.
        """
        url = method = status = None
        headers: Optional[Dict[str, Any]] = None

        if isinstance(response_or_html, Response):
            url = response_or_html.url
            status = getattr(response_or_html, "status", None)
            method = getattr(getattr(response_or_html, "request", None), "method", None)
            try:
                headers = {k.decode("latin-1"): v[0].decode("latin-1") for k, v in response_or_html.headers.items()}
            except Exception:
                headers = None
            html = response_or_html.text
        else:
            html = str(response_or_html)

        # Filtra campos None do contexto para evitar problemas de validação
        context_data = {}
        for key in ["tipo", "busca", "numero", "cnpj", "page_idx", "endpoint"]:
            value = context.get(key)
            if value is not None:
                context_data[key] = value

        doc = {
            "url": url,
            "method": method,
            "status": status,
            "headers": headers,
            "html": html,
            "payload": None,
            "context": context_data,
            "fetched_at": _iso_now(),
            "hash_html": _sha256(html),
        }
        self.raw_pages.insert_one(doc)
        if self.logger:
            ident = context.get("numero") or context.get("cnpj") or "-"
            self.logger.info("[raw] saved %s (%s) %s", context.get("tipo"), ident, url)

    # PROCESSOS
    def upsert_processo(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executa upsert idempotente em processos.

        Espera item com os campos exigidos pelo PRD e:
        - _id = NPU *com hífens* (idempotência/auditabilidade)
        - numero_processo, numero_legado, data_autuacao (ISO), relator,
          envolvidos[], movimentacoes[], fonte_url, scraped_at
        """
        if "_id" not in item:
            raise ValueError("item sem _id (NPU normalizado com hífens)")

        item = dict(item)  # cópia defensiva
        item.setdefault("scraped_at", _iso_now())

        res = self.processos.update_one({"_id": item["_id"]}, {"$set": item}, upsert=True)

        action = "insert" if res.matched_count == 0 else "update"
        if self.logger:
            self.logger.info("[processos] %s _id=%s relator=%s", action, item["_id"], item.get("relator"))
        return item

    # SCRAPY INTERFACE
    def process_item(self, item, spider):
        """
        Mantém interface Scrapy mas não transforma itens aqui.

        Os spiders chamam explicitamente save_raw_page() e upsert_processo()
        para garantir que TODO HTML seja salvo conforme exigido pelo PRD,
        incluindo páginas de lista e erro que não geram itens estruturados.
        """
        return item
