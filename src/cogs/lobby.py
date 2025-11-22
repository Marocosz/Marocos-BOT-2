import discord
import random
from discord.ext import commands
from src.database.repositories import PlayerRepository, MatchRepository
from src.services.matchmaker import MatchMaker

# --- COMPONENTE DE SELEÇÃO DE JOGADOR (PICK) ---
class PlayerSelect(discord.ui.Select):
    def __init__(self, players, placeholder):
        # Limita visualização para evitar erro de limite do discord
        options = [
            discord.SelectOption(label=p['name'], value=str(p['id']), description=f"MMR: {p['mmr']}")
            for p in players[:25]
        ]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.view.process_pick(interaction, self.values[0])

# --- VIEW DE SELEÇÃO DE CAPITÃO MANUAL ---
class ManualCaptainSelect(discord.ui.Select):
    def __init__(self, players, placeholder, is_first_cap=True):
        self.is_first_cap = is_first_cap
        options = [
            discord.SelectOption(label=p['name'], value=str(p['id']))
            for p in players[:25]
        ]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.view.process_selection(interaction, self.values[0], self.is_first_cap)

class ManualCaptainView(discord.ui.View):
    def __init__(self, lobby_cog, players, interaction):
        super().__init__(timeout=120)
        self.lobby_cog = lobby_cog
        self.players = players
        self.admin_interaction = interaction 
        self.cap1 = None
        self.add_item(ManualCaptainSelect(players, "Selecione o Capitão 1 (Azul)", True))
        self.add_cancel_button()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.admin_interaction.user.id:
            return True
        await interaction.response.send_message("⛔ Apenas o Admin que iniciou pode escolher.", ephemeral=True)
        return False

    async def process_selection(self, interaction, selected_id, is_first_cap):
        player = next((p for p in self.players if str(p['id']) == selected_id), None)
        if is_first_cap:
            self.cap1 = player
            remaining = [p for p in self.players if p['id'] != player['id']]
            self.clear_items()
            self.add_item(ManualCaptainSelect(remaining, "Selecione o Capitão 2 (Vermelho)", False))
            self.add_cancel_button()
            await interaction.response.edit_message(content=f"✅ Capitão 1 definido: **{player['name']}**. Escolha o segundo:", view=self)
        else:
            cap2 = player
            # LIMPEZA: Remove botões
            await interaction.response.edit_message(content=f"✅ Capitães definidos: **{self.cap1['name']}** vs **{cap2['name']}**", view=None)
            await self.lobby_cog.start_coinflip_phase(self.admin_interaction, self.players, self.cap1, cap2)

    def add_cancel_button(self):
        btn = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.danger, row=2, emoji="✖️")
        btn.callback = self.cancel_callback
        self.add_item(btn)

    async def cancel_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Admins.", ephemeral=True)
        
        self.lobby_cog.queue = []
        await self.lobby_cog.update_lobby_message()
        await interaction.response.edit_message(content="❌ Seleção Cancelada.", view=None)
        self.stop()

# --- VIEW 3: O DRAFT ---
class DraftView(discord.ui.View):
    def __init__(self, lobby_cog, guild_id, cap_blue, cap_red, pool, first_pick_side):
        super().__init__(timeout=600)
        self.lobby_cog = lobby_cog 
        self.guild_id = guild_id
        self.cap_blue = cap_blue
        self.cap_red = cap_red
        self.pool = pool
        self.turn = first_pick_side 
        self.team_blue = [cap_blue]
        self.team_red = [cap_red]
        self.update_components()

    def update_components(self):
        self.clear_items()
        if self.pool:
            picker_name = self.cap_blue['name'] if self.turn == 'BLUE' else self.cap_red['name']
            self.add_item(PlayerSelect(self.pool, placeholder=f"Vez de {picker_name} escolher..."))
        
        cancel_btn = discord.ui.Button(label="Cancelar Draft (Admin)", style=discord.ButtonStyle.danger, row=2, emoji="✖️")
        cancel_btn.callback = self.cancel_callback
        self.add_item(cancel_btn)

    async def cancel_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Apenas Administradores podem cancelar o draft!", ephemeral=True)
            return

        embed = discord.Embed(title="❌ Draft Cancelado", description=f"Cancelado por {interaction.user.mention}.", color=0xff0000)
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()
        self.lobby_cog.queue = []
        await self.lobby_cog.update_lobby_message()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        picker_id = self.cap_blue['id'] if self.turn == 'BLUE' else self.cap_red['id']
        if interaction.user.guild_permissions.administrator: return True
        if picker_id < 0: return True
        if interaction.user.id == picker_id: return True
        await interaction.response.send_message(f"✋ Espere sua vez! Agora é a vez do Capitão {self.turn}.", ephemeral=True)
        return False

    async def process_pick(self, interaction: discord.Interaction, picked_id: str):
        picked_player = next((p for p in self.pool if str(p['id']) == picked_id), None)
        if not picked_player: return

        if self.turn == 'BLUE':
            self.team_blue.append(picked_player)
            self.turn = 'RED'
        else:
            self.team_red.append(picked_player)
            self.turn = 'BLUE'
        
        self.pool.remove(picked_player)
        
        if not self.pool:
            await self.finish_draft(interaction)
        else:
            self.update_components()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def finish_draft(self, interaction: discord.Interaction):
        # Filtra bots de teste (ID < 0)
        real_blue = [p for p in self.team_blue if p['id'] > 0]
        real_red = [p for p in self.team_red if p['id'] > 0]

        match_id = await MatchRepository.create_match(
            guild_id=self.guild_id,
            blue_team=real_blue,
            red_team=real_red
        )
        
        embed = discord.Embed(title=f"⚔️ PARTIDA #{match_id} (Draft Finalizado)", color=0x2ecc71)
        
        def fmt(team):
            if not team: return "Vazio"
            avg = sum(p['mmr'] for p in team) // len(team)
            names = "\n".join([f"• {p['name']} ({p['mmr']})" for p in team])
            return f"{names}\n\n📊 **Média:** {avg}"

        embed.add_field(name=f"🔵 Time Azul (Cap. {self.cap_blue['name']})", value=fmt(self.team_blue), inline=True)
        embed.add_field(name=f"🔴 Time Vermelho (Cap. {self.cap_red['name']})", value=fmt(self.team_red), inline=True)
        embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)
        embed.add_field(name="📢 Instruções", value=f"Resultado: `.resultado {match_id} Blue/Red`", inline=False)
        
        # LIMPEZA
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    def get_embed(self):
        color = 0x3498db if self.turn == 'BLUE' else 0xe74c3c
        picker = self.cap_blue['name'] if self.turn == 'BLUE' else self.cap_red['name']
        embed = discord.Embed(title="👑 Draft em Andamento", description=f"**Vez de:** {picker} escolher jogador!", color=color)
        b_str = "\n".join([p['name'] for p in self.team_blue])
        r_str = "\n".join([p['name'] for p in self.team_red])
        p_str = ", ".join([f"`{p['name']}`" for p in self.pool])
        embed.add_field(name="🔵 Time Azul", value=b_str, inline=True)
        embed.add_field(name="🔴 Time Vermelho", value=r_str, inline=True)
        if p_str: embed.add_field(name="📋 Disponíveis", value=p_str, inline=False)
        return embed

# --- VIEW INTERMEDIÁRIA: ESCOLHA DE LADO (COINFLIP) ---
class SideSelectView(discord.ui.View):
    def __init__(self, lobby_cog, cap_priority, cap_secondary, pool):
        super().__init__(timeout=120)
        self.lobby_cog = lobby_cog
        self.cap_priority = cap_priority
        self.cap_secondary = cap_secondary
        self.pool = pool

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator: pass 
        elif interaction.user.id != self.cap_secondary['id'] and self.cap_secondary['id'] > 0:
            await interaction.response.send_message(f"✋ Apenas {self.cap_secondary['name']} pode escolher o lado!", ephemeral=True)
            return False
        return True

    async def start_draft_phase(self, interaction, cap_blue, cap_red, first_pick_side):
        # LIMPEZA: Remove os botões de escolha de lado
        try: await interaction.message.edit(view=None)
        except: pass
        
        view = DraftView(self.lobby_cog, interaction.guild.id, cap_blue, cap_red, self.pool, first_pick_side)
        await interaction.response.send_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Quero Lado Azul", style=discord.ButtonStyle.primary, emoji="🔵")
    async def blue_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_draft_phase(interaction, cap_blue=self.cap_secondary, cap_red=self.cap_priority, first_pick_side='RED')

    @discord.ui.button(label="Quero Lado Vermelho", style=discord.ButtonStyle.danger, emoji="🔴")
    async def red_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_draft_phase(interaction, cap_blue=self.cap_priority, cap_red=self.cap_secondary, first_pick_side='BLUE')

    @discord.ui.button(label="Cancelar (Admin)", style=discord.ButtonStyle.danger, emoji="✖️", row=2)
    async def cancel_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Admins.", ephemeral=True)
        
        self.lobby_cog.queue = []
        await self.lobby_cog.update_lobby_message()
        # LIMPEZA
        await interaction.response.edit_message(content="❌ Processo cancelado.", embed=None, view=None)
        self.stop()

# --- VIEW NOVO: ESCOLHA DE LADO (BALANCEADO) ---
class BalancedSideSelectView(discord.ui.View):
    def __init__(self, lobby_cog, guild_id, winning_cap, winning_team, losing_cap, losing_team):
        super().__init__(timeout=180)
        self.lobby_cog = lobby_cog
        self.guild_id = guild_id
        self.winning_cap = winning_cap
        self.winning_team = winning_team
        self.losing_cap = losing_cap
        self.losing_team = losing_team

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator: pass
        elif interaction.user.id != self.winning_cap['id'] and self.winning_cap['id'] > 0:
            await interaction.response.send_message(f"✋ Apenas {self.winning_cap['name']} pode escolher o lado!", ephemeral=True)
            return False
        return True

    async def finalize_match(self, interaction, blue_team, red_team):
        # LIMPEZA
        try: await interaction.message.edit(view=None)
        except: pass

        match_id = await MatchRepository.create_match(self.guild_id, blue_team, red_team)
        embed = discord.Embed(title=f"⚔️ PARTIDA #{match_id} (Balanceada)", color=0x2ecc71)
        def fmt(team):
            avg = sum(p['mmr'] for p in team) // len(team)
            return "\n".join([f"• {p['name']} ({p['mmr']})" for p in team]) + f"\n\n📊 **Média:** {avg}"

        cap_blue_name = max(blue_team, key=lambda x: x['mmr'])['name']
        cap_red_name = max(red_team, key=lambda x: x['mmr'])['name']

        embed.add_field(name=f"🔵 Time Azul (Cap. {cap_blue_name})", value=fmt(blue_team), inline=True)
        embed.add_field(name=f"🔴 Time Vermelho (Cap. {cap_red_name})", value=fmt(red_team), inline=True)
        embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)
        embed.add_field(name="📢 Instruções", value=f"ID: **{match_id}**\n`.resultado {match_id} Blue/Red`", inline=False)
        
        await interaction.response.send_message(embed=embed)
        await self.lobby_cog.update_lobby_message()

    @discord.ui.button(label="Escolher BLUE", style=discord.ButtonStyle.primary, emoji="🔵")
    async def choose_blue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalize_match(interaction, blue_team=self.winning_team, red_team=self.losing_team)

    @discord.ui.button(label="Escolher RED", style=discord.ButtonStyle.danger, emoji="🔴")
    async def choose_red(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalize_match(interaction, blue_team=self.losing_team, red_team=self.winning_team)

    @discord.ui.button(label="Cancelar (Admin)", style=discord.ButtonStyle.danger, emoji="✖️", row=2)
    async def cancel_bal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Admins.", ephemeral=True)
        
        self.lobby_cog.queue = []
        await self.lobby_cog.update_lobby_message()
        await interaction.response.edit_message(content="❌ Criação cancelada.", embed=None, view=None)
        self.stop()

# --- VIEW 1: LOBBY ---
class LobbyView(discord.ui.View):
    def __init__(self, lobby_cog, disabled=False):
        super().__init__(timeout=None) 
        self.lobby_cog = lobby_cog
        if disabled:
            # Se travado, removemos os botões da lista (melhor que disable)
            # Ou desabilitamos. O usuário pediu para "sumir".
            # Para sumir, a gente simplesmente não adiciona nada no init ou limpa.
            self.clear_items()
            return

    @discord.ui.button(label="Entrar", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="lobby_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.process_join(interaction)

    @discord.ui.button(label="Sair", style=discord.ButtonStyle.danger, emoji="🏃", custom_id="lobby_leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.process_leave(interaction)

    @discord.ui.button(label="Perfil", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="lobby_profile")
    async def profile_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Use `.perfil` para ver seus stats.", ephemeral=True)

    @discord.ui.button(label="Resetar Fila (Admin)", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="lobby_reset", row=1)
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Administradores podem resetar a fila.", ephemeral=True)
        
        self.lobby_cog.queue = []
        await self.lobby_cog.update_lobby_message()
        await interaction.response.send_message("✅ Fila resetada.", ephemeral=True)

# --- VIEW 2: MODO SELECT ---
class ModeSelectView(discord.ui.View):
    def __init__(self, lobby_cog, players):
        super().__init__(timeout=None)
        self.lobby_cog = lobby_cog
        self.players = players

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("⛔ Apenas Administradores podem iniciar.", ephemeral=True)
        return False
    
    async def cleanup(self, interaction):
        # LIMPEZA: Remove os botões de seleção de modo
        try: await interaction.message.edit(view=None)
        except: pass

    @discord.ui.button(label="Auto-Balanceado", style=discord.ButtonStyle.primary, emoji="⚖️")
    async def auto_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cleanup(interaction)
        await self.lobby_cog.start_match_balanced(interaction, self.players)
        self.stop()

    @discord.ui.button(label="Capitães (Top Elo)", style=discord.ButtonStyle.secondary, emoji="👑")
    async def captains_mmr(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cleanup(interaction)
        await self.lobby_cog.setup_captains_phase(interaction, self.players, mode="mmr")
        self.stop()

    @discord.ui.button(label="Capitães (Aleatório)", style=discord.ButtonStyle.secondary, emoji="🎲")
    async def captains_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cleanup(interaction)
        await self.lobby_cog.setup_captains_phase(interaction, self.players, mode="random")
        self.stop()

    @discord.ui.button(label="Capitães (Manual)", style=discord.ButtonStyle.secondary, emoji="👮")
    async def captains_manual(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Para manual, não limpamos ainda pois é uma view efemera
        await self.lobby_cog.setup_captains_manual(interaction, self.players)
        await self.cleanup(interaction)
        self.stop()

    @discord.ui.button(label="Cancelar (Admin)", style=discord.ButtonStyle.danger, emoji="✖️", row=2)
    async def cancel_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.lobby_cog.queue = []
        await self.lobby_cog.update_lobby_message()
        await self.cleanup(interaction)
        await interaction.followup.send("❌ Setup cancelado.")
        self.stop()

# --- LOBBY COG ---
class Lobby(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue = [] 
        self.lobby_message: discord.Message = None
        self.QUEUE_LIMIT = 1 # DEBUG MODE (MUDE PARA 10)

    def get_queue_embed(self, locked=False):
        count = len(self.queue)
        if locked:
            color = 0x000000 
            title = "🔒 LOBBY FECHADO"
            desc = "Aguarde o Admin configurar a partida..."
        else:
            color = 0x3498db
            title = f"🏆 Lobby Liga Interna ({count}/{self.QUEUE_LIMIT})"
            if count == 0: desc = "A fila está vazia."
            else:
                lines = [f"`{i+1}.` **{p['name']}** ({p['mmr']}) - {p.get('main_lane','?').title()}" for i, p in enumerate(self.queue)]
                desc = "\n".join(lines)
        embed = discord.Embed(title=title, description=desc, color=color)
        if not locked: embed.set_footer(text="Clique para entrar • Requer registro (.registrar)")
        return embed

    async def update_lobby_message(self, interaction: discord.Interaction = None, locked=False):
        embed = self.get_queue_embed(locked=locked)
        # Se locked=True, LobbyView(disabled=True) vai limpar os items, fazendo os botões sumirem
        view = LobbyView(self, disabled=locked) 
        
        # Se locked, queremos view=None para garantir que suma? 
        # Não, pois LobbyView limpo é melhor se quisermos reativar depois, 
        # mas view=None garante sumiço visual total.
        if locked: view = None 

        try:
            if interaction and not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            elif self.lobby_message:
                await self.lobby_message.edit(embed=embed, view=view)
        except: pass

    async def process_join(self, interaction: discord.Interaction):
        if len(self.queue) >= self.QUEUE_LIMIT:
            return await interaction.response.send_message("Fila cheia!", ephemeral=True)
        user = interaction.user
        if any(p['id'] == user.id for p in self.queue):
            return await interaction.response.send_message("Já está na fila.", ephemeral=True)
        player = await PlayerRepository.get_player_by_discord_id(user.id)
        if not player: return await interaction.response.send_message("🛑 Use `.registrar` primeiro.", ephemeral=True)

        self.queue.append({'id': user.id, 'name': user.display_name, 'mmr': player.mmr, 'main_lane': player.main_lane.value if player.main_lane else "FILL"})
        
        if len(self.queue) >= self.QUEUE_LIMIT:
            await self.update_lobby_message(interaction, locked=True)
            await self.prompt_game_mode(interaction.channel)
        else:
            await self.update_lobby_message(interaction)

    async def process_leave(self, interaction: discord.Interaction):
        user = interaction.user
        self.queue = [p for p in self.queue if p['id'] != user.id]
        await self.update_lobby_message(interaction)

    async def prompt_game_mode(self, channel):
        players_snapshot = self.queue.copy()
        self.queue = [] 
        player_names = ", ".join([f"**{p['name']}**" for p in players_snapshot])
        embed = discord.Embed(title="⚡ Painel de Controle", description="O Lobby encheu! Escolha o modo:", color=0xffd700)
        embed.add_field(name="Jogadores", value=player_names, inline=False)
        view = ModeSelectView(self, players_snapshot)
        await channel.send(content="||@here|| 🔔 **Lobby Pronto!**", embed=embed, view=view)

    # --- OPÇÃO A: AUTOMÁTICO ---
    async def start_match_balanced(self, interaction, players):
        # DEBUG FILL
        if len(players) < 10:
            for i in range(10 - len(players)):
                players.append({'id': -1*(i+500), 'name': f'Bot Bal {i}', 'mmr': 1000, 'main_lane': 'FILL'})

        team_blue, team_red = MatchMaker.balance_teams(players)
        
        if team_blue: cap_blue = max(team_blue, key=lambda x: x['mmr'])
        else: cap_blue = {'id': -1, 'name': 'Bot', 'mmr': 1000}
        if team_red: cap_red = max(team_red, key=lambda x: x['mmr'])
        else: cap_red = {'id': -2, 'name': 'Bot', 'mmr': 1000}

        if random.choice([True, False]): win, lose, w_team, l_team = cap_blue, cap_red, team_blue, team_red
        else: win, lose, w_team, l_team = cap_red, cap_blue, team_red, team_blue

        embed = discord.Embed(title="⚖️ Times Balanceados! (Sorteio)", color=0xff9900)
        embed.description = f"**{win['name']}** venceu o cara-ou-coroa e escolhe o **LADO**."
        view = BalancedSideSelectView(self, interaction.guild.id, win, w_team, lose, l_team)
        await interaction.followup.send(embed=embed, view=view)

    # --- OPÇÃO B: FASE CAPITÃES ---
    async def setup_captains_phase(self, interaction, players, mode="mmr"):
        # DEBUG FILL
        all_participants = players.copy()
        if len(all_participants) < 10: 
            for i in range(10 - len(all_participants)):
                all_participants.append({'id': -1 * (i+100), 'name': f'Bot Teste {i+1}', 'mmr': 1000 + (i*10), 'main_lane': 'FILL'})

        if mode == "mmr":
            sorted_p = sorted(all_participants, key=lambda x: x['mmr'], reverse=True)
            cap1, cap2 = sorted_p[0], sorted_p[1]
        else:
            random.shuffle(all_participants)
            cap1, cap2 = all_participants[0], all_participants[1]

        await self.start_coinflip_phase(interaction, all_participants, cap1, cap2)

    # --- OPÇÃO C: CAPITÃES MANUAL ---
    async def setup_captains_manual(self, interaction, players):
        # DEBUG FILL
        if len(players) < 10:
            for i in range(10 - len(players)): players.append({'id': -1*(i+100), 'name': f'Bot {i+1}', 'mmr': 1000})
        view = ManualCaptainView(self, players, interaction)
        await interaction.response.send_message("Selecione os capitães abaixo:", view=view, ephemeral=True)

    # --- FASE COMUM ---
    async def start_coinflip_phase(self, interaction, all_players, cap1, cap2):
        pool = [p for p in all_players if p['id'] != cap1['id'] and p['id'] != cap2['id']]
        if random.choice([True, False]): cap_priority, cap_secondary = cap1, cap2
        else: cap_priority, cap_secondary = cap2, cap1

        embed = discord.Embed(title="🪙 Moeda Girada!", color=0xff9900)
        embed.description = f"**{cap_priority['name']}** prioridade de Pick.\n**{cap_secondary['name']}** escolhe o **Lado**."
        embed.set_footer(text=f"Aguardando {cap_secondary['name']} escolher o lado...")
        
        view = SideSelectView(self, cap_priority, cap_secondary, pool)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed, view=view)
        await self.update_lobby_message()

    # --- COMANDOS ---
    @commands.command(name="fila")
    async def fila(self, ctx):
        if self.lobby_message:
            try: await self.lobby_message.delete()
            except: pass
        embed = self.get_queue_embed()
        view = LobbyView(self)
        self.lobby_message = await ctx.send(embed=embed, view=view)

    @commands.command(name="resetar")
    async def resetar(self, ctx): pass

    @commands.command(name="resultado")
    async def resultado(self, ctx, match_id: int = None, winner: str = None):
        if not ctx.author.guild_permissions.administrator: return await ctx.reply("⛔ Apenas Administradores.")
        if not match_id or not winner: return await ctx.reply("❌ Uso: `.resultado <ID> <Blue/Red>`")
        winner = winner.upper()
        if winner not in ['BLUE', 'RED', 'AZUL', 'VERMELHO']: return await ctx.reply("❌ Inválido.")
        if winner == 'AZUL': winner = 'BLUE'
        if winner == 'VERMELHO': winner = 'RED'
        status = await MatchRepository.finish_match(match_id, winner)
        if status == "SUCCESS":
            embed = discord.Embed(title=f"✅ Partida #{match_id} Finalizada!", description=f"Vencedor: **TIME {winner}**", color=0x2ecc71)
            await ctx.reply(embed=embed)
        elif status == "ALREADY_FINISHED": await ctx.reply(f"🔒 Já finalizada.")
        else: await ctx.reply("❌ Partida não encontrada.")

    @commands.command(name="anular")
    async def anular(self, ctx, match_id: int = None):
        if not ctx.author.guild_permissions.administrator: return await ctx.reply("⛔ Apenas Administradores.")
        if not match_id: return await ctx.reply("❌ Uso: `.anular <ID>`")
        status = await MatchRepository.cancel_match(match_id)
        if status == "SUCCESS": await ctx.reply(f"🚫 Partida **#{match_id}** ANULADA.")
        elif status == "NOT_ACTIVE": await ctx.reply(f"❌ Partida não ativa.")
        else: await ctx.reply("❌ Não encontrada.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Lobby(bot))