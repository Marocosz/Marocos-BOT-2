import asyncio
import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("RIOT_API_KEY")
RIOT_ID = "Marocos#KAT" # Seu nick

# Lista de servidores para testar
REGIONS = {
    "br1": "Brasil",
    "na1": "North America",
    "euw1": "Europe West",
    "eun1": "Europe Nordic & East",
    "la1": "Latin America North",
    "la2": "Latin America South",
}

async def find_account():
    print(f"🔍 Procurando {RIOT_ID} pelo mundo...")
    headers = {"X-Riot-Token": API_KEY}

    async with aiohttp.ClientSession() as session:
        # 1. Pega o PUUID (Global)
        name, tag = RIOT_ID.split("#")
        url_acc = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
        
        puuid = None
        async with session.get(url_acc, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                puuid = data['puuid']
                print(f"✅ Conta Riot encontrada! PUUID: {puuid[:10]}...")
            else:
                print(f"❌ Conta Riot não encontrada (Erro {resp.status}). Verifique o Nick.")
                return

        # 2. Testa em cada região
        print("\n--- Testando Servidores de Jogo ---")
        found = False
        for code, name in REGIONS.items():
            print(f"Testando {name} ({code})... ", end="")
            
            url_sum = f"https://{code}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
            async with session.get(url_sum, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ ENCONTRADO!")
                    print(f"   > Nível: {data.get('summonerLevel')}")
                    print(f"   > ID: {data.get('id')}")
                    print(f"   🔴 SOLUÇÃO: Mude RIOT_REGION={code} no seu arquivo .env")
                    found = True
                    break # Para de procurar
                elif resp.status == 404:
                    print("❌ Não existe aqui.")
                else:
                    print(f"⚠️ Erro {resp.status}")

        if not found:
            print("\n🚫 A conta Riot existe, mas não tem perfil de LoL em nenhum servidor testado.")
            print("👉 SOLUÇÃO: Logue no League of Legends, escolha um nome de invocador e termine o tutorial.")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(find_account())