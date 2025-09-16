// =============================================================================
// TRF5 Scraper - MongoDB Initialization Script
// =============================================================================
// Este script é executado automaticamente quando o container MongoDB é criado
// pela primeira vez. Cria o banco 'trf5' e usuário de aplicação com permissões
// restritas para desenvolvimento local.

print('=============================================================================');
print('TRF5 Scraper - Inicializando MongoDB');
print('=============================================================================');

// Conecta ao banco 'trf5' (será criado se não existir)
db = db.getSiblingDB('trf5');

print('📁 Criando banco de dados: trf5');

// Cria usuário de aplicação com permissões restritas
print('👤 Criando usuário de aplicação: trf5');

db.createUser({
  user: 'trf5',
  pwd: 'trf5pass',
  roles: [
    {
      role: 'readWrite',
      db: 'trf5'
    }
  ]
});

print('✅ Usuário "trf5" criado com permissões readWrite no banco "trf5"');

// Criar coleções iniciais com validação (opcional)
print('📋 Criando coleções com validação...');

// Coleção raw_pages - para HTML bruto
db.createCollection('raw_pages', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['url', 'html', 'context', 'fetched_at'],
      properties: {
        url: {
          bsonType: 'string',
          description: 'URL da página acessada'
        },
        method: {
          bsonType: 'string',
          enum: ['GET', 'POST'],
          description: 'Método HTTP usado'
        },
        status: {
          bsonType: 'int',
          minimum: 100,
          maximum: 599,
          description: 'Status code HTTP'
        },
        html: {
          bsonType: 'string',
          description: 'Conteúdo HTML bruto da página'
        },
        context: {
          bsonType: 'object',
          required: ['tipo'],
          properties: {
            tipo: {
              bsonType: 'string',
              enum: ['lista', 'detalhe', 'form', 'erro'],
              description: 'Tipo de página classificada'
            },
            busca: {
              bsonType: 'string',
              enum: ['numero', 'cnpj'],
              description: 'Tipo de busca realizada'
            },
            numero: {
              bsonType: 'string',
              pattern: '^\\d{7}-\\d{2}\\.\\d{4}\\.\\d\\.\\d{2}\\.\\d{4}$',
              description: 'NPU normalizado com hífens'
            },
            cnpj: {
              bsonType: 'string',
              pattern: '^\\d{14}$',
              description: 'CNPJ normalizado apenas dígitos'
            },
            page_idx: {
              bsonType: 'int',
              minimum: 0,
              description: 'Índice da página na paginação'
            }
          }
        },
        fetched_at: {
          bsonType: 'string',
          pattern: '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}$',
          description: 'Timestamp ISO-8601 da coleta'
        },
        hash_html: {
          bsonType: 'string',
          pattern: '^sha256:[a-f0-9]{64}$',
          description: 'Hash SHA-256 do HTML para integridade'
        }
      }
    }
  }
});

print('✅ Coleção "raw_pages" criada com validação');

// Coleção processos - para dados estruturados
db.createCollection('processos', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['_id', 'numero_processo', 'fonte_url', 'scraped_at'],
      properties: {
        _id: {
          bsonType: 'string',
          pattern: '^\\d{7}-\\d{2}\\.\\d{4}\\.\\d\\.\\d{2}\\.\\d{4}$',
          description: 'NPU normalizado como chave primária'
        },
        numero_processo: {
          bsonType: 'string',
          description: 'Número principal do processo'
        },
        numero_legado: {
          bsonType: ['string', 'null'],
          description: 'Número legado do processo'
        },
        data_autuacao: {
          bsonType: ['string', 'null'],
          pattern: '^\\d{4}-\\d{2}-\\d{2}(T\\d{2}:\\d{2}:\\d{2})?$',
          description: 'Data de autuação em formato ISO-8601'
        },
        relator: {
          bsonType: ['string', 'null'],
          description: 'Nome do relator (sem títulos)'
        },
        envolvidos: {
          bsonType: 'array',
          items: {
            bsonType: 'object',
            required: ['papel', 'nome'],
            properties: {
              papel: {
                bsonType: 'string',
                description: 'Papel do envolvido (ex: APTE, APDO)'
              },
              nome: {
                bsonType: 'string',
                description: 'Nome do envolvido'
              }
            }
          },
          description: 'Lista de envolvidos no processo'
        },
        movimentacoes: {
          bsonType: 'array',
          items: {
            bsonType: 'object',
            required: ['data', 'texto'],
            properties: {
              data: {
                bsonType: 'string',
                pattern: '^\\d{4}-\\d{2}-\\d{2}(T\\d{2}:\\d{2}:\\d{2})?$',
                description: 'Data da movimentação em formato ISO-8601'
              },
              texto: {
                bsonType: 'string',
                description: 'Texto da movimentação'
              }
            }
          },
          description: 'Lista de movimentações do processo'
        },
        fonte_url: {
          bsonType: 'string',
          description: 'URL de origem dos dados'
        },
        scraped_at: {
          bsonType: 'string',
          pattern: '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}$',
          description: 'Timestamp ISO-8601 da extração'
        }
      }
    }
  }
});

print('✅ Coleção "processos" criada com validação');

// Criar índices para performance conforme PRD
print('🔍 Criando índices para performance...');

// Índices para raw_pages
db.raw_pages.createIndex(
  { "context.tipo": 1, "fetched_at": -1 },
  { name: "idx_tipo_fetched", background: true }
);

db.raw_pages.createIndex(
  { "url": 1, "method": 1 },
  { name: "idx_url_method", background: true }
);

db.raw_pages.createIndex(
  { "context.numero": 1 },
  { name: "idx_numero", background: true, sparse: true }
);

db.raw_pages.createIndex(
  { "context.cnpj": 1 },
  { name: "idx_cnpj", background: true, sparse: true }
);

print('✅ Índices criados para "raw_pages"');

// Índices para processos
db.processos.createIndex(
  { "relator": 1, "data_autuacao": -1 },
  { name: "idx_relator_data", background: true, sparse: true }
);

db.processos.createIndex(
  { "scraped_at": -1 },
  { name: "idx_scraped_at", background: true }
);

print('✅ Índices criados para "processos"');

// Inserir dados de teste (opcional)
print('🧪 Inserindo dados de exemplo...');

// Exemplo de documento raw_pages
db.raw_pages.insertOne({
  url: "http://www5.trf5.jus.br/cp/",
  method: "GET",
  status: 200,
  html: "<!DOCTYPE html><html><head><title>TRF5 - Consulta Processual</title></head><body>Página inicial</body></html>",
  context: {
    tipo: "form",
    busca: "cnpj",
    cnpj: "00000000000191",
    endpoint: "form"
  },
  fetched_at: new Date().toISOString().slice(0, 19),
  hash_html: "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
});

print('✅ Documento de exemplo inserido em "raw_pages"');

// Exemplo de documento processos
db.processos.insertOne({
  _id: "0000000-00.0000.0.00.0000",
  numero_processo: "0000000-00.0000.0.00.0000",
  numero_legado: "00.00.000000-0",
  data_autuacao: "2025-01-01",
  relator: "Exemplo de Relator",
  envolvidos: [
    { papel: "APTE", nome: "Empresa Exemplo LTDA" },
    { papel: "APDO", nome: "União Federal" }
  ],
  movimentacoes: [
    { data: "2025-01-01T10:00:00", texto: "Processo autuado" },
    { data: "2025-01-02T14:30:00", texto: "Processo distribuído" }
  ],
  fonte_url: "http://www5.trf5.jus.br/cp/processo/0000000-00.0000.0.00.0000",
  scraped_at: new Date().toISOString().slice(0, 19)
});

print('✅ Documento de exemplo inserido em "processos"');

// Verificar criação
print('📊 Verificando estrutura criada...');

print('Coleções criadas:');
db.listCollections().forEach(function(collection) {
  print('  - ' + collection.name);
});

print('Índices em raw_pages:');
db.raw_pages.getIndexes().forEach(function(index) {
  print('  - ' + index.name + ': ' + JSON.stringify(index.key));
});

print('Índices em processos:');
db.processos.getIndexes().forEach(function(index) {
  print('  - ' + index.name + ': ' + JSON.stringify(index.key));
});

print('Contadores:');
print('  - raw_pages: ' + db.raw_pages.countDocuments({}));
print('  - processos: ' + db.processos.countDocuments({}));

print('=============================================================================');
print('✅ Inicialização do MongoDB concluída com sucesso!');
print('');
print('🔗 Strings de conexão:');
print('  Admin:   mongodb://root:rootpass@localhost:27017/admin');
print('  App:     mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin');
print('');
print('🧪 Para testar a conexão:');
print('  mongosh "mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin"');
print('');
print('📁 Coleções disponíveis: raw_pages, processos');
print('🔍 Índices otimizados para consultas do TRF5 Scraper');
print('=============================================================================');