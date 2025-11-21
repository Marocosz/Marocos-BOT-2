import asyncio
import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("RIOT_API_KEY")
REGION = "br1" # Vamos testar forçando BR
RIOT_ID = "Marocos#KAT" # O nick que está dando erro

async def test_riot():
    print(f"--- INICIANDO DIAGNÓSTICO ---")
    print(f"1. API Key carregada: {API_KEY[:5]}...{API_KEY[-5:]}")
    
    headers = {"X-Riot-Token": API_KEY}
    
    async with aiohttp.ClientSession() as session:
        # PASSO 1: Buscar PUUID (Account V1 - Americas)
        name, tag = RIOT_ID.split("#")
        url_account = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
        
        print(f"\n2. Buscando Conta ({url_account})...")
        async with session.get(url_account, headers=headers) as resp:
            if resp.status != 200:
                print(f"❌ ERRO ACCOUNT-V1: {resp.status}")
                print(await resp.text())
                return
            data_acc = await resp.json()
            puuid = data_acc['puuid']
            print(f"✅ PUUID Encontrado: {puuid[:15]}...")

        # PASSO 2: Buscar Summoner (Summoner V4 - BR1)
        # AQUI QUE PROVAVELMENTE ESTÁ O ERRO
        url_summoner = f"https://{REGION}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        
        print(f"\n3. Buscando Dados de Invocador no servidor {REGION.upper()}...")
        async with session.get(url_summoner, headers=headers) as resp:
            if resp.status != 200:
                print(f"❌ ERRO SUMMONER-V4: {resp.status}")
                print("MOTIVO PROVÁVEL: A conta existe, mas NÃO É do servidor Brasileiro (BR1).")
                return
            data_sum = await resp.json()
            print(f"✅ Sucesso! Nível: {data_sum['summonerLevel']} | ID: {data_sum['id']}")
            summoner_id = data_sum['id']

        # PASSO 3: Buscar Elo (League V4)
        url_rank = f"https://{REGION}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
        print(f"\n4. Buscando Elo...")
        async with session.get(url_rank, headers=headers) as resp:
            data_rank = await resp.json()
            print(f"✅ Rank Raw Data: {data_rank}")

if __name__ == "__main__":
    if os.name == 'nt': # Fix para Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_riot())