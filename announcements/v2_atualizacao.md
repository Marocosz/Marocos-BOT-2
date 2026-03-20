# Liga Interna — Atualização v2.0

## Novos Comandos

**`.historico_liga`** (alias `.hliga`) — seus últimos 10 jogos internos com resultado (V/D), lado jogado e data relativa

**`.partida <ID>`** — detalhes completos de qualquer partida: composição dos times, MMR de cada jogador na época, resultado e timestamps

**`.h2h @user1 @user2`** — confronto direto entre dois jogadores: histórico como adversários (WR individual), como parceiros (WR juntos) e últimas partidas em comum

**`.recalcular_mmr`** *(admin)* — recalcula o MMR de todos os jogadores registrados com base no rank salvo, sem chamar a Riot API

## Melhorias

**MMR imediato após resultado**
O MMR agora é atualizado imediatamente após o `.resultado`, sem aguardar a task de rastreamento de 10 minutos.

**Streaks de vitórias**
Sequências de vitórias são rastreadas por jogador. Marcos de **3, 5, 7, 10, 15 e 20** vitórias seguidas são anunciados automaticamente no canal. A sequência atual aparece no `.ranking` com 🔥 e no `.perfil`.

**MVP e iMVP salvos no perfil**
Os títulos de MVP e iMVP agora são registrados no banco de dados. O `.perfil` passa a exibir quantas vezes cada jogador foi votado como MVP (melhor do vencedor) ou iMVP (pior do perdedor).

**Fila persistente**
A fila de jogadores agora sobrevive a reinicializações do bot. Se o bot cair com uma fila aberta, ela é restaurada automaticamente quando ele voltar.

**Notificação de level up**
Ao subir de nível no sistema de comunidade, o bot envia um embed de parabéns no canal com o novo nível e o XP necessário para o próximo.

## Correções

**`.registrar`** — a ordem das lanes agora é intuitiva: `.registrar Nick#TAG Mid Top` define **Mid** como principal e **Top** como secundária (antes a lógica era invertida)

**Votação MVP/iMVP** — corrigido bug onde a própria reação do bot era contada como voto, inflando o resultado

## Sistema de Agenda

Novo sistema para agendar eventos com antecedência.

**`.agendar DD/MM/YYYY HH:MM Título`** *(admin)* — cria um evento com botões de confirmação no canal. O embed é atualizado em tempo real à medida que os jogadores confirmam presença.

**`.agenda`** — lista todos os eventos abertos com data, confirmados e vagas.

**`.agenda <ID>`** — reposta o embed completo de um evento específico com os botões de confirmar/sair funcionando. Útil quando a mensagem original sumiu no histórico do canal.

**Controles do admin:** `.cancelar_agenda`, `.add_agenda @user`, `.kick_agenda @user`, `.iniciar_agenda`

**Lembretes automáticos por DM:** o bot avisa cada confirmado **24 horas** e **30 minutos** antes do evento começar.

## Cargos Automáticos de Vencedor/Perdedor

O bot agora atribui os cargos de vencedor e perdedor automaticamente ao registrar o `.resultado`, eliminando o processo manual.

Ao finalizar uma partida, o bot remove os cargos antigos dos 10 jogadores e reatribui conforme o resultado: cargo de vencedor para o time vencedor, cargo de perdedor para o time perdedor.

**Configuração inicial (admin):**
`.config_cargo vencedor @Vencedor`
`.config_cargo perdedor @Perdedor`

## Help Atualizado

O painel de ajuda (`.ajuda`) foi completamente reescrito com 7 seções cobrindo todos os comandos, incluindo o novo sistema de Agenda e todas as funcionalidades adicionadas nesta atualização.

## Verificação de Registro Automática

O processo de vinculação de conta Riot foi melhorado.

**Antes:** era necessário clicar no botão "Já troquei!" repetidamente e torcer para a API da Riot ter atualizado.

**Agora:** após trocar o ícone no LoL, o bot verifica automaticamente a cada **1 minuto** por até **10 minutos**. Assim que a API da Riot atualizar (o que pode levar alguns minutos), o registro é concluído sozinho — sem precisar clicar em nada.

O botão "Já troquei! Verificar agora" ainda existe para quem quiser tentar antecipadamente.
