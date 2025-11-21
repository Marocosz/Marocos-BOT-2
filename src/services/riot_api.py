import aiohttp
import os
from urllib.parse import quote

class RiotAPI:
    def __init__(self):
        self.api_key = os.getenv("RIOT_API_KEY")
        self.region = os.getenv("RIOT_REGION", "br1").lower()
        self.routing_region = "americas" 
        self.platform_region = "br1" 
        self.ddragon_version = "14.1.1"
        self.champ_map = {}

    async def _request(self, url: str):
        headers = {"X-Riot-Token": self.api_key}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 403:
                    print(f"⛔ ERRO 403: API Key Expirada! Renove em developer.riotgames.com")
                    return None
                elif response.status == 404:
                    return [] # Retorna lista vazia se não tiver dados (normal)
                else:
                    print(f"⚠️ Erro {response.status}: {url}")
                    return None

    async def get_account_by_riot_id(self, game_name: str, tag_line: str):
        """Pega o PUUID (Identidade Global)"""
        name = quote(game_name)
        tag = quote(tag_line)
        url = f"https://{self.routing_region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
        return await self._request(url)

    async def get_summoner_by_puuid(self, puuid: str):
        """Pega Nível e Ícone"""
        url = f"https://{self.platform_region}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        return await self._request(url)

    async def get_rank_by_puuid(self, puuid: str):
        """
        🔥 MUDANÇA CRÍTICA:
        Usando o endpoint 'by-puuid' que está na sua lista de permitidos.
        """
        url = f"https://{self.platform_region}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        
        # Debug para ver o que chega
        data = await self._request(url)
        if data:
            print(f"✅ ELO ENCONTRADO VIA PUUID: {data}")
        else:
            print(f"⚠️ API retornou lista vazia para Rank via PUUID.")
            
        return data

    async def get_top_mastery(self, puuid: str, count: int = 3):
        """Pega Maestria"""
        url = f"https://{self.platform_region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count={count}"
        return await self._request(url)

    async def get_champion_name(self, champ_id: int):
        """Traduz ID -> Nome do Campeão"""
        if not self.champ_map:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get("https://ddragon.leagueoflegends.com/api/versions.json") as resp:
                        v = await resp.json()
                        self.ddragon_version = v[0]
                    url = f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}/data/pt_BR/champion.json"
                    async with session.get(url) as resp:
                        data = await resp.json()
                        for name, info in data['data'].items():
                            self.champ_map[int(info['key'])] = info['name']
            except:
                pass
        return self.champ_map.get(int(champ_id), str(champ_id))