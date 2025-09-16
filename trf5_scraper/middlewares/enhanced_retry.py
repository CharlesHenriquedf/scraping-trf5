# -*- coding: utf-8 -*-

"""
Enhanced Retry Middleware para TRF5 Scraper

Middleware avançado de retry com:
- Retry exponential backoff
- Retry baseado em conteúdo (além de status codes)
- Diferentes estratégias por tipo de request
- Monitoramento de padrões de falha
- Integração com sistema de logs
"""

import random
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Union, Dict, Any
from urllib.parse import urlparse

from scrapy import signals
from scrapy.http import Request, Response
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.exceptions import NotConfigured, IgnoreRequest
from scrapy.utils.response import response_status_message
from scrapy.spiders import Spider


class EnhancedRetryMiddleware(RetryMiddleware):
    """
    Middleware de retry aprimorado com estratégias inteligentes.

    Funcionalidades:
    - Exponential backoff com jitter
    - Retry baseado em conteúdo HTML
    - Diferentes configurações por tipo de endpoint
    - Rate limiting adaptativo
    - Monitoramento de health do servidor
    """

    def __init__(self, settings):
        """Inicializa middleware com configurações avançadas."""
        # Configurações básicas herdadas
        super().__init__(settings)

        # Configurações avançadas
        self.max_retry_times = settings.getint('ENHANCED_RETRY_TIMES', 5)
        self.retry_http_codes = set(int(x) for x in settings.getlist('RETRY_HTTP_CODES'))

        # Exponential backoff settings
        self.initial_delay = settings.getfloat('RETRY_INITIAL_DELAY', 1.0)
        self.max_delay = settings.getfloat('RETRY_MAX_DELAY', 60.0)
        self.backoff_multiplier = settings.getfloat('RETRY_BACKOFF_MULTIPLIER', 2.0)
        self.jitter_enabled = settings.getbool('RETRY_JITTER_ENABLED', True)

        # Content-based retry patterns
        self.retry_content_patterns = settings.getlist('RETRY_CONTENT_PATTERNS', [
            'erro interno do servidor',
            'sistema temporariamente indisponível',
            'manutenção programada',
            'service unavailable',
            'gateway timeout',
            'connection timed out',
            'erro 5',  # Páginas de erro do TRF5
        ])

        # Diferentes configurações por endpoint
        self.endpoint_configs = {
            'form': {
                'max_retries': settings.getint('RETRY_FORM_MAX', 3),
                'delay_multiplier': 1.5,
                'timeout_multiplier': 1.2
            },
            'detail': {
                'max_retries': settings.getint('RETRY_DETAIL_MAX', 4),
                'delay_multiplier': 1.0,
                'timeout_multiplier': 1.0
            },
            'list': {
                'max_retries': settings.getint('RETRY_LIST_MAX', 5),
                'delay_multiplier': 2.0,
                'timeout_multiplier': 1.5
            },
            'stable_route': {
                'max_retries': settings.getint('RETRY_STABLE_MAX', 6),
                'delay_multiplier': 0.8,
                'timeout_multiplier': 0.9
            }
        }

        # Monitoramento de saúde do servidor
        self.server_health = {
            'consecutive_failures': 0,
            'last_success': datetime.now(),
            'failure_rate_window': [],
            'is_degraded': False
        }

        # Configurações de rate limiting adaptativo
        self.adaptive_delay_enabled = settings.getbool('RETRY_ADAPTIVE_DELAY', True)
        self.server_health_window = settings.getint('RETRY_HEALTH_WINDOW', 100)

        # Logging
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_crawler(cls, crawler):
        """Factory method para criar middleware a partir do crawler."""
        if not crawler.settings.getbool('ENHANCED_RETRY_ENABLED', True):
            raise NotConfigured('Enhanced retry middleware is disabled')

        middleware = cls(crawler.settings)
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        return middleware

    def spider_opened(self, spider):
        """Callback quando spider é aberto."""
        self.logger.info(
            "Enhanced retry middleware ativado (max_retries=%d, patterns=%d)",
            self.max_retry_times, len(self.retry_content_patterns)
        )

    def process_response(self, request: Request, response: Response, spider: Spider) -> Union[Request, Response]:
        """Processa response e decide se deve fazer retry."""

        # Atualizar monitoramento de saúde do servidor
        self._update_server_health(response)

        # Verificar se precisa de retry baseado em status code
        if response.status in self.retry_http_codes:
            reason = response_status_message(response.status)
            return self._retry_request(request, reason, spider) or response

        # Verificar se precisa de retry baseado em conteúdo
        if self._should_retry_based_on_content(response):
            reason = "Conteúdo indica erro do servidor"
            return self._retry_request(request, reason, spider) or response

        # Verificar se servidor está degradado e ajustar comportamento
        if self.server_health['is_degraded']:
            self._apply_degraded_mode_adjustments(request, spider)

        return response

    def process_exception(self, request: Request, exception: Exception, spider: Spider) -> Optional[Request]:
        """Processa exceções e decide se deve fazer retry."""

        # Atualizar contador de falhas
        self.server_health['consecutive_failures'] += 1
        self._update_server_health_from_exception(exception)

        # Determinar se deve fazer retry baseado no tipo de exceção
        if self._should_retry_exception(exception):
            reason = f"{exception.__class__.__name__}: {str(exception)}"
            return self._retry_request(request, reason, spider)

        return None

    def _should_retry_based_on_content(self, response: Response) -> bool:
        """Verifica se deve fazer retry baseado no conteúdo da resposta."""

        # Verificar status 200 mas com conteúdo de erro
        if response.status == 200:
            text = response.text.lower()

            # Verificar padrões de erro no conteúdo
            for pattern in self.retry_content_patterns:
                if pattern.lower() in text:
                    self.logger.warning(
                        "Conteúdo de erro detectado (pattern: %s) em %s",
                        pattern, response.url
                    )
                    return True

            # Verificar se resposta está muito pequena (possível erro)
            if len(text.strip()) < 100:
                self.logger.warning(
                    "Resposta muito pequena (%d chars) em %s - possível erro",
                    len(text), response.url
                )
                return True

            # Verificar se contém apenas tags HTML básicas (resposta vazia)
            import re
            clean_text = re.sub(r'<[^>]+>', '', text).strip()
            if len(clean_text) < 50:
                self.logger.warning(
                    "Resposta praticamente vazia em %s - possível erro",
                    response.url
                )
                return True

        return False

    def _should_retry_exception(self, exception: Exception) -> bool:
        """Determina se deve fazer retry baseado no tipo de exceção."""

        # Lista de exceções que justificam retry
        retryable_exceptions = [
            'TimeoutError',
            'ConnectionError',
            'ConnectTimeout',
            'ReadTimeout',
            'DNSLookupError',
            'TunnelError',
            'TCPTimedOutError'
        ]

        exception_name = exception.__class__.__name__
        return exception_name in retryable_exceptions

    def _retry_request(self, request: Request, reason: str, spider: Spider) -> Optional[Request]:
        """Executa retry de request com estratégia inteligente."""

        # Obter número de retries já feitos
        retries = request.meta.get('retry_times', 0) + 1

        # Determinar configuração baseada no endpoint
        endpoint_type = request.meta.get('context', {}).get('endpoint', 'default')
        config = self.endpoint_configs.get(endpoint_type, {})
        max_retries = config.get('max_retries', self.max_retry_times)

        # Verificar se excedeu limite de retries
        if retries > max_retries:
            self.logger.error(
                "Máximo de retries excedido (%d) para %s: %s",
                max_retries, request.url, reason
            )
            return None

        # Calcular delay com exponential backoff e jitter
        delay = self._calculate_retry_delay(retries, config)

        # Aplicar delay se configurado
        if delay > 0:
            self.logger.info(
                "Retry %d/%d para %s em %.1fs (motivo: %s)",
                retries, max_retries, request.url, delay, reason
            )
            time.sleep(delay)
        else:
            self.logger.info(
                "Retry %d/%d para %s (motivo: %s)",
                retries, max_retries, request.url, reason
            )

        # Criar novo request com configurações ajustadas
        retry_request = request.copy()
        retry_request.meta['retry_times'] = retries
        retry_request.meta['retry_reason'] = reason
        retry_request.dont_filter = True

        # Ajustar timeout se servidor estiver degradado
        if self.server_health['is_degraded']:
            current_timeout = retry_request.meta.get('download_timeout', 30)
            timeout_multiplier = config.get('timeout_multiplier', 1.0)
            new_timeout = min(current_timeout * timeout_multiplier, 120)  # Max 2 min
            retry_request.meta['download_timeout'] = new_timeout

            self.logger.info("Timeout ajustado para %.1fs devido degradação do servidor", new_timeout)

        return retry_request

    def _calculate_retry_delay(self, retry_count: int, config: Dict[str, Any]) -> float:
        """Calcula delay para retry com exponential backoff e jitter."""

        # Multiplicador específico do endpoint
        delay_multiplier = config.get('delay_multiplier', 1.0)

        # Exponential backoff
        delay = self.initial_delay * (self.backoff_multiplier ** (retry_count - 1))
        delay *= delay_multiplier

        # Aplicar limite máximo
        delay = min(delay, self.max_delay)

        # Adicionar jitter para evitar thundering herd
        if self.jitter_enabled:
            jitter = random.uniform(0.5, 1.5)
            delay *= jitter

        # Delay adicional se servidor estiver degradado
        if self.server_health['is_degraded']:
            delay *= 2.0  # Dobrar delay em modo degradado
            self.logger.debug("Delay aumentado devido degradação do servidor")

        return delay

    def _update_server_health(self, response: Response) -> None:
        """Atualiza monitoramento de saúde do servidor baseado na resposta."""

        now = datetime.now()

        # Classificar resposta
        is_success = (200 <= response.status < 400 and
                     not self._should_retry_based_on_content(response))

        if is_success:
            self.server_health['consecutive_failures'] = 0
            self.server_health['last_success'] = now
        else:
            self.server_health['consecutive_failures'] += 1

        # Atualizar janela de taxa de falha
        self.server_health['failure_rate_window'].append({
            'timestamp': now,
            'is_failure': not is_success
        })

        # Manter apenas últimas N entradas
        window = self.server_health['failure_rate_window']
        if len(window) > self.server_health_window:
            self.server_health['failure_rate_window'] = window[-self.server_health_window:]

        # Determinar se servidor está degradado
        self._assess_server_degradation()

    def _update_server_health_from_exception(self, exception: Exception) -> None:
        """Atualiza saúde do servidor baseado em exceção."""

        now = datetime.now()

        self.server_health['failure_rate_window'].append({
            'timestamp': now,
            'is_failure': True
        })

        # Manter janela de tamanho fixo
        window = self.server_health['failure_rate_window']
        if len(window) > self.server_health_window:
            self.server_health['failure_rate_window'] = window[-self.server_health_window:]

        self._assess_server_degradation()

    def _assess_server_degradation(self) -> None:
        """Avalia se servidor está em estado degradado."""

        window = self.server_health['failure_rate_window']

        if len(window) < 10:  # Precisa de dados mínimos
            return

        # Calcular taxa de falha dos últimos eventos
        recent_failures = sum(1 for event in window[-20:] if event['is_failure'])
        failure_rate = recent_failures / min(20, len(window))

        # Verificar degradação baseado em múltiplos critérios
        consecutive_failures = self.server_health['consecutive_failures']
        time_since_success = datetime.now() - self.server_health['last_success']

        was_degraded = self.server_health['is_degraded']

        # Critérios para degradação
        high_failure_rate = failure_rate > 0.5  # 50% falhas
        many_consecutive_failures = consecutive_failures > 5
        long_time_without_success = time_since_success > timedelta(minutes=5)

        is_degraded = (high_failure_rate or many_consecutive_failures or
                      long_time_without_success)

        self.server_health['is_degraded'] = is_degraded

        # Log mudanças de estado
        if is_degraded and not was_degraded:
            self.logger.warning(
                "Servidor TRF5 detectado como DEGRADADO "
                "(taxa_falha=%.1f%%, falhas_consecutivas=%d, tempo_sem_sucesso=%s)",
                failure_rate * 100, consecutive_failures,
                str(time_since_success).split('.')[0]
            )
        elif not is_degraded and was_degraded:
            self.logger.info("Servidor TRF5 RECUPERADO - operação normal")

    def _apply_degraded_mode_adjustments(self, request: Request, spider: Spider) -> None:
        """Aplica ajustes quando servidor está em modo degradado."""

        # Aumentar delay entre requests
        if hasattr(spider, 'download_delay'):
            original_delay = getattr(spider, '_original_download_delay', spider.download_delay)
            if not hasattr(spider, '_original_download_delay'):
                spider._original_download_delay = original_delay

            spider.download_delay = original_delay * 2.0

        # Log periodicamente sobre estado degradado
        if random.random() < 0.1:  # 10% das vezes
            self.logger.warning(
                "Operando em MODO DEGRADADO - delays aumentados, timeouts estendidos"
            )

    def get_server_health_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de saúde do servidor para monitoramento."""

        window = self.server_health['failure_rate_window']

        if not window:
            return {'status': 'unknown', 'sample_size': 0}

        # Calcular estatísticas
        recent_failures = sum(1 for event in window[-20:] if event['is_failure'])
        total_requests = min(20, len(window))
        failure_rate = recent_failures / total_requests if total_requests > 0 else 0

        return {
            'status': 'degraded' if self.server_health['is_degraded'] else 'healthy',
            'failure_rate': failure_rate,
            'consecutive_failures': self.server_health['consecutive_failures'],
            'last_success': self.server_health['last_success'].isoformat(),
            'sample_size': len(window),
            'recent_failures': recent_failures,
            'total_requests': total_requests
        }