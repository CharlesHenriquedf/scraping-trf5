#!/bin/bash

# =============================================================================
# TRF5 Scraper - Reprocessamento Offline
# =============================================================================
# Este script executa o reprocessamento de p�ginas HTML j� salvas no MongoDB
# sem fazer novas requisi��es de rede. �til para testar extractors e debugging.

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

# Configura��es padr�o (podem ser alteradas via par�metros)
LIMIT=${1:-10}
SKIP=${2:-0}
TIPO=${3:-}
BUSCA=${4:-}
LOG_LEVEL=${5:-INFO}

# Arquivo de log da execu��o
LOG_FILE="$LOG_DIR/reprocess_offline_${TIMESTAMP}.log"

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
    if ! scrapy list | grep -q "parse_raw"; then
        error "Spider 'parse_raw' n�o encontrado"
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

# Fun��o para verificar dados dispon�veis
check_available_data() {
    log "Verificando dados dispon�veis para reprocessamento..."

    if command -v mongosh &> /dev/null; then
        MONGO_CMD="mongosh"
    else
        MONGO_CMD="mongo"
    fi

    # Verificar total de p�ginas salvas
    local total_pages
    total_pages=$(timeout 15 "$MONGO_CMD" \
        "${MONGO_URI:-mongodb://localhost:27017/trf5}" \
        --quiet \
        --eval "db.raw_pages.countDocuments({})" 2>/dev/null || echo "0")

    if [ "$total_pages" -eq 0 ]; then
        error "Nenhuma p�gina HTML encontrada na cole��o raw_pages"
        error "Execute primeiro a coleta de dados:"
        echo "  ./scripts/run_npu.sh"
        echo "  ./scripts/run_cnpj.sh"
        exit 1
    fi

    success "Total de p�ginas HTML dispon�veis: $total_pages"

    # Mostrar distribui��o por tipo
    echo ""
    log "Distribui��o de p�ginas por tipo:"

    timeout 15 "$MONGO_CMD" \
        "${MONGO_URI:-mongodb://localhost:27017/trf5}" \
        --quiet \
        --eval "
        db.raw_pages.aggregate([
            {\$group: {
                _id: '\$context.tipo',
                count: {\$sum: 1}
            }},
            {\$sort: {_id: 1}}
        ]).forEach(function(doc) {
            print('  ' + (doc._id || 'undefined') + ': ' + doc.count + ' p�ginas');
        });
        " 2>/dev/null || warning "Erro ao consultar distribui��o"

    # Mostrar distribui��o por tipo de busca
    echo ""
    log "Distribui��o de p�ginas por tipo de busca:"

    timeout 15 "$MONGO_CMD" \
        "${MONGO_URI:-mongodb://localhost:27017/trf5}" \
        --quiet \
        --eval "
        db.raw_pages.aggregate([
            {\$group: {
                _id: '\$context.busca',
                count: {\$sum: 1}
            }},
            {\$sort: {_id: 1}}
        ]).forEach(function(doc) {
            print('  ' + (doc._id || 'undefined') + ': ' + doc.count + ' p�ginas');
        });
        " 2>/dev/null || warning "Erro ao consultar distribui��o por busca"
}

# Fun��o para executar reprocessamento
execute_reprocessing() {
    log "Executando reprocessamento offline..."
    log "Configura��es:"
    log "  Limit: $LIMIT"
    log "  Skip: $SKIP"
    log "  Tipo: ${TIPO:-todos}"
    log "  Busca: ${BUSCA:-todas}"
    log "  Arquivo de log: $LOG_FILE"

    # Garantir que est� no diret�rio correto
    cd "$PROJECT_DIR"

    # Ativar ambiente virtual se existir
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi

    # Montar comando com par�metros opcionais
    local cmd="scrapy crawl parse_raw -a limit=$LIMIT -a skip=$SKIP -s LOG_LEVEL=$LOG_LEVEL -s LOG_FILE=$LOG_FILE"

    if [ -n "$TIPO" ]; then
        cmd="$cmd -a tipo=$TIPO"
    fi

    if [ -n "$BUSCA" ]; then
        cmd="$cmd -a busca=$BUSCA"
    fi

    # Executar scrapy
    log "Comando: $cmd"
    echo ""

    if eval "$cmd"; then
        success "Reprocessamento offline conclu�do com sucesso"
        return 0
    else
        error "Reprocessamento offline falhou"
        return 1
    fi
}

# Fun��o para verificar resultados
verify_results() {
    log "Verificando resultados do reprocessamento..."

    if [ -f "$LOG_FILE" ]; then
        echo ""
        log "An�lise do log de execu��o:"

        # Contar documentos processados
        local processed=$(grep -c "Reprocessando.*offline" "$LOG_FILE" 2>/dev/null || echo "0")
        local successful=$(grep -c "reprocessado com sucesso" "$LOG_FILE" 2>/dev/null || echo "0")
        local failed=$(grep -c "Falha ao extrair dados" "$LOG_FILE" 2>/dev/null || echo "0")

        echo "  Documentos processados: $processed"
        echo "  Sucessos: $successful"
        echo "  Falhas: $failed"

        if [ "$processed" -gt 0 ]; then
            local success_rate=$(( successful * 100 / processed ))
            echo "  Taxa de sucesso: $success_rate%"
        fi

        # Verificar se nenhuma requisi��o de rede foi feita
        local network_requests=$(grep -c "Crawled.*200\|Crawled.*302" "$LOG_FILE" 2>/dev/null || echo "0")
        if [ "$network_requests" -eq 0 ]; then
            success " Nenhuma requisi��o de rede foi feita (modo offline)"
        else
            warning "� Foram feitas $network_requests requisi��es de rede (n�o deveria acontecer)"
        fi

        # Mostrar �ltimas linhas se houve erros
        if [ "$failed" -gt 0 ]; then
            echo ""
            warning "�ltimas linhas do log (poss�veis erros):"
            tail -5 "$LOG_FILE"
        fi
    else
        warning "Arquivo de log n�o encontrado: $LOG_FILE"
    fi
}

# Fun��o para gerar relat�rio
generate_report() {
    local report_file="$LOG_DIR/reprocess_offline_report_${TIMESTAMP}.txt"

    {
        echo "=================================="
        echo "TRF5 Scraper - Relat�rio Reprocessamento Offline"
        echo "=================================="
        echo "Data: $(date)"
        echo "Configura��es:"
        echo "  Limit: $LIMIT"
        echo "  Skip: $SKIP"
        echo "  Tipo filtro: ${TIPO:-todos}"
        echo "  Busca filtro: ${BUSCA:-todas}"
        echo ""
        echo "Arquivos gerados:"
        echo "  Log de execu��o: $LOG_FILE"
        echo "  Este relat�rio: $report_file"
        echo ""

        # Estat�sticas do log
        if [ -f "$LOG_FILE" ]; then
            echo "Estat�sticas da execu��o:"
            local processed=$(grep -c "Reprocessando.*offline" "$LOG_FILE" 2>/dev/null || echo "0")
            local successful=$(grep -c "reprocessado com sucesso" "$LOG_FILE" 2>/dev/null || echo "0")
            local failed=$(grep -c "Falha ao extrair dados" "$LOG_FILE" 2>/dev/null || echo "0")

            echo "  Documentos processados: $processed"
            echo "  Sucessos: $successful"
            echo "  Falhas: $failed"

            if [ "$processed" -gt 0 ]; then
                local success_rate=$(( successful * 100 / processed ))
                echo "  Taxa de sucesso: $success_rate%"
            fi
        else
            echo "  Erro: Log de execu��o n�o encontrado"
        fi

        echo ""
        echo "Para verificar os dados:"
        echo "  mongosh \"${MONGO_URI:-mongodb://localhost:27017/trf5}\""
        echo "  db.processos.find().sort({scraped_at: -1}).limit(5)"
        echo "=================================="
    } > "$report_file"

    echo ""
    success "Relat�rio salvo em: $report_file"
}

# Fun��o para mostrar ajuda
show_help() {
    echo "Uso: $0 [LIMIT] [SKIP] [TIPO] [BUSCA] [LOG_LEVEL]"
    echo ""
    echo "Par�metros:"
    echo "  LIMIT      M�ximo de documentos a processar (padr�o: 10)"
    echo "  SKIP       Documentos a pular no in�cio (padr�o: 0)"
    echo "  TIPO       Filtrar por tipo de p�gina: detalhe, lista, form (padr�o: todos)"
    echo "  BUSCA      Filtrar por tipo de busca: numero, cnpj (padr�o: todas)"
    echo "  LOG_LEVEL  N�vel de log Scrapy (padr�o: INFO)"
    echo ""
    echo "Exemplos:"
    echo "  $0                        # Processar 10 documentos mais recentes"
    echo "  $0 20                     # Processar 20 documentos"
    echo "  $0 15 5                   # Processar 15 documentos, pulando os 5 primeiros"
    echo "  $0 10 0 detalhe           # Processar apenas p�ginas de detalhe"
    echo "  $0 5 0 detalhe numero     # Processar detalhes de busca por n�mero"
    echo "  $0 10 0 \"\" \"\" DEBUG       # Processar com log DEBUG"
    echo ""
    echo "Nota: Este spider n�o faz requisi��es de rede, apenas reprocessa"
    echo "      p�ginas HTML j� salvas na cole��o raw_pages do MongoDB."
}

# Fun��o principal
main() {
    # Verificar se foi solicitada ajuda
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        show_help
        exit 0
    fi

    echo "=================================="
    echo "TRF5 Scraper - Reprocessamento Offline"
    echo "=================================="
    echo "Reprocessa p�ginas HTML j� coletadas sem fazer requisi��es de rede"
    echo ""
    echo "Configura��es:"
    echo "  Limit: $LIMIT documentos"
    echo "  Skip: $SKIP documentos"
    echo "  Tipo: ${TIPO:-todos}"
    echo "  Busca: ${BUSCA:-todas}"
    echo "  Log level: $LOG_LEVEL"
    echo ""

    # Criar diret�rio de logs
    mkdir -p "$LOG_DIR"

    # Verificar pr�-requisitos
    check_prerequisites

    # Verificar dados dispon�veis
    check_available_data

    echo ""
    warning "Este processo reanalisa p�ginas HTML j� salvas"
    warning "N�o ser�o feitas novas requisi��es ao TRF5"
    echo ""

    # Executar reprocessamento
    if execute_reprocessing; then
        echo ""
        success " Reprocessamento offline conclu�do com sucesso!"

        # Verificar resultados
        verify_results

        # Gerar relat�rio
        generate_report

        echo ""
        success "<� Execu��o completa! Verifique os resultados"
        echo ""
        echo "Pr�ximos passos:"
        echo "  1. Verificar dados: ./scripts/mongo_queries.sh"
        echo "  2. Comparar com dados originais no MongoDB"

        exit 0
    else
        echo ""
        error "L Reprocessamento offline falhou"
        error "Verifique o log: $LOG_FILE"

        # Mostrar �ltimas linhas do log se existir
        if [ -f "$LOG_FILE" ]; then
            echo ""
            warning "�ltimas 10 linhas do log:"
            tail -10 "$LOG_FILE"
        fi

        exit 1
    fi
}

# Executar fun��o principal
main "$@"