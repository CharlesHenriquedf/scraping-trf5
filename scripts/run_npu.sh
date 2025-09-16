#!/bin/bash

# =============================================================================
# TRF5 Scraper - Execução de Todos os NPUs do Banco do Brasil
# =============================================================================
# Este script executa a coleta de todos os NPUs fornecidos pelo Banco do Brasil
# para o desafio técnico, testando também a idempotência (executa cada NPU 2x)

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

# Função para executar NPU
execute_npu() {
    local npu="$1"
    local attempt="$2"
    local log_file="$LOG_DIR/npu_${npu//[.-]/}_attempt${attempt}_${TIMESTAMP}.log"

    log "Executando NPU: $npu (tentativa $attempt)"

    # Garantir que está no diretório correto
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

    # Verificar MongoDB
    if ! check_mongodb; then
        warning "MongoDB não conectado. Para usar Docker:"
        echo "  cd docker && docker compose up -d"
        exit 1
    fi

    success "Todos os pré-requisitos verificados"
}

# Função para gerar relatório
generate_report() {
    local report_file="$LOG_DIR/npu_execution_report_${TIMESTAMP}.txt"

    {
        echo "=================================="
        echo "TRF5 Scraper - Relatório de Execução NPUs BB"
        echo "=================================="
        echo "Data: $(date)"
        echo "Total de execuções: $TOTAL_EXECUTIONS"
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
    success "Relatório salvo em: $report_file"
}

# Banner principal
main() {
    echo "=================================="
    echo "TRF5 Scraper - Execução NPUs BB"
    echo "=================================="
    echo "Executando ${#NPUS_BB[@]} NPUs do Banco do Brasil"
    echo "Cada NPU será executado 2 vezes para testar idempotência"
    echo ""

    # Criar diretório de logs
    mkdir -p "$LOG_DIR"

    # Verificar pré-requisitos
    check_prerequisites

    echo ""
    log "Iniciando execução de NPUs..."
    echo ""

    # Executar cada NPU duas vezes
    for npu in "${NPUS_BB[@]}"; do
        echo ""
        log "Processando NPU: $npu"
        echo ""

        # Primeira execução (deve fazer INSERT)
        log "1ª execução (esperado: INSERT)"
        if execute_npu "$npu" "1"; then
            ((SUCCESS_COUNT++))
        else
            ((FAILED_COUNT++))
        fi
        ((TOTAL_EXECUTIONS++))

        sleep 2  # Pequena pausa entre execuções

        # Segunda execução (deve fazer UPDATE - idempotência)
        log "2ª execução (esperado: UPDATE - idempotência)"
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

    # Gerar relatório
    generate_report

    # Verificação final no MongoDB
    log "Verificando dados no MongoDB..."

    if command -v mongosh &> /dev/null; then
        MONGO_CMD="mongosh"
    else
        MONGO_CMD="mongo"
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
        success "<‰ Todas as execuções concluídas com sucesso!"
        success "=Ê $SUCCESS_COUNT/$TOTAL_EXECUTIONS execuções bem-sucedidas"
        success "=Ä Dados verificados no MongoDB"
        exit 0
    else
        error "L $FAILED_COUNT/$TOTAL_EXECUTIONS execuções falharam"
        warning "=Ë Verifique os logs em $LOG_DIR para detalhes"
        exit 1
    fi
}

# Executar função principal
main "$@"