import discord
import random
from discord.ext import commands
import unicodedata

from src.services.riot_api import RiotAPI
from src.database.repositories import PlayerRepository


# View do Botão (Continua igual, pois botões são ótimos para segurança)
class VerifyView(discord.ui.View):
    def __init__(self, bot, ctx, riot_service, puuid, target_icon_id, account_data, lanes):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        self.riot_service = riot_service
        self.puuid = puuid
        self.target_icon_id = target_icon_id
        self.account_data = account_data
        self.lanes = lanes

    @discord.ui.button(label="Já troquei! Verificar", style=discord.ButtonStyle.green)
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Ei, saia daqui! Use .registrar para fazer o seu.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            summoner_data = await self.riot_service.get_summoner_by_puuid(self.puuid)
            current_icon = summoner_data.get('profileIconId')

            if current_icon == self.target_icon_id:
                full_data = {**self.account_data, 'profileIconId': current_icon}

                await PlayerRepository.upsert_player(
                    discord_id=self.ctx.author.id,
                    riot_data=full_data,
                    lane_main=self.lanes['main'],
                    lane_sec=self.lanes['sec']
                )

                embed = discord.Embed(title="✅ Identidade Confirmada!", color=0x00ff00)
                embed.description = f"Conta **{self.account_data['gameName']}** vinculada com sucesso."
                embed.set_thumbnail(url=f"http://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{current_icon}.png")

                self.clear_items()
                await interaction.edit_original_response(embed=embed, view=self)
                self.stop()
            else:
                await interaction.followup.send(
                    f"❌ Ícone incorreto! Atual: **{current_icon}** | Necessário: **{self.target_icon_id}**.",
                    ephemeral=True
                )
        except Exception as e:
            print(f"Erro verify: {e}")


class Auth(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.riot_service = RiotAPI()

    # Remove caracteres invisíveis (problema comum vindo de celular)
    def remove_invisible(self, text: str):
        if not text:
            return text
        # Garantimos a limpeza de caracteres de formatação
        return "".join(
            c for c in text
            if unicodedata.category(c) != "Cf"
        )

    def clean_lane(self, lane_input: str):
        if not lane_input: return None
        l = lane_input.lower().strip()
        if l in ['top', 'topo']: return 'TOP'
        if l in ['jungle', 'jg', 'selva']: return 'JUNGLE'
        if l in ['mid', 'meio']: return 'MID'
        if l in ['adc', 'bot', 'atirador']: return 'ADC'
        if l in ['sup', 'support', 'suporte']: return 'SUPPORT'
        if l in ['fill', 'todos']: return 'FILL'
        return None

    @commands.command(name="registrar")
    async def registrar(self, ctx, *, args: str = None):
        """
        Uso: .registrar Nick#TAG MainLane [SecLane]
        Ex: .registrar Marocos#BR1 Mid Top
        """

        if not args:
            embed = discord.Embed(title="❌ Formato Inválido", color=0xff0000)
            embed.description = (
                "Você precisa informar o Nick e a Lane Principal.\n\n"
                "**Exemplo:**\n"
                "`.registrar Faker#KR1 Mid`\n"
                "`.registrar Eric ツ#2000 Jungle Top`"
            )
            await ctx.reply(embed=embed)
            return
            
        # 1. Limpeza Imediata da string completa
        cleaned_full_args = self.remove_invisible(args).strip()

        # --- PARSER POR POSIÇÃO (MAIS ROBUSTO CONTRA CARACTERES INVÁLIDOS) ---
        
        # 2. Encontrar a última parte que NÃO é uma lane
        parts = cleaned_full_args.split() 
        
        # Lista temporária para armazenar as lanes na ordem [L2, L1] (se encontradas)
        found_lane_parts = [] 
        
        # Tenta extrair a L2 (parts[-1]) e depois a L1 (parts[-2])
        if len(parts) >= 1:
            # Tenta pegar a última como L2 (Secondary na lógica de parsing, mas L2 na ordem)
            l2_input = parts[-1]
            if self.clean_lane(l2_input):
                found_lane_parts.append(l2_input) # L2 (ex: Top)
                
                if len(parts) >= 2:
                    # Tenta pegar a penúltima como L1 (Main na lógica de parsing, mas L1 na ordem)
                    l1_input = parts[-2]
                    if self.clean_lane(l1_input):
                        found_lane_parts.append(l1_input) # L1 (ex: Mid)
        
        # 3. Mapeamento das Lanes e Riot ID
        
        # Se encontrou 2 lanes (L2, L1)
        if len(found_lane_parts) == 2:
            # found_lane_parts[0] = L2 (TOP), found_lane_parts[1] = L1 (MID)
            main_lane = found_lane_parts[1] # L1 deve ser a Main
            sec_lane = found_lane_parts[0]  # L2 deve ser a Sec
            riot_id = " ".join(parts[:-2]).strip()
        # Se encontrou 1 lane (L2 ou L1, deve ser L2)
        elif len(found_lane_parts) == 1:
            main_lane = found_lane_parts[0]
            sec_lane = None
            riot_id = " ".join(parts[:-1]).strip()
        # Se não encontrou nenhuma lane (o Nick#TAG foi o último ou único argumento)
        else:
            # 4. VALIDAÇÃO MÍNIMA CORRETA
            await ctx.reply("❌ Você precisa informar pelo menos Nick#TAG e a lane principal.")
            return

        # ---------------------------------------------------------

        # 5. Checagem de formato final da TAG
        if "#" not in riot_id:
            await ctx.reply("❌ O Nick deve ter a TAG. Ex: `Nome#BR1`")
            return

        # 6. Limpeza e Finalização do Dicionário
        m_lane_clean = self.clean_lane(main_lane)
        s_lane_clean = self.clean_lane(sec_lane) if sec_lane else None

        if not m_lane_clean:
            # Checagem de segurança (redundante)
            await ctx.reply("❌ Lane principal inválida! Use: Top, Jungle, Mid, Adc ou Sup.")
            return

        # Dicionário de Lanes final (L1 -> Main, L2 -> Sec)
        lanes_data = {'main': m_lane_clean, 'sec': s_lane_clean}


        msg_wait = await ctx.reply("⏳ Buscando conta na Riot...")

        try:
            game_name, tag_line = riot_id.split("#", 1)
            account_data = await self.riot_service.get_account_by_riot_id(game_name, tag_line)

            if not account_data:
                await msg_wait.edit(content=f"❌ Conta **{riot_id}** não encontrada.")
                return

            summoner_data = await self.riot_service.get_summoner_by_puuid(account_data['puuid'])
            current_icon_id = summoner_data['profileIconId']

            target_icon_id = current_icon_id
            while target_icon_id == current_icon_id:
                target_icon_id = random.randint(0, 28)

            icon_url = f"http://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{target_icon_id}.png"

            embed = discord.Embed(
                title="🛡️ Verificação de Segurança",
                description=(
                    f"Para confirmar **{riot_id}**, troque seu ícone no LoL para o mesmo da imagem ao lado.\n"
                    f"Depois clique no botão **Verificar**.\n"
                    f"\n"
                    f"Esse ícone aleatório ajuda a garantir que você é o dono da conta.\n"
                    f"**IMPORTANTE:** Após a verificação, você pode trocar o ícone de volta normalmente.\n"
                    f"\n\n"
                    f"Este ícone estará no final da sua lista de ícones dentro do lol."
                ),
                color=0xffcc00
            )
            embed.set_thumbnail(url=icon_url)

            view = VerifyView(
                bot=self.bot,
                ctx=ctx,
                riot_service=self.riot_service,
                puuid=account_data['puuid'],
                target_icon_id=target_icon_id,
                account_data=account_data,
                lanes=lanes_data
            )

            await msg_wait.delete()
            await ctx.reply(embed=embed, view=view)

        except Exception as e:
            print(f"Erro .registrar: {e}")
            await ctx.reply("💥 Erro interno ao conectar com a Riot.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Auth(bot))