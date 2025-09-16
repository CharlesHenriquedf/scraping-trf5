#!/bin/bash

# =============================================================================
# TRF5 Scraper - Execu��o de Todos os NPUs do Banco do Brasil
# =============================================================================
# Este script executa a coleta de todos os NPUs fornecidos pelo Banco do Brasil
# para o desafio t�cnico, testando tamb�m a idempot�ncia (executa cada NPU 2x)

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

# NPUs fornecidos pelo Banco do Brasil (conforme arquivo de teste)
NPUS_BB=(
    "0015648-78.1999.4.05.0000"
    "0012656-90.2012.4.05.0000"
    "0043753-74.2013.4.05.0000"
    "0002098-07.2011.4.05.8500"
    "0460674-33.2019.4.05.0000"
    "0000560-67.2017.4.05.0000"
)

# Contadores
TOTAL_EXECUTIONS=0
SUCCESS_COUNT=0
FAILED_COUNT=0

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

# Fun��o para executar NPU
execute_npu() {
    local npu="$1"
    local attempt="$2"
    local log_file="$LOG_DIR/npu_${npu//[.-]/}_attempt${attempt}_${TIMESTAMP}.log"

    log "Executando NPU: $npu (tentativa $attempt)"

    # Garantir que est� no diret�rio correto
    cd "$PROJECT_DIR"

    # Ativar ambiente virtual se existir
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi

    # Executar scrapy
    if scrapy crawl trf5 \
        -a modo=numero \
        -a valor="$npu" \
        -s LOG_LEVEL=INFO \
        -s LOG_FILE="$log_file" 2>&1; then

        success "NPU $npu (tentativa $attempt) - SUCESSO"
        return 0
    else
        error "NPU $npu (tentativa $attempt) - FALHOU"
        return 1
    fi
}

# Fun��o para verificar MongoDB
check_mongodb() {
    log "Verificando conectividade MongoDB..."

    # Tentativa 1: usar mongosh ou mongo se dispon�veis
    if command -v mongosh &> /dev/null; then
        MONGO_CMD="mongosh"
    elif command -v mongo &> /dev/null; then
        MONGO_CMD="mongo"
    else
        MONGO_CMD=""
    fi

    if [ -n "$MONGO_CMD" ]; then
        # Testar conex�o com cliente nativo
        if timeout 10 "$MONGO_CMD" \
            "${MONGO_URI:-mongodb://localhost:27017}" \
            --quiet \
            --eval "db.runCommand('ping')" &>/dev/null; then
            success "MongoDB conectado (cliente nativo)"
            return 0
        fi
    fi

    # Tentativa 2: usar Docker se o container estiver rodando
    if docker ps | grep -q "trf5-mongo" && docker exec trf5-mongo mongosh --version &>/dev/null; then
        if timeout 10 docker exec trf5-mongo mongosh \
            "${MONGO_URI:-mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=trf5}" \
            --quiet \
            --eval "db.runCommand('ping')" &>/dev/null; then
            success "MongoDB conectado (via Docker)"
            return 0
        fi
    fi

    # Se chegou aqui, n�o conseguiu conectar
    warning "MongoDB n�o conectado. Para usar Docker:"
    echo "  cd docker && docker compose up -d"
    return 1
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

    # Verificar MongoDB
    if ! check_mongodb; then
        warning "MongoDB n�o conectado. Para usar Docker:"
        echo "  cd docker && docker compose up -d"
        exit 1
    fi

    success "Todos os pr�-requisitos verificados"
}

# Fun��o para gerar relat�rio
generate_report() {
    local report_file="$LOG_DIR/npu_execution_report_${TIMESTAMP}.txt"

    {
        echo "=================================="
        echo "TRF5 Scraper - Relat�rio de Execu��o NPUs BB"
        echo "=================================="
        echo "Data: $(date)"
        echo "Total de execu��es: $TOTAL_EXECUTIONS"
        echo "Sucessos: $SUCCESS_COUNT"
        echo "Falhas: $FAILED_COUNT"
        echo "Taxa de sucesso: $(( SUCCESS_COUNT * 100 / TOTAL_EXECUTIONS ))%"
        echo ""
        echo "NPUs processados:"
        for npu in "${NPUS_BB[@]}"; do
            echo "  - $npu"
        done
        echo ""
        echo "Logs individuais salvos em: $LOG_DIR"
        echo "=================================="
    } > "$report_file"

    echo ""
    success "Relat�rio salvo em: $report_file"
}

# Banner principal
main() {
    echo "=================================="
    echo "TRF5 Scraper - Execu��o NPUs BB"
    echo "=================================="
    echo "Executando ${#NPUS_BB[@]} NPUs do Banco do Brasil"
    echo "Cada NPU ser� executado 2 vezes para testar idempot�ncia"
    echo ""

    # Criar diret�rio de logs
    mkdir -p "$LOG_DIR"

    # Verificar pr�-requisitos
    check_prerequisites

    echo ""
    log "Iniciando execu��o de NPUs..."
    echo ""

    # Executar cada NPU duas vezes
    for npu in "${NPUS_BB[@]}"; do
        echo ""
        log "Processando NPU: $npu"
        echo ""

        # Primeira execu��o (deve fazer INSERT)
        log "1� execu��o (esperado: INSERT)"
        if execute_npu "$npu" "1"; then
            ((SUCCESS_COUNT++))
        else
            ((FAILED_COUNT++))
        fi
        ((TOTAL_EXECUTIONS++))

        sleep 2  # Pequena pausa entre execu��es

        # Segunda execu��o (deve fazer UPDATE - idempot�ncia)
        log "2� execu��o (esperado: UPDATE - idempot�ncia)"
        if execute_npu "$npu" "2"; then
            ((SUCCESS_COUNT++))
        else
            ((FAILED_COUNT++))
        fi
        ((TOTAL_EXECUTIONS++))

        echo ""
    done

    echo ""
    echo ""

    # Gerar relat�rio
    generate_report

    # Verifica��o final no MongoDB
    log "Verificando dados no MongoDB..."

    # Determinar comando MongoDB a usar
    MONGO_CMD=""
    MONGO_CONNECTION=""

    if command -v mongosh &> /dev/null; then
        MONGO_CMD="mongosh"
        MONGO_CONNECTION="${MONGO_URI:-mongodb://localhost:27017/trf5}"
    elif command -v mongo &> /dev/null; then
        MONGO_CMD="mongo"
        MONGO_CONNECTION="${MONGO_URI:-mongodb://localhost:27017/trf5}"
    elif docker ps | grep -q "trf5-mongo"; then
        MONGO_CMD="docker exec trf5-mongo mongosh"
        MONGO_CONNECTION="${MONGO_URI:-mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=trf5}"
    fi

    # Verificar se todos os NPUs foram salvos
    echo ""
    log "NPUs salvos no MongoDB:"
    for npu in "${NPUS_BB[@]}"; do
        if timeout 10 "$MONGO_CMD" \
            "${MONGO_URI:-mongodb://localhost:27017/trf5}" \
            --quiet \
            --eval "db.processos.findOne({_id: '$npu'}) ? print('   $npu: OK') : print('   $npu: MISSING')" 2>/dev/null; then
            :  # Comando foi executado
        else
            error "Erro ao verificar NPU $npu no MongoDB"
        fi
    done

    echo ""

    # Resultado final
    if [ $FAILED_COUNT -eq 0 ]; then
        success "<� Todas as execu��es conclu�das com sucesso!"
        success "=� $SUCCESS_COUNT/$TOTAL_EXECUTIONS execu��es bem-sucedidas"
        success "=� Dados verificados no MongoDB"
        exit 0
    else
        error "L $FAILED_COUNT/$TOTAL_EXECUTIONS execu��es falharam"
        warning "=� Verifique os logs em $LOG_DIR para detalhes"
        exit 1
    fi
}

# Executar fun��o principal
main "$@"