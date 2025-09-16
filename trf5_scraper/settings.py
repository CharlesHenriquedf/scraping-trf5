# -*- coding: utf-8 -*-

"""
Configurações do Scrapy para o projeto TRF5 Scraper.

Este arquivo contém todas as configurações necessárias para garantir
operação respeitosa e confiável do raspador, incluindo políticas de
cortesia, integração com MongoDB e configurações de encoding.
"""

import os

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

# Política de retry para lidar com falhas temporárias de rede
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

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