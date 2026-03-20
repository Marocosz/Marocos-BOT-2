# MarocosBot — Liga Interna de League of Legends

Bot Discord para gerenciamento completo de uma liga interna de League of Legends. Integra-se à Riot API para verificação de contas, rastreamento de elo em tempo real, sistema de MMR próprio com fórmula híbrida, matchmaking automatizado e sistema de engajamento comunitário.

---

## Sumário

- [Visão Geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Funcionalidades](#funcionalidades)
- [Regras de Negócio](#regras-de-negócio)
- [Stack Tecnológica](#stack-tecnológica)
- [Integrações](#integrações)
- [Fluxos Internos](#fluxos-internos)
- [Referência de Comandos](#referência-de-comandos)
- [Sistema de Agenda](#sistema-de-agenda)
- [Sistema de Anúncios](#sistema-de-anúncios)
- [Configuração e Instalação](#configuração-e-instalação)
- [Limitações e Melhorias](#limitações-e-melhorias)

---

## Visão Geral

O MarocosBot resolve o problema de organizar competições internas de League of Legends em servidores Discord, onde não existe uma ferramenta oficial para:

- Verificar que cada participante é dono de sua própria conta Riot
- Calcular um MMR interno justo que reflita o nível real do jogador
- Montar times equilibrados automaticamente
- Conduzir drafts de capitães com interface interativa
- Rastrear promoções/rebaixamentos em tempo real e notificar o servidor
- Engajar a comunidade com um sistema de XP por voz e mensagens

**Casos de uso principais:**
- Um organizador abre fila, 10 jogadores entram, times são balanceados ou capitães selecionam jogadores via draft
- Resultado registrado → W/L e MMR atualizados → votação MVP/iMVP lançada automaticamente
- Background task monitora mudanças de elo a cada 10 minutos e posta notificações no canal configurado

---

## Arquitetura

O projeto segue uma arquitetura em camadas com separação clara de responsabilidades:

```
src/
├── main.py                  # Entry point: inicializa RobustBot, carrega cogs, inicia DB
├── bot/                     # Classe RobustBot (extends commands.Bot)
├── cogs/                    # Módulos de comandos Discord (carregados dinamicamente)
│   ├── auth.py              # Registro de jogadores e verificação Riot
│   ├── lobby.py             # Fila, draft, resultado de partidas (maior módulo)
│   ├── ranking.py           # Ranking, perfil, MMR, histórico, live
│   ├── comunidade.py        # Sistema de XP/níveis e perfil social
│   ├── agenda.py            # Eventos agendados com confirmação e lembretes automáticos
│   ├── tracking.py          # Background task de rastreamento de elo
│   ├── admin.py             # Comandos administrativos
│   ├── general.py           # Sistema de ajuda interativo (7 seções)
│   ├── utility.py           # Ferramentas de meta e builds
│   └── zoeira.py            # Easter egg
├── database/
│   ├── config.py            # Engine SQLAlchemy async + session factory
│   ├── models.py            # Modelos ORM (Players, Matches, CommunityProfiles, etc.)
│   └── repositories.py      # Camada de acesso a dados (CRUD por domínio)
├── services/
│   ├── riot_api.py          # Cliente da Riot Games API (rate limit, semáforo)
│   ├── matchmaker.py        # Cálculo de MMR e balanceamento de times
│   └── queue_manager.py     # Estado da fila de partidas
└── utils/
    └── views.py             # BaseInteractiveView e componentes Discord UI reutilizáveis
```

### Comunicação entre componentes

- **Cogs** nunca acessam modelos ORM diretamente — passam pelos **Repositories**
- **Services** são stateless (exceto queue_manager) e chamados pelos cogs
- **RiotAPI** é injetado/importado nos cogs que precisam de dados externos
- **Views** (botões, dropdowns) callbacks chamam de volta os métodos dos cogs que as criaram

---

## Funcionalidades

### Registro de Jogadores (`.registrar`)

Vincula a conta Discord do usuário a uma conta Riot com verificação anti-fraude:

1. Usuário informa `Nick#TAG`, lane principal e opcionalmente lane secundária
2. Bot busca o PUUID na Riot API
3. Gera número de ícone aleatório (0–28) e exibe embed pedindo para trocar o ícone
4. Ao clicar no botão de verificação, compara o ícone atual do perfil com o solicitado
5. Se confirmado: cria registro do jogador e calcula MMR inicial com base no rank atual

### Sistema de Fila e Partidas (`.fila`)

**Modos de criação de times:**

| Modo | Descrição |
|------|-----------|
| ⚖️ Auto-Balanceado | Snake distribution por MMR — matematicamente equilibrado |
| 👑 Capitães - Top Elo | 2 jogadores de maior MMR viram capitães |
| 🎲 Capitães - Aleatório | 2 capitães escolhidos aleatoriamente |
| 👮 Capitães - Manual | Admin seleciona capitães via dropdown |

**Fluxo de draft com capitães:**
1. Coin flip determina prioridade (First Pick) vs escolha de lado
2. Capitão secundário escolhe Blue ou Red
3. Draft alternado: cada capitão escolhe 1 jogador por vez até completar 10
4. Escolhas exibidas em embed atualizado em tempo real

**Registro de resultado (`.resultado <ID> <Blue/Red>`):**
- Atualiza W/L de cada jogador
- **Recalcula MMR imediatamente** para todos os participantes (não aguarda task de 10min)
- Atualiza streaks de vitórias — anuncia marcos de 3, 5, 7, 10, 15, 20 vitórias seguidas
- Lança automaticamente votações de MVP (melhor do time vencedor) e iMVP (pior do time perdedor)
- Votação dura 30 minutos; contagem exclui a própria reação do bot
- Em empate: exibe todos os nomes empatados

### Sistema de MMR

MMR interno calculado por fórmula híbrida em `services/matchmaker.py`:

```
base_score = tier_value + rank_value + lp

# Master+ especial:
base_score = 2800 + lp

# Peso por fila:
base_ajustado = base_score × (0.85 se Flex | 1.0 se SoloQ)

# Bônus de velocidade (K-Factor diminui com experiência):
k = 20 (<50 jogos) | 12 (50-100) | 8 (100-150) | 4 (150-200) | 2 (200+)
bonus = (WR% - 50) × k

mmr_final = base_ajustado + bonus  (mínimo: 0)
```

**Valores por tier:**

| Tier | Valor base |
|------|-----------|
| IRON | 0 |
| BRONZE | 400 |
| SILVER | 800 |
| GOLD | 1200 |
| PLATINUM | 1600 |
| EMERALD | 2000 |
| DIAMOND | 2400 |
| MASTER+ | 2800 |
| UNRANKED | 1000 |

**Rank dentro do tier:** IV=+0, III=+100, II=+200, I=+300

### Balanceamento de Times (Snake Distribution)

Com 10 jogadores ordenados por MMR (maior → menor), a distribuição é:
- **Time Blue:** índices [0, 3, 4, 7, 8]
- **Time Red:** índices [1, 2, 5, 6, 9]

Isso garante que os dois times tenham soma de MMR matematicamente equivalente.

### Rastreamento de Elo (Background Task)

Loop a cada 10 minutos que:
1. Busca todos os jogadores registrados com PUUID
2. Consulta rank atual na Riot API (prioriza SoloQ, fallback para Flex)
3. Recalcula MMR e salva no banco independentemente de mudança de elo
4. Se tier/rank mudou: posta mensagem aleatória de promoção ou rebaixamento no canal configurado

### Sistema de XP e Níveis

| Ação | XP ganho | Regras |
|------|----------|--------|
| Mensagem de texto | 15–25 XP | Cooldown de 5 segundos |
| Permanência em voz | 10 XP/minuto | Mínimo 2 pessoas no canal; para se mutar/desativar som |

**Fórmula de nível:** `xp_necessário = nível_atual × 100 × 1.2`

**Sessões de voz:** Rastreadas via timestamps no evento `on_voice_state_update`. Sessões em andamento são restauradas no restart do bot se ainda houver 2+ pessoas no canal.

**Status de atividade calculado automaticamente:**

| Última mensagem | Status |
|----------------|--------|
| < 1 hora | 🟢 Online & Ativo |
| < 24 horas | 🟡 Visto Hoje |
| < 7 dias | 🟠 Casual |
| < 30 dias | 🔴 Ausente |
| > 30 dias | 💀 Inativo |
| Nunca | 👻 Fantasma |

### Cargos Automáticos de Vencedor/Perdedor

Ao registrar `.resultado`, o bot remove automaticamente os cargos de vencedor e perdedor de todos os 10 jogadores da partida e reatribui conforme o resultado:

- **Time vencedor** recebe o cargo de vencedor
- **Time perdedor** recebe o cargo de perdedor

Configuração (uma única vez):
```
.config_cargo vencedor @NomeDoCargoVencedor
.config_cargo perdedor @NomeDoCardoPerdedor
```

> O bot precisa ter permissão de "Gerenciar Cargos" e estar acima dos cargos configurados na hierarquia do servidor.

### Streaks e Conquistas

- `current_win_streak` e `best_win_streak` rastreados por jogador no banco
- Ao registrar resultado, vitórias incrementam o streak; derrotas zeram
- Marcos anunciados automaticamente no canal: **3, 5, 7, 10, 15, 20** vitórias seguidas
- Streak aparece no `.ranking` (ícone 🔥) e no `.perfil`

### Histórico Interno (`.historico_liga`) e Detalhes (`.partida`)

- `.historico_liga [@user]` — **todas** as partidas internas com paginação (10/página), resultado (W/L), lado jogado e data. Cabeçalho exibe WR geral
- `.partida <ID>` — detalhes completos: times, MMR snapshot no momento da partida, resultado, datas

### Confronto Direto (`.h2h @user1 @user2`)

Compara o histórico entre dois jogadores registrados:
- Partidas como **adversários**: vitórias de cada um, winrate
- Partidas como **aliados**: WR juntos
- Últimas 5 partidas em comum com resultado

### Ferramentas de Meta

- **`.build <campeão>`** — busca fuzzy por nome (similaridade ≥ 0.7), exibe skills, lore e links diretos para U.GG e OP.GG. Dados do campeão cacheados no startup via Data Dragon.
- **`.meta <lane>`** — links diretos para tier lists de U.GG, OP.GG e Lolalytics
- **`.patch`** — versão atual do jogo com link para notas de patch em PT-BR

---

## Regras de Negócio

### Registro
- Conta Riot obrigatória no formato `Nick#TAG`
- Verificação por ícone impede usurpação de contas de terceiros
- Caracteres Unicode invisíveis removidos automaticamente do input
- Se 2 lanes informadas, a **última vira lane principal** (comportamento específico de parsing)
- Se sem rank: MMR inicial = 1000

### Fila e Partidas
- Fila comporta exatamente 10 jogadores (produção) — configurável via `DEBUG_QUEUE_LIMIT`
- Não é possível abrir nova fila com partida `IN_PROGRESS`
- Jogadores com ID negativo são bots de preenchimento (modo debug)
- Somente jogadores reais (ID > 0) participam de votações e cálculos de capitão
- Match ID auto-incrementa e persiste no banco; reiniciar o bot não reinicia a contagem

### MMR
- Flex 5v5 sempre vale 85% de uma conta equivalente em SoloQ
- K-factor da velocidade reduz progressivamente com a quantidade de jogos (20x → 2x)
- MMR nunca é negativo

### XP e Voz
- XP de voz só conta com **2+ pessoas** no canal
- Sessão de voz pausada se usuário mutar, desativar som ou trocar de canal
- Cooldown de 5s entre ganhos de XP por texto

### Rastreamento
- Alertas disparam apenas em mudança de tier/rank (não por LP)
- MMR é recalculado em todo ciclo independentemente de mudança visível

---

## Stack Tecnológica

| Tecnologia | Versão | Papel |
|-----------|--------|-------|
| Python | 3.11 | Linguagem principal |
| discord.py | 2.6.4 | Framework Discord — eventos, comandos, UI (Views/Buttons) |
| SQLAlchemy | 2.0.44 | ORM assíncrono — mapeamento e queries |
| aiosqlite | 0.21.0 | Driver SQLite async |
| aiohttp | 3.13.2 | HTTP client assíncrono (Riot API) |
| python-dotenv | 1.2.1 | Carregamento de variáveis de ambiente do `.env` |
| requests | 2.32.5 | HTTP sync (Data Dragon, utilitários) |
| Docker | - | Containerização para deploy no Coolify |

---

## Integrações

### Riot Games API

**Base URL:** `https://{region}.api.riotgames.com`
**Routing:** `https://americas.api.riotgames.com` (para histórico)

| Endpoint | Uso |
|---------|-----|
| `/riot/account/v1/accounts/by-riot-id/{name}/{tag}` | Busca PUUID por Nick#TAG |
| `/lol/summoner/v4/summoners/by-puuid/{puuid}` | Dados do summoner (nível, ícone) |
| `/lol/league/v4/entries/by-puuid/{puuid}` | Ranks SoloQ e Flex |
| `/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top` | Top maestrias |
| `/lol/match/v5/matches/by-puuid/{puuid}/ids` | IDs das últimas partidas |
| `/lol/match/v5/matches/{matchId}` | Detalhes de uma partida |
| `/lol/spectator/v5/active-games/by-summoner/{summonerId}` | Partida ao vivo |
| Data Dragon | Cache de dados de campeões (nome, skills, lore, splash art) |

**Rate limiting:** Semáforo com máximo 10 requisições simultâneas. Em 429, aguarda o valor de `Retry-After`. Em 403, alerta sobre API key inválida.

### Discord API (via discord.py)

**Intents usadas:** `default` + `message_content` + `members` + `presences`

O bot utiliza extensivamente:
- **Views** com botões e dropdowns para todo o fluxo de lobby/draft
- **Reactions** para votação de MVP/iMVP
- **Embeds** formatados para perfis, ranking e notificações
- **Background Tasks** para o loop de rastreamento de elo

---

## Fluxos Internos

### Registro de Jogador
```
.registrar Nick#TAG Lane → validação de input → limpeza Unicode
    → Riot API: busca PUUID → gera ícone aleatório → embed de verificação
        ↓ (clique no botão, timeout 180s)
    → Riot API: busca ícone atual → compara com solicitado
        ↓ (match)
    → cria Player no DB → Riot API: busca rank → calcula MMR inicial → salva
```

### Ciclo de Partida
```
.fila → botões Entrar/Sair → fila atinge 10 → seleção de modo
    ↓
Auto-balanceado: snake distribution → captains nomeados → coinflip → draft
Capitães: seleção → coinflip → escolha de lado → draft alternado
    ↓
DraftView: 10 picks concluídos → .resultado ID lado
    ↓
DB: finish_match() → W/L atualizado → polls MVP/iMVP (30min)
    ↓
Poll encerra → contagem de reações (−1 do bot) → exibe vencedor → reset lobby
```

### Rastreamento de Elo
```
Loop 10min → get_all_players_with_puuid()
    ↓ (para cada jogador, 1.5s de intervalo)
Riot API: get_rank_by_puuid() → calcula MMR ajustado → salva no DB
    ↓ (se tier/rank mudou)
Busca tracking_channel do guild → posta mensagem aleatória de promoção/rebaixamento
```

### XP por Voz
```
on_voice_state_update → usuário entra com 2+ pessoas no canal
    → inicia session: {user_id: datetime.now()}
        ↓ (ao sair / mutar / desativar som)
    → calcula minutos = (agora - início)
    → CommunityRepository.add_xp(user_id, minutos * 10, voice_minutes=minutos)
        ↓ (se xp >= xp_necessário)
    → level++ → reação 🆙 na última mensagem
```

---

## Referência de Comandos

### Jogadores

| Comando | Aliases | Argumentos | Descrição |
|---------|---------|-----------|-----------|
| `.registrar` | — | `<Nick#TAG> <Lane> [Lane2]` | Vincula conta Riot com verificação por ícone |
| `.perfil` | — | `[@user]` | Exibe card completo: ranks, MMR, streaks, maestrias |
| `.mmr` | — | `[@user]` | Breakdown detalhado do cálculo de MMR |
| `.historico` | — | `[@user]` | Últimas 10 partidas ranqueadas (Riot API) |
| `.historico_liga` | `.hliga` | `[@user]` | Histórico de partidas internas da liga |
| `.partida` | — | `<ID>` | Detalhes completos de uma partida interna |
| `.h2h` | — | `<@user1> <@user2>` | Confronto direto entre dois jogadores |
| `.live` | — | `[@user]` | Verifica se o jogador está em partida agora |
| `.ranking` | `.top`, `.leaderboard` | — | Ranking interno paginado (mostra streak 🔥) |
| `.social` | `.perfil_social`, `.rank`, `.comunidade` | `[@user]` | Perfil de engajamento: XP, nível, voz, mensagens |
| `.ranking_xp` | `.topxp`, `.top_social` | — | Top 10 por nível e XP |
| `.fila` | — | — | Abre fila para nova partida |
| `.ajuda` | `.help`, `.comandos` | — | Menu interativo de ajuda com 7 seções |
| `.agenda` | — | `[ID]` | Lista eventos abertos ou exibe embed completo de um evento específico |

### Ferramentas

| Comando | Argumentos | Descrição |
|---------|-----------|-----------|
| `.build` | `<campeão>` | Skills, lore e links de builds (U.GG, OP.GG) |
| `.meta` | `<lane>` | Links para tier lists da lane |
| `.patch` | — | Versão atual + link para patch notes PT-BR |

### Admin / Organizador

| Comando | Argumentos | Descrição |
|---------|-----------|-----------|
| `.resultado` | `<ID> <Blue\|Red>` | Registra resultado, atualiza MMR, streaks e lança MVP/iMVP |
| `.anular` | `<ID>` | Cancela partida sem registrar stats |
| `.recalcular_mmr` | `.recalc_mmr` | Recalcula MMR de todos os jogadores (dados cached) |
| `.config_cargo` | `<vencedor\|perdedor> @Cargo` | Define cargo atribuído automaticamente após cada resultado |
| `.config_aviso` | `<#canal>` | Define canal de notificações de elo (também usado pelo `announce.py`) |
| `.forcar_check` | — | Força execução imediata do loop de rastreamento |
| `.fake_elo` | `<@user> <TIER> <RANK> [SOLO\|FLEX]` | Testa notificações de elo |
| `.resetar` | — | Alterna entre modo debug e produção na fila |
| `.clear` | — | Apaga últimas 1000 mensagens do bot (com confirmação) |
| `.clear_all` | — | Apaga últimas 1000 mensagens de todos (com confirmação) |

### Agenda (Admin)

| Comando | Argumentos | Descrição |
|---------|-----------|-----------|
| `.agendar` | `<DD/MM/YYYY> <HH:MM> <Título>` | Cria evento com embed e botões de confirmação |
| `.cancelar_agenda` | `<ID>` | Cancela evento e notifica confirmados por DM |
| `.add_agenda` | `<ID> @user` | Adiciona jogador manualmente ao evento |
| `.kick_agenda` | `<ID> @user` | Remove jogador do evento |
| `.iniciar_agenda` | `<ID>` | Fecha inscrições e pinga todos os confirmados no canal |

---

## Sistema de Agenda

Sistema para agendar eventos com antecedência, gerenciar confirmações e enviar lembretes automáticos por DM — completamente desacoplado da fila de partidas.

### Fluxo básico

```
Admin: .agendar 21/03/2025 21:00 Sexta Ranqueada
    → bot posta embed com botões [✅ Confirmar] [❌ Sair]
    → jogadores clicam para confirmar (embed atualiza em tempo real)
        ↓ (automático, sem ação manual)
    → DM 24h antes → DM 30min antes para cada confirmado
        ↓ (quando chegar a hora)
    → Admin: .iniciar_agenda <ID>
    → bot pinga todos os confirmados no canal + fecha inscrições
    → Admin abre .fila manualmente com quem apareceu
```

### Lembretes automáticos

Task em background (a cada 5 minutos) verifica eventos abertos e envia DM para cada confirmado:
- **24 horas antes** do horário agendado
- **30 minutos antes** do horário agendado

Lembretes são enviados uma única vez (flags `notified_24h` / `notified_30min` no banco). Se o jogador tiver DMs fechadas, o bot ignora silenciosamente.

### Views persistentes

Os botões de confirmar/sair usam `custom_id` por evento (`agenda_confirm_{id}`) com `timeout=None`. Ao reiniciar o bot, o cog re-registra as views de todos os eventos abertos via `cog_load`, garantindo que os botões continuem funcionando mesmo após restart.

### Recuperar embed de um evento

Se a mensagem original subiu no histórico do canal e não é mais visível:

```
.agenda 3   → reposta o embed completo do evento #3 com os botões funcionando
```

A referência da mensagem no banco é atualizada para a nova mensagem, garantindo que futuras confirmações editem o embed correto.

### Cancelamento

`.cancelar_agenda <ID>` cancela o evento e envia DM de aviso para cada confirmado automaticamente.

---

## Sistema de Anúncios

O bot possui um sistema de anúncios controlado pelo **backend** — você cria um arquivo Markdown localmente e executa um script que envia a mensagem diretamente no canal configurado do Discord, sem precisar digitar nada no chat.

### Setup

O script usa automaticamente o canal já configurado via `.config_aviso #canal` (o mesmo canal de notificações de elo). Nenhuma configuração extra necessária.

Se quiser enviar em um canal diferente sem configurar nada, use `--channel <id>` diretamente.

### Criando um anúncio

Crie um arquivo `.md` na pasta `announcements/` (ou em qualquer lugar):

```markdown
# Versão 2.1 — Novos Comandos

## O que há de novo

- `.h2h @user1 @user2` — confronto direto entre dois jogadores
- `.historico_liga` — seus últimos 10 jogos internos
- `.partida <ID>` — detalhes completos de qualquer partida

## Correções

- MMR agora atualizado imediatamente após `.resultado`
- Contagem de MVP não conta mais a reação do próprio bot
- Fila agora sobrevive a reinicializações do bot
```

- A primeira linha `# Heading` vira o **título** do embed no Discord
- O restante vira o **corpo** (suporta `**negrito**`, `*itálico*`, listas, `## seções`)
- Se não houver heading, o nome do arquivo vira o título

### Enviando

```bash
# Da raiz do projeto
python announce.py <tipo> <arquivo.md> [--mention <texto>] [--guild <id>]
```

**Tipos disponíveis:**

| Tipo | Emoji | Cor | Uso |
|------|-------|-----|-----|
| `update` | 🔄 | Azul | Atualizações de versão, changelogs |
| `feature` | ✨ | Verde | Novas funcionalidades |
| `maintenance` | 🔧 | Laranja | Avisos de manutenção ou downtime |
| `event` | 🏆 | Roxo | Eventos, torneios, campeonatos |
| `info` | 📢 | Cinza | Informações gerais, comunicados |

**Exemplos:**

```bash
# Envia changelog de atualização (usa o canal do .config_aviso)
python announce.py update announcements/exemplo_update.md

# Feature nova com menção @everyone
python announce.py feature announcements/nova_feature.md --mention @everyone

# Aviso de manutenção em servidor específico
python announce.py maintenance announcements/manutencao.md --guild 123456789012345678

# Canal manual direto (sem precisar de .config_aviso)
python announce.py info announcements/aviso.md --channel 987654321098765432

# Evento com menção @aqui
python announce.py event announcements/torneio.md --mention "@here"
```

**Comportamento com múltiplos servidores:**

Se o bot estiver em mais de um servidor com `.config_aviso` configurado, o script envia para **todos** por padrão. Use `--guild <id>` para filtrar um servidor específico.

### Como funciona internamente

```
announce.py
    → lê o .md e extrai título + corpo
    → consulta data/database.sqlite (tracking_channel_id por guild)
      ou usa --channel <id> diretamente (ignora o banco)
    → chama Discord REST API diretamente com o bot token
    → envia embed formatado no canal
```

O script **não depende do bot estar rodando** — ele usa o token do `.env` para chamar a API do Discord diretamente. Não requer dependências extras além da stdlib do Python.

### Saída esperada

```
  Tipo   : Atualizacao
  Titulo : Versão 2.1 — Novos Comandos
  Corpo  : 312 caracteres

[*] Enviando para guild 123456789012345678 -> canal 987654321098765432 ...
    [OK] Enviado!

[OK] 1/1 servidor(es) receberam o anuncio.
```

---

## Configuração e Instalação

### Pré-requisitos

- Python 3.11+
- Conta de desenvolvedor Discord (bot token)
- Chave da Riot API ([developer.riotgames.com](https://developer.riotgames.com))

### Instalação local

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Criar arquivo de configuração
cp .env.example .env   # edite com suas chaves

# 3. Inicializar banco de dados (primeira vez)
python force_tables.py

# 4. Aplicar migrações (se atualizar de versão anterior)
python update_db.py

# 5. Rodar o bot
python -m src.main
```

### Variáveis de ambiente

```env
DISCORD_TOKEN=           # Token do bot Discord
APP_ID=                  # Application ID do bot Discord
RIOT_API_KEY=            # Chave da Riot API
RIOT_REGION=br1          # Região (br1, na1, euw1, etc.)
DATABASE_URL=sqlite+aiosqlite:///./data/database.sqlite
LOG_LEVEL=INFO
DEBUG_GUILD_ID=          # ID do servidor para testes (opcional)
```

### Docker / Coolify

```bash
docker build -t marocos-bot .
docker run --env-file .env marocos-bot
```

O arquivo `data/database.sqlite` deve ser montado como volume persistente para não perder dados ao atualizar o container.

### Utilitários de banco de dados

```bash
python force_tables.py     # Cria/recria tabelas (use só na primeira vez ou após reset)
python migration_tool.py   # Executa migrações de schema
python update_db.py        # Atualiza schema incrementalmente
python debug_api.py        # Testa chamadas à Riot API
```

---

## Limitações e Melhorias

### Limitações atuais

- **SQLite** não suporta múltiplas escritas concorrentes — adequado para comunidades pequenas/médias, mas limitante para servidores muito ativos
- **Chave de API da Riot** de desenvolvimento expira a cada 24h; produção exige chave aprovada de produção
- **Uma instância por token** — não é possível rodar dois bots com o mesmo token simultaneamente (use tokens separados para dev/prod)
- **Match history** limitado a 10 partidas por consulta na Riot API

### Melhorias sugeridas

- Migrar para PostgreSQL para maior robustez e suporte a concorrência
- Adicionar sistema de log estruturado com rotação de arquivos
- Criar endpoint de health check para monitoramento no Coolify
- Implementar `.env.example` para facilitar onboarding
- Adicionar cooldown de comandos por usuário para evitar spam
- Dashboard web para visualização de stats e histórico de partidas
