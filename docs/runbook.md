# Runbook Operacional - TRF5 Scraper

Este documento fornece instruções operacionais detalhadas para execução, monitoramento e troubleshooting do TRF5 Scraper.

## <¯ Checklist de Pré-Execução

Antes de executar qualquer comando, verifique:

```bash
# 1. Ambiente virtual ativo
source .venv/bin/activate

# 2. MongoDB rodando
docker ps | grep mongo
# ou
mongosh --eval "db.runCommand('ping')"

# 3. Conectividade com TRF5
curl -I http://www5.trf5.jus.br/cp/

# 4. Spiders disponíveis
scrapy list
# Deve retornar: trf5, parse_raw

# 5. Variáveis de ambiente
echo $MONGO_URI
echo $MONGO_DB
```

## =Ë Comandos de Execução

### 1. Busca por NPU (Teste Individual)

```bash
# Comando base
scrapy crawl trf5 \
  -a modo=numero \
  -a valor="0015648-78.1999.4.05.0000" \
  -s LOG_LEVEL=INFO

# Com log em arquivo
scrapy crawl trf5 \
  -a modo=numero \
  -a valor="0015648-78.1999.4.05.0000" \
  -s LOG_LEVEL=INFO \
  -s LOG_FILE=logs/npu_$(date +%Y%m%d_%H%M%S).log

# Teste de idempotência (executar 2x o mesmo)
scrapy crawl trf5 -a modo=numero -a valor="0015648-78.1999.4.05.0000" -s LOG_LEVEL=INFO
# Primeira execução: deve logar "insert"
# Segunda execução: deve logar "update"
```

### 2. Descoberta por CNPJ

```bash
# Comando base com limites
scrapy crawl trf5 \
  -a modo=cnpj \
  -a valor="00.000.000/0001-91" \
  -a max_pages=2 \
  -a max_details_per_page=5 \
  -s LOG_LEVEL=INFO

# Teste ampliado (cuidado com rate limiting)
scrapy crawl trf5 \
  -a modo=cnpj \
  -a valor="00.000.000/0001-91" \
  -a max_pages=5 \
  -a max_details_per_page=10 \
  -s LOG_LEVEL=INFO \
  -s LOG_FILE=logs/cnpj_$(date +%Y%m%d_%H%M%S).log
```

### 3. Reprocessamento Offline

```bash
# Reprocessar últimas 10 páginas
scrapy crawl parse_raw -a limit=10 -s LOG_LEVEL=INFO

# Reprocessar por tipo específico
scrapy crawl parse_raw -a limit=20 -a tipo=detalhe -s LOG_LEVEL=INFO

# Reprocessar por tipo de busca
scrapy crawl parse_raw -a limit=15 -a busca=numero -s LOG_LEVEL=INFO
```

## =' Scripts de Automação

### Executar Todos os NPUs do BB

```bash
./scripts/run_npu.sh
```

**O que faz:**
- Executa todos os 6 NPUs fornecidos pelo Banco do Brasil
- Testa idempotência executando cada NPU 2 vezes
- Salva logs individuais para cada execução
- Gera relatório final de sucesso/falha

### Descoberta por CNPJ com Limites

```bash
./scripts/run_cnpj.sh
```

**O que faz:**
- Executa descoberta pelo CNPJ do Banco do Brasil
- Aplica limites seguros (max_pages=2, max_details_per_page=5)
- Monitora paginação e classificação de páginas
- Salva evidências de listas e detalhes coletados

### Reprocessamento Offline

```bash
./scripts/reprocess_offline.sh
```

**O que faz:**
- Reprocessa páginas HTML salvas sem fazer requisições de rede
- Testa a robustez dos extractors
- Útil para debug e refinamento dos parsers

### Consultas MongoDB Rápidas

```bash
./scripts/mongo_queries.sh
```

**O que faz:**
- Executa consultas padrão de verificação
- Mostra últimas páginas coletadas
- Lista processos extraídos
- Verifica integridade dos dados

## =Ê Monitoramento Durante Execução

### Logs Críticos a Observar

#### 1. Iniciação do Spider
```
[trf5] INFO: Iniciando coleta TRF5 (modo=numero, valor=0015648-78.1999.4.05.0000, max_pages=5, max_details=10)
```

#### 2. Classificação de Páginas
```
[trf5] INFO: Página de lista processada (page=0, tipo=list, url=http://...)
[trf5] INFO: Página não é detalhe conforme esperado: http://...
```

#### 3. Paginação Detectada
```
[trf5] INFO: Paginação detectada: Total=157, last_page=15
[trf5] INFO: Extraídos 5 links de detalhe desta página (total coletado: 12)
```

#### 4. Persistência MongoDB
```
[mongo] INFO: [raw] saved detalhe (0015648-78.1999.4.05.0000) http://...
[mongo] INFO: [processos] insert _id=0015648-78.1999.4.05.0000 relator=João da Silva
[mongo] INFO: [processos] update _id=0015648-78.1999.4.05.0000 relator=João da Silva
```

#### 5. Rate Limiting e Cortesia
```
[scrapy.downloadermiddlewares.robotstxt] DEBUG: Forbidden by robots.txt: <GET http://...>
[scrapy.extensions.throttle] INFO: AutoThrottle: Adjusting delay to 1.2s
```

### Sinais de Problema

#### L Conectividade
```
twisted.internet.error.ConnectError: An error occurred
scrapy.downloadermiddlewares.retry] DEBUG: Retrying <GET http://...>
```

#### L Classificação Errada
```
[trf5] WARNING: Página não é lista conforme esperado: http://...
[trf5] WARNING: Página de erro detectada: http://...
```

#### L Extração Falhou
```
[trf5] WARNING: Número do processo não encontrado em http://...
[trf5] ERROR: Erro ao extrair dados do processo http://... KeyError: 'relator'
```

#### L MongoDB Indisponível
```
[mongo] ERROR: Erro ao conectar no MongoDB: ServerSelectionTimeoutError
```

## =Ä Consultas MongoDB de Verificação

### Conectar ao MongoDB

```bash
# Via mongosh local
mongosh "mongodb://localhost:27017/trf5"

# Via Docker
docker exec -it trf5-mongo mongosh "mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin"
```

### Consultas Essenciais

#### 1. Verificar Últimas Páginas Coletadas
```javascript
db.raw_pages.find({}, {
  url: 1,
  "context.tipo": 1,
  "context.busca": 1,
  "context.numero": 1,
  "context.cnpj": 1,
  "context.page_idx": 1,
  fetched_at: 1
}).sort({_id: -1}).limit(10).toArray()
```

#### 2. Contar Páginas por Tipo
```javascript
db.raw_pages.aggregate([
  {$group: {
    _id: "$context.tipo",
    count: {$sum: 1}
  }}
])
```

#### 3. Verificar Processos Extraídos
```javascript
db.processos.find({}, {
  numero_processo: 1,
  relator: 1,
  data_autuacao: 1,
  "envolvidos.0.papel": 1,
  "movimentacoes.0.data": 1,
  scraped_at: 1
}).sort({_id: -1}).limit(5).toArray()
```

#### 4. Validar NPUs do Banco do Brasil
```javascript
var npus_bb = [
  "0015648-78.1999.4.05.0000",
  "0012656-90.2012.4.05.0000",
  "0043753-74.2013.4.05.0000",
  "0002098-07.2011.4.05.8500",
  "0460674-33.2019.4.05.0000",
  "0000560-67.2017.4.05.0000"
];

npus_bb.forEach(npu => {
  var doc = db.processos.findOne({_id: npu});
  print(`${npu}: ${doc ? 'OK' : 'MISSING'}`);
});
```

#### 5. Verificar Qualidade dos Dados
```javascript
// Processos sem relator
db.processos.find({$or: [{relator: null}, {relator: ""}]}).count()

// Processos sem envolvidos
db.processos.find({$or: [{envolvidos: null}, {envolvidos: []}]}).count()

// Processos sem movimentações
db.processos.find({$or: [{movimentacoes: null}, {movimentacoes: []}]}).count()

// Datas não ISO
db.processos.find({data_autuacao: {$not: /^\d{4}-\d{2}-\d{2}/}}).count()
```

## =¨ Troubleshooting

### Problema: Scrapy não encontra spiders

**Sintoma:**
```
AttributeError: 'NoneType' object has no attribute 'split'
spider not found: trf5
```

**Solução:**
```bash
# Verificar estrutura do projeto
ls -la trf5_scraper/spiders/
cat scrapy.cfg

# Recompiliar Python
python3 -m py_compile trf5_scraper/spiders/trf5.py
```

### Problema: MongoDB connection failed

**Sintoma:**
```
pymongo.errors.ServerSelectionTimeoutError: localhost:27017
```

**Solução:**
```bash
# Verificar status
docker ps | grep mongo

# Restart se necessário
docker compose -f docker/compose.yaml restart

# Verificar logs
docker logs trf5-mongo
```

### Problema: TRF5 site inacessível

**Sintoma:**
```
twisted.internet.error.DNSLookupError
```

**Solução:**
```bash
# Testar conectividade
ping www5.trf5.jus.br
curl -v http://www5.trf5.jus.br/cp/

# Verificar proxy/firewall
echo $http_proxy
echo $https_proxy
```

### Problema: Rate limiting / 429 errors

**Sintoma:**
```
[scrapy.downloadermiddlewares.retry] DEBUG: Retrying <GET http://...> (failed 1 times): 429
```

**Solução:**
```bash
# Aumentar delays
scrapy crawl trf5 -a modo=... -s DOWNLOAD_DELAY=2.0 -s AUTOTHROTTLE_START_DELAY=3.0

# Reduzir concorrência
scrapy crawl trf5 -a modo=... -s CONCURRENT_REQUESTS=1
```

### Problema: Dados extraídos incorretos

**Sintoma:**
```javascript
// MongoDB mostra campos vazios ou incorretos
db.processos.find({relator: "DESEMBARGADOR FEDERAL João"}) // título não removido
```

**Solução:**
```bash
# Reprocessar offline para testar extractors
scrapy crawl parse_raw -a limit=5 -s LOG_LEVEL=DEBUG

# Verificar normalização
python3 -c "
from trf5_scraper.utils.normalize import normalize_relator
print(normalize_relator('DESEMBARGADOR FEDERAL João Silva'))
"
```

## =È Métricas de Sucesso

### Execução por NPU
-  6/6 NPUs processados com sucesso
-  Segunda execução de cada NPU gera "update" (não "insert")
-  Todos campos obrigatórios preenchidos
-  Datas em formato ISO-8601

### Descoberta por CNPJ
-  Paginação detectada corretamente
-  Limites respeitados (max_pages, max_details_per_page)
-  Classificação correta: lista ’ detalhes
-  Processos únicos salvos (sem duplicatas)

### Reprocessamento Offline
-  Execução sem requisições de rede
-  Mesmos dados extraídos do HTML salvo
-  Logs "reprocessando" visíveis

### Qualidade dos Dados
-  Relator sem prefixos ("João Silva" não "Des. João Silva")
-  Envolvidos com papel e nome
-  Movimentações em ordem cronológica
-  NPU usado como _id para idempotência

## <¯ Checklist Final de Validação

Antes de considerar a execução completa:

```bash
# 1. Executar todos NPUs
./scripts/run_npu.sh

# 2. Testar descoberta CNPJ
./scripts/run_cnpj.sh

# 3. Verificar dados no MongoDB
./scripts/mongo_queries.sh

# 4. Testar reprocessamento
./scripts/reprocess_offline.sh

# 5. Executar QA completo
./scripts/claude/post_checks_trf5.sh

# 6. Verificar evidências
ls -la docs/evidencias/
```

### Critérios de Aceite Final

- [ ] 6 NPUs do BB salvos em `processos`
- [ ] Descoberta por CNPJ funcionando com limites
- [ ] HTML bruto salvo em `raw_pages`
- [ ] Idempotência comprovada (logs insert’update)
- [ ] Reprocessamento offline operacional
- [ ] Políticas de cortesia ativas
- [ ] Logs claros e informativos
- [ ] Consultas MongoDB retornam dados válidos

---

**Nota:** Este runbook assume execução em ambiente Linux/Mac. Para Windows, adapte os comandos conforme necessário.

**Contato:** Verificar logs detalhados em caso de problemas. Todos os comandos geram logs informativos para troubleshooting.