#!/bin/bash

# =============================================================================
# TRF5 Scraper - Consultas MongoDB Rapidas
# =============================================================================
# Este script executa consultas padronizadas no MongoDB para verificacao
# dos dados coletados pelo TRF5 Scraper

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuracoes
MONGO_URI=${MONGO_URI:-"mongodb://localhost:27017"}
MONGO_DB=${MONGO_DB:-"trf5"}

# NPUs do Banco do Brasil para verificacao
NPUS_BB=(
    "0015648-78.1999.4.05.0000"
    "0012656-90.2012.4.05.0000"
    "0043753-74.2013.4.05.0000"
    "0002098-07.2011.4.05.8500"
    "0460674-33.2019.4.05.0000"
    "0000560-67.2017.4.05.0000"
)

# Funcao para logging
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
    echo -e "${YELLOW}a${NC} $1"
}

info() {
    echo -e "${CYAN}9${NC} $1"
}

# Funcao para verificar MongoDB
check_mongodb() {
    log "Verificando conectividade MongoDB..."

    if command -v mongosh &> /dev/null; then
        MONGO_CMD="mongosh"
    elif command -v mongo &> /dev/null; then
        MONGO_CMD="mongo"
    else
        warning "MongoDB client nao encontrado (mongosh ou mongo)"
        echo "Para usar este script, instale o MongoDB client:"
        echo "  # Ubuntu/Debian"
        echo "  sudo apt install mongodb-clients"
        echo "  # ou baixe mongosh do site oficial do MongoDB"
        echo ""
        info "Pulando consultas MongoDB (cliente nao disponivel)"
        return 1
    fi

    # Testar conexao
    if timeout 10 "$MONGO_CMD" \
        "$MONGO_URI" \
        --quiet \
        --eval "db.runCommand('ping')" &>/dev/null; then
        success "MongoDB conectado em $MONGO_URI"
        return 0
    else
        warning "MongoDB nao acessivel em $MONGO_URI"
        echo "Verifique se o MongoDB esta rodando:"
        echo "  docker ps | grep mongo"
        echo "  cd docker && docker compose up -d"
        echo ""
        info "Pulando consultas MongoDB (conexao nao disponivel)"
        return 1
    fi
}

# Funcao para executar consulta
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

# Consulta 1: Estatisticas gerais
query_general_stats() {
    local query='
    print("» ESTATISTICAS GERAIS");
    print("PPPPPPPPPPPPPPPPPPPPPPP");
    print("");

    // Colecoes disponiveis
    print("»  Colecoes disponiveis:");
    db.listCollections().forEach(function(collection) {
        var count = db[collection.name].countDocuments({});
        print("   " + collection.name + ": " + count + " documentos");
    });

    print("");

    // Estatisticas de raw_pages
    print("» Raw Pages (HTML bruto):");
    var rawStats = db.raw_pages.aggregate([
        {$group: {
            _id: "$context.tipo",
            count: {$sum: 1}
        }},
        {$sort: {_id: 1}}
    ]).toArray();

    rawStats.forEach(function(stat) {
        print("   " + (stat._id || "undefined") + ": " + stat.count + " paginas");
    });

    var totalRaw = db.raw_pages.countDocuments({});
    print("   Total: " + totalRaw + " paginas HTML salvas");

    print("");

    // Estatisticas de processos
    print("a  Processos estruturados:");
    var totalProcessos = db.processos.countDocuments({});
    print("   Total: " + totalProcessos + " processos extraidos");

    if (totalProcessos > 0) {
        var comRelator = db.processos.countDocuments({relator: {$ne: null, $ne: ""}});
        var comEnvolvidos = db.processos.countDocuments({envolvidos: {$ne: null, $ne: []}});
        var comMovimentacoes = db.processos.countDocuments({movimentacoes: {$ne: null, $ne: []}});

        print("   Com relator: " + comRelator + " (" + Math.round(comRelator*100/totalProcessos) + "%)");
        print("   Com envolvidos: " + comEnvolvidos + " (" + Math.round(comEnvolvidos*100/totalProcessos) + "%)");
        print("   Com movimentaes: " + comMovimentacoes + " (" + Math.round(comMovimentacoes*100/totalProcessos) + "%)");
    }
    '

    execute_query "» Estatisticas Gerais" "$query"
}

# Consulta 2: Ultimas paginas coletadas
query_recent_pages() {
    local query='
    print("=R ULTIMAS PAGINAS COLETADAS");
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
        var pageIdx = doc.context.page_idx !== undefined ? " (pag " + doc.context.page_idx + ")" : "";
        var timestamp = doc.fetched_at || "N/A";

        print("< " + tipo + " | " + busca + " | " + identificador + pageIdx);
        print("   URL: " + (doc.url || "N/A"));
        print("   Coletado: " + timestamp);
        print("");
    });
    '

    execute_query "=R Ultimas Paginas Coletadas" "$query"
}

# Consulta 3: Processos extraidos
query_extracted_processes() {
    local query='
    print("a  PROCESSOS EXTRAIDOS");
    print("PPPPPPPPPPPPPPPPPPPPPPP");
    print("");

    var totalProcessos = db.processos.countDocuments({});
    if (totalProcessos === 0) {
        print("L Nenhum processo encontrado na colecao processos");
        return;
    }

    print("» ultimos 5 processos extraidos:");
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
        print("» " + (doc.numero_processo || doc._id));
        print("   Relator: " + (doc.relator || "N/A"));
        print("   Data autuacao: " + (doc.data_autuacao || "N/A"));

        if (doc.envolvidos && doc.envolvidos.length > 0) {
            print("   Primeiro envolvido: " + doc.envolvidos[0].papel + " - " + doc.envolvidos[0].nome);
        } else {
            print("   Envolvidos: N/A");
        }

        if (doc.movimentacoes && doc.movimentacoes.length > 0) {
            print("   ultima movimentacao: " + doc.movimentacoes[0].data);
        } else {
            print("   Movimentacoes: N/A");
        }

        print("   Extraido em: " + (doc.scraped_at || "N/A"));
        print("");
    });
    '

    execute_query "a Processos Extraidos" "$query"
}

# Consulta 4: Verificar NPUs do Banco do Brasil
query_bb_npus() {
    local npus_array=$(printf '"%s",' "${NPUS_BB[@]}")
    npus_array="[${npus_array%,}]"

    local query="
    print(\"<a VERIFICACAO NPUs BANCO DO BRASIL\");
    print(\"PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP\");
    print(\"\");

    var npusBB = $npus_array;
    var encontrados = 0;
    var faltantes = [];

    print(\"» Verificando NPUs fornecidos pelo Banco do Brasil:\");
    print(\"\");

    npusBB.forEach(function(npu) {
        var processo = db.processos.findOne({_id: npu});
        if (processo) {
            encontrados++;
            print(\" \" + npu + \" - OK\");
            print(\"   Relator: \" + (processo.relator || \"N/A\"));
            print(\"   Data autuacao: \" + (processo.data_autuacao || \"N/A\"));
        } else {
            faltantes.push(npu);
            print(\"L \" + npu + \" - FALTANDO\");
        }
        print(\"\");
    });

    print(\"» Resumo:\");
    print(\"   Encontrados: \" + encontrados + \"/\" + npusBB.length);
    print(\"   Faltantes: \" + faltantes.length + \"/\" + npusBB.length);

    if (faltantes.length > 0) {
        print(\"\");
        print(\"a  NPUs faltantes:\");
        faltantes.forEach(function(npu) {
            print(\"   - \" + npu);
        });
        print(\"\");
        print(\"» Para coletar NPUs faltantes:\");
        print(\"   ./scripts/run_npu.sh\");
    }
    "

    execute_query "<a Verificao NPUs Banco do Brasil" "$query"
}

# Consulta 5: Analise de qualidade dos dados
query_data_quality() {
    local query='
    print("= ANaLISE DE QUALIDADE DOS DADOS");
    print("PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP");
    print("");

    var totalProcessos = db.processos.countDocuments({});
    if (totalProcessos === 0) {
        print("L Nenhum processo para analisar");
        return;
    }

    print("» Qualidade dos campos obrigatorios:");
    print("");

    // Verificar campos obrigatorios
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
    print("= Verificacoes de formato:");

    // Verificar formato de datas ISO
    var datasNaoISO = db.processos.countDocuments({
        data_autuacao: {$exists: true, $ne: null, $not: /^\d{4}-\d{2}-\d{2}/}
    });

    if (datasNaoISO === 0) {
        print(" Todas as datas de autuacao estao em formato ISO-8601");
    } else {
        print("L " + datasNaoISO + " datas de autuacao nao estao em formato ISO-8601");
    }

    // Verificar relatores com prefixos nao removidos
    var relatoresComPrefixo = db.processos.countDocuments({
        relator: {$regex: /^(Des\.|DESEMBARGADOR|JUIZ)/i}
    });

    if (relatoresComPrefixo === 0) {
        print(" Todos os relatores estao sem prefixos/titulos");
    } else {
        print("L " + relatoresComPrefixo + " relatores ainda contem prefixos/titulos");

        print("");
        print("» Exemplos de relatores com prefixo:");
        db.processos.find(
            {relator: {$regex: /^(Des\.|DESEMBARGADOR|JUIZ)/i}},
            {numero_processo: 1, relator: 1}
        ).limit(3).forEach(function(doc) {
            print("   " + doc.numero_processo + ": " + doc.relator);
        });
    }

    print("");
    print("» Estatisticas de envolvidos:");
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
        print("   Media de envolvidos: " + Math.round(stat.media * 100) / 100);
        print("   Minimo: " + stat.minimo + ", Maximo: " + stat.maximo);
    }

    print("");
    print("» Estatisticas de movimentaes:");
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
        print("   Processos com movimentaes: " + stat.total);
        print("   Media de movimentaes: " + Math.round(stat.media * 100) / 100);
        print("   Minimo: " + stat.minimo + ", Maximo: " + stat.maximo);
    }
    '

    execute_query "= Analise de Qualidade dos Dados" "$query"
}

# Consulta 6: Estatisticas de descoberta por CNPJ
query_cnpj_discovery() {
    local query='
    print("<a DESCOBERTA POR CNPJ");
    print("PPPPPPPPPPPPPPPPPPPPPP");
    print("");

    // Verificar paginas coletadas via CNPJ
    var paginasCNPJ = db.raw_pages.countDocuments({"context.busca": "cnpj"});

    if (paginasCNPJ === 0) {
        print("L Nenhuma pagina coletada via busca por CNPJ");
        print("");
        print("» Para executar descoberta por CNPJ:");
        print("   ./scripts/run_cnpj.sh");
        return;
    }

    print("» Paginas coletadas via CNPJ: " + paginasCNPJ);
    print("");

    // Distribuicao por tipo de pagina
    print("» Distribuicao por tipo:");
    db.raw_pages.aggregate([
        {$match: {"context.busca": "cnpj"}},
        {$group: {
            _id: "$context.tipo",
            count: {$sum: 1}
        }},
        {$sort: {_id: 1}}
    ]).forEach(function(doc) {
        print("   " + (doc._id || "undefined") + ": " + doc.count + " paginas");
    });

    // Verificar paginacao detectada
    print("");
    print("» Analise de paginacao:");
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

        print("   Paginas de lista: " + paginasLista);
        print("   Com indice de pagina: " + paginasComIndice);

        if (paginasComIndice > 0) {
            var maxPageIdx = db.raw_pages.findOne(
                {"context.busca": "cnpj", "context.tipo": "lista"},
                {"context.page_idx": 1}
            ).context.page_idx;

            print("   Paginas navegadas: 0 ate " + (maxPageIdx || 0));
        }
    }

    // Processos descobertos via CNPJ (aproximacao)
    print("");
    print("a  Processos potencialmente descobertos via CNPJ:");
    var processosCNPJ = db.processos.countDocuments({});
    print("   Total de processos extraidos: " + processosCNPJ);
    print("   (Nota: Podem incluir NPUs coletados diretamente)");
    '

    execute_query "<a Descoberta por CNPJ" "$query"
}

# Funcao para mostrar ajuda
show_help() {
    echo "Uso: $0 [OPCAO]"
    echo ""
    echo "Executa consultas padronizadas no MongoDB do TRF5 Scraper"
    echo ""
    echo "Opcoes:"
    echo "  -a, --all         Executar todas as consultas (padrao)"
    echo "  -s, --stats       Apenas estatisticas gerais"
    echo "  -p, --pages       Apenas Ultimas paginas coletadas"
    echo "  -r, --processes   Apenas processos extraidos"
    echo "  -b, --bb-npus     Apenas verificacao dos NPUs do BB"
    echo "  -q, --quality     Apenas analise de qualidade dos dados"
    echo "  -c, --cnpj        Apenas estatisticas de descoberta por CNPJ"
    echo "  -h, --help        Mostrar esta ajuda"
    echo ""
    echo "Variaveis de ambiente:"
    echo "  MONGO_URI         URI de conexao MongoDB (padrao: mongodb://localhost:27017)"
    echo "  MONGO_DB          Nome da base de dados (padrao: trf5)"
    echo ""
    echo "Exemplos:"
    echo "  $0                # Executar todas as consultas"
    echo "  $0 --stats        # Apenas estatisticas gerais"
    echo "  $0 --bb-npus      # Verificar NPUs do Banco do Brasil"
    echo ""
    echo "  MONGO_URI=mongodb://localhost:27017 $0  # Usar URI especifica"
}

# Funcao principal
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
    if ! check_mongodb; then
        echo ""
        warning "Consultas MongoDB nao podem ser executadas (dependencias nao disponiveis)"
        echo ""
        info "Para usar este script, certifique-se de que:"
        echo "  1. mongosh ou mongo estao instalados"
        echo "  2. MongoDB esta rodando e acessivel"
        echo ""
        exit 0
    fi

    # Executar consultas baseadas na opaao
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
            warning "Opcao desconhecida: $option"
            echo "Use $0 --help para ver as opcoes disponiveis"
            exit 1
            ;;
    esac

    echo ""
    echo ""
    echo ""
    success " Consultas concluidas com sucesso!"
    echo ""
    info "» Dicas:"
    echo "  Para conectar diretamente: mongosh \"$MONGO_URI/$MONGO_DB\""
    echo "  Para executar consultas especificas: $0 --help"
    echo "  Para coletar mais dados: ./scripts/run_npu.sh ou ./scripts/run_cnpj.sh"
}

# Executar funcao principal
main "$@"