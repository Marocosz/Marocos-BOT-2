# Ideias — Comunidade & XP

## Gamificação de XP

**Missões diárias/semanais**
Objetivos automáticos que resetam periodicamente. Exemplos: "Jogue 3 partidas internas", "Mande 20 mensagens", "Passe 1h em voz". Recompensa: bônus de XP.

**Multiplicador por streak de presença**
Dias consecutivos enviando mensagem aumentam o ganho de XP (1.0× → 1.5× em 7 dias). Quebrou a streak, volta ao base.

**XP por reação recebida**
Ganhar XP quando outros reagem às suas mensagens. Limite diário para evitar farm.

**Bônus de primeiro login do dia**
Primeira mensagem do dia dá XP extra fixo.

---

## Sistema de Conquistas (Badges)

Conquistas permanentes desbloqueáveis que aparecem no `.social`.

| Badge | Condição |
|-------|----------|
| 🔥 Em Chamas | 5 vitórias seguidas |
| 👑 Lenda | 100 partidas internas |
| 🗣️ Falante | 1000 mensagens |
| 🎙️ Podcaster | 100h em voz |
| 🏆 Campeão | Vencer uma season |
| 💀 Humilhado | Ser iMVP 10 vezes |

Comando: `.conquistas [@user]` — exibe todas as badges com data de desbloqueio.

---

## Cargos Automáticos

**Cargo de Vencedor / Perdedor (Liga)**
Ao registrar `.resultado`, o bot remove os cargos anteriores dos 10 jogadores e reatribui automaticamente — vencedores ganham o cargo de vencedor, perdedores o de perdedor. Substitui o processo manual.

Configuração:
```
.config_cargo vencedor @Vencedor
.config_cargo perdedor @Perdedor
```

**Cargos por Nível (Comunidade)**
Ao subir de nível, o bot verifica se o novo nível bate com um threshold configurado e atribui o cargo. Cargos acumulam (não remove o anterior).

Configuração:
```
.config_nivel_cargo 10 @Veterano
.config_nivel_cargo 25 @Senior
.config_nivel_cargo 50 @Lenda
```

> O bot precisa ter permissão "Gerenciar Cargos" e estar acima dos cargos que vai atribuir na hierarquia.

---

## Brincadeiras / Engajamento

**`.duelo @user`** — desafio de quem tem mais XP/MMR, bot anuncia o resultado com texto dramático.

**`.sorte`** — cooldown de 24h, chance de ganhar ou perder XP (roleta).

**`.trivia`** — pergunta de LoL com reação de resposta, quem acertar primeiro ganha XP.

**`.clima_do_servidor`** — conta mensagens enviadas hoje e classifica o servidor (Morto / Casual / Agitado / Caótico).

---

## Seasons / Temporadas

Reset periódico de MMR interno (não de XP/comunidade). Ao final da season, bot anuncia ranking final e atribui cargo/título permanente ao campeão.

Comando: `.season` — mostra temporada atual, data de fim e ranking parcial.

---

## Stats Mais Ricos

**`.comparar @user1 @user2`** — card comparando MMR, WR, MVP count, nível, voz.

**`.mais_ativo`** — quem mais mandou mensagens / ficou em voz na última semana.

**`.nemesis @user`** — contra quem você mais perdeu internamente.

---

## Automações de Comunidade

**Cargo automático por nível** — ao atingir nível 10/25/50, bot atribui cargo automaticamente. *(ver seção Cargos acima)*

**Mensagem de boas-vindas** — quando alguém entra no servidor, ganha XP de estreia e o bot posta embed de boas-vindas.

**Post semanal automático** — toda segunda-feira o bot posta o ranking da semana anterior (mais ativo, mais vitórias, melhor WR).
