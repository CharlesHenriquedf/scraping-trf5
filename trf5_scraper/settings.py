# -*- coding: utf-8 -*-

"""
Configurações do Scrapy para o projeto TRF5 Scraper.

Este arquivo contém todas as configurações necessárias para garantir
operação respeitosa e confiável do raspador, incluindo políticas de
cortesia, integração com MongoDB e configurações de encoding.
"""

import os
from pathlib import Path

# Carregamento automático de variáveis de ambiente do arquivo .env
try:
    from dotenv import load_dotenv
    # Procura o arquivo .env na raiz do projeto
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[INFO] Variáveis carregadas de: {env_path}")
    else:
        print(f"[WARNING] Arquivo .env não encontrado em: {env_path}")
except ImportError:
    print("[WARNING] python-dotenv não encontrado. Instale com: pip install python-dotenv")

# Informações básicas do projeto
BOT_NAME = 'trf5_scraper'

SPIDER_MODULES = ['trf5_scraper.spiders']
NEWSPIDER_MODULE = 'trf5_scraper.spiders'

# === REQUISITOS NÃO FUNCIONAIS (RNF) ===

# RNF-01: Respeitar robots.txt conforme exigido pelo PRD
# Garante conformidade com as diretrizes do site e evita bloqueios
ROBOTSTXT_OBEY = True

# RNF-02: Controle de velocidade para preservar infraestrutura do TRF5
# Delay mínimo entre requisições para evitar sobrecarga do servidor
DOWNLOAD_DELAY = 0.7

# RNF-03: Ajuste automático de velocidade baseado na resposta do servidor
# Sistema inteligente que adapta a velocidade conforme latência detectada
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
AUTOTHROTTLE_DEBUG = False

# RNF-04: Controle de concorrência
# Máximo de requisições simultâneas para evitar sobrecarga do servidor
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1

# RNF-05: Timeouts para evitar travamento em requisições lentas
DOWNLOAD_TIMEOUT = 30

# === CONFIGURAÇÃO DE PIPELINES ===

# Pipeline para persistência no MongoDB
# Processa os itens coletados e armazena tanto HTML bruto quanto dados estruturados
ITEM_PIPELINES = {
    'trf5_scraper.pipelines.mongo_pipeline.MongoPipeline': 300,
}

# === CONFIGURAÇÃO DO MONGODB ===

# Conexão com MongoDB via variáveis de ambiente
# Permite configuração flexível sem hardcode de credenciais
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
MONGO_DB = os.getenv('MONGO_DB', 'trf5')

# === CONFIGURAÇÃO DE ENCODING ===

# RNF-06: Garantir encoding UTF-8 para preservar acentuação
# Essencial para dados jurídicos em português
FEED_EXPORT_ENCODING = 'utf-8'

# === CONFIGURAÇÃO DE USER-AGENT ===

# User-Agent personalizado para identificação clara nas requisições
USER_AGENT = 'trf5_scraper (+http://www.yourdomain.com)'

# === CONFIGURAÇÃO DE LOG ===

# Configuração padrão de logs para facilitar debugging em desenvolvimento
LOG_LEVEL = 'INFO'

# === CONFIGURAÇÕES DE CACHE E DUPLICADOS ===

# Filtro de requisições duplicadas habilitado por padrão
# Evita reprocessamento desnecessário de URLs já visitadas
DUPEFILTER_DEBUG = False

# === CONFIGURAÇÕES DE RETRY ===

# Política básica de retry (mantida para compatibilidade)
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# === CONFIGURAÇÕES DE RETRY AVANÇADO ===

# Enhanced retry middleware habilitado
ENHANCED_RETRY_ENABLED = True
ENHANCED_RETRY_TIMES = 5

# Exponential backoff configurações
RETRY_INITIAL_DELAY = 1.0
RETRY_MAX_DELAY = 60.0
RETRY_BACKOFF_MULTIPLIER = 2.0
RETRY_JITTER_ENABLED = True

# Retry baseado em conteúdo (detecta erros em páginas 200 OK)
RETRY_CONTENT_PATTERNS = [
    'erro interno do servidor',
    'sistema temporariamente indisponível',
    'manutenção programada',
    'service unavailable',
    'gateway timeout',
    'connection timed out',
    'erro 5',
    'página não encontrada',
    'acesso negado'
]

# Configurações específicas por tipo de endpoint
RETRY_FORM_MAX = 3
RETRY_DETAIL_MAX = 4
RETRY_LIST_MAX = 5
RETRY_STABLE_MAX = 6

# Rate limiting adaptativo
RETRY_ADAPTIVE_DELAY = True
RETRY_HEALTH_WINDOW = 100

# === CONFIGURAÇÃO DE MIDDLEWARES ===

# Middlewares de download customizados
DOWNLOADER_MIDDLEWARES = {
    # Enhanced retry middleware (substitui o padrão)
    'scrapy.downloadermiddlewares.retry.RetryMiddleware': None,  # Desabilita padrão
    'trf5_scraper.middlewares.enhanced_retry.EnhancedRetryMiddleware': 550,

    # Outros middlewares mantidos na ordem padrão
    'scrapy.downloadermiddlewares.httpauth.HttpAuthMiddleware': 300,
    'scrapy.downloadermiddlewares.downloadtimeout.DownloadTimeoutMiddleware': 350,
    'scrapy.downloadermiddlewares.defaultheaders.DefaultHeadersMiddleware': 400,
    'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': 500,
    'scrapy.downloadermiddlewares.redirect.MetaRefreshMiddleware': 580,
    'scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware': 590,
    'scrapy.downloadermiddlewares.redirect.RedirectMiddleware': 600,
    'scrapy.downloadermiddlewares.cookies.CookiesMiddleware': 700,
    'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware': 750,
    'scrapy.downloadermiddlewares.stats.DownloaderStats': 850,
}

# === CONFIGURAÇÕES DE COOKIES ===

# Habilitado para manter sessão durante navegação por formulários
COOKIES_ENABLED = True
COOKIES_DEBUG = False

# === CONFIGURAÇÕES DE SEGURANÇA ===

# Redirecionamentos habilitados para seguir mudanças de URL
REDIRECT_ENABLED = True
REDIRECT_MAX_TIMES = 5

# === EXTENSÕES DESABILITADAS PARA PERFORMANCE ===

# Telemetria e estatísticas desnecessárias para este projeto
TELNETCONSOLE_ENABLED = False