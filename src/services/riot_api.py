import aiohttp
import os
from urllib.parse import quote

class RiotAPI:
    def __init__(self):
        self.api_key = os.getenv("RIOT_API_KEY")
        self.region = os.getenv("RIOT_REGION", "br1").lower()
        self.routing_region = "americas"
        self.platform_region = "br1"
        self.ddragon_version = "14.1.1" # Valor inicial, será atualizado dinamicamente
        self.champ_map = {}

    async def _request(self, url: str):
        headers = {"X-Riot-Token": self.api_key}

        # DEBUG – você pode remover depois
        print(f"[RIOT API] GET -> {url}")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:

                if response.status == 200:
                    return await response.json()

                elif response.status == 403:
                    print("⛔ ERRO 403: API Key expirada.")
                    return None

                elif response.status == 404:
                    # print("⚠️ ERRO 404: Recurso não encontrado.") # Silenciado para evitar spam no log de match
                    return None 

                else:
                    print(f"⚠️ Erro {response.status}: {url}")
                    return None

    # --- MÉTODOS DE CONTA E SUMMONER (Mantidos) ---

    async def get_account_by_riot_id(self, game_name: str, tag_line: str):
        """Pega o PUUID global a partir de RiotID"""
        name = quote(game_name)
        tag = quote(tag_line)

        url = (
            f"https://{self.routing_region}.api.riotgames.com"
            f"/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
        )
        return await self._request(url)

    async def get_summoner_by_puuid(self, puuid: str):
        url = (
            f"https://{self.platform_region}.api.riotgames.com"
            f"/lol/summoner/v4/summoners/by-puuid/{puuid}"
        )
        return await self._request(url)

    async def get_rank_by_puuid(self, puuid: str):
        url = (
            f"https://{self.platform_region}.api.riotgames.com"
            f"/lol/league/v4/entries/by-puuid/{puuid}"
        )

        data = await self._request(url)
        if data:
            print(f"✅ RANK ENCONTRADO: {data}")
        else:
            print("⚠️ Nenhuma entrada de rank encontrada.")
        return data

    async def get_top_mastery(self, puuid: str, count: int = 3):
        url = (
            f"https://{self.platform_region}.api.riotgames.com"
            f"/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count={count}"
        )
        return await self._request(url)

    # --- NOVOS MÉTODOS (Histórico e Live) ---

    async def get_match_ids(self, puuid: str, count: int = 5):
        """Busca IDs das partidas recentes (Match V5 - Americas)"""
        url = (
            f"https://{self.routing_region}.api.riotgames.com"
            f"/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count={count}"
        )
        return await self._request(url)

    async def get_match_detail(self, match_id: str):
        """Busca detalhes da partida (Match V5 - Americas)"""
        url = (
            f"https://{self.routing_region}.api.riotgames.com"
            f"/lol/match/v5/matches/{match_id}"
        )
        return await self._request(url)

    async def get_active_game(self, summoner_id: str):
        """Busca partida ao vivo (Spectator V5 - BR1) - Requer Summoner ID"""
        url = (
            f"https://{self.platform_region}.api.riotgames.com"
            f"/lol/spectator/v5/active-games/by-summoner/{summoner_id}"
        )
        return await self._request(url)

    # --- UTILITÁRIOS DATADRAGON (Mantidos) ---

    async def update_version(self):
        """Busca a versão mais recente do jogo no DataDragon"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://ddragon.leagueoflegends.com/api/versions.json") as resp:
                    if resp.status == 200:
                        versions = await resp.json()
                        self.ddragon_version = versions[0]
        except Exception as e:
            print(f"Erro ao atualizar versão DataDragon: {e}")

    async def get_all_champions_data(self):
        """Baixa o JSON gigante com todos os campeões (para busca de nome)"""
        await self.update_version()
        url = f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}/data/pt_BR/champion.json"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            print(f"Erro ao baixar lista de campeões: {e}")
        return None

    async def get_champion_detail(self, champion_id_name: str):
        """Pega dados detalhados"""
        await self.update_version()
        url = f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}/data/pt_BR/champion/{champion_id_name}.json"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data['data'][champion_id_name]
        except Exception as e:
            print(f"Erro ao baixar detalhes do campeão {champion_id_name}: {e}")
        return None

    async def get_champion_name(self, champ_id: int):
        """Traduz ID numérico (Ex: 64) para Nome (Ex: Lee Sin) usando Cache"""
        if not self.champ_map:
            data = await self.get_all_champions_data()
            if data:
                for name, info in data["data"].items():
                    self.champ_map[int(info["key"])] = info["name"]

        return self.champ_map.get(int(champ_id), str(champ_id))