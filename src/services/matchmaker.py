class MatchMaker:
    """
    Responsável pela inteligência de cálculo de MMR e Balanceamento.
    Lógica Híbrida: Base Elo + Nerf Flex + Velocity (Jogos baixos com WR alto = MMR Explosivo).
    """

    # Base Score por Tier (Aproximação do MMR Visível)
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
    def calculate_adjusted_mmr(tier: str, rank: str, lp: int, wins: int, losses: int, queue_type: str) -> int:
        """
        Calcula o MMR Real.
        Fórmula: ((Base + LP) * PesoFila) + (DiffWinrate * FatorIncerteza)
        """
        tier_upper = tier.upper()
        rank_upper = rank.upper()

        # 1. Base Score (Elo Visual Puro)
        tier_score = MatchMaker.TIER_VALUES.get(tier_upper, 1000)

        # Lógica especial para Mestre+ (onde o Rank é sempre 'I' ou vazio, e a pontuação é o Base + LP)
        if tier_upper in ['MASTER', 'GRANDMASTER', 'CHALLENGER']:
            # Para Mestre+, o Base Score é o valor do TIER_VALUES (2800) + o LP direto.
            base_score = tier_score + lp
        else:
            # Para elos normais (Iron a Diamond)
            rank_score = MatchMaker.RANK_VALUES.get(rank_upper, 0)
            # Base + Divisão + LP
            base_score = tier_score + rank_score + lp

        # 2. Peso da Fila (Nerf na Flex mantido)
        # Se for Flex, vale 85% do MMR de SoloQ na base
        queue_multiplier = 0.85 if queue_type == 'RANKED_FLEX_SR' else 1.0
        
        total_games = wins + losses
        if total_games == 0:
            return int(base_score * queue_multiplier)

        # 3. Lógica de Velocity (O peso de ter menos partidas)
        winrate = (wins / total_games) * 100
        wr_diff = winrate - 50 # Ex: 60% WR -> +10 pontos de diferença

        # K-Factor: Escada de estabilidade detalhada
        if total_games < 50:
            k_factor = 20 # Smurf/Início: Impacto explosivo
        elif total_games < 100:
            k_factor = 12 # Subida Rápida
        elif total_games < 150:
            k_factor = 8 # Estabilizando
        elif total_games < 200:
            k_factor = 4 # Quase travado
        else:
            k_factor = 2 # Hardstuck (>200 jogos): Impacto mínimo do WR

        # Bônus ou Penalidade calculado
        bonus = wr_diff * k_factor

        # Cálculo Final: Base ajustada pela fila + Bônus de desempenho
        final_mmr = (base_score * queue_multiplier) + bonus
        
        return int(max(0, final_mmr))

    # --- NOVA FUNÇÃO: BALANCEAMENTO DE TIMES ---
    @staticmethod
    def balance_teams(players: list):
        """
        Recebe uma lista de 10 dicionários {'id': ..., 'mmr': ..., 'name': ...}
        Retorna (blue_team, red_team) balanceados por MMR.
        """
        # 1. Ordena do maior MMR para o menor
        sorted_players = sorted(players, key=lambda x: x['mmr'], reverse=True)
        
        blue = []
        red = []
        
        # 2. Distribuição "Snake" (A-B-B-A-A-B...)
        # Garante que o 1º (Melhor) fique contra o 2º e 3º.
        # Padrão de índices para o Blue: 0, 3, 4, 7, 8
        # Padrão de índices para o Red:  1, 2, 5, 6, 9
        
        for i, p in enumerate(sorted_players):
            if i in [0, 3, 4, 7, 8]:
                blue.append(p)
            else:
                red.append(p)
                
        return blue, red