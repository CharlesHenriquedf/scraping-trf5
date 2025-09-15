# PRD — Coletor TRF5 (Desafio Técnico)

Versão: 1.0 • Data: 15/09/2025

---

# 1. Objetivo e escopo

Implementar um raspador **exclusivamente com Scrapy (Python 3.x)** capaz de:

1. Consultar **processos por Número (NPU)**.
2. Descobrir **processos por CNPJ** (Banco do Brasil).
3. **Persistir**: salvar **HTML bruto** das páginas acessadas e **dados estruturados** do processo em **MongoDB**.
4. **Extrair exatamente** os campos exigidos pelo teste (conforme a imagem/anotação):

   * `numero_processo` (fallback: `numero_legado`),
   * `numero_legado`,
   * `data_autuacao`,
   * `envolvidos[]` com `papel` e `nome`,
   * `relator` (apenas o nome),
   * `movimentacoes[]` com `data` e `texto`.
5. **Documentar** execução, decisões e dificuldades.
6. Publicar o projeto em **repositório Git público**.

**Fora do escopo**: CI/CD, dashboards, simulações, testes com fixtures. **Todos os testes serão E2E em ambiente real** contra a URL pública da Consulta Processual do TRF5.

---

# 2. Requisitos funcionais (RF) e critérios de aceite

## RF-01 — Busca por Número do Processo (NPU)

* **Entrada**: NPU com ou sem hífens (`0015648-78.1999.4.05.0000` ou `00156487819994050000`).
* **Fluxo**: acessar a **página de detalhe** do processo e extrair os campos exigidos.
* **Persistência**: salvar página de detalhe em `raw_pages` e item normalizado em `processos`.
* **Aceite**: para cada NPU da lista do teste, primeira execução insere; segunda execução realiza **update** (idempotência).

## RF-02 — Descoberta por CNPJ

* **Entrada**: CNPJ (aceitar com formatação; normalizar para dígitos).
* **Fluxo**: abrir a página pública de **Consulta Processual do TRF5**, selecionar o modo **CPF/CNPJ**, submeter o formulário e **navegar pelas páginas de resultados** (lista), seguindo para as páginas de **detalhe** de cada processo.
* **Paginação**: detectar por texto “Total: N” (quando presente) ou por barra/tabela de páginas; respeitar limites configuráveis (`max_pages`, `max_details_per_page`).
* **Persistência**: salvar cada **lista** e cada **detalhe** em `raw_pages`; salvar itens parseados em `processos`.
* **Aceite**: execução com limites pequenos (ex.: `max_pages=2` e `max_details_per_page=5`) deve registrar listas e detalhes, com paginação corretamente identificada e itens inseridos/atualizados.

## RF-03 — Extração de dados (campos obrigatórios)

* **numero\_processo**: string; **se ausente**, preencher com `numero_legado`.
* **numero\_legado**: string.
* **data\_autuacao**: `datetime` (normalizar para ISO-8601).
* **envolvidos\[]**: lista de `{papel: string, nome: string}`.
* **relator**: string (apenas o **nome**, sem prefixos/cargos).
* **movimentacoes\[]**: lista de `{data: datetime, texto: string}` (data normalizada ISO-8601).

**Aceite**: todos os campos acima presentes e coerentes nos documentos inseridos/atualizados em `processos`.

## RF-04 — Persistência e idempotência

* **MongoDB** com duas coleções: `raw_pages` e `processos`.
* **Idempotência**: `processos._id` = **NPU normalizado**; `update_one(..., upsert=True)`.
* **Evidência**: logs diferenciando **insert** e **update**.

## RF-05 — Documentação mínima

* **README** com: como instalar, configurar, rodar por NPU, rodar por CNPJ, limites, exemplos de logs e exemplo de consultas no Mongo.

---

# 3. Requisitos não funcionais (RNF)

* **Tecnologia**: Python 3.11+; Scrapy puro; MongoDB.
* **Respeito ao site**: `ROBOTSTXT_OBEY=True`, `DOWNLOAD_DELAY>=0.5s`, `AUTOTHROTTLE_ENABLED=True`.
* **Confiabilidade**: salvar sempre o **HTML bruto**; detectar corretamente tipos de página (**lista**, **detalhe**, **erro**).
* **Simplicidade**: código legível, com separação mínima (spider, parser, pipeline).
* **Logs**: mensagens de negócio claras (paginação, totais, inserts/updates).

---

# 4. Fluxos detalhados

## 4.1. Consulta por Número (NPU)

1. **Normalização de entrada**: remover caracteres não numéricos; se vier sem hífens, também montar a versão com hífens (formato padrão NPU).
2. **Acesso ao detalhe**: tentar URL canônica de **detalhe do processo** (que aceita NPU com hífen).
3. **Classificação**: confirmar que a página é de **detalhe** verificando cabeçalhos/metadados típicos (ex.: rótulos “PROCESSO Nº”, “RELATOR”, “AUTUADO EM”, quadro de **envolvidos**, quadro de **movimentações**).
4. **Persistência bruta**: gravar em `raw_pages` com `context.tipo="detalhe"` e `context.numero=<NPU>`.
5. **Parse**: extrair campos obrigatórios (Seção 5).
6. **Upsert**: gravar em `processos` com `_id=<NPU normalizado>`.

## 4.2. Descoberta por CNPJ

1. **Acesso**: carregar a **Consulta Processual do TRF5**.
2. **Submissão**: `FormRequest.from_response` selecionando **CPF/CNPJ** e preenchendo o CNPJ **apenas dígitos**.
3. **Lista**: página de resultados com tabela de processos.
4. **Paginação**:

   * **Modo A (Total\:N)**: extrair `total` e `page_size` (padrão 10 quando implícito); calcular `last_page`.
   * **Modo B (barra/tabela)**: extrair links “próxima/última” e índices de página.
5. **Iteração**: respeitar `max_pages`; em cada página, limitar a `max_details_per_page` ao seguir os links de detalhe.
6. **Persistência bruta**: gravar cada lista em `raw_pages` com `context.tipo="lista"`, `context.cnpj`, `context.page_idx`.
7. **Detalhes**: seguir os links de processo; para cada detalhe, salvar em `raw_pages` e parsear como no fluxo de NPU.
8. **Upsert**: gravar itens em `processos` por `_id` (NPU normalizado).

---

# 5. Regras de parsing e normalizações

## 5.1. Identificação de campos

* **numero\_processo**

  * Procurar rótulo “PROCESSO Nº …” próximo ao topo.
  * **Fallback**: se não for encontrado, usar `numero_legado` como `numero_processo`.
* **numero\_legado**

  * Número antigo exibido no topo (geralmente próximo ao cabeçalho; no material de referência está destacado em verde).
* **data\_autuacao**

  * Rótulo “AUTUADO EM dd/mm/aaaa” (e possivelmente hora).
  * Converter para **ISO-8601**. Se vier somente data: `YYYY-MM-DD`.
* **relator**

  * Linha “RELATOR …” (ou equivalente).
  * **Remover títulos** (ex.: “DESEMBARGADOR FEDERAL”) e manter **apenas o nome**.
* **envolvidos\[]**

  * Tabela/blocos com **papel** à esquerda (ex.: “APTE”, “APDO”, “Advogado/Procurador”) e **nome** à direita.
  * Extrair **todos** os pares; criar entrada `{papel, nome}` para cada linha.
* **movimentacoes\[]**

  * Lista cronológica com **data** (linha superior) e **texto** (linha inferior).
  * Converter a data para **ISO-8601**. Se vier com hora (ex.: “06/10/2020 03:13”), produzir `YYYY-MM-DDTHH:MM:SS`.

## 5.2. Normalizações e utilidades

* **Datas**: aceitar `dd/mm/aaaa` e `dd/mm/aaaa HH:MM`; timezone indefinida (armazenar sem “Z”).
* **NPU**:

  * `normalize_npu_hyphenated(n)` → com hífens (formato humano).
  * `normalize_npu_digits(n)` → apenas dígitos (para `_id` se desejado; este PRD adota **com hífens** como `_id` para auditabilidade).
* **CNPJ**: `re.sub(r'\D','', value)`.
* **Texto**: strip + colapsar múltiplos espaços; manter acentos (UTF-8).
* **Relator**: `re.sub(r'^\s*(Des\.?|DESEMBARGADOR(A)?\s+FEDERAL|JUIZ(A)?\s+FEDERAL)\s+', '', nome, flags=IGNORECASE)`.

---

# 6. Persistência (MongoDB)

## 6.1. Coleção `raw_pages`

Documento por **requisição útil** (lista/detalhe):

```json
{
  "url": "https://…",
  "method": "GET",
  "status": 200,
  "headers": {"Content-Type": "text/html; charset=…"},
  "html": "<!doctype html>…",
  "payload": null,
  "context": {
    "tipo": "lista|detalhe",
    "busca": "numero|cnpj",
    "numero": "0015648-78.1999.4.05.0000",
    "cnpj": "00000000000191",
    "page_idx": 0,
    "endpoint": "form|detalhe"
  },
  "fetched_at": "YYYY-MM-DDTHH:MM:SS",
  "hash_html": "sha256:…"
}
```

**Índices**:

* `{ "context.tipo": 1, "fetched_at": -1 }`
* `{ "url": 1, "method": 1 }`

## 6.2. Coleção `processos`

```json
{
  "_id": "0015648-78.1999.4.05.0000",
  "numero_processo": "0015648-78.1999.4.05.0000",
  "numero_legado": "99.05…8",
  "data_autuacao": "2000-04-15",
  "relator": "Fulano de Tal",
  "envolvidos": [
    {"papel":"APTE","nome":"..."},
    {"papel":"APDO","nome":"..."}
  ],
  "movimentacoes": [
    {"data":"2020-10-06T03:13:00","texto":"…"},
    {"data":"2020-10-06T03:12:00","texto":"…"}
  ],
  "fonte_url": "https://…/processo/0015648-78.1999.4.05.0000",
  "scraped_at": "YYYY-MM-DDTHH:MM:SS"
}
```

**Upsert idempotente** por `_id`.
**Índices**: `{ "relator": 1, "data_autuacao": -1 }` (opcional).

---

### 6.3 Provisionamento local do MongoDB (Docker)

**Escopo:** disponibilizar um MongoDB local, reproduzível e isolado, para execução E2E real do raspador, sem impacto em ambientes de terceiros.

**Pré-requisitos:** Docker Engine ≥ 24 e Docker Compose plugin.

**Diretório do projeto:** `trf5-scraper/docker/`

**Arquivos:**

* `docker/compose.yaml`
* `docker/mongo/initdb.d/init.js` (criação de banco e usuário de aplicação)

**Conteúdo sugerido de `docker/compose.yaml`:**

```yaml
name: trf5
services:
  mongo:
    image: mongo:7.0
    container_name: trf5-mongo
    ports:
      - "127.0.0.1:27017:27017"
    environment:
      MONGO_INITDB_ROOT_USERNAME: root
      MONGO_INITDB_ROOT_PASSWORD: rootpass
    volumes:
      - trf5_mongo_data:/data/db
      - ./mongo/initdb.d:/docker-entrypoint-initdb.d:ro
    restart: unless-stopped
volumes:
  trf5_mongo_data:
```

**Conteúdo sugerido de `docker/mongo/initdb.d/init.js`:**

```javascript
// Cria DB 'trf5' e usuário de aplicação com permissões restritas
db = db.getSiblingDB('trf5');
db.createUser({
  user: 'trf5',
  pwd: 'trf5pass',
  roles: [{ role: 'readWrite', db: 'trf5' }]
});
```

**Variáveis de ambiente (atualizar `config/.env.example`):**

```
# Conexão de aplicação (usa usuário trf5 criado no init.js)
MONGO_URI=mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin
MONGO_DB=trf5
```

**Comandos operacionais:**

```bash
# Subir o Mongo
cd docker
docker compose up -d

# Verificar
docker compose ps
docker logs -f trf5-mongo | head -n 50

# Acessar via mongosh (opcional)
mongosh "mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin"

# Backup (arquivo único)
docker exec trf5-mongo sh -c "mongodump --db trf5 --archive" > ../backups/trf5-$(date +%F).archive

# Restore (a partir de um arquivo)
docker exec -i trf5-mongo sh -c "mongorestore --archive" < ../backups/trf5-YYYY-MM-DD.archive

# Parar e remover
docker compose down
# Remover também o volume (apaga os dados locais)
docker compose down -v
```

**Integração com o código:**

* `settings.py` deve ler `MONGO_URI` e `MONGO_DB` das variáveis de ambiente.
* O pipeline `MongoPipeline` usa diretamente essas variáveis; não versionar dados nem credenciais reais.

**Boas práticas de segurança e desempenho (dev):**

* Bind apenas em `127.0.0.1` (já configurado em `ports`).
* Usuário de aplicação separado do root (`trf5`), com `readWrite` apenas no DB `trf5`.
* Volumes persistentes (`trf5_mongo_data`) para não perder dados entre execuções.
* Não versionar arquivos de backup; incluir `backups/` no `.gitignore`.

**Observação de produção:** esta configuração é somente para desenvolvimento local. Para ambientes gerenciados/produção, usar serviço gerenciado (ex.: Atlas) ou configuração própria com autenticação robusta, TLS e backups automatizados.

---

# 7. Arquitetura de código

# Estrutura de diretórios recomendada

```
trf5-scraper/
├─ scrapy.cfg
├─ requirements.txt
├─ .gitignore
├─ README.md
├─ docs/
│  ├─ PRD-Coletor-TRF5.md        # PRD oficial do projeto (este documento)
│  ├─ runbook.md                 # Comandos de execução e verificação (NPU, CNPJ, offline)
│  └─ evidencias/                # Prints de logs/consultas Mongo usados na entrega
├─ config/
│  ├─ .env.example               # MONGO_URI, MONGO_DB e parâmetros padrão de execução
│  └─ settings.local.py          # (opcional) overrides locais do Scrapy
├─ trf5_scraper/                 # Pacote Scrapy
│  ├─ __init__.py
│  ├─ settings.py                # ROBOTSTXT_OBEY, DOWNLOAD_DELAY, AUTOTHROTTLE, pipelines
│  ├─ items.py                   # (opcional) defin. de Items; pode-se usar dicts se preferir
│  ├─ pipelines/
│  │  ├─ __init__.py
│  │  └─ mongo_pipeline.py       # Salva raw_pages e faz upsert em processos
│  ├─ utils/
│  │  ├─ __init__.py
│  │  ├─ normalize.py            # normalizações: NPU, CNPJ, datas, limpeza de texto
│  │  ├─ classify.py             # detecta tipo de página: lista/detalhe/erro
│  │  └─ pagination.py           # extrai Total:N | barra de páginas; calcula last_page
│  └─ spiders/
│     ├─ __init__.py
│     ├─ trf5.py                 # spider principal: modo=numero | modo=cnpj (FormRequest)
│     └─ parse_raw.py            # reprocessa raw_pages(tipo="detalhe") sem rede
├─ scripts/
│  ├─ run_npu.sh                 # wrapper p/ execução real por NPU (lista do BB)
│  ├─ run_cnpj.sh                # wrapper p/ execução real por CNPJ (limites, ordenação)
│  ├─ reprocess_offline.sh       # wrapper p/ spider parse_raw (amostra/limit)
│  └─ mongo_queries.sh           # consultas rápidas ao Mongo (amostras do README)
└─ logs/
   └─ .gitkeep                   # diretório para logs locais (opcional)
```

## Justificativa detalhada (mapeamento PRD → estrutura)

* **Scrapy + pacote `trf5_scraper`**
  Atende ao requisito “Scrapy puro” e organiza configurações e código de forma canônica:

  * `settings.py`: define polidez (`ROBOTSTXT_OBEY`, `DOWNLOAD_DELAY`, `AUTOTHROTTLE`) e registra `MongoPipeline`.
  * `items.py`: opcional; se preferir, usar apenas dicts. Mantido para clareza e evolução.
* **Spiders**

  * `spiders/trf5.py` cobre **RF-01 (NPU)** e **RF-02 (CNPJ)**:

    * `modo=numero`: acessa a página de detalhe por NPU, salva `raw_pages` e emite o item de processo.
    * `modo=cnpj`: usa `FormRequest.from_response` na Consulta Processual, detecta **lista** e **paginação** (Total\:N ou barra), segue para **detalhes** respeitando `max_pages` e `max_details_per_page`.
    * Em ambos, chama utilidades de normalização e classificação para robustez.
  * `spiders/parse_raw.py` cumpre **reprocesso offline**: lê HTML salvo (`raw_pages.tipo="detalhe"`) e reaplica o mesmo parser sem rede.
* **Pipelines**

  * `pipelines/mongo_pipeline.py`:

    * Persiste **HTML bruto** (auditoria) em `raw_pages`.
    * Executa **upsert idempotente** em `processos` com `_id = NPU normalizado` (RF-04).
    * Emite logs “insert”/“update” para evidência objetiva.
* **Utils**

  * `normalize.py`: datas → ISO-8601; NPU (com e sem hífen); CNPJ só dígitos; limpeza de espaços; remoção de títulos em `relator`.
  * `classify.py`: heurísticas estáveis para distinguir **lista** / **detalhe** / **erro**.
  * `pagination.py`: dois modos de paginação (por **Total\:N** e por **barra de páginas**), cálculo de `last_page` e limites.
* **Docs**

  * `docs/PRD-Coletor-TRF5.md`: mantém o PRD sob controle de versão, como exigido.
  * `docs/runbook.md`: operacional do avaliador (como rodar por NPU/CNPJ, checar Mongo e reprocessar).
  * `docs/evidencias/`: armazena prints/trechos de logs e resultados de `mongosh` exigidos no pacote de entrega.
* **Scripts (execução E2E real)**

  * Wrappers simples evitam erros de digitação durante a avaliação e padronizam parâmetros:

    * `run_npu.sh`: itera a lista do BB e reexecuta o mesmo NPU para evidenciar **update**.
    * `run_cnpj.sh`: roda descoberta real com limites (ex.: `max_pages=2`, `max_details_per_page=5`).
    * `reprocess_offline.sh`: demonstra o **parse offline**.
    * `mongo_queries.sh`: executa as duas consultas de verificação documentadas no PRD.
* **Config**

  * `.env.example` com `MONGO_URI` e `MONGO_DB`.
  * `settings.local.py` (opcional) para overrides locais sem alterar `settings.py`.
* **Logs**

  * Pasta para logs locais (se optar por `LOG_FILE` do Scrapy); não compromete os requisitos.

---

**settings.py (essencial)**

* `ROBOTSTXT_OBEY=True`
* `DOWNLOAD_DELAY=0.7`
* `AUTOTHROTTLE_ENABLED=True`
* `ITEM_PIPELINES = {"trf5_scraper.pipelines.MongoPipeline": 300}`
* Configuração via ENV: `MONGO_URI`, `MONGO_DB` (ex.: `mongodb://localhost:27017`, `trf5`).

---

# 8. Classificação de página e paginação

## 8.1. Classificação

* **detalhe**: presença simultânea de rótulos/chaves como “PROCESSO Nº”, “RELATOR”, quadro de **envolvidos** e seção de **movimentações**.
* **lista**: tabela de resultados com múltiplos processos e links para detalhe; presença de “Total:” ou barra de páginas.
* **erro**: mensagens de “nenhum resultado”, redirecionos, ou respostas sem a estrutura esperada.

## 8.2. Paginação

* **Modo Total\:N**: extrair inteiro `N`; inferir `page_size` (10 quando não informado); `last_page = ceil(N/page_size) - 1`.
* **Modo Barra**: extrair âncoras de páginas; se existir “última”, seguir seu índice; senão, iterar “próxima” até ausentar o link.
* **Limites operacionais**: `max_pages` e `max_details_per_page` para evitar excesso de tráfego.

---

# 9. Testes E2E (somente ambiente real)

## 9.1. Pré-requisitos

* MongoDB acessível.
* Variáveis de ambiente configuradas (`MONGO_URI`, `MONGO_DB`).
* Proxy/Firewall liberados para acesso ao domínio público do TRF5.

## 9.2. Cenário A — NPU (lista do BB)

Executar um por vez (exemplo):

```
scrapy crawl trf5 -a modo=numero -a valor="0015648-78.1999.4.05.0000" -s LOG_LEVEL=INFO
```

Reexecutar o mesmo comando para validar **update**.

Repetir para:

```
0012656-90.2012.4.05.0000
0043753-74.2013.4.05.0000
0002098-07.2011.4.05.8500
0460674-33.2019.4.05.0000
0000560-67.2017.4.05.0000
```

**Aceite**:

* `raw_pages` com `context.tipo="detalhe"`.
* `processos` com `_id=<NPU>` e campos exigidos.
* Segunda execução: log de **update**.

## 9.3. Cenário B — CNPJ (descoberta)

```
scrapy crawl trf5 \
  -a modo=cnpj -a valor="00.000.000/0001-91" \
  -a max_pages=2 -a max_details_per_page=5 \
  -s LOG_LEVEL=INFO
```

**Aceite**:

* Logs indicando **paginação detectada** (Total\:N ou barra).
* `raw_pages` para **lista** (`page_idx=0..`) e para **detalhes**.
* `processos` populado/atualizado.

## 9.4. Cenário C — Reprocesso offline

```
scrapy crawl parse_raw -a limit=10 -s LOG_LEVEL=INFO
```

**Aceite**:

* Logs “Reprocessando página i: {url}” e “Processo atualizado: {NPU}”.
* Sem requisições de rede.

## 9.5. Consultas rápidas no Mongo (evidência)

Últimas páginas:

```
mongosh trf5 --quiet --eval '
db.raw_pages.find({}, {url:1,"context.tipo":1,"context.busca":1,"context.page_idx":1})
.sort({_id:-1}).limit(10).toArray()
'
```

Processos (NPU + relator):

```
mongosh trf5 --quiet --eval '
db.processos.find({}, {numero_processo:1, relator:1})
.sort({_id:-1}).limit(5).toArray()
'
```

---

# 10. Critérios de aceite do MVP

* [ ] **RF-01**: Para cada NPU da lista, detalhe salvo em `raw_pages` e item em `processos`; 2ª execução realiza **update** (sem duplicidade).
* [ ] **RF-02**: Descoberta via **formulário oficial**, paginação detectada (Total\:N ou barra), limites respeitados, listas e detalhes salvos.
* [ ] **RF-03**: Todos os **campos obrigatórios** presentes e normalizados (datas ISO; relator só nome; `numero_processo` com fallback).
* [ ] **RF-04**: Idempotência válida (insert vs update logados).
* [ ] **RF-05**: README com instruções, comandos e exemplos de verificação no Mongo.
* [ ] **RNF**: Scrapy puro; respeito a robots/delay/autothrottle; logs claros.

---

# 11. Operação (Runbook)

## 11.1. Configuração

```
export MONGO_URI="mongodb://localhost:27017"
export MONGO_DB="trf5"
```

(ou via `.env`/settings conforme preferido)

## 11.2. Execução

* **Número (exemplo)**
  `scrapy crawl trf5 -a modo=numero -a valor="0015648-78.1999.4.05.0000" -s LOG_LEVEL=INFO`
* **CNPJ (exemplo)**
  `scrapy crawl trf5 -a modo=cnpj -a valor="00.000.000/0001-91" -a max_pages=2 -a max_details_per_page=5 -s LOG_LEVEL=INFO`
* **Offline (exemplo)**
  `scrapy crawl parse_raw -a limit=10 -s LOG_LEVEL=INFO`

---

# 12. Riscos e mitigação

* **Variações de layout**: usar seletores resilientes e regex de apoio; sempre salvar HTML bruto.
* **Rate limiting**: atraso + autotrottle + limites de paginação.
* **Encoding**: forçar UTF-8 e testar acentuação; normalizar datas.
* **Campos ausentes**: aplicar fallbacks documentados (ex.: `numero_processo` ← `numero_legado`).
* **Ambiguidade na paginação**: suportar ambos os modos (“Total\:N” e barra de páginas).

---

# 13. Entregáveis

1. **Código Scrapy** (spider, parser, pipeline, utilidades).
2. **README** com instalação, execução (NPU/CNPJ/offline), parâmetros e consultas Mongo.
3. **PRD (este documento)**.
4. **Evidências**: trechos de logs e saídas do Mongo dos três cenários (NPU, CNPJ e offline).

---

# 14. Decisões de implementação (resumo)

* **Scrapy + Mongo** pela simplicidade e bônus do teste.
* **FormRequest** na busca por CNPJ (aderência ao site oficial).
* **raw\_pages** sempre gravado (auditoria e reprocesso).
* **Idempotência** por `_id = NPU normalizado`.
* **Somente testes reais** (sem fixtures) conforme exigido.

---
