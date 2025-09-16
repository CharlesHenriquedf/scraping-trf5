# Runbook Operacional - TRF5 Scraper

Este documento fornece instru��es operacionais detalhadas para execu��o, monitoramento e troubleshooting do TRF5 Scraper.

## Checklist de Pre-Execucao

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

# 4. Spiders dispon�veis
scrapy list
# Deve retornar: trf5, parse_raw

# 5. Vari�veis de ambiente
echo $MONGO_URI
echo $MONGO_DB
```

## Comandos de Execucao

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

# Teste de idempot�ncia (executar 2x o mesmo)
scrapy crawl trf5 -a modo=numero -a valor="0015648-78.1999.4.05.0000" -s LOG_LEVEL=INFO
# Primeira execu��o: deve logar "insert"
# Segunda execu��o: deve logar "update"
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
# Reprocessar �ltimas 10 p�ginas
scrapy crawl parse_raw -a limit=10 -s LOG_LEVEL=INFO

# Reprocessar por tipo espec�fico
scrapy crawl parse_raw -a limit=20 -a tipo=detalhe -s LOG_LEVEL=INFO

# Reprocessar por tipo de busca
scrapy crawl parse_raw -a limit=15 -a busca=numero -s LOG_LEVEL=INFO
```

## =' Scripts de Automa��o

### Executar Todos os NPUs do BB

```bash
./scripts/run_npu.sh
```

**O que faz:**
- Executa todos os 6 NPUs fornecidos pelo Banco do Brasil
- Testa idempot�ncia executando cada NPU 2 vezes
- Salva logs individuais para cada execu��o
- Gera relat�rio final de sucesso/falha

### Descoberta por CNPJ com Limites

```bash
./scripts/run_cnpj.sh
```

**O que faz:**
- Executa descoberta pelo CNPJ do Banco do Brasil
- Aplica limites seguros (max_pages=2, max_details_per_page=5)
- Monitora pagina��o e classifica��o de p�ginas
- Salva evid�ncias de listas e detalhes coletados

### Reprocessamento Offline

```bash
./scripts/reprocess_offline.sh
```

**O que faz:**
- Reprocessa p�ginas HTML salvas sem fazer requisi��es de rede
- Testa a robustez dos extractors
- �til para debug e refinamento dos parsers

### Consultas MongoDB R�pidas

```bash
./scripts/mongo_queries.sh
```

**O que faz:**
- Executa consultas padr�o de verifica��o
- Mostra �ltimas p�ginas coletadas
- Lista processos extra�dos
- Verifica integridade dos dados

## =� Monitoramento Durante Execu��o

### Logs Cr�ticos a Observar

#### 1. Inicia��o do Spider
```
[trf5] INFO: Iniciando coleta TRF5 (modo=numero, valor=0015648-78.1999.4.05.0000, max_pages=5, max_details=10)
```

#### 2. Classifica��o de P�ginas
```
[trf5] INFO: P�gina de lista processada (page=0, tipo=list, url=http://...)
[trf5] INFO: P�gina n�o � detalhe conforme esperado: http://...
```

#### 3. Pagina��o Detectada
```
[trf5] INFO: Pagina��o detectada: Total=157, last_page=15
[trf5] INFO: Extra�dos 5 links de detalhe desta p�gina (total coletado: 12)
```

#### 4. Persist�ncia MongoDB
```
[mongo] INFO: [raw] saved detalhe (0015648-78.1999.4.05.0000) http://...
[mongo] INFO: [processos] insert _id=0015648-78.1999.4.05.0000 relator=Jo�o da Silva
[mongo] INFO: [processos] update _id=0015648-78.1999.4.05.0000 relator=Jo�o da Silva
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

#### L Classifica��o Errada
```
[trf5] WARNING: P�gina n�o � lista conforme esperado: http://...
[trf5] WARNING: P�gina de erro detectada: http://...
```

#### L Extra��o Falhou
```
[trf5] WARNING: N�mero do processo n�o encontrado em http://...
[trf5] ERROR: Erro ao extrair dados do processo http://... KeyError: 'relator'
```

#### L MongoDB Indispon�vel
```
[mongo] ERROR: Erro ao conectar no MongoDB: ServerSelectionTimeoutError
```

## =� Consultas MongoDB de Verifica��o

### Conectar ao MongoDB

```bash
# Via mongosh local
mongosh "mongodb://localhost:27017/trf5"

# Via Docker
docker exec -it trf5-mongo mongosh "mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin"
```

### Consultas Essenciais

#### 1. Verificar �ltimas P�ginas Coletadas
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

#### 2. Contar P�ginas por Tipo
```javascript
db.raw_pages.aggregate([
  {$group: {
    _id: "$context.tipo",
    count: {$sum: 1}
  }}
])
```

#### 3. Verificar Processos Extra�dos
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

// Processos sem movimenta��es
db.processos.find({$or: [{movimentacoes: null}, {movimentacoes: []}]}).count()

// Datas n�o ISO
db.processos.find({data_autuacao: {$not: /^\d{4}-\d{2}-\d{2}/}}).count()
```

## =� Troubleshooting

### Problema: Scrapy n�o encontra spiders

**Sintoma:**
```
AttributeError: 'NoneType' object has no attribute 'split'
spider not found: trf5
```

**Solu��o:**
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

**Solu��o:**
```bash
# Verificar status
docker ps | grep mongo

# Restart se necess�rio
docker compose -f docker/compose.yaml restart

# Verificar logs
docker logs trf5-mongo
```

### Problema: TRF5 site inacess�vel

**Sintoma:**
```
twisted.internet.error.DNSLookupError
```

**Solu��o:**
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

**Solu��o:**
```bash
# Aumentar delays
scrapy crawl trf5 -a modo=... -s DOWNLOAD_DELAY=2.0 -s AUTOTHROTTLE_START_DELAY=3.0

# Reduzir concorr�ncia
scrapy crawl trf5 -a modo=... -s CONCURRENT_REQUESTS=1
```

### Problema: Dados extra�dos incorretos

**Sintoma:**
```javascript
// MongoDB mostra campos vazios ou incorretos
db.processos.find({relator: "DESEMBARGADOR FEDERAL Jo�o"}) // t�tulo n�o removido
```

**Solu��o:**
```bash
# Reprocessar offline para testar extractors
scrapy crawl parse_raw -a limit=5 -s LOG_LEVEL=DEBUG

# Verificar normaliza��o
python3 -c "
from trf5_scraper.utils.normalize import normalize_relator
print(normalize_relator('DESEMBARGADOR FEDERAL Jo�o Silva'))
"
```

## =� M�tricas de Sucesso

### Execu��o por NPU
-  6/6 NPUs processados com sucesso
-  Segunda execu��o de cada NPU gera "update" (n�o "insert")
-  Todos campos obrigat�rios preenchidos
-  Datas em formato ISO-8601

### Descoberta por CNPJ
-  Pagina��o detectada corretamente
-  Limites respeitados (max_pages, max_details_per_page)
-  Classifica��o correta: lista � detalhes
-  Processos �nicos salvos (sem duplicatas)

### Reprocessamento Offline
-  Execu��o sem requisi��es de rede
-  Mesmos dados extra�dos do HTML salvo
-  Logs "reprocessando" vis�veis

### Qualidade dos Dados
-  Relator sem prefixos ("Jo�o Silva" n�o "Des. Jo�o Silva")
-  Envolvidos com papel e nome
-  Movimenta��es em ordem cronol�gica
-  NPU usado como _id para idempot�ncia

## <� Checklist Final de Valida��o

Antes de considerar a execu��o completa:

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

# 6. Verificar evid�ncias
ls -la docs/evidencias/
```

### Crit�rios de Aceite Final

- [ ] 6 NPUs do BB salvos em `processos`
- [ ] Descoberta por CNPJ funcionando com limites
- [ ] HTML bruto salvo em `raw_pages`
- [ ] Idempot�ncia comprovada (logs insert�update)
- [ ] Reprocessamento offline operacional
- [ ] Pol�ticas de cortesia ativas
- [ ] Logs claros e informativos
- [ ] Consultas MongoDB retornam dados v�lidos

---

**Nota:** Este runbook assume execu��o em ambiente Linux/Mac. Para Windows, adapte os comandos conforme necess�rio.

**Contato:** Verificar logs detalhados em caso de problemas. Todos os comandos geram logs informativos para troubleshooting.