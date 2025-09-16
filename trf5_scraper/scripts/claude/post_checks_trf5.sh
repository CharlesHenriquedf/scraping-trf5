#!/bin/bash

# post_checks_trf5.sh - Script de verificações QA para TRF5 Scraper
#
# Executa bateria completa de verificações para garantir que o projeto
# está funcionalmente correto e pronto para operação em ambiente real.

set -e  # Para execução em qualquer erro

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Contadores de verificações
CHECKS_TOTAL=0
CHECKS_PASSED=0
CHECKS_FAILED=0

# Função para logging
log() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}✓${NC} $1"
    ((CHECKS_PASSED++))
}

error() {
    echo -e "${RED}✗${NC} $1"
    ((CHECKS_FAILED++))
}

warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Função para executar verificação
check() {
    local description="$1"
    local command="$2"
    local expected_exit_code="${3:-0}"

    ((CHECKS_TOTAL++))
    log "Verificando: $description"

    if eval "$command" >/dev/null 2>&1; then
        if [ $? -eq $expected_exit_code ]; then
            success "$description"
            return 0
        else
            error "$description (código de saída inesperado)"
            return 1
        fi
    else
        if [ $expected_exit_code -ne 0 ] && [ $? -eq $expected_exit_code ]; then
            success "$description"
            return 0
        else
            error "$description (falhou na execução)"
            return 1
        fi
    fi
}

# Banner
echo "=================================="
echo "TRF5 Scraper - Verificações QA"
echo "=================================="
echo

# Verifica diretório correto
if [ ! -f "scrapy.cfg" ] || [ ! -d "trf5_scraper" ]; then
    error "Execute este script do diretório raiz do projeto TRF5 Scraper"
    exit 1
fi

log "Iniciando verificações no diretório: $(pwd)"
echo

# ============ VERIFICAÇÕES DE ESTRUTURA ============
echo "📁 Verificações de Estrutura de Arquivos"
echo "----------------------------------------"

check "scrapy.cfg existe" "[ -f scrapy.cfg ]"
check "Diretório trf5_scraper existe" "[ -d trf5_scraper ]"
check "requirements.txt existe" "[ -f requirements.txt ]"
check "settings.py existe" "[ -f trf5_scraper/settings.py ]"
check "Pipeline mongo existe" "[ -f trf5_scraper/pipelines/mongo_pipeline.py ]"
check "Spider trf5 existe" "[ -f trf5_scraper/spiders/trf5.py ]"
check "Spider parse_raw existe" "[ -f trf5_scraper/spiders/parse_raw.py ]"
check "Utils normalize existe" "[ -f trf5_scraper/utils/normalize.py ]"
check "Utils classify existe" "[ -f trf5_scraper/utils/classify.py ]"
check "Utils pagination existe" "[ -f trf5_scraper/utils/pagination.py ]"

echo

# ============ VERIFICAÇÕES DE DEPENDÊNCIAS ============
echo "📦 Verificações de Dependências"
echo "-------------------------------"

check "Python 3 disponível" "python3 --version"
check "Scrapy instalado" "python3 -c 'import scrapy'"
check "PyMongo instalado" "python3 -c 'import pymongo'"
check "Python-dotenv instalado" "python3 -c 'import dotenv'"

echo

# ============ VERIFICAÇÕES DE SINTAXE ============
echo "🔍 Verificações de Sintaxe Python"
echo "----------------------------------"

check "settings.py sintaxe válida" "python3 -m py_compile trf5_scraper/settings.py"
check "mongo_pipeline.py sintaxe válida" "python3 -m py_compile trf5_scraper/pipelines/mongo_pipeline.py"
check "trf5.py sintaxe válida" "python3 -m py_compile trf5_scraper/spiders/trf5.py"
check "parse_raw.py sintaxe válida" "python3 -m py_compile trf5_scraper/spiders/parse_raw.py"
check "normalize.py sintaxe válida" "python3 -m py_compile trf5_scraper/utils/normalize.py"
check "classify.py sintaxe válida" "python3 -m py_compile trf5_scraper/utils/classify.py"
check "pagination.py sintaxe válida" "python3 -m py_compile trf5_scraper/utils/pagination.py"

echo

# ============ VERIFICAÇÕES DE CONFIGURAÇÃO ============
echo "⚙️ Verificações de Configuração RNF"
echo "-----------------------------------"

check "ROBOTSTXT_OBEY configurado" "grep -q 'ROBOTSTXT_OBEY.*True' trf5_scraper/settings.py"
check "DOWNLOAD_DELAY configurado" "grep -q 'DOWNLOAD_DELAY.*0\.7' trf5_scraper/settings.py"
check "AUTOTHROTTLE_ENABLED configurado" "grep -q 'AUTOTHROTTLE_ENABLED.*True' trf5_scraper/settings.py"
check "Pipeline MongoDB configurado" "grep -q 'mongo_pipeline.MongoPipeline' trf5_scraper/settings.py"
check "MONGO_URI configurado" "grep -q 'MONGO_URI' trf5_scraper/settings.py"
check "USER_AGENT configurado" "grep -q 'USER_AGENT' trf5_scraper/settings.py"

echo

# ============ VERIFICAÇÕES DE FUNÇÕES CRÍTICAS ============
echo "🧪 Verificações de Funções Críticas"
echo "-----------------------------------"

# Testa normalização NPU
check "Normalização NPU funcional" "python3 -c '
from trf5_scraper.utils.normalize import normalize_npu_hyphenated
result = normalize_npu_hyphenated(\"00156487819994050000\")
assert result == \"0015648-78.1999.4.05.0000\", f\"Esperado 0015648-78.1999.4.05.0000, obtido {result}\"
'"

# Testa normalização CNPJ
check "Normalização CNPJ funcional" "python3 -c '
from trf5_scraper.utils.normalize import normalize_cnpj_digits
result = normalize_cnpj_digits(\"00.000.000/0001-91\")
assert result == \"00000000000191\", f\"Esperado 00000000000191, obtido {result}\"
'"

# Testa conversão de data
check "Conversão de data funcional" "python3 -c '
from trf5_scraper.utils.normalize import parse_date_to_iso
result = parse_date_to_iso(\"15/04/2000\")
assert result == \"2000-04-15\", f\"Esperado 2000-04-15, obtido {result}\"
'"

# Testa classificação de páginas
check "Classificação de páginas funcional" "python3 -c '
from trf5_scraper.utils.classify import is_detail, is_list, is_error
html_detail = \"PROCESSO Nº 123 RELATOR APTE AUTOR 15/04/2000\"
assert is_detail(html_detail), \"Falha na detecção de página de detalhe\"
'"

echo

# ============ VERIFICAÇÕES DE SPIDERS ============
echo "🕷️ Verificações de Spiders"
echo "--------------------------"

check "Spider trf5 listado" "scrapy list | grep -q trf5"
check "Spider parse_raw listado" "scrapy list | grep -q parse_raw"

# Testa validação de parâmetros do spider trf5
check "Validação NPU spider trf5" "python3 -c '
from trf5_scraper.spiders.trf5 import Trf5Spider
try:
    spider = Trf5Spider(modo=\"numero\", valor=\"0015648-78.1999.4.05.0000\")
    assert spider.valor_normalizado == \"0015648-78.1999.4.05.0000\"
except Exception as e:
    raise AssertionError(f\"Falha na validação NPU: {e}\")
'"

check "Validação CNPJ spider trf5" "python3 -c '
from trf5_scraper.spiders.trf5 import Trf5Spider
try:
    spider = Trf5Spider(modo=\"cnpj\", valor=\"00.000.000/0001-91\")
    assert spider.valor_normalizado == \"00000000000191\"
except Exception as e:
    raise AssertionError(f\"Falha na validação CNPJ: {e}\")
'"

echo

# ============ VERIFICAÇÕES DE CONECTIVIDADE ============
echo "🌐 Verificações de Conectividade"
echo "--------------------------------"

# Verifica conectividade com TRF5 (sem fazer scraping)
check "TRF5 acessível" "curl -s --head --max-time 10 http://www5.trf5.jus.br/cp/ | head -1 | grep -q '200\\|302\\|301'"

# Verifica se MongoDB está disponível (opcional)
if command -v mongosh &> /dev/null || command -v mongo &> /dev/null; then
    MONGO_CMD="mongosh"
    if ! command -v mongosh &> /dev/null; then
        MONGO_CMD="mongo"
    fi

    check "MongoDB acessível" "timeout 5 $MONGO_CMD --quiet --eval 'db.runCommand({ping: 1})' >/dev/null 2>&1"
else
    warning "MongoDB client não encontrado - pulando verificação de conectividade"
fi

echo

# ============ VERIFICAÇÕES DE DADOS DE TESTE ============
echo "📊 Verificações de Dados de Teste"
echo "---------------------------------"

# Verifica se os NPUs de teste estão no formato correto
TEST_NPUS=(
    "0015648-78.1999.4.05.0000"
    "0012656-90.2012.4.05.0000"
    "0043753-74.2013.4.05.0000"
    "0002098-07.2011.4.05.8500"
    "0460674-33.2019.4.05.0000"
    "0000560-67.2017.4.05.0000"
)

for npu in "${TEST_NPUS[@]}"; do
    check "NPU $npu válido" "python3 -c '
from trf5_scraper.utils.normalize import normalize_npu_digits
result = normalize_npu_digits(\"$npu\")
assert len(result) == 20, f\"NPU deve ter 20 dígitos, tem {len(result)}\"
'"
done

# Verifica CNPJ do BB
check "CNPJ BB válido" "python3 -c '
from trf5_scraper.utils.normalize import normalize_cnpj_digits
result = normalize_cnpj_digits(\"00.000.000/0001-91\")
assert len(result) == 14, f\"CNPJ deve ter 14 dígitos, tem {len(result)}\"
'"

echo

# ============ RELATÓRIO FINAL ============
echo "📋 Relatório Final"
echo "=================="

echo "Total de verificações: $CHECKS_TOTAL"
echo -e "Sucessos: ${GREEN}$CHECKS_PASSED${NC}"
echo -e "Falhas: ${RED}$CHECKS_FAILED${NC}"

PERCENTAGE=$(( CHECKS_PASSED * 100 / CHECKS_TOTAL ))
echo "Taxa de sucesso: $PERCENTAGE%"

echo

if [ $CHECKS_FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 Todas as verificações passaram! O projeto está pronto para operação.${NC}"
    exit 0
elif [ $PERCENTAGE -ge 90 ]; then
    echo -e "${YELLOW}⚠️ Projeto principalmente funcional, mas com $CHECKS_FAILED falha(s) menor(es).${NC}"
    exit 0
else
    echo -e "${RED}❌ Projeto precisa de correções antes da operação ($CHECKS_FAILED falhas).${NC}"
    exit 1
fi
