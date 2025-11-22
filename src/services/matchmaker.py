class MatchMaker:
    """
    Responsável pela inteligência de cálculo de MMR e Balanceamento.
    """

    TIER_VALUES = {
        'IRON': 0,
        'BRONZE': 400,
        'SILVER': 800,
        'GOLD': 1200,
        'PLATINUM': 1600,
        'EMERALD': 2000,
        'DIAMOND': 2400,
        'MASTER': 2800,
        'GRANDMASTER': 2800, 
        'CHALLENGER': 2800,
        'UNRANKED': 1000 
    }

    RANK_VALUES = {
        'IV': 0,
        'III': 100,
        'II': 200,
        'I': 300,
        '': 0
    }

    @staticmethod
    def calculate_adjusted_mmr(tier: str, rank: str, lp: int, wins: int, losses: int) -> int:
        """
        Calcula o MMR Real baseado no algoritmo 'Marocos MMR':
        BaseElo + (WinrateDiff * FatorConfiança)
        """
        # 1. Cálculo da Base (Elo Puro)
        tier_score = MatchMaker.TIER_VALUES.get(tier.upper(), 1000)
        rank_score = MatchMaker.RANK_VALUES.get(rank.upper(), 0)
        
        # CORREÇÃO AQUI: Padronizei o nome da variável para 'base_score'
        base_score = tier_score + rank_score + lp

        # Se não tem jogos, retorna a base pura
        total_games = wins + losses
        if total_games == 0:
            return base_score

        # 2. Winrate Difference
        winrate = (wins / total_games) * 100
        wr_diff = winrate - 50  # Ex: 60% WR -> +10

        # 3. Fator de Confiança (Smurf vs Hardstuck)
        if total_games < 30:
            k_factor = 15  # Smurf: WR impacta muito
        elif total_games < 100:
            k_factor = 8   # Médio
        else:
            k_factor = 4   # Hardstuck: WR impacta pouco

        # Bônus ou Penalidade
        bonus = wr_diff * k_factor

        # CORREÇÃO AQUI: Agora a variável existe
        final_mmr = int(base_score + bonus)
        
        # Trava de segurança (Ninguém pode ter MMR negativo)
        return max(0, final_mmr)