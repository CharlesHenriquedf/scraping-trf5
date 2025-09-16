#!/bin/bash

# =============================================================================
# TRF5 Scraper - Execu��o de Descoberta por CNPJ
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

# Configura��es
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

# CNPJ do Banco do Brasil (conforme arquivo de teste)
CNPJ_BB="00.000.000/0001-91"

# Configura��es padr�o (podem ser alteradas via par�metros)
MAX_PAGES=${1:-2}
MAX_DETAILS_PER_PAGE=${2:-5}
LOG_LEVEL=${3:-INFO}

# Arquivo de log da execu��o
LOG_FILE="$LOG_DIR/cnpj_discovery_${TIMESTAMP}.log"

# Fun��o para logging
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
    echo -e "${YELLOW}�${NC} $1"
}

# Fun��o para verificar MongoDB
check_mongodb() {
    log "Verificando conectividade MongoDB..."

    if command -v mongosh &> /dev/null; then
        MONGO_CMD="mongosh"
    elif command -v mongo &> /dev/null; then
        MONGO_CMD="mongo"
    else
        error "MongoDB client n�o encontrado (mongosh ou mongo)"
        return 1
    fi

    # Testar conex�o
    if timeout 10 "$MONGO_CMD" \
        "${MONGO_URI:-mongodb://localhost:27017}" \
        --quiet \
        --eval "db.runCommand('ping')" &>/dev/null; then
        success "MongoDB conectado"
        return 0
    else
        error "MongoDB n�o acess�vel em ${MONGO_URI:-mongodb://localhost:27017}"
        return 1
    fi
}

# Fun��o para verificar pr�-requisitos
check_prerequisites() {
    log "Verificando pr�-requisitos..."

    # Verificar se estamos no diret�rio correto
    if [ ! -f "scrapy.cfg" ] || [ ! -d "trf5_scraper" ]; then
        error "Execute este script do diret�rio raiz do projeto TRF5 Scraper"
        exit 1
    fi

    # Verificar Scrapy
    if ! command -v scrapy &> /dev/null; then
        error "Scrapy n�o encontrado. Ative o ambiente virtual:"
        echo "  source .venv/bin/activate"
        exit 1
    fi

    # Verificar spiders
    if ! scrapy list | grep -q "trf5"; then
        error "Spider 'trf5' n�o encontrado"
        exit 1
    fi

    # Verificar conectividade TRF5
    log "Testando conectividade com TRF5..."
    if curl -s --head --max-time 10 http://www5.trf5.jus.br/cp/ | head -1 | grep -q "200\|302\|301"; then
        success "TRF5 acess�vel"
    else
        error "TRF5 n�o acess�vel. Verifique sua conex�o com a internet"
        exit 1
    fi

    # Verificar MongoDB
    if ! check_mongodb; then
        warning "MongoDB n�o conectado. Para usar Docker:"
        echo "  cd docker && docker compose up -d"
        exit 1
    fi

    success "Todos os pr�-requisitos verificados"
}

# Fun��o para executar descoberta CNPJ
execute_cnpj_discovery() {
    log "Executando descoberta por CNPJ..."
    log "CNPJ: $CNPJ_BB"
    log "M�ximo de p�ginas: $MAX_PAGES"
    log "M�ximo de detalhes por p�gina: $MAX_DETAILS_PER_PAGE"
    log "Arquivo de log: $LOG_FILE"

    # Garantir que est� no diret�rio correto
    cd "$PROJECT_DIR"

    # Ativar ambiente virtual se existir
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi

    # Executar scrapy
    log "Iniciando execu��o do scrapy..."

    if scrapy crawl trf5 \
        -a modo=cnpj \
        -a valor="$CNPJ_BB" \
        -a max_pages="$MAX_PAGES" \
        -a max_details_per_page="$MAX_DETAILS_PER_PAGE" \
        -s LOG_LEVEL="$LOG_LEVEL" \
        -s LOG_FILE="$LOG_FILE"; then

        success "Descoberta por CNPJ conclu�da com sucesso"
        return 0
    else
        error "Descoberta por CNPJ falhou"
        return 1
    fi
}

# Fun��o principal
main() {
    echo "=================================="
    echo "TRF5 Scraper - Descoberta por CNPJ"
    echo "=================================="
    echo "CNPJ: $CNPJ_BB (Banco do Brasil)"
    echo "Configura��es:"
    echo "  M�ximo de p�ginas: $MAX_PAGES"
    echo "  M�ximo de detalhes por p�gina: $MAX_DETAILS_PER_PAGE"
    echo "  N�vel de log: $LOG_LEVEL"
    echo ""

    # Criar diret�rio de logs
    mkdir -p "$LOG_DIR"

    # Verificar pr�-requisitos
    check_prerequisites

    echo ""
    warning "ATEN��O: Esta � uma execu��o contra o sistema REAL do TRF5"
    warning "Os limites foram configurados para ser respeitoso com o servidor"
    echo ""

    # Executar descoberta
    if execute_cnpj_discovery; then
        success " Descoberta por CNPJ conclu�da com sucesso!"
        exit 0
    else
        error "L Descoberta por CNPJ falhou"
        exit 1
    fi
}

# Executar fun��o principal
main "$@"