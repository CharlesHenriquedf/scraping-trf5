#!/bin/bash

# =============================================================================
# TRF5 Scraper - Consultas MongoDB R�pidas
# =============================================================================
# Este script executa consultas padronizadas no MongoDB para verifica��o
# dos dados coletados pelo TRF5 Scraper

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configura��es
MONGO_URI=${MONGO_URI:-"mongodb://localhost:27017"}
MONGO_DB=${MONGO_DB:-"trf5"}

# NPUs do Banco do Brasil para verifica��o
NPUS_BB=(
    "0015648-78.1999.4.05.0000"
    "0012656-90.2012.4.05.0000"
    "0043753-74.2013.4.05.0000"
    "0002098-07.2011.4.05.8500"
    "0460674-33.2019.4.05.0000"
    "0000560-67.2017.4.05.0000"
)

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

info() {
    echo -e "${CYAN}9${NC} $1"
}

# Fun��o para verificar MongoDB
check_mongodb() {
    log "Verificando conectividade MongoDB..."

    if command -v mongosh &> /dev/null; then
        MONGO_CMD="mongosh"
    elif command -v mongo &> /dev/null; then
        MONGO_CMD="mongo"
    else
        warning "MongoDB client n�o encontrado (mongosh ou mongo)"
        echo "Para usar este script, instale o MongoDB client:"
        echo "  # Ubuntu/Debian"
        echo "  sudo apt install mongodb-clients"
        echo "  # ou baixe mongosh do site oficial do MongoDB"
        echo ""
        info "Pulando consultas MongoDB (cliente n�o disponível)"
        return 1
    fi

    # Testar conex�o
    if timeout 10 "$MONGO_CMD" \
        "$MONGO_URI" \
        --quiet \
        --eval "db.runCommand('ping')" &>/dev/null; then
        success "MongoDB conectado em $MONGO_URI"
        return 0
    else
        warning "MongoDB n�o acess�vel em $MONGO_URI"
        echo "Verifique se o MongoDB est� rodando:"
        echo "  docker ps | grep mongo"
        echo "  cd docker && docker compose up -d"
        echo ""
        info "Pulando consultas MongoDB (conex�o n�o disponível)"
        return 1
    fi
}

# Fun��o para executar consulta
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

# Consulta 1: Estat�sticas gerais
query_general_stats() {
    local query='
    print("=� ESTAT�STICAS GERAIS");
    print("PPPPPPPPPPPPPPPPPPPPPPP");
    print("");

    // Cole��es dispon�veis
    print("=�  Cole��es dispon�veis:");
    db.listCollections().forEach(function(collection) {
        var count = db[collection.name].countDocuments({});
        print("   " + collection.name + ": " + count + " documentos");
    });

    print("");

    // Estat�sticas de raw_pages
    print("=� Raw Pages (HTML bruto):");
    var rawStats = db.raw_pages.aggregate([
        {$group: {
            _id: "$context.tipo",
            count: {$sum: 1}
        }},
        {$sort: {_id: 1}}
    ]).toArray();

    rawStats.forEach(function(stat) {
        print("   " + (stat._id || "undefined") + ": " + stat.count + " p�ginas");
    });

    var totalRaw = db.raw_pages.countDocuments({});
    print("   Total: " + totalRaw + " p�ginas HTML salvas");

    print("");

    // Estat�sticas de processos
    print("�  Processos estruturados:");
    var totalProcessos = db.processos.countDocuments({});
    print("   Total: " + totalProcessos + " processos extra�dos");

    if (totalProcessos > 0) {
        var comRelator = db.processos.countDocuments({relator: {$ne: null, $ne: ""}});
        var comEnvolvidos = db.processos.countDocuments({envolvidos: {$ne: null, $ne: []}});
        var comMovimentacoes = db.processos.countDocuments({movimentacoes: {$ne: null, $ne: []}});

        print("   Com relator: " + comRelator + " (" + Math.round(comRelator*100/totalProcessos) + "%)");
        print("   Com envolvidos: " + comEnvolvidos + " (" + Math.round(comEnvolvidos*100/totalProcessos) + "%)");
        print("   Com movimenta��es: " + comMovimentacoes + " (" + Math.round(comMovimentacoes*100/totalProcessos) + "%)");
    }
    '

    execute_query "=� Estat�sticas Gerais" "$query"
}

# Consulta 2: �ltimas p�ginas coletadas
query_recent_pages() {
    local query='
    print("=R �LTIMAS P�GINAS COLETADAS");
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
        var pageIdx = doc.context.page_idx !== undefined ? " (p�g " + doc.context.page_idx + ")" : "";
        var timestamp = doc.fetched_at || "N/A";

        print("< " + tipo + " | " + busca + " | " + identificador + pageIdx);
        print("   URL: " + (doc.url || "N/A"));
        print("   Coletado: " + timestamp);
        print("");
    });
    '

    execute_query "=R �ltimas P�ginas Coletadas" "$query"
}

# Consulta 3: Processos extra�dos
query_extracted_processes() {
    local query='
    print("�  PROCESSOS EXTRA�DOS");
    print("PPPPPPPPPPPPPPPPPPPPPPP");
    print("");

    var totalProcessos = db.processos.countDocuments({});
    if (totalProcessos === 0) {
        print("L Nenhum processo encontrado na cole��o processos");
        return;
    }

    print("=� �ltimos 5 processos extra�dos:");
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
        print("=� " + (doc.numero_processo || doc._id));
        print("   Relator: " + (doc.relator || "N/A"));
        print("   Data autua��o: " + (doc.data_autuacao || "N/A"));

        if (doc.envolvidos && doc.envolvidos.length > 0) {
            print("   Primeiro envolvido: " + doc.envolvidos[0].papel + " - " + doc.envolvidos[0].nome);
        } else {
            print("   Envolvidos: N/A");
        }

        if (doc.movimentacoes && doc.movimentacoes.length > 0) {
            print("   �ltima movimenta��o: " + doc.movimentacoes[0].data);
        } else {
            print("   Movimenta��es: N/A");
        }

        print("   Extra�do em: " + (doc.scraped_at || "N/A"));
        print("");
    });
    '

    execute_query "� Processos Extra�dos" "$query"
}

# Consulta 4: Verificar NPUs do Banco do Brasil
query_bb_npus() {
    local npus_array=$(printf '"%s",' "${NPUS_BB[@]}")
    npus_array="[${npus_array%,}]"

    local query="
    print(\"<� VERIFICA��O NPUs BANCO DO BRASIL\");
    print(\"PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP\");
    print(\"\");

    var npusBB = $npus_array;
    var encontrados = 0;
    var faltantes = [];

    print(\"=� Verificando NPUs fornecidos pelo Banco do Brasil:\");
    print(\"\");

    npusBB.forEach(function(npu) {
        var processo = db.processos.findOne({_id: npu});
        if (processo) {
            encontrados++;
            print(\" \" + npu + \" - OK\");
            print(\"   Relator: \" + (processo.relator || \"N/A\"));
            print(\"   Data autua��o: \" + (processo.data_autuacao || \"N/A\"));
        } else {
            faltantes.push(npu);
            print(\"L \" + npu + \" - FALTANDO\");
        }
        print(\"\");
    });

    print(\"=� Resumo:\");
    print(\"   Encontrados: \" + encontrados + \"/\" + npusBB.length);
    print(\"   Faltantes: \" + faltantes.length + \"/\" + npusBB.length);

    if (faltantes.length > 0) {
        print(\"\");
        print(\"�  NPUs faltantes:\");
        faltantes.forEach(function(npu) {
            print(\"   - \" + npu);
        });
        print(\"\");
        print(\"=� Para coletar NPUs faltantes:\");
        print(\"   ./scripts/run_npu.sh\");
    }
    "

    execute_query "<� Verifica��o NPUs Banco do Brasil" "$query"
}

# Consulta 5: An�lise de qualidade dos dados
query_data_quality() {
    local query='
    print("= AN�LISE DE QUALIDADE DOS DADOS");
    print("PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP");
    print("");

    var totalProcessos = db.processos.countDocuments({});
    if (totalProcessos === 0) {
        print("L Nenhum processo para analisar");
        return;
    }

    print("=� Qualidade dos campos obrigat�rios:");
    print("");

    // Verificar campos obrigat�rios
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
    print("= Verifica��es de formato:");

    // Verificar formato de datas ISO
    var datasNaoISO = db.processos.countDocuments({
        data_autuacao: {$exists: true, $ne: null, $not: /^\d{4}-\d{2}-\d{2}/}
    });

    if (datasNaoISO === 0) {
        print(" Todas as datas de autua��o est�o em formato ISO-8601");
    } else {
        print("L " + datasNaoISO + " datas de autua��o n�o est�o em formato ISO-8601");
    }

    // Verificar relatores com prefixos n�o removidos
    var relatoresComPrefixo = db.processos.countDocuments({
        relator: {$regex: /^(Des\.|DESEMBARGADOR|JUIZ)/i}
    });

    if (relatoresComPrefixo === 0) {
        print(" Todos os relatores est�o sem prefixos/t�tulos");
    } else {
        print("L " + relatoresComPrefixo + " relatores ainda cont�m prefixos/t�tulos");

        print("");
        print("=� Exemplos de relatores com prefixo:");
        db.processos.find(
            {relator: {$regex: /^(Des\.|DESEMBARGADOR|JUIZ)/i}},
            {numero_processo: 1, relator: 1}
        ).limit(3).forEach(function(doc) {
            print("   " + doc.numero_processo + ": " + doc.relator);
        });
    }

    print("");
    print("=� Estat�sticas de envolvidos:");
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
        print("   M�dia de envolvidos: " + Math.round(stat.media * 100) / 100);
        print("   M�nimo: " + stat.minimo + ", M�ximo: " + stat.maximo);
    }

    print("");
    print("=� Estat�sticas de movimenta��es:");
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
        print("   Processos com movimenta��es: " + stat.total);
        print("   M�dia de movimenta��es: " + Math.round(stat.media * 100) / 100);
        print("   M�nimo: " + stat.minimo + ", M�ximo: " + stat.maximo);
    }
    '

    execute_query "= An�lise de Qualidade dos Dados" "$query"
}

# Consulta 6: Estat�sticas de descoberta por CNPJ
query_cnpj_discovery() {
    local query='
    print("<� DESCOBERTA POR CNPJ");
    print("PPPPPPPPPPPPPPPPPPPPPP");
    print("");

    // Verificar p�ginas coletadas via CNPJ
    var paginasCNPJ = db.raw_pages.countDocuments({"context.busca": "cnpj"});

    if (paginasCNPJ === 0) {
        print("L Nenhuma p�gina coletada via busca por CNPJ");
        print("");
        print("=� Para executar descoberta por CNPJ:");
        print("   ./scripts/run_cnpj.sh");
        return;
    }

    print("=� P�ginas coletadas via CNPJ: " + paginasCNPJ);
    print("");

    // Distribui��o por tipo de p�gina
    print("=� Distribui��o por tipo:");
    db.raw_pages.aggregate([
        {$match: {"context.busca": "cnpj"}},
        {$group: {
            _id: "$context.tipo",
            count: {$sum: 1}
        }},
        {$sort: {_id: 1}}
    ]).forEach(function(doc) {
        print("   " + (doc._id || "undefined") + ": " + doc.count + " p�ginas");
    });

    // Verificar pagina��o detectada
    print("");
    print("=� An�lise de pagina��o:");
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

        print("   P�ginas de lista: " + paginasLista);
        print("   Com �ndice de p�gina: " + paginasComIndice);

        if (paginasComIndice > 0) {
            var maxPageIdx = db.raw_pages.findOne(
                {"context.busca": "cnpj", "context.tipo": "lista"},
                {"context.page_idx": 1}
            ).context.page_idx;

            print("   P�ginas navegadas: 0 at� " + (maxPageIdx || 0));
        }
    }

    // Processos descobertos via CNPJ (aproxima��o)
    print("");
    print("�  Processos potencialmente descobertos via CNPJ:");
    var processosCNPJ = db.processos.countDocuments({});
    print("   Total de processos extra�dos: " + processosCNPJ);
    print("   (Nota: Podem incluir NPUs coletados diretamente)");
    '

    execute_query "<� Descoberta por CNPJ" "$query"
}

# Fun��o para mostrar ajuda
show_help() {
    echo "Uso: $0 [OPCAO]"
    echo ""
    echo "Executa consultas padronizadas no MongoDB do TRF5 Scraper"
    echo ""
    echo "Op��es:"
    echo "  -a, --all         Executar todas as consultas (padr�o)"
    echo "  -s, --stats       Apenas estat�sticas gerais"
    echo "  -p, --pages       Apenas �ltimas p�ginas coletadas"
    echo "  -r, --processes   Apenas processos extra�dos"
    echo "  -b, --bb-npus     Apenas verifica��o dos NPUs do BB"
    echo "  -q, --quality     Apenas an�lise de qualidade dos dados"
    echo "  -c, --cnpj        Apenas estat�sticas de descoberta por CNPJ"
    echo "  -h, --help        Mostrar esta ajuda"
    echo ""
    echo "Vari�veis de ambiente:"
    echo "  MONGO_URI         URI de conex�o MongoDB (padr�o: mongodb://localhost:27017)"
    echo "  MONGO_DB          Nome da base de dados (padr�o: trf5)"
    echo ""
    echo "Exemplos:"
    echo "  $0                # Executar todas as consultas"
    echo "  $0 --stats        # Apenas estat�sticas gerais"
    echo "  $0 --bb-npus      # Verificar NPUs do Banco do Brasil"
    echo ""
    echo "  MONGO_URI=mongodb://localhost:27017 $0  # Usar URI espec�fica"
}

# Fun��o principal
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
        warning "Consultas MongoDB n�o podem ser executadas (depend�ncias n�o disponíveis)"
        echo ""
        info "Para usar este script, certifique-se de que:"
        echo "  1. mongosh ou mongo est�o instalados"
        echo "  2. MongoDB est� rodando e acess�vel"
        echo ""
        exit 0
    fi

    # Executar consultas baseadas na op��o
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
            warning "Op��o desconhecida: $option"
            echo "Use $0 --help para ver as op��es dispon�veis"
            exit 1
            ;;
    esac

    echo ""
    echo ""
    echo ""
    success " Consultas conclu�das com sucesso!"
    echo ""
    info "=� Dicas:"
    echo "  Para conectar diretamente: mongosh \"$MONGO_URI/$MONGO_DB\""
    echo "  Para executar consultas espec�ficas: $0 --help"
    echo "  Para coletar mais dados: ./scripts/run_npu.sh ou ./scripts/run_cnpj.sh"
}

# Executar fun��o principal
main "$@"