import discord
import random
from discord.ext import commands
from src.database.repositories import PlayerRepository, MatchRepository
from src.services.matchmaker import MatchMaker
import asyncio
# NOVO: Importa a Base View
from src.utils.views import BaseInteractiveView 

# --- IMPORTS PARA PERSISTÊNCIA DE ESTADO ---
from sqlalchemy import select, func
from src.database.config import get_session
from src.database.models import Match as MatchModel # Alias para não confundir com a classe do discord se houvesse
# -------------------------------------------


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

# --- VIEW DE SELEÇÃO DE CAPITÃO MANUAL (AJUSTADA) ---
class ManualCaptainSelect(discord.ui.Select):
    def __init__(self, players, placeholder, is_first_cap=True):
        self.is_first_cap = is_first_cap
        options = [
            discord.SelectOption(label=p['name'], value=str(p['id']))
            for p in players[:25]
        ]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # NOTA: O fluxo agora é simplificado para ir direto ao coinflip
        await self.view.process_selection(interaction, self.values[0], self.is_first_cap)

class ManualCaptainView(BaseInteractiveView): # HERDA DA BASE
    def __init__(self, lobby_cog, players, interaction):
        super().__init__(timeout=900) # AJUSTE 1: Aumentado para 15 minutos (900s)
        self.lobby_cog = lobby_cog
        self.players = players
        self.admin_interaction = interaction 
        self.cap1 = None
        self.add_item(ManualCaptainSelect(players, "Selecione o Capitão 1", True)) # REMOVIDA SIDE (Azul)
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
            self.add_item(ManualCaptainSelect(remaining, "Selecione o Capitão 2", False)) # REMOVIDA SIDE (Vermelho)
            self.add_cancel_button()
            await interaction.response.edit_message(content=f"✅ Capitão 1 definido: **{player['name']}**. Escolha o segundo:", view=self)
        else:
            cap2 = player
            # LIMPEZA: Remove botões
            await interaction.response.edit_message(content=f"✅ Capitães definidos: **{self.cap1['name']}** vs **{cap2['name']}**", view=None)
            
            # MUDANÇA 2: Agora, após escolher os 2, vai direto para o COINFLIP normal
            # O sistema de coinflip decide quem é priority/secondary.
            await self.lobby_cog.start_coinflip_phase(self.admin_interaction, self.players, self.cap1, cap2)

    def add_cancel_button(self):
        # AJUSTE 3: Contraste melhorado
        btn = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary, row=2, emoji="✖️") 
        btn.callback = self.cancel_callback
        self.add_item(btn)

    async def cancel_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Admins.", ephemeral=True)
        
        await self.lobby_cog.reset_lobby_state()
        await interaction.response.edit_message(content="❌ Seleção Cancelada. Fila reaberta.", view=None)
        self.stop()

# --- VIEW 3: O DRAFT ---
class DraftView(BaseInteractiveView): # HERDA DA BASE
    def __init__(self, lobby_cog, guild_id, cap_blue, cap_red, pool, first_pick_side):
        super().__init__(timeout=900) # AJUSTE 1: Aumentado para 15 minutos (900s)
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
        
        # AJUSTE 3: Contraste melhorado
        cancel_btn = discord.ui.Button(label="Cancelar Draft (Admin)", style=discord.ButtonStyle.secondary, row=2, emoji="✖️") 
        cancel_btn.callback = self.cancel_callback
        self.add_item(cancel_btn)

    async def cancel_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Apenas Administradores podem cancelar o draft!", ephemeral=True)
            return

        embed = discord.Embed(title="❌ Draft Cancelado", description=f"Cancelado por {interaction.user.mention}. Fila reaberta.", color=0xff0000)
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()
        await self.lobby_cog.reset_lobby_state()

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
            # Filtra bots do calculo de media
            real_players = [p for p in team if p['id'] > 0]
            avg = sum(p['mmr'] for p in real_players) // len(real_players) if real_players else 0
            names = "\n".join([f"• {p['name']} ({p['mmr']})" for p in team])
            return f"{names}\n\n📊 **Média:** {avg}"

        embed.add_field(name=f"🔵 Time Azul (Cap. {self.cap_blue['name']})", value=fmt(self.team_blue), inline=True)
        embed.add_field(name=f"🔴 Time Vermelho (Cap. {self.cap_red['name']})", value=fmt(self.team_red), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        # ID DA PARTIDA EM DESTAQUE AQUI
        embed.add_field(name="📢 Instruções", value=f"ID: **{match_id}**\n`.resultado {match_id} Blue/Red`", inline=False)
        
        # LIMPEZA
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()
        # MUDANÇA: Não chama reset_lobby_state, pois a partida NÃO FOI FINALIZADA OFICIALMENTE AINDA (.resultado que faz isso)
        # Apenas limpamos o ID da partida e resetamos o estado de Lock
        self.lobby_cog.current_match_id = 0 
        await self.lobby_cog.update_lobby_message(locked=True) # Trava o painel principal
        # IMPORTANTE: Liberamos o lock apenas quando o resultado for dado ou resetado, 
        # mas aqui o lobby já foi consumido, então o update_lobby_message(locked=True) vai mostrar "LOBBY FECHADO".

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
class SideSelectView(BaseInteractiveView): # HERDA DA BASE
    def __init__(self, lobby_cog, cap_priority, cap_secondary, pool):
        super().__init__(timeout=900) # AJUSTE 1: Aumentado para 15 minutos (900s)
        self.lobby_cog = lobby_cog
        self.cap_priority = cap_priority
        self.cap_secondary = cap_secondary
        self.pool = pool

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Permite Admin ou o Capitão Secundário
        if interaction.user.guild_permissions.administrator: return True
        if interaction.user.id == self.cap_secondary['id'] and self.cap_secondary['id'] > 0: return True
        
        await interaction.response.send_message(f"✋ Apenas {self.cap_secondary['name']} pode escolher o lado!", ephemeral=True)
        return False

    async def start_draft_phase(self, interaction, cap_blue, cap_red, first_pick_side):
        # LIMPEZA: Remove os botões de escolha de lado
        try: await interaction.message.edit(view=None)
        except: pass
        
        view = DraftView(self.lobby_cog, interaction.guild.id, cap_blue, cap_red, self.pool, first_pick_side)
        
        # AQUI PRECISAMOS SALVAR A REFERÊNCIA DA MENSAGEM DO DRAFTVIEW!
        sent_message = await interaction.response.send_message(embed=view.get_embed(), view=view)
        
    @discord.ui.button(label="Quero Lado Azul", style=discord.ButtonStyle.primary, emoji="🔵")
    async def blue_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_draft_phase(interaction, cap_blue=self.cap_secondary, cap_red=self.cap_priority, first_pick_side='RED')

    # AJUSTE 3: Contraste melhorado
    @discord.ui.button(label="Quero Lado Vermelho", style=discord.ButtonStyle.secondary, emoji="🔴") 
    async def red_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_draft_phase(interaction, cap_blue=self.cap_priority, cap_red=self.cap_secondary, first_pick_side='BLUE')

    # AJUSTE 3: Contraste melhorado
    @discord.ui.button(label="Cancelar (Admin)", style=discord.ButtonStyle.secondary, emoji="✖️", row=2) 
    async def cancel_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Admins.", ephemeral=True)
        
        await self.lobby_cog.reset_lobby_state()
        # LIMPEZA
        await interaction.response.edit_message(content="❌ Processo cancelado. Fila reaberta.", embed=None, view=None)
        self.stop()

# --- VIEW NOVO: ESCOLHA DE LADO (BALANCEADO) ---
class BalancedSideSelectView(BaseInteractiveView): # HERDA DA BASE
    def __init__(self, lobby_cog, guild_id, winning_cap, winning_team, losing_cap, losing_team):
        super().__init__(timeout=900) # AJUSTE 1: Aumentado para 15 minutos (900s)
        self.lobby_cog = lobby_cog
        self.guild_id = guild_id
        self.winning_cap = winning_cap
        self.winning_team = winning_team
        self.losing_cap = losing_cap
        self.losing_team = losing_team

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Permite Admin ou o Capitão Vencedor
        if interaction.user.guild_permissions.administrator: return True
        if interaction.user.id == self.winning_cap['id'] and self.winning_cap['id'] > 0: return True
            
        await interaction.response.send_message(f"✋ Apenas {self.winning_cap['name']} pode escolher o lado!", ephemeral=True)
        return False

    async def finalize_match(self, interaction, blue_team, red_team):
        # LIMPEZA
        try: await interaction.message.edit(view=None)
        except: pass

        # Cria a partida no banco (somente com jogadores reais)
        real_blue = [p for p in blue_team if p['id'] > 0]
        real_red = [p for p in red_team if p['id'] > 0]
        
        match_id = await MatchRepository.create_match(self.guild_id, real_blue, real_red)
        embed = discord.Embed(title=f"⚔️ PARTIDA #{match_id} (Balanceada)", color=0x2ecc71)
        
        def fmt(team):
            # Filtra bots para media
            real_players = [p for p in team if p['id'] > 0]
            avg = sum(p['mmr'] for p in real_players) // len(real_players) if real_players else 0
            return "\n".join([f"• {p['name']} ({p['mmr']})" for p in team]) + f"\n\n📊 **Média:** {avg}"

        # Ajuste para garantir que a pessoa com maior MMR no time seja considerada o Cap. visual
        cap_blue_name = max(blue_team, key=lambda x: x['mmr'])['name']
        cap_red_name = max(red_team, key=lambda x: x['mmr'])['name']

        embed.add_field(name=f"🔵 Time Azul (Cap. {cap_blue_name})", value=fmt(blue_team), inline=True)
        embed.add_field(name=f"🔴 Time Vermelho (Cap. {cap_red_name})", value=fmt(red_team), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        # ID DA PARTIDA EM DESTAQUE AQUI
        embed.add_field(name="📢 Instruções", value=f"ID: **{match_id}**\n`.resultado {match_id} Blue/Red`", inline=False)
        
        await interaction.response.send_message(embed=embed)
        await self.lobby_cog.reset_lobby_state(match_id) # NOVO: Passa o ID para que o reset_lobby_state possa finalizar o processo

    @discord.ui.button(label="Escolher BLUE", style=discord.ButtonStyle.primary, emoji="🔵")
    async def choose_blue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalize_match(interaction, blue_team=self.winning_team, red_team=self.losing_team)

    # AJUSTE 3: Contraste melhorado
    @discord.ui.button(label="Escolher RED", style=discord.ButtonStyle.secondary, emoji="🔴") 
    async def choose_red(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalize_match(interaction, blue_team=self.losing_team, red_team=self.winning_team)

    # AJUSTE 3: Contraste melhorado
    @discord.ui.button(label="Cancelar (Admin)", style=discord.ButtonStyle.secondary, emoji="✖️", row=2) 
    async def cancel_bal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Admins.", ephemeral=True)
        
        await self.lobby_cog.reset_lobby_state()
        await interaction.response.edit_message(content="❌ Criação cancelada. Fila reaberta.", embed=None, view=None)
        self.stop()

# --- VIEW 1: LOBBY ---
class LobbyView(BaseInteractiveView): # HERDA DA BASE
    def __init__(self, lobby_cog, disabled=False):
        # NOTA: Timeout None aqui para durar a vida útil da mensagem principal
        super().__init__(timeout=None) 
        self.lobby_cog = lobby_cog
        
        # Se disabled for True, a view será enviada sem botões de interação da fila.
        if disabled:
            self.clear_items()
            # Nenhum botão é adicionado, garantindo que a View esteja vazia.
            return

        # NO MODO HABILITADO (disabled=False):
        # Os botões decorados são AUTOCARREGADOS. 
        pass

    @discord.ui.button(label="Entrar", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="lobby_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.process_join(interaction)

    # AJUSTE 3: Contraste melhorado
    @discord.ui.button(label="Sair", style=discord.ButtonStyle.secondary, emoji="🏃", custom_id="lobby_leave") 
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.process_leave(interaction)

    @discord.ui.button(label="Perfil", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="lobby_profile")
    async def profile_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Use `.perfil` para ver seus stats.", ephemeral=True)

    # NOVO BOTÃO: Cancelar Fila (Admin)
    @discord.ui.button(label="Cancelar Fila (Admin)", style=discord.ButtonStyle.secondary, emoji="✖️", custom_id="lobby_cancel", row=1)
    async def cancel_queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Administradores podem cancelar a fila.", ephemeral=True)
        
        await self.lobby_cog.reset_lobby_state()
        await interaction.response.send_message("❌ Fila cancelada e lobby reaberto.", ephemeral=True)


    # AJUSTE 3: Contraste melhorado
    @discord.ui.button(label="Resetar Fila (Admin)", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="lobby_reset", row=1) 
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Administradores podem resetar a fila.", ephemeral=True)
        
        await self.lobby_cog.reset_lobby_state()
        await interaction.response.send_message("✅ Fila resetada. Lobby reaberto.", ephemeral=True)


# --- VIEW 2: MODO SELECT ---
class ModeSelectView(BaseInteractiveView): # HERDA DA BASE
    def __init__(self, lobby_cog, players):
        super().__init__(timeout=900) # AJUSTE 1: Aumentado para 15 minutos (900s)
        self.lobby_cog = lobby_cog
        self.players = players

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("⛔ Apenas Administradores podem iniciar.", ephemeral=True)
        return False
    
    async def cleanup(self, interaction: discord.Interaction):
        # LIMPEZA: Remove os botões de seleção de modo
        try: 
            if not interaction.response.is_done():
                await interaction.response.edit_message(view=None)
            else:
                await interaction.message.edit(view=None)
        except: 
            pass

    @discord.ui.button(label="Auto-Balanceado", style=discord.ButtonStyle.primary, emoji="⚖️")
    async def auto_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.start_match_balanced(interaction, self.players)
        await self.cleanup(interaction) 
        self.stop()

    @discord.ui.button(label="Capitães (Top Elo)", style=discord.ButtonStyle.secondary, emoji="👑")
    async def captains_mmr(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.setup_captains_phase(interaction, self.players, mode="mmr")
        await self.cleanup(interaction)
        self.stop()

    @discord.ui.button(label="Capitães (Aleatório)", style=discord.ButtonStyle.secondary, emoji="🎲")
    async def captains_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.setup_captains_phase(interaction, self.players, mode="random")
        await self.cleanup(interaction)
        self.stop()

    # MUDANÇA: O botão manual agora não atribui side, apenas chama a fase de coinflip.
    @discord.ui.button(label="Capitães (Manual)", style=discord.ButtonStyle.secondary, emoji="👮") 
    async def captains_manual(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.setup_captains_manual(interaction, self.players)
        await self.cleanup(interaction) 
        self.stop()

    @discord.ui.button(label="Cancelar (Admin)", style=discord.ButtonStyle.secondary, emoji="✖️", row=2)
    async def cancel_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.reset_lobby_state()
        await self.cleanup(interaction) 
        await interaction.response.send_message("❌ Setup cancelado e fila reaberta.")
        self.stop()


# --- LOBBY COG ---
class Lobby(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue = [] 
        self.lobby_message: discord.Message = None
        
        # VARIÁVEL PARA RASTREAR O PRÓXIMO ID DE PARTIDA (0 = Sem ID, 1 = Próxima é a #1)
        self.current_match_id = 0 
        
        # --- VARIÁVEIS DE DEBUG ---
        self.DEBUG_QUEUE_LIMIT = 10 
        self.DEBUG_FILL_ENABLE = False 
        self.QUEUE_LIMIT = self.DEBUG_QUEUE_LIMIT 
        # -------------------------
        
        self.VOTE_EMOJIS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣'] 

        # NOVO: Variável de controle para TRAVAR o comando .fila quando já existe processo de criação
        self.lobby_locked = False

        # --- INICIALIZAÇÃO DA PERSISTÊNCIA DE ID ---
        self.bot.loop.create_task(self.initialize_match_id())

    # --- MÉTODO PARA RECUPERAR O ÚLTIMO ID NO BANCO ---
    async def initialize_match_id(self):
        """
        Busca no banco o maior ID de partida existente e define o próximo.
        Isso evita que o ID reinicie para 1 quando o bot reinicia.
        """
        try:
            async with get_session() as session:
                # Seleciona o maior ID da tabela matches
                stmt = select(func.max(MatchModel.id))
                result = await session.execute(stmt)
                last_id = result.scalar() or 0 # Se for None (banco vazio), retorna 0
                
                self.current_match_id = last_id + 1
                print(f"✅ [Lobby] Estado recuperado. Próxima partida será a #{self.current_match_id}")
        except Exception as e:
            print(f"❌ [Lobby] Erro ao recuperar ID da partida: {e}")
            self.current_match_id = 1 # Fallback

    def get_queue_embed(self, locked=False, finished_match_id: int = 0):
        count = len(self.queue)
        limit = self.QUEUE_LIMIT
        
        # 1. Definindo o rótulo do ID da Partida
        if finished_match_id > 0:
            match_ref = f" #{finished_match_id}"
            title = f"❌ LOBBY ENCERRADO | Partida{match_ref}"
            color = 0xe74c3c
            desc = f"A Partida{match_ref} foi finalizada/anulada. Use `.fila` para a próxima partida."
        elif self.current_match_id > 0:
            match_ref = f" #{self.current_match_id}"
            if locked:
                color = 0x000000 
                title = f"🔒 LOBBY FECHADO{match_ref}"
                desc = "Aguarde o Admin configurar a partida..."
            else:
                color = 0x3498db
                title = f"🏆 Fila para Partida{match_ref} ({count}/{limit})"
                if count == 0: desc = "A fila está vazia."
                else:
                    lines = [f"`{i+1}.` **{p['name']}** ({p['mmr']}) - {p.get('main_lane','?').title()}" for i, p in enumerate(self.queue)]
                    desc = "\n".join(lines)
        else: # ID 0 (antes de iniciar a primeira fila)
            match_ref = " #Nº 1"
            color = 0x3498db
            title = f"🏆 Fila para Partida{match_ref} ({count}/{limit})"
            if count == 0: desc = "A fila está vazia."
            else:
                lines = [f"`{i+1}.` **{p['name']}** ({p['mmr']}) - {p.get('main_lane','?').title()}" for i, p in enumerate(self.queue)]
                desc = "\n".join(lines)

        embed = discord.Embed(title=title, description=desc, color=color)
        
        # Footer só aparece se não estiver ENCERRADO
        if finished_match_id == 0:
            embed.set_footer(text="Clique para entrar • Requer registro (.registrar)")
            
        return embed

    async def update_lobby_message(self, interaction: discord.Interaction = None, locked=False, finished_match_id: int = 0):
        # Atualiza o status interno de travamento
        if locked:
            self.lobby_locked = True
        
        embed = self.get_queue_embed(locked=locked, finished_match_id=finished_match_id)
        
        # A View é desabilitada se o lobby estiver ENCERADO (finished_match_id > 0) 
        # OU se estiver FECHADO (locked=True).
        view_disabled = (finished_match_id > 0) or locked
        view = LobbyView(self, disabled=view_disabled) 
        
        try:
            if interaction and not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            elif self.lobby_message:
                await self.lobby_message.edit(embed=embed, view=view)
        except: pass

    async def reset_lobby_state(self, finished_match_id: int = 0):
        """Reinicia o estado da fila e atualiza a mensagem principal."""
        
        # 1. Limpa a fila e libera o Lock
        self.queue = []
        self.lobby_locked = False
        
        # 2. Se uma partida foi finalizada/anulada (ID > 0), imobilizamos o card atual
        if finished_match_id > 0:
            # Incrementamos o ID para a PRÓXIMA fila.
            self.current_match_id = finished_match_id + 1
            # Imobiliza o card atual para o estado "LOBBY ENCERRADO"
            await self.update_lobby_message(finished_match_id=finished_match_id)
        else:
            # Se for cancelamento de setup (ou reset), apenas reabrimos a fila no ID atual.
            await self.update_lobby_message()

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
            # Trava o lobby, mas mantém os jogadores na queue para a fase de modo
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
        
        player_names = ", ".join([f"**{p['name']}**" for p in players_snapshot])
        # NOVO: Inclui o ID da partida no Painel de Controle
        embed = discord.Embed(title=f"⚡ Painel de Controle | Partida #{self.current_match_id}", description="O Lobby encheu! Escolha o modo:", color=0xffd700)
        embed.add_field(name="Jogadores", value=player_names, inline=False)
        view = ModeSelectView(self, players_snapshot)
        
        await channel.send(content="||@here|| 🔔 **Lobby Pronto!**", embed=embed, view=view)

    # --- OPÇÃO A: AUTOMÁTICO ---
    async def start_match_balanced(self, interaction, players):
        
        # --- DEBUG FILL RESTAURADO ---
        all_participants = players.copy()
        if self.DEBUG_FILL_ENABLE and len(all_participants) < 10:
            for i in range(10 - len(all_participants)):
                # ID Negativo para filtrar bots na hora de salvar o resultado no DB
                all_participants.append({'id': -1*(i+500), 'name': f'Bot Bal {i}', 'mmr': random.randint(800, 1500), 'main_lane': 'FILL'})
        # -----------------------------

        team_blue, team_red = MatchMaker.balance_teams(all_participants)
        
        # Define Capitães (maior MMR em cada time, ignorando bots)
        real_blue = [p for p in team_blue if p['id'] > 0]
        real_red = [p for p in team_red if p['id'] > 0]

        cap_blue = max(real_blue, key=lambda x: x['mmr']) if real_blue else team_blue[0]
        cap_red = max(real_red, key=lambda x: x['mmr']) if real_red else team_red[0]
        
        # Sorteio para quem escolhe o lado
        if random.choice([True, False]): win, lose, w_team, l_team = cap_blue, cap_red, team_blue, team_red
        else: win, lose, w_team, l_team = cap_red, cap_blue, team_red, team_blue

        embed = discord.Embed(title="⚖️ Times Balanceados! (Sorteio)", color=0xff9900)
        embed.description = f"**{win['name']}** (Capitão do time sorteado) venceu o cara-ou-coroa e escolhe o **LADO**."
        view = BalancedSideSelectView(self, interaction.guild.id, win, w_team, lose, l_team)
        await interaction.followup.send(embed=embed, view=view)

    # --- OPÇÃO B: FASE CAPITÃES (MMR/RANDOM) ---
    async def setup_captains_phase(self, interaction, players, mode="mmr"):
        
        # --- DEBUG FILL RESTAURADO ---
        all_participants = players.copy()
        if self.DEBUG_FILL_ENABLE and len(all_participants) < 10: 
            for i in range(10 - len(all_participants)):
                all_participants.append({'id': -1 * (i+100), 'name': f'Bot Teste {i+1}', 'mmr': random.randint(800, 1500), 'main_lane': 'FILL'})
        # -----------------------------

        # Lógica para definir os capitães
        if mode == "mmr":
            # Filtra apenas jogadores reais para escolher o Top Elo (se houver pelo menos 2)
            real_players = [p for p in all_participants if p['id'] > 0]
            if len(real_players) >= 2:
                sorted_p = sorted(real_players, key=lambda x: x['mmr'], reverse=True)
                cap1, cap2 = sorted_p[0], sorted_p[1]
            else:
                # Se não tem 2 jogadores reais, escolhe aleatoriamente do pool (inclui bots se necessário)
                random.shuffle(all_participants)
                cap1, cap2 = all_participants[0], all_participants[1]
        else: # Random
            random.shuffle(all_participants)
            cap1, cap2 = all_participants[0], all_participants[1]

        await self.start_coinflip_phase(interaction, all_participants, cap1, cap2)

    # --- OPÇÃO C: CAPITÃES MANUAL (AJUSTADA) ---
    async def setup_captains_manual(self, interaction, players):
        
        # --- DEBUG FILL RESTAURADO ---
        if self.DEBUG_FILL_ENABLE and len(players) < 10:
            all_participants = players.copy()
            for i in range(10 - len(all_participants)): 
                all_participants.append({'id': -1*(i+100), 'name': f'Bot {i+1}', 'mmr': random.randint(800, 1500), 'main_lane': 'FILL'})
            view = ManualCaptainView(self, all_participants, interaction)
        else:
            view = ManualCaptainView(self, players, interaction)
        # -----------------------------
        
        # NOTA: ManualCaptainView agora não se preocupa com sides (Azul/Vermelho)
        await interaction.response.send_message("Selecione os capitães abaixo:", view=view, ephemeral=True)

    # --- FASE COMUM (COINFLIP) ---
    async def start_coinflip_phase(self, interaction, all_players, cap1, cap2):
        pool = [p for p in all_players if p['id'] != cap1['id'] and p['id'] != cap2['id']]
        if random.choice([True, False]): cap_priority, cap_secondary = cap1, cap2
        else: cap_priority, cap_secondary = cap2, cap1

        embed = discord.Embed(title="🪙 Moeda Girada!", color=0xff9900)
        embed.description = f"**{cap_priority['name']}** prioridade de Pick (First Pick).\n**{cap_secondary['name']}** escolhe o **Lado**."
        embed.set_footer(text=f"Aguardando {cap_secondary['name']} escolher o lado...")
        
        view = SideSelectView(self, cap_priority, cap_secondary, pool)
        
        if interaction.response.is_done():
            sent_message = await interaction.followup.send(embed=embed, view=view)
        else:
            sent_message = await interaction.response.send_message(embed=embed, view=view)
        
        view.message = sent_message # Captura a referência para o timeout

    # --- NOVO MÉTODO 1: LÓGICA DE CRIAÇÃO E AGENDAMENTO DAS ENQUETES ---
    async def _start_mvp_polls(self, channel: discord.TextChannel, match_id: int, winner_side: str, match_details: dict):
        # 1. Separar Times e Cores
        if winner_side == 'BLUE':
            winning_team = match_details['blue_team']
            losing_team = match_details['red_team']
            winning_color = 0x3498db
            losing_color = 0xe74c3c
        else: # RED
            winning_team = match_details['red_team']
            losing_team = match_details['blue_team']
            winning_color = 0xe74c3c
            losing_color = 0x3498db

        # Filtrar apenas jogadores reais para a votação
        real_winning_team = [p for p in winning_team if p['id'] > 0]
        real_losing_team = [p for p in losing_team if p['id'] > 0]
        
        # Se não houver jogadores reais suficientes, pula a votação
        if not real_winning_team or not real_losing_team:
            print(f"Enquete MVP/iMVP pulada para Partida #{match_id}: jogadores insuficientes.")
            return

        # 2. Enquete MVP (Time Vencedor)
        mvp_desc = "**Vote no Jogador Mais Valioso (MVP)** do time vencedor:\n\n"
        mvp_players_list = [f"{self.VOTE_EMOJIS[i]} {player['name']} ({player['mmr']})" for i, player in enumerate(real_winning_team)]
        
        mvp_embed = discord.Embed(
            title=f"⭐ ENQUETE MVP | Partida #{match_id} (Time {winner_side})",
            description=mvp_desc + "\n".join(mvp_players_list),
            color=winning_color
        )
        mvp_embed.set_footer(text="A votação dura 30 minutos. Vote com a reação correspondente.")
        mvp_message = await channel.send(content="||@here||", embed=mvp_embed)
        
        for i in range(len(real_winning_team)):
            await mvp_message.add_reaction(self.VOTE_EMOJIS[i])

        # 3. Enquete iMVP (Time Perdedor)
        loser_side = 'BLUE' if winner_side == 'RED' else 'RED'
        imvp_desc = "**Vote no Jogador Inverso (iMVP) do Time Perdedor** (aquele que mais dificultou para o próprio time):\n\n"
        imvp_players_list = [f"{self.VOTE_EMOJIS[i]} {player['name']} ({player['mmr']})" for i, player in enumerate(real_losing_team)]
                
        imvp_embed = discord.Embed(
            title=f"👎 ENQUETE iMVP | Partida #{match_id} (Time {loser_side})",
            description=imvp_desc + "\n".join(imvp_players_list),
            color=losing_color
        )
        imvp_embed.set_footer(text="A votação dura 30 minutos. Vote com a reação correspondente.")
        imvp_message = await channel.send(embed=imvp_embed)
        
        for i in range(len(real_losing_team)):
            await imvp_message.add_reaction(self.VOTE_EMOJIS[i])

        # 4. Agendar a finalização da enquete
        self.bot.loop.create_task(self._finalize_poll_after_delay(
            channel, 
            match_id, 
            mvp_message.id, 
            imvp_message.id,
            real_winning_team, 
            real_losing_team
        ))

    # --- NOVO MÉTODO 2: CÁLCULO DOS RESULTADOS ---
    def _calculate_poll_result(self, message: discord.Message, team: list) -> str:
        max_votes = -1
        winner_names = "Ninguém votou!"
        
        for reaction in message.reactions:
            try:
                # Encontra o índice do emoji no array VOTE_EMOJIS
                emoji_index = self.VOTE_EMOJIS.index(str(reaction.emoji))
            except ValueError:
                continue # Ignora emojis não relacionados à votação

            # Garante que o índice é válido e corresponde a um jogador real
            if emoji_index < len(team):
                player_name = team[emoji_index]['name']
                vote_count = reaction.count - 1 # Subtrai 1 (a reação do próprio bot)
                
                if vote_count > max_votes:
                    max_votes = vote_count
                    winner_names = f"**{player_name}** com {vote_count} voto(s)."
                elif vote_count == max_votes and max_votes > 0:
                    winner_names += f" e **{player_name}** (Empate)"

        return winner_names if max_votes > 0 else "Ninguém votou!"

    # --- NOVO MÉTODO 3: FINALIZAÇÃO AGENDADA ---
    async def _finalize_poll_after_delay(self, channel: discord.TextChannel, match_id: int, mvp_msg_id: int, imvp_msg_id: int, winning_team: list, losing_team: list, delay_minutes=30):
        
        await asyncio.sleep(delay_minutes * 60) # Espera 30 minutos
        
        try:
            mvp_msg = await channel.fetch_message(mvp_msg_id)
            imvp_msg = await channel.fetch_message(imvp_msg_id)
            
            # 1. Calcular resultados
            mvp_result = self._calculate_poll_result(mvp_msg, winning_team)
            imvp_result = self._calculate_poll_result(imvp_msg, losing_team)
            
            # 2. Formatar a mensagem final
            final_embed = discord.Embed(
                title=f"🗳️ RESULTADO FINAL | Partida #{match_id}",
                description=f"A votação foi encerrada após **{delay_minutes} minutos**.",
                color=0x2ecc71
            )
            final_embed.add_field(name="🏆 MVP do Time Vencedor", value=mvp_result, inline=False)
            final_embed.add_field(name="💀 iMVP (Inverse) do Time Perdedor", value=imvp_result, inline=False)
            
            await channel.send(embed=final_embed)
            
            # 3. Limpar embeds originais
            await mvp_msg.edit(embed=mvp_msg.embeds[0].set_footer(text="Votação ENCERRADA."), view=None)
            await imvp_msg.edit(embed=imvp_msg.embeds[0].set_footer(text="Votação ENCERRADA."), view=None)
            
        except discord.NotFound:
            # Caso as mensagens tenham sido deletadas
            await channel.send(f"❌ Não foi possível encontrar as mensagens da enquete da Partida #{match_id} para finalizar.")
        except Exception as e:
            # Log de erro
            print(f"Erro ao finalizar a enquete da Partida #{match_id}: {e}")
            pass


    # --- COMANDOS ---
    @commands.command(name="fila")
    async def fila(self, ctx):
        
        # 1. CHECAGEM: Se já existe uma partida em andamento, não permite criar uma nova fila
        if self.current_match_id > 0 and await MatchRepository.get_match_details(self.current_match_id):
            return await ctx.reply(f"⚠️ Já existe uma partida em andamento (ID #{self.current_match_id}). Finalize-a antes de criar uma nova fila.")
        
        # 2. CHECAGEM (NOVO): Se o lobby estiver em modo 'locked' (Draft/Setup), impede .fila
        if self.lobby_locked:
            return await ctx.reply("⚠️ Um lobby já está sendo configurado (Draft/Setup). Aguarde ou cancele o atual.")

        # 3. OBTENDO O PRÓXIMO ID PARA EXIBIÇÃO (Se a fila estava limpa, inicia em 1)
        # NOTA: O self.initialize_match_id já deve ter rodado, mas se falhou, isso garante.
        if self.current_match_id == 0:
            self.current_match_id = 1
        
        # 4. LIMPEZA DA MENSAGEM ANTERIOR (CORREÇÃO DE DUPLICIDADE)
        # Se existe uma mensagem anterior, tentamos deletar ela para não ficar duplicada no chat.
        if self.lobby_message:
            try: await self.lobby_message.delete()
            except: pass
        
        embed = self.get_queue_embed()
        view = LobbyView(self)
        
        # ENVIA E SALVA A REFERÊNCIA (APENAS UMA VEZ)
        self.lobby_message = await ctx.send(embed=embed, view=view)


    @commands.command(name="resetar")
    async def resetar(self, ctx): 
        if not ctx.author.guild_permissions.administrator: return await ctx.reply("⛔ Apenas Administradores.")
        
        # Opção para alternar entre debug e produção rapidamente:
        if self.QUEUE_LIMIT == 10:
             self.QUEUE_LIMIT = self.DEBUG_QUEUE_LIMIT
             await ctx.reply(f"✅ Modo de Fila DEBUG ativado. Limite: **{self.QUEUE_LIMIT}**.")
        else:
             self.QUEUE_LIMIT = 10
             await ctx.reply(f"✅ Modo de Fila PRODUÇÃO ativado. Limite: **{self.QUEUE_LIMIT}**.")
             
        await self.reset_lobby_state()
        
    @commands.command(name="resultado")
    async def resultado(self, ctx, match_id: int = None, winner: str = None):
        if not ctx.author.guild_permissions.administrator: return await ctx.reply("⛔ Apenas Administradores.")
        if not match_id or not winner: return await ctx.reply("❌ Uso: `.resultado <ID> <Blue/Red>`")
        
        winner = winner.upper()
        if winner == 'AZUL': winner = 'BLUE'
        if winner == 'VERMELHO': winner = 'RED'
        if winner not in ['BLUE', 'RED']: return await ctx.reply("❌ Lado Inválido.")
        
        # NOVO: Obtem os detalhes antes de finalizar
        match_details = await MatchRepository.get_match_details(match_id) # CHAMA O MÉTODO REQUERIDO
        
        # Se get_match_details retornar None, a partida não está ATIVA ou não existe.
        if not match_details: 
            return await ctx.reply(f"❌ Partida #{match_id} não encontrada ou já finalizada/anulada.")
        
        status = await MatchRepository.finish_match(match_id, winner)
        
        if status == "SUCCESS":
            # NOVO: Inicia o processo de enquetes
            await self._start_mvp_polls(ctx.channel, match_id, winner, match_details) 
            
            embed = discord.Embed(title=f"✅ Partida #{match_id} Finalizada!", description=f"Vencedor: **TIME {winner}**", color=0x2ecc71)
            await ctx.reply(embed=embed)
            
            # NOVO: Limpa a fila e imobiliza o card principal para o estado ENCERRADO
            await self.reset_lobby_state(match_id) 
            
        elif status == "ALREADY_FINISHED": await ctx.reply(f"🔒 Partida #{match_id} já finalizada.")
        else: await ctx.reply(f"❌ Não foi possível finalizar a Partida #{match_id}.")

    @commands.command(name="anular")
    async def anular(self, ctx, match_id: int = None):
        if not ctx.author.guild_permissions.administrator: return await ctx.reply("⛔ Apenas Administradores.")
        if not match_id: return await ctx.reply("❌ Uso: `.anular <ID>`")
        
        # NOVO: Se a partida for anulada, o ID atual é incrementado para a próxima fila.
        status = await MatchRepository.cancel_match(match_id)
        
        if status == "SUCCESS": 
            await ctx.reply(f"🚫 Partida **#{match_id}** ANULADA.")
            # Imobiliza o card principal
            await self.reset_lobby_state(match_id)
            
        elif status == "NOT_ACTIVE": await ctx.reply(f"❌ Partida não ativa.")
        else: await ctx.reply("❌ Não encontrada.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Lobby(bot))