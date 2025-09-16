#!/bin/bash

# =============================================================================
# TRF5 Scraper - Reprocessamento Offline
# =============================================================================
# Este script executa o reprocessamento de páginas HTML já salvas no MongoDB
# sem fazer novas requisições de rede. Útil para testar extractors e debugging.

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

# Configurações padrão (podem ser alteradas via parâmetros)
LIMIT=${1:-10}
SKIP=${2:-0}
TIPO=${3:-}
BUSCA=${4:-}
LOG_LEVEL=${5:-INFO}

# Arquivo de log da execução
LOG_FILE="$LOG_DIR/reprocess_offline_${TIMESTAMP}.log"

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
    if ! scrapy list | grep -q "parse_raw"; then
        error "Spider 'parse_raw' não encontrado"
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

# Função para verificar dados disponíveis
check_available_data() {
    log "Verificando dados disponíveis para reprocessamento..."

    if command -v mongosh &> /dev/null; then
        MONGO_CMD="mongosh"
    else
        MONGO_CMD="mongo"
    fi

    # Verificar total de páginas salvas
    local total_pages
    total_pages=$(timeout 15 "$MONGO_CMD" \
        "${MONGO_URI:-mongodb://localhost:27017/trf5}" \
        --quiet \
        --eval "db.raw_pages.countDocuments({})" 2>/dev/null || echo "0")

    if [ "$total_pages" -eq 0 ]; then
        error "Nenhuma página HTML encontrada na coleção raw_pages"
        error "Execute primeiro a coleta de dados:"
        echo "  ./scripts/run_npu.sh"
        echo "  ./scripts/run_cnpj.sh"
        exit 1
    fi

    success "Total de páginas HTML disponíveis: $total_pages"

    # Mostrar distribuição por tipo
    echo ""
    log "Distribuição de páginas por tipo:"

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
            print('  ' + (doc._id || 'undefined') + ': ' + doc.count + ' páginas');
        });
        " 2>/dev/null || warning "Erro ao consultar distribuição"

    # Mostrar distribuição por tipo de busca
    echo ""
    log "Distribuição de páginas por tipo de busca:"

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
            print('  ' + (doc._id || 'undefined') + ': ' + doc.count + ' páginas');
        });
        " 2>/dev/null || warning "Erro ao consultar distribuição por busca"
}

# Função para executar reprocessamento
execute_reprocessing() {
    log "Executando reprocessamento offline..."
    log "Configurações:"
    log "  Limit: $LIMIT"
    log "  Skip: $SKIP"
    log "  Tipo: ${TIPO:-todos}"
    log "  Busca: ${BUSCA:-todas}"
    log "  Arquivo de log: $LOG_FILE"

    # Garantir que está no diretório correto
    cd "$PROJECT_DIR"

    # Ativar ambiente virtual se existir
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi

    # Montar comando com parâmetros opcionais
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
        success "Reprocessamento offline concluído com sucesso"
        return 0
    else
        error "Reprocessamento offline falhou"
        return 1
    fi
}

# Função para verificar resultados
verify_results() {
    log "Verificando resultados do reprocessamento..."

    if [ -f "$LOG_FILE" ]; then
        echo ""
        log "Análise do log de execução:"

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

        # Verificar se nenhuma requisição de rede foi feita
        local network_requests=$(grep -c "Crawled.*200\|Crawled.*302" "$LOG_FILE" 2>/dev/null || echo "0")
        if [ "$network_requests" -eq 0 ]; then
            success " Nenhuma requisição de rede foi feita (modo offline)"
        else
            warning "  Foram feitas $network_requests requisições de rede (não deveria acontecer)"
        fi

        # Mostrar últimas linhas se houve erros
        if [ "$failed" -gt 0 ]; then
            echo ""
            warning "Últimas linhas do log (possíveis erros):"
            tail -5 "$LOG_FILE"
        fi
    else
        warning "Arquivo de log não encontrado: $LOG_FILE"
    fi
}

# Função para gerar relatório
generate_report() {
    local report_file="$LOG_DIR/reprocess_offline_report_${TIMESTAMP}.txt"

    {
        echo "=================================="
        echo "TRF5 Scraper - Relatório Reprocessamento Offline"
        echo "=================================="
        echo "Data: $(date)"
        echo "Configurações:"
        echo "  Limit: $LIMIT"
        echo "  Skip: $SKIP"
        echo "  Tipo filtro: ${TIPO:-todos}"
        echo "  Busca filtro: ${BUSCA:-todas}"
        echo ""
        echo "Arquivos gerados:"
        echo "  Log de execução: $LOG_FILE"
        echo "  Este relatório: $report_file"
        echo ""

        # Estatísticas do log
        if [ -f "$LOG_FILE" ]; then
            echo "Estatísticas da execução:"
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
            echo "  Erro: Log de execução não encontrado"
        fi

        echo ""
        echo "Para verificar os dados:"
        echo "  mongosh \"${MONGO_URI:-mongodb://localhost:27017/trf5}\""
        echo "  db.processos.find().sort({scraped_at: -1}).limit(5)"
        echo "=================================="
    } > "$report_file"

    echo ""
    success "Relatório salvo em: $report_file"
}

# Função para mostrar ajuda
show_help() {
    echo "Uso: $0 [LIMIT] [SKIP] [TIPO] [BUSCA] [LOG_LEVEL]"
    echo ""
    echo "Parâmetros:"
    echo "  LIMIT      Máximo de documentos a processar (padrão: 10)"
    echo "  SKIP       Documentos a pular no início (padrão: 0)"
    echo "  TIPO       Filtrar por tipo de página: detalhe, lista, form (padrão: todos)"
    echo "  BUSCA      Filtrar por tipo de busca: numero, cnpj (padrão: todas)"
    echo "  LOG_LEVEL  Nível de log Scrapy (padrão: INFO)"
    echo ""
    echo "Exemplos:"
    echo "  $0                        # Processar 10 documentos mais recentes"
    echo "  $0 20                     # Processar 20 documentos"
    echo "  $0 15 5                   # Processar 15 documentos, pulando os 5 primeiros"
    echo "  $0 10 0 detalhe           # Processar apenas páginas de detalhe"
    echo "  $0 5 0 detalhe numero     # Processar detalhes de busca por número"
    echo "  $0 10 0 \"\" \"\" DEBUG       # Processar com log DEBUG"
    echo ""
    echo "Nota: Este spider não faz requisições de rede, apenas reprocessa"
    echo "      páginas HTML já salvas na coleção raw_pages do MongoDB."
}

# Função principal
main() {
    # Verificar se foi solicitada ajuda
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        show_help
        exit 0
    fi

    echo "=================================="
    echo "TRF5 Scraper - Reprocessamento Offline"
    echo "=================================="
    echo "Reprocessa páginas HTML já coletadas sem fazer requisições de rede"
    echo ""
    echo "Configurações:"
    echo "  Limit: $LIMIT documentos"
    echo "  Skip: $SKIP documentos"
    echo "  Tipo: ${TIPO:-todos}"
    echo "  Busca: ${BUSCA:-todas}"
    echo "  Log level: $LOG_LEVEL"
    echo ""

    # Criar diretório de logs
    mkdir -p "$LOG_DIR"

    # Verificar pré-requisitos
    check_prerequisites

    # Verificar dados disponíveis
    check_available_data

    echo ""
    warning "Este processo reanalisa páginas HTML já salvas"
    warning "Não serão feitas novas requisições ao TRF5"
    echo ""

    # Executar reprocessamento
    if execute_reprocessing; then
        echo ""
        success " Reprocessamento offline concluído com sucesso!"

        # Verificar resultados
        verify_results

        # Gerar relatório
        generate_report

        echo ""
        success "<‰ Execução completa! Verifique os resultados"
        echo ""
        echo "Próximos passos:"
        echo "  1. Verificar dados: ./scripts/mongo_queries.sh"
        echo "  2. Comparar com dados originais no MongoDB"

        exit 0
    else
        echo ""
        error "L Reprocessamento offline falhou"
        error "Verifique o log: $LOG_FILE"

        # Mostrar últimas linhas do log se existir
        if [ -f "$LOG_FILE" ]; then
            echo ""
            warning "Últimas 10 linhas do log:"
            tail -10 "$LOG_FILE"
        fi

        exit 1
    fi
}

# Executar função principal
main "$@"