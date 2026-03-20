# Ideias — Inteligência Artificial no Bot

---

## Assistente de Texto (LLM)

**`.ask <pergunta>`** — integração com Claude ou GPT-4o para responder perguntas sobre LoL em linguagem natural.
Exemplos: "Qual a melhor build de Jinx contra tanques?", "Como jogar o early game com Thresh?". Contexto do servidor pode ser injetado no prompt (patch atual, meta da liga interna).

**Análise de perfil com IA** — ao rodar `.perfil`, o bot gera um parágrafo automático descrevendo o jogador com base nos dados:
> "Marcos é um jogador Mid com tendência agressiva — WR de 68% nas últimas 10 partidas, melhor performance quando começa no Blue Side. Sequência atual de 4 vitórias."

**Coach automático** — após cada partida registrada, bot envia DM com análise baseada nos dados disponíveis (lado jogado, WR recente, streak, quem eram os adversários):
> "Você perdeu 3 das últimas 4 partidas jogando no Red Side. Considere ajustar a estratégia nesse lado."

---

## Matchmaking Inteligente

**Balanceamento por fator de confiança** — em vez de balancear só por MMR, o modelo considera:
- WR dos últimos 10 jogos (forma atual)
- Performance por lado (Blue vs Red)
- Sinergia histórica entre duplas (quem joga bem junto)

Resultado: times que matematicamente têm MMR equivalente E historicamente performam melhor juntos.

**Predição de resultado** — antes do jogo começar, o bot exibe a probabilidade de vitória de cada time com base nos dados históricos de confrontos diretos e forma recente:
> "Blue Side tem 62% de chance de vitória com base nos últimos 20 confrontos entre esses jogadores."

---

## Análise de Imagem (Vision)

**Análise de tela de fim de jogo** — jogador envia screenshot do scoreboard ao fim de uma partida ranqueada. O bot lê os dados (KDA, CS, dano, visão) via Vision API e gera um resumo:
> "Boa partida! KDA 8/2/11, dano acima da média do seu histórico. Ponto de melhoria: ward score baixo para um suporte."

**Verificação automática de rank** — em vez de chamar a Riot API periodicamente, o jogador envia print do perfil e o bot extrai o rank via OCR, sem depender de chave de API de produção. Útil como fallback ou para servidores sem API key.

---

## Resumo e Narrativa de Partidas

**Narrador automático** — após `.resultado`, o bot gera uma narrativa dramática da partida com base nos dados:
> "Em uma virada histórica, o Time Blue dominou o Red Side de ponta a ponta. Destaque para João, MVP pela terceira vez consecutiva, que mais uma vez silenciou os céticos."

Estilo configurável: sério, dramático, zoeira.

**Resumo semanal gerado por IA** — toda segunda-feira, o bot posta um resumo narrativo da semana: quem se destacou, quem caiu, rivalidades emergentes, streaks quebradas.

---

## Moderação e Clima

**Detector de toxicidade** — monitora mensagens do servidor e alerta moderadores (sem banir automaticamente) quando detecta linguagem agressiva direcionada. Modelo leve rodando localmente (ex: `detoxify`).

**Termômetro de clima** — analisa o tom geral das mensagens do dia e classifica o servidor:
> "🌡️ Clima hoje: Tenso. Muita reclamação após a última partida."

---

## Recomendações Personalizadas

**Recomendador de campeão** — com base na lane do jogador, rank e meta atual, sugere campeões para aprender:
> "Para seu perfil Mid/Assassino no Gold, os campeões com maior curva de impacto agora são: Zed, Talon, Qiyana."

**Sugestão de duo** — analisa o histórico de partidas internas e sugere com quem o jogador performa melhor:
> "Você vence 78% das partidas quando está no mesmo time que Pedro. Considerem duo."

---

## Implementação Técnica

| Ideia | Tecnologia sugerida | Custo |
|-------|-------------------|-------|
| Assistente / análise de perfil / coach | Claude API (`claude-haiku-4-5` para custo baixo) | Por token |
| Análise de imagem (scoreboard, rank) | Claude Vision ou GPT-4o Vision | Por token |
| Narrador de partidas / resumo semanal | Claude API | Por token |
| Predição de resultado | Modelo treinado localmente com histórico interno | Zero (após treino) |
| Detector de toxicidade | `detoxify` (Python, roda local, open source) | Zero |
| Recomendador de campeão / duo | Regras + embedding simples ou LLM | Baixo |

**Arquitetura sugerida para LLM:**
- Criar `src/services/ai_service.py` com cliente Anthropic
- Injetar contexto relevante (dados do jogador, histórico, meta) no system prompt
- Cachear respostas que não mudam frequentemente (ex: recomendações de campeão por patch)
- Usar `claude-haiku-4-5` para features de alto volume (narrador, coach por DM) e `claude-sonnet-4-6` para análises mais complexas

**Custo estimado para comunidade pequena (~20 jogadores ativos):**
- Coach pós-partida + narrador: ~$1–3/mês com Haiku
- Assistente `.ask` depende do volume de uso — recomendado limitar com cooldown por usuário
