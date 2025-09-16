# Docker Setup - TRF5 Scraper MongoDB

Este diretório contém a configuração Docker Compose para executar MongoDB localmente para o TRF5 Scraper.

## 🚀 Início Rápido

```bash
# Subir o MongoDB
docker compose up -d

# Verificar status
docker compose ps

# Ver logs
docker compose logs -f mongo

# Testar conexão
mongosh "mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin"
```

## 📁 Estrutura

```
docker/
├── compose.yaml              # Configuração principal
├── mongo/
│   ├── initdb.d/
│   │   └── init.js           # Script de inicialização
│   └── mongod.conf           # Configuração MongoDB
├── data/                     # Dados persistentes (criado automaticamente)
├── backups/                  # Backups (criado automaticamente)
└── README.md                 # Este arquivo
```

## 🗄️ Usuários e Acesso

### Root (Admin)
- **Usuário**: `root`
- **Senha**: `rootpass`
- **URI**: `mongodb://root:rootpass@localhost:27017/admin`

### Aplicação
- **Usuário**: `trf5`
- **Senha**: `trf5pass`
- **URI**: `mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin`

## 🔧 Comandos Úteis

### Gerenciar Container

```bash
# Subir serviços
docker compose up -d

# Parar serviços
docker compose stop

# Parar e remover
docker compose down

# Parar e remover com dados
docker compose down -v
```

### Interface Web (Opcional)

```bash
# Subir com Mongo Express
docker compose --profile tools up -d

# Acessar: http://localhost:8081
# Usuário: admin
# Senha: admin123
```

### Backup e Restore

```bash
# Backup completo
docker exec trf5-mongo sh -c "mongodump --db trf5 --archive" > ./backups/trf5-$(date +%F).archive

# Backup apenas processos
docker exec trf5-mongo sh -c "mongodump --db trf5 --collection processos --archive" > ./backups/processos-$(date +%F).archive

# Restore
docker exec -i trf5-mongo sh -c "mongorestore --archive" < ./backups/trf5-YYYY-MM-DD.archive
```

### Logs e Debug

```bash
# Logs em tempo real
docker compose logs -f

# Logs do MongoDB apenas
docker compose logs -f mongo

# Entrar no container
docker exec -it trf5-mongo bash

# Executar mongosh no container
docker exec -it trf5-mongo mongosh "mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin"
```

## 📊 Verificação de Funcionamento

```bash
# 1. Container rodando
docker compose ps

# 2. MongoDB respondendo
docker exec trf5-mongo mongosh --eval "db.runCommand('ping')"

# 3. Banco e coleções criados
docker exec trf5-mongo mongosh "mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin" --eval "show collections"

# 4. Conectar do host
mongosh "mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin" --eval "db.processos.find().limit(1)"
```

## 🔒 Segurança

- **Bind local**: MongoDB só aceita conexões de localhost
- **Autenticação**: Usuário root separado do usuário da aplicação
- **Permissões**: Usuário `trf5` tem apenas readWrite no banco `trf5`
- **Rede isolada**: Container roda em rede Docker dedicada

## 🐛 Troubleshooting

### MongoDB não inicia

```bash
# Verificar logs
docker compose logs mongo

# Verificar permissões do diretório data
ls -la data/

# Remover dados corrompidos
docker compose down -v
rm -rf data/
docker compose up -d
```

### Não consegue conectar

```bash
# Verificar se está rodando
docker compose ps

# Testar dentro do container
docker exec -it trf5-mongo mongosh

# Verificar variáveis de ambiente
docker exec trf5-mongo env | grep MONGO
```

### Performance lenta

```bash
# Verificar recursos
docker stats trf5-mongo

# Verificar logs de operações lentas
docker compose logs mongo | grep slow
```

## 📋 Configuração da Aplicação

No arquivo `.env` da aplicação, use:

```bash
MONGO_URI=mongodb://trf5:trf5pass@localhost:27017/trf5?authSource=admin
MONGO_DB=trf5
```

## 🧹 Limpeza Completa

```bash
# Parar e remover tudo
docker compose down -v

# Remover dados locais
rm -rf data/ backups/

# Remover imagens (opcional)
docker rmi mongo:7.0 mongo-express:1.0.2
```

---

**Nota**: Esta configuração é para desenvolvimento local. Para produção, use MongoDB Atlas ou configure TLS, firewall e autenticação robusta.