# TRF5 Scraper - Desafio Técnico

Raspador desenvolvido em **Scrapy** para extrair dados de processos jurídicos do **Tribunal Regional Federal da 5ª Região (TRF5)**.

## Funcionalidades

- **Busca por NPU**: Consulta processos específicos por número
- **Descoberta por CNPJ**: Encontra processos associados a um CNPJ
- **Persistência MongoDB**: Armazena HTML bruto e dados estruturados
- **Idempotência**: Updates automáticos sem duplicação
- **Reprocessamento offline**: Analisa dados salvos sem rede
- **Políticas de cortesia**: Respeita robots.txt e rate limiting

## URL Alvo

- **Sistema TRF5**: http://www5.trf5.jus.br/cp/

## Dados Extraídos

Para cada processo, o scraper extrai:

- `numero_processo` - Número principal (com fallback para numero_legado)
- `numero_legado` - Número antigo do processo
- `data_autuacao` - Data de autuação (ISO-8601)
- `envolvidos[]` - Lista com papel e nome de cada envolvido
- `relator` - Nome do relator (sem títulos/cargos)
- `movimentacoes[]` - Lista cronológica com data e texto

## Instalação

### Pré-requisitos

#### Obrigatórios
- **Python 3.11+**
- **Docker** (para MongoDB via container)
- **Git**

#### Opcionais (para scripts de automação)
- **mongosh** ou **mongo** - Cliente MongoDB para verificações
  - Instalação: https://docs.mongodb.com/mongosh/install/
  - Usado apenas por scripts auxiliares em `scripts/`

### 1. Clone o repositório

```bash
git clone https://github.com/CharlesHenriquedf/scraping-trf5.git
cd scraping-trf5
```

### 2. Ambiente virtual

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou
.venv\Scripts\activate     # Windows
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

### 4. Configurar MongoDB

#### Opção A: Docker (Recomendado)

```bash
cd docker
docker compose up -d
# ou docker-compose up -d (se usando Compose v1)
```

#### Opção B: MongoDB local

Certifique-se que o MongoDB está rodando em `localhost:27017`

### 5. Configurar variáveis de ambiente

**IMPORTANTE**: O arquivo `.env` é carregado automaticamente pelo Scrapy. Não é necessário definir variáveis manualmente no terminal.

```bash
cp config/.env.example .env
# O arquivo .env já vem pré-configurado para Docker
# Editar apenas se necessário para seu ambiente específico
```

**Configuração padrão (funciona com Docker):**
```bash
MONGO_URI=mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=trf5
MONGO_DB=trf5
```

## Como Usar

### Busca por Número do Processo (NPU)

```bash
# Exemplo com NPU do Banco do Brasil
scrapy crawl trf5 -a modo=numero -a valor="0015648-78.1999.4.05.0000" -s LOG_LEVEL=INFO
```

**NPUs disponíveis para teste** (fornecidos pelo Banco do Brasil):
- `0015648-78.1999.4.05.0000`
- `0012656-90.2012.4.05.0000`
- `0043753-74.2013.4.05.0000`
- `0002098-07.2011.4.05.8500`
- `0460674-33.2019.4.05.0000`
- `0000560-67.2017.4.05.0000`

### Descoberta por CNPJ

**IMPORTANTE**: A busca por CNPJ só retornará resultados se a empresa possuir processos ativos no sistema TRF5. Use CNPJs reais de empresas que tenham processos na justiça federal da 5ª região (AL, CE, PB, PE, RN, SE).

```bash
# Exemplo com CNPJ do Banco do Brasil - pode não retornar resultados
scrapy crawl trf5 \
  -a modo=cnpj \
  -a valor="00.000.000/0001-91" \
  -a max_pages=2 \
  -a max_details_per_page=5 \
  -s LOG_LEVEL=INFO
```

**Dica de uso**: Para verificar se um CNPJ possui processos, faça primeiro uma busca com `max_pages=1 max_details_per_page=1` antes de executar uma coleta completa.

### Reprocessamento Offline

```bash
# Reprocessa dados salvos sem fazer novas requisições
scrapy crawl parse_raw -a limit=10 -s LOG_LEVEL=INFO
```

## Scripts de Automação

Para facilitar a execução, use os scripts disponíveis:

### Testar todos os NPUs do BB

```bash
./scripts/run_npu.sh
```

### Descoberta por CNPJ com limites

```bash
./scripts/run_cnpj.sh
```

### Reprocessamento offline

```bash
./scripts/reprocess_offline.sh
```

### Consultas rápidas no MongoDB

```bash
./scripts/mongo_queries.sh
```

## Verificação dos Dados

### Conectar ao MongoDB

```bash
# Via Docker (recomendado)
docker exec trf5-mongo mongosh "mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=trf5"

# Via mongosh local (se instalado)
mongosh "mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=trf5"
```

### Consultas de Verificação

#### Ver últimas páginas coletadas:

```javascript
db.raw_pages.find({}, {url:1,"context.tipo":1,"context.busca":1,"context.page_idx":1})
.sort({_id:-1}).limit(10).toArray()
```

#### Ver processos extraídos:

```javascript
db.processos.find({}, {numero_processo:1, relator:1})
.sort({_id:-1}).limit(5).toArray()
```

#### Verificar idempotência (inserções vs atualizações):

```javascript
// Execute o mesmo NPU duas vezes e verifique os logs
// Primeira execução: "insert"
// Segunda execução: "update"
```

## Configurações

### Variáveis de Ambiente

```bash
# MongoDB
MONGO_URI=mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=trf5
MONGO_DB=trf5

# Scrapy (opcional)
LOG_LEVEL=INFO
```

### Políticas de Cortesia

O scraper implementa as seguintes políticas para respeitar o servidor TRF5:

- `ROBOTSTXT_OBEY=True` - Respeita robots.txt
- `DOWNLOAD_DELAY=0.7` - Delay mínimo entre requisições
- `AUTOTHROTTLE_ENABLED=True` - Ajuste automático de velocidade
- `CONCURRENT_REQUESTS=1` - Uma requisição por vez

## Estrutura de Dados MongoDB

### Coleção `raw_pages`

Armazena HTML bruto de todas as páginas acessadas:

```json
{
  "_id": ObjectId("..."),
  "url": "http://www5.trf5.jus.br/cp/processo/0015648-78.1999.4.05.0000",
  "html": "<!doctype html>...",
  "context": {
    "tipo": "detalhe",
    "busca": "numero",
    "numero": "0015648-78.1999.4.05.0000"
  },
  "fetched_at": "2025-09-15T14:30:00",
  "hash_html": "sha256:..."
}
```

### Coleção `processos`

Armazena dados estruturados extraídos:

```json
{
  "_id": "0015648-78.1999.4.05.0000",
  "numero_processo": "0015648-78.1999.4.05.0000",
  "numero_legado": "99.05...",
  "data_autuacao": "2000-04-15",
  "relator": "João da Silva",
  "envolvidos": [
    {"papel": "APTE", "nome": "Empresa XYZ"},
    {"papel": "APDO", "nome": "União Federal"}
  ],
  "movimentacoes": [
    {"data": "2020-10-06T03:13:00", "texto": "Petição protocolada"},
    {"data": "2020-10-06T03:12:00", "texto": "Processo distribuído"}
  ],
  "fonte_url": "http://www5.trf5.jus.br/cp/processo/0015648-78.1999.4.05.0000",
  "scraped_at": "2025-09-15T14:30:00"
}
```

## Desenvolvimento

### Estrutura do Projeto

```
scraping-trf5/
├── scrapy.cfg                    # Configuração Scrapy
├── requirements.txt              # Dependências Python
├── README.md                     # Este arquivo
├── trf5_scraper/                 # Pacote principal
│   ├── settings.py               # Configurações Scrapy
│   ├── spiders/
│   │   ├── trf5.py               # Spider principal (NPU + CNPJ)
│   │   └── parse_raw.py          # Reprocessamento offline
│   ├── pipelines/
│   │   └── mongo_pipeline.py     # Pipeline MongoDB
│   └── utils/
│       ├── normalize.py          # Normalização de dados
│       ├── classify.py           # Classificação de páginas
│       └── pagination.py         # Tratamento de paginação
├── scripts/                      # Scripts de automação
├── docker/                       # Setup MongoDB
├── docs/                         # Documentação
└── config/                       # Configurações
```

### Executar Testes

```bash
# Verificações automáticas de qualidade
./scripts/claude/post_checks_trf5.sh

# Teste de conectividade TRF5
curl -I http://www5.trf5.jus.br/cp/

# Verificar spiders disponíveis
scrapy list
```

## Dados de Teste

### NPUs do Banco do Brasil
```
0015648-78.1999.4.05.0000
0012656-90.2012.4.05.0000
0043753-74.2013.4.05.0000
0002098-07.2011.4.05.8500
0460674-33.2019.4.05.0000
0000560-67.2017.4.05.0000
```

### CNPJ do Banco do Brasil
```
00.000.000/0001-91
```

## Logs e Monitoramento

### Logs Importantes

Durante a execução, observe os logs para:

- **Classificação de páginas**: `detalhe`, `lista`, `erro`
- **Paginação detectada**: `Total: N` ou `próxima página`
- **Persistência**: `[raw]` para HTML bruto, `[processos]` para dados estruturados
- **Idempotência**: `insert` vs `update` no MongoDB

### Exemplo de Log Típico

```
2025-09-15 14:30:00 [trf5] INFO: Iniciando coleta TRF5 (modo=numero, valor=0015648-78.1999.4.05.0000)
2025-09-15 14:30:01 [mongo] INFO: [raw] saved detalhe (0015648-78.1999.4.05.0000) http://...
2025-09-15 14:30:01 [mongo] INFO: [processos] insert _id=0015648-78.1999.4.05.0000 relator=João da Silva
```

## Solução de Problemas

### MongoDB não conecta

```bash
# Verificar se está rodando
docker ps | grep mongo
# ou
docker exec trf5-mongo mongosh --eval "db.runCommand('ping')"
```

### Scrapy não encontra spiders

```bash
# Verificar estrutura
scrapy list
# Deve mostrar: trf5, parse_raw
```

### Site TRF5 inacessível

```bash
# Testar conectividade
curl -I http://www5.trf5.jus.br/cp/
# Deve retornar: HTTP/1.0 302 Moved Temporarily
```

### Logs não aparecem

```bash
# Aumentar verbosidade
scrapy crawl trf5 -a modo=numero -a valor="..." -s LOG_LEVEL=DEBUG
```

## Contribuição

Este projeto foi desenvolvido como desafio técnico para o **Banco do Brasil**, seguindo exatamente as especificações fornecidas no arquivo de teste.

### Critérios de Avaliação Atendidos

1. **Código legível, simples e claro**
2. **Documentação completa** (este README)
3. **Qualidade dos dados** (todos campos obrigatórios)
4. **Arquitetura sólida** (Scrapy + MongoDB + idempotência)

## Licença

Este projeto é um desafio técnico e seu uso está restrito ao processo de avaliação.

---

**Desenvolvido com Scrapy + Python 3.11 + MongoDB**

Para dúvidas ou problemas, verifique os logs detalhados ou execute os scripts de verificação disponíveis em `scripts/`.