#!/bin/bash

# =============================================================================
# TRF5 Scraper - Consultas MongoDB Rápidas
# =============================================================================
# Este script executa consultas padronizadas no MongoDB para verificação
# dos dados coletados pelo TRF5 Scraper

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configurações
MONGO_URI=${MONGO_URI:-"mongodb://localhost:27017"}
MONGO_DB=${MONGO_DB:-"trf5"}

# NPUs do Banco do Brasil para verificação
NPUS_BB=(
    "0015648-78.1999.4.05.0000"
    "0012656-90.2012.4.05.0000"
    "0043753-74.2013.4.05.0000"
    "0002098-07.2011.4.05.8500"
    "0460674-33.2019.4.05.0000"
    "0000560-67.2017.4.05.0000"
)

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

info() {
    echo -e "${CYAN}9${NC} $1"
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
        echo "Instale o MongoDB client:"
        echo "  # Ubuntu/Debian"
        echo "  sudo apt install mongodb-clients"
        echo "  # ou baixe mongosh do site oficial do MongoDB"
        exit 1
    fi

    # Testar conexão
    if timeout 10 "$MONGO_CMD" \
        "$MONGO_URI" \
        --quiet \
        --eval "db.runCommand('ping')" &>/dev/null; then
        success "MongoDB conectado em $MONGO_URI"
        return 0
    else
        error "MongoDB não acessível em $MONGO_URI"
        echo "Verifique se o MongoDB está rodando:"
        echo "  docker ps | grep mongo"
        echo "  cd docker && docker compose up -d"
        exit 1
    fi
}

# Função para executar consulta
execute_query() {
    local title="$1"
    local query="$2"
    local separator="${3:-true}"

    if [ "$separator" = "true" ]; then
        echo ""
        echo ""
    fi

    echo -e "${CYAN}$title${NC}"
    echo ""

    if timeout 30 "$MONGO_CMD" \
        "$MONGO_URI/$MONGO_DB" \
        --quiet \
        --eval "$query" 2>/dev/null; then
        return 0
    else
        error "Erro ao executar consulta: $title"
        return 1
    fi
}

# Consulta 1: Estatísticas gerais
query_general_stats() {
    local query='
    print("=Ê ESTATÍSTICAS GERAIS");
    print("PPPPPPPPPPPPPPPPPPPPPPP");
    print("");

    // Coleções disponíveis
    print("=Â  Coleções disponíveis:");
    db.listCollections().forEach(function(collection) {
        var count = db[collection.name].countDocuments({});
        print("   " + collection.name + ": " + count + " documentos");
    });

    print("");

    // Estatísticas de raw_pages
    print("=Ä Raw Pages (HTML bruto):");
    var rawStats = db.raw_pages.aggregate([
        {$group: {
            _id: "$context.tipo",
            count: {$sum: 1}
        }},
        {$sort: {_id: 1}}
    ]).toArray();

    rawStats.forEach(function(stat) {
        print("   " + (stat._id || "undefined") + ": " + stat.count + " páginas");
    });

    var totalRaw = db.raw_pages.countDocuments({});
    print("   Total: " + totalRaw + " páginas HTML salvas");

    print("");

    // Estatísticas de processos
    print("–  Processos estruturados:");
    var totalProcessos = db.processos.countDocuments({});
    print("   Total: " + totalProcessos + " processos extraídos");

    if (totalProcessos > 0) {
        var comRelator = db.processos.countDocuments({relator: {$ne: null, $ne: ""}});
        var comEnvolvidos = db.processos.countDocuments({envolvidos: {$ne: null, $ne: []}});
        var comMovimentacoes = db.processos.countDocuments({movimentacoes: {$ne: null, $ne: []}});

        print("   Com relator: " + comRelator + " (" + Math.round(comRelator*100/totalProcessos) + "%)");
        print("   Com envolvidos: " + comEnvolvidos + " (" + Math.round(comEnvolvidos*100/totalProcessos) + "%)");
        print("   Com movimentações: " + comMovimentacoes + " (" + Math.round(comMovimentacoes*100/totalProcessos) + "%)");
    }
    '

    execute_query "=Ê Estatísticas Gerais" "$query"
}

# Consulta 2: Últimas páginas coletadas
query_recent_pages() {
    local query='
    print("=R ÚLTIMAS PÁGINAS COLETADAS");
    print("PPPPPPPPPPPPPPPPPPPPPPPPPPPPP");
    print("");

    db.raw_pages.find({}, {
        url: 1,
        "context.tipo": 1,
        "context.busca": 1,
        "context.numero": 1,
        "context.cnpj": 1,
        "context.page_idx": 1,
        fetched_at: 1
    }).sort({_id: -1}).limit(10).forEach(function(doc) {
        var tipo = doc.context.tipo || "N/A";
        var busca = doc.context.busca || "N/A";
        var identificador = doc.context.numero || doc.context.cnpj || "N/A";
        var pageIdx = doc.context.page_idx !== undefined ? " (pág " + doc.context.page_idx + ")" : "";
        var timestamp = doc.fetched_at || "N/A";

        print("< " + tipo + " | " + busca + " | " + identificador + pageIdx);
        print("   URL: " + (doc.url || "N/A"));
        print("   Coletado: " + timestamp);
        print("");
    });
    '

    execute_query "=R Últimas Páginas Coletadas" "$query"
}

# Consulta 3: Processos extraídos
query_extracted_processes() {
    local query='
    print("–  PROCESSOS EXTRAÍDOS");
    print("PPPPPPPPPPPPPPPPPPPPPPP");
    print("");

    var totalProcessos = db.processos.countDocuments({});
    if (totalProcessos === 0) {
        print("L Nenhum processo encontrado na coleção processos");
        return;
    }

    print("=Ë Últimos 5 processos extraídos:");
    print("");

    db.processos.find({}, {
        numero_processo: 1,
        relator: 1,
        data_autuacao: 1,
        "envolvidos.0.papel": 1,
        "envolvidos.0.nome": 1,
        "movimentacoes.0.data": 1,
        scraped_at: 1
    }).sort({_id: -1}).limit(5).forEach(function(doc) {
        print("=Ä " + (doc.numero_processo || doc._id));
        print("   Relator: " + (doc.relator || "N/A"));
        print("   Data autuação: " + (doc.data_autuacao || "N/A"));

        if (doc.envolvidos && doc.envolvidos.length > 0) {
            print("   Primeiro envolvido: " + doc.envolvidos[0].papel + " - " + doc.envolvidos[0].nome);
        } else {
            print("   Envolvidos: N/A");
        }

        if (doc.movimentacoes && doc.movimentacoes.length > 0) {
            print("   Última movimentação: " + doc.movimentacoes[0].data);
        } else {
            print("   Movimentações: N/A");
        }

        print("   Extraído em: " + (doc.scraped_at || "N/A"));
        print("");
    });
    '

    execute_query "– Processos Extraídos" "$query"
}

# Consulta 4: Verificar NPUs do Banco do Brasil
query_bb_npus() {
    local npus_array=$(printf '"%s",' "${NPUS_BB[@]}")
    npus_array="[${npus_array%,}]"

    local query="
    print(\"<æ VERIFICAÇÃO NPUs BANCO DO BRASIL\");
    print(\"PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP\");
    print(\"\");

    var npusBB = $npus_array;
    var encontrados = 0;
    var faltantes = [];

    print(\"=Ë Verificando NPUs fornecidos pelo Banco do Brasil:\");
    print(\"\");

    npusBB.forEach(function(npu) {
        var processo = db.processos.findOne({_id: npu});
        if (processo) {
            encontrados++;
            print(\" \" + npu + \" - OK\");
            print(\"   Relator: \" + (processo.relator || \"N/A\"));
            print(\"   Data autuação: \" + (processo.data_autuacao || \"N/A\"));
        } else {
            faltantes.push(npu);
            print(\"L \" + npu + \" - FALTANDO\");
        }
        print(\"\");
    });

    print(\"=Ê Resumo:\");
    print(\"   Encontrados: \" + encontrados + \"/\" + npusBB.length);
    print(\"   Faltantes: \" + faltantes.length + \"/\" + npusBB.length);

    if (faltantes.length > 0) {
        print(\"\");
        print(\"   NPUs faltantes:\");
        faltantes.forEach(function(npu) {
            print(\"   - \" + npu);
        });
        print(\"\");
        print(\"=¡ Para coletar NPUs faltantes:\");
        print(\"   ./scripts/run_npu.sh\");
    }
    "

    execute_query "<æ Verificação NPUs Banco do Brasil" "$query"
}

# Consulta 5: Análise de qualidade dos dados
query_data_quality() {
    local query='
    print("= ANÁLISE DE QUALIDADE DOS DADOS");
    print("PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP");
    print("");

    var totalProcessos = db.processos.countDocuments({});
    if (totalProcessos === 0) {
        print("L Nenhum processo para analisar");
        return;
    }

    print("=Ê Qualidade dos campos obrigatórios:");
    print("");

    // Verificar campos obrigatórios
    var semNumeroProcesso = db.processos.countDocuments({$or: [{numero_processo: null}, {numero_processo: ""}]});
    var semRelator = db.processos.countDocuments({$or: [{relator: null}, {relator: ""}]});
    var semDataAutuacao = db.processos.countDocuments({$or: [{data_autuacao: null}, {data_autuacao: ""}]});
    var semEnvolvidos = db.processos.countDocuments({$or: [{envolvidos: null}, {envolvidos: []}]});
    var semMovimentacoes = db.processos.countDocuments({$or: [{movimentacoes: null}, {movimentacoes: []}]});

    print(" numero_processo: " + (totalProcessos - semNumeroProcesso) + "/" + totalProcessos + " preenchidos");
    print(" relator: " + (totalProcessos - semRelator) + "/" + totalProcessos + " preenchidos");
    print(" data_autuacao: " + (totalProcessos - semDataAutuacao) + "/" + totalProcessos + " preenchidos");
    print(" envolvidos: " + (totalProcessos - semEnvolvidos) + "/" + totalProcessos + " com dados");
    print(" movimentacoes: " + (totalProcessos - semMovimentacoes) + "/" + totalProcessos + " com dados");

    print("");
    print("= Verificações de formato:");

    // Verificar formato de datas ISO
    var datasNaoISO = db.processos.countDocuments({
        data_autuacao: {$exists: true, $ne: null, $not: /^\d{4}-\d{2}-\d{2}/}
    });

    if (datasNaoISO === 0) {
        print(" Todas as datas de autuação estão em formato ISO-8601");
    } else {
        print("L " + datasNaoISO + " datas de autuação não estão em formato ISO-8601");
    }

    // Verificar relatores com prefixos não removidos
    var relatoresComPrefixo = db.processos.countDocuments({
        relator: {$regex: /^(Des\.|DESEMBARGADOR|JUIZ)/i}
    });

    if (relatoresComPrefixo === 0) {
        print(" Todos os relatores estão sem prefixos/títulos");
    } else {
        print("L " + relatoresComPrefixo + " relatores ainda contêm prefixos/títulos");

        print("");
        print("=Ý Exemplos de relatores com prefixo:");
        db.processos.find(
            {relator: {$regex: /^(Des\.|DESEMBARGADOR|JUIZ)/i}},
            {numero_processo: 1, relator: 1}
        ).limit(3).forEach(function(doc) {
            print("   " + doc.numero_processo + ": " + doc.relator);
        });
    }

    print("");
    print("=È Estatísticas de envolvidos:");
    var estatEnvolvidos = db.processos.aggregate([
        {$match: {envolvidos: {$ne: null, $ne: []}}},
        {$project: {count: {$size: "$envolvidos"}}},
        {$group: {
            _id: null,
            total: {$sum: 1},
            media: {$avg: "$count"},
            maximo: {$max: "$count"},
            minimo: {$min: "$count"}
        }}
    ]).toArray();

    if (estatEnvolvidos.length > 0) {
        var stat = estatEnvolvidos[0];
        print("   Processos com envolvidos: " + stat.total);
        print("   Média de envolvidos: " + Math.round(stat.media * 100) / 100);
        print("   Mínimo: " + stat.minimo + ", Máximo: " + stat.maximo);
    }

    print("");
    print("=È Estatísticas de movimentações:");
    var estatMovimentacoes = db.processos.aggregate([
        {$match: {movimentacoes: {$ne: null, $ne: []}}},
        {$project: {count: {$size: "$movimentacoes"}}},
        {$group: {
            _id: null,
            total: {$sum: 1},
            media: {$avg: "$count"},
            maximo: {$max: "$count"},
            minimo: {$min: "$count"}
        }}
    ]).toArray();

    if (estatMovimentacoes.length > 0) {
        var stat = estatMovimentacoes[0];
        print("   Processos com movimentações: " + stat.total);
        print("   Média de movimentações: " + Math.round(stat.media * 100) / 100);
        print("   Mínimo: " + stat.minimo + ", Máximo: " + stat.maximo);
    }
    '

    execute_query "= Análise de Qualidade dos Dados" "$query"
}

# Consulta 6: Estatísticas de descoberta por CNPJ
query_cnpj_discovery() {
    local query='
    print("<â DESCOBERTA POR CNPJ");
    print("PPPPPPPPPPPPPPPPPPPPPP");
    print("");

    // Verificar páginas coletadas via CNPJ
    var paginasCNPJ = db.raw_pages.countDocuments({"context.busca": "cnpj"});

    if (paginasCNPJ === 0) {
        print("L Nenhuma página coletada via busca por CNPJ");
        print("");
        print("=¡ Para executar descoberta por CNPJ:");
        print("   ./scripts/run_cnpj.sh");
        return;
    }

    print("=Ê Páginas coletadas via CNPJ: " + paginasCNPJ);
    print("");

    // Distribuição por tipo de página
    print("=Ä Distribuição por tipo:");
    db.raw_pages.aggregate([
        {$match: {"context.busca": "cnpj"}},
        {$group: {
            _id: "$context.tipo",
            count: {$sum: 1}
        }},
        {$sort: {_id: 1}}
    ]).forEach(function(doc) {
        print("   " + (doc._id || "undefined") + ": " + doc.count + " páginas");
    });

    // Verificar paginação detectada
    print("");
    print("=Ñ Análise de paginação:");
    var paginasLista = db.raw_pages.countDocuments({
        "context.busca": "cnpj",
        "context.tipo": "lista"
    });

    if (paginasLista > 0) {
        var paginasComIndice = db.raw_pages.countDocuments({
            "context.busca": "cnpj",
            "context.tipo": "lista",
            "context.page_idx": {$exists: true, $ne: null}
        });

        print("   Páginas de lista: " + paginasLista);
        print("   Com índice de página: " + paginasComIndice);

        if (paginasComIndice > 0) {
            var maxPageIdx = db.raw_pages.findOne(
                {"context.busca": "cnpj", "context.tipo": "lista"},
                {"context.page_idx": 1}
            ).context.page_idx;

            print("   Páginas navegadas: 0 até " + (maxPageIdx || 0));
        }
    }

    // Processos descobertos via CNPJ (aproximação)
    print("");
    print("–  Processos potencialmente descobertos via CNPJ:");
    var processosCNPJ = db.processos.countDocuments({});
    print("   Total de processos extraídos: " + processosCNPJ);
    print("   (Nota: Podem incluir NPUs coletados diretamente)");
    '

    execute_query "<â Descoberta por CNPJ" "$query"
}

# Função para mostrar ajuda
show_help() {
    echo "Uso: $0 [OPCAO]"
    echo ""
    echo "Executa consultas padronizadas no MongoDB do TRF5 Scraper"
    echo ""
    echo "Opções:"
    echo "  -a, --all         Executar todas as consultas (padrão)"
    echo "  -s, --stats       Apenas estatísticas gerais"
    echo "  -p, --pages       Apenas últimas páginas coletadas"
    echo "  -r, --processes   Apenas processos extraídos"
    echo "  -b, --bb-npus     Apenas verificação dos NPUs do BB"
    echo "  -q, --quality     Apenas análise de qualidade dos dados"
    echo "  -c, --cnpj        Apenas estatísticas de descoberta por CNPJ"
    echo "  -h, --help        Mostrar esta ajuda"
    echo ""
    echo "Variáveis de ambiente:"
    echo "  MONGO_URI         URI de conexão MongoDB (padrão: mongodb://localhost:27017)"
    echo "  MONGO_DB          Nome da base de dados (padrão: trf5)"
    echo ""
    echo "Exemplos:"
    echo "  $0                # Executar todas as consultas"
    echo "  $0 --stats        # Apenas estatísticas gerais"
    echo "  $0 --bb-npus      # Verificar NPUs do Banco do Brasil"
    echo ""
    echo "  MONGO_URI=mongodb://localhost:27017 $0  # Usar URI específica"
}

# Função principal
main() {
    local option="${1:-all}"

    # Verificar ajuda
    if [[ "$option" == "-h" ]] || [[ "$option" == "--help" ]]; then
        show_help
        exit 0
    fi

    echo "=================================="
    echo "TRF5 Scraper - Consultas MongoDB"
    echo "=================================="
    echo "Conectando em: $MONGO_URI/$MONGO_DB"
    echo ""

    # Verificar MongoDB
    check_mongodb

    # Executar consultas baseadas na opção
    case "$option" in
        -a|--all|all)
            query_general_stats
            query_recent_pages
            query_extracted_processes
            query_bb_npus
            query_data_quality
            query_cnpj_discovery
            ;;
        -s|--stats)
            query_general_stats
            ;;
        -p|--pages)
            query_recent_pages
            ;;
        -r|--processes)
            query_extracted_processes
            ;;
        -b|--bb-npus)
            query_bb_npus
            ;;
        -q|--quality)
            query_data_quality
            ;;
        -c|--cnpj)
            query_cnpj_discovery
            ;;
        *)
            warning "Opção desconhecida: $option"
            echo "Use $0 --help para ver as opções disponíveis"
            exit 1
            ;;
    esac

    echo ""
    echo ""
    echo ""
    success " Consultas concluídas com sucesso!"
    echo ""
    info "=¡ Dicas:"
    echo "  " Para conectar diretamente: mongosh \"$MONGO_URI/$MONGO_DB\""
    echo "  " Para executar consultas específicas: $0 --help"
    echo "  " Para coletar mais dados: ./scripts/run_npu.sh ou ./scripts/run_cnpj.sh"
}

# Executar função principal
main "$@"