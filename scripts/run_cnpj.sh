#!/bin/bash

# =============================================================================
# TRF5 Scraper - Execução de Descoberta por CNPJ
# =============================================================================
# Este script executa a descoberta de processos por CNPJ do Banco do Brasil
# com limites seguros para evitar sobrecarga do sistema TRF5

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configurações
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

# CNPJ do Banco do Brasil (conforme arquivo de teste)
CNPJ_BB="00.000.000/0001-91"

# Configurações padrão (podem ser alteradas via parâmetros)
MAX_PAGES=${1:-2}
MAX_DETAILS_PER_PAGE=${2:-5}
LOG_LEVEL=${3:-INFO}

# Arquivo de log da execução
LOG_FILE="$LOG_DIR/cnpj_discovery_${TIMESTAMP}.log"

# Função para logging
log() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}${NC} $1"
}

error() {
    echo -e "${RED}${NC} $1"
}

warning() {
    echo -e "${YELLOW} ${NC} $1"
}

# Função para verificar MongoDB
check_mongodb() {
    log "Verificando conectividade MongoDB..."

    if command -v mongosh &> /dev/null; then
        MONGO_CMD="mongosh"
    elif command -v mongo &> /dev/null; then
        MONGO_CMD="mongo"
    else
        error "MongoDB client não encontrado (mongosh ou mongo)"
        return 1
    fi

    # Testar conexão
    if timeout 10 "$MONGO_CMD" \
        "${MONGO_URI:-mongodb://localhost:27017}" \
        --quiet \
        --eval "db.runCommand('ping')" &>/dev/null; then
        success "MongoDB conectado"
        return 0
    else
        error "MongoDB não acessível em ${MONGO_URI:-mongodb://localhost:27017}"
        return 1
    fi
}

# Função para verificar pré-requisitos
check_prerequisites() {
    log "Verificando pré-requisitos..."

    # Verificar se estamos no diretório correto
    if [ ! -f "scrapy.cfg" ] || [ ! -d "trf5_scraper" ]; then
        error "Execute este script do diretório raiz do projeto TRF5 Scraper"
        exit 1
    fi

    # Verificar Scrapy
    if ! command -v scrapy &> /dev/null; then
        error "Scrapy não encontrado. Ative o ambiente virtual:"
        echo "  source .venv/bin/activate"
        exit 1
    fi

    # Verificar spiders
    if ! scrapy list | grep -q "trf5"; then
        error "Spider 'trf5' não encontrado"
        exit 1
    fi

    # Verificar conectividade TRF5
    log "Testando conectividade com TRF5..."
    if curl -s --head --max-time 10 http://www5.trf5.jus.br/cp/ | head -1 | grep -q "200\|302\|301"; then
        success "TRF5 acessível"
    else
        error "TRF5 não acessível. Verifique sua conexão com a internet"
        exit 1
    fi

    # Verificar MongoDB
    if ! check_mongodb; then
        warning "MongoDB não conectado. Para usar Docker:"
        echo "  cd docker && docker compose up -d"
        exit 1
    fi

    success "Todos os pré-requisitos verificados"
}

# Função para executar descoberta CNPJ
execute_cnpj_discovery() {
    log "Executando descoberta por CNPJ..."
    log "CNPJ: $CNPJ_BB"
    log "Máximo de páginas: $MAX_PAGES"
    log "Máximo de detalhes por página: $MAX_DETAILS_PER_PAGE"
    log "Arquivo de log: $LOG_FILE"

    # Garantir que está no diretório correto
    cd "$PROJECT_DIR"

    # Ativar ambiente virtual se existir
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi

    # Executar scrapy
    log "Iniciando execução do scrapy..."

    if scrapy crawl trf5 \
        -a modo=cnpj \
        -a valor="$CNPJ_BB" \
        -a max_pages="$MAX_PAGES" \
        -a max_details_per_page="$MAX_DETAILS_PER_PAGE" \
        -s LOG_LEVEL="$LOG_LEVEL" \
        -s LOG_FILE="$LOG_FILE"; then

        success "Descoberta por CNPJ concluída com sucesso"
        return 0
    else
        error "Descoberta por CNPJ falhou"
        return 1
    fi
}

# Função principal
main() {
    echo "=================================="
    echo "TRF5 Scraper - Descoberta por CNPJ"
    echo "=================================="
    echo "CNPJ: $CNPJ_BB (Banco do Brasil)"
    echo "Configurações:"
    echo "  Máximo de páginas: $MAX_PAGES"
    echo "  Máximo de detalhes por página: $MAX_DETAILS_PER_PAGE"
    echo "  Nível de log: $LOG_LEVEL"
    echo ""

    # Criar diretório de logs
    mkdir -p "$LOG_DIR"

    # Verificar pré-requisitos
    check_prerequisites

    echo ""
    warning "ATENÇÃO: Esta é uma execução contra o sistema REAL do TRF5"
    warning "Os limites foram configurados para ser respeitoso com o servidor"
    echo ""

    # Executar descoberta
    if execute_cnpj_discovery; then
        success " Descoberta por CNPJ concluída com sucesso!"
        exit 0
    else
        error "L Descoberta por CNPJ falhou"
        exit 1
    fi
}

# Executar função principal
main "$@"