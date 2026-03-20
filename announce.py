#!/usr/bin/env python3
"""
Envia um anuncio no Discord a partir de um arquivo Markdown.

Usa o canal configurado via `.config_aviso #canal` no Discord (tracking_channel_id).
Alternativamente, informe --channel <id> para enviar em qualquer canal sem configuracao previa.

Uso:
    python announce.py <tipo> <arquivo.md> [opcoes]

Tipos:
    update        Atualizacao do bot
    feature       Nova funcionalidade
    maintenance   Aviso de manutencao
    event         Evento especial
    info          Informativo geral

Opcoes:
    --channel <id>     ID do canal Discord (ignora o banco de dados)
    --guild <id>       ID do servidor (filtra quando ha multiplos servidores)
    --mention <texto>  Mencao opcional (ex: @everyone)

Exemplos:
    python announce.py update changelog.md
    python announce.py feature nova_feature.md --mention @everyone
    python announce.py info aviso.md --channel 987654321098765432
    python announce.py maintenance aviso.md --guild 123456789012345678

Formato do .md:
    # Titulo do Anuncio

    Corpo do anuncio aqui.
    Suporta **negrito**, *italico*, listas, ## secoes, etc.
"""

import sys
import os
import sqlite3
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime


def load_dotenv(filepath=".env"):
    if not os.path.exists(filepath):
        return
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value

load_dotenv()

# ---

DB_FILE = "data/database.sqlite"
DISCORD_API = "https://discord.com/api/v10"

TYPES = {
    "update": {
        "label": "Atualizacao",
        "emoji": "🔄",
        "color": 0x3498DB,
        "footer": "Atualizacao do Bot",
    },
    "feature": {
        "label": "Nova Feature",
        "emoji": "✨",
        "color": 0x2ECC71,
        "footer": "Nova Funcionalidade",
    },
    "maintenance": {
        "label": "Manutencao",
        "emoji": "🔧",
        "color": 0xE67E22,
        "footer": "Aviso de Manutencao",
    },
    "event": {
        "label": "Evento",
        "emoji": "🏆",
        "color": 0x9B59B6,
        "footer": "Evento Especial",
    },
    "info": {
        "label": "Informativo",
        "emoji": "📢",
        "color": 0x95A5A6,
        "footer": "Informativo",
    },
}


def parse_markdown(filepath: str):
    """
    Le o .md e retorna (titulo, corpo).
    Primeiro '# heading' = titulo; resto = corpo.
    Sem heading: nome do arquivo vira titulo.
    """
    with open(filepath, encoding="utf-8") as f:
        content = f.read().strip()

    lines = content.splitlines()
    title = None
    body_lines = []

    for line in lines:
        if title is None and line.startswith("# "):
            title = line[2:].strip()
        else:
            body_lines.append(line)

    if title is None:
        title = os.path.splitext(os.path.basename(filepath))[0].replace("_", " ").title()
        body_lines = lines

    body = "\n".join(body_lines).strip()
    return title, body


def get_channels_from_db(guild_id=None):
    """Retorna lista de (guild_id, tracking_channel_id) do banco."""
    if not os.path.exists(DB_FILE):
        print(f"[ERRO] Banco de dados nao encontrado: {DB_FILE}")
        sys.exit(1)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if guild_id:
        cursor.execute(
            "SELECT guild_id, tracking_channel_id FROM guild_configs "
            "WHERE guild_id = ? AND tracking_channel_id IS NOT NULL",
            (guild_id,),
        )
    else:
        cursor.execute(
            "SELECT guild_id, tracking_channel_id FROM guild_configs "
            "WHERE tracking_channel_id IS NOT NULL"
        )

    rows = cursor.fetchall()
    conn.close()
    return rows


def send_to_discord(token: str, channel_id: int, title: str, body: str, ann_type: str, mention: str = None):
    """Envia o embed via Discord REST API (sem dependencias externas)."""
    meta = TYPES[ann_type]

    embed = {
        "title": f"{meta['emoji']} {title}",
        "description": body[:4096],
        "color": meta["color"],
        "footer": {"text": meta["footer"]},
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }

    payload = {"embeds": [embed]}
    if mention:
        payload["content"] = mention

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "MarocosBot/1.0",
    }

    req = urllib.request.Request(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace")
        return e.code, body_err


def main():
    parser = argparse.ArgumentParser(
        description="Envia anuncio no Discord via arquivo Markdown.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("tipo", choices=list(TYPES.keys()), help="Tipo do anuncio")
    parser.add_argument("arquivo", help="Caminho para o arquivo .md")
    parser.add_argument("--channel", type=int, default=None, help="ID do canal (ignora o banco)")
    parser.add_argument("--guild", type=int, default=None, help="ID do servidor (filtra o banco)")
    parser.add_argument("--mention", default=None, help='Mencao opcional (ex: @everyone)')
    args = parser.parse_args()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("[ERRO] DISCORD_TOKEN nao encontrado no .env")
        sys.exit(1)

    if not os.path.exists(args.arquivo):
        print(f"[ERRO] Arquivo nao encontrado: {args.arquivo}")
        sys.exit(1)

    title, body = parse_markdown(args.arquivo)

    print(f"\n  Tipo   : {TYPES[args.tipo]['label']}")
    print(f"  Titulo : {title}")
    print(f"  Corpo  : {len(body)} caracteres")
    if args.mention:
        print(f"  Mencao : {args.mention}")
    print()

    # Monta lista de destinos
    if args.channel:
        # Canal informado diretamente — ignora o banco
        targets = [(args.guild or 0, args.channel)]
        print(f"[*] Destino manual: canal {args.channel}")
    else:
        targets = get_channels_from_db(args.guild)
        if not targets:
            if args.guild:
                print(f"[ERRO] Guild {args.guild} nao tem canal configurado.")
            else:
                print("[ERRO] Nenhum servidor tem canal configurado.")
            print("       Configure com .config_aviso #canal no Discord, ou use --channel <id>.")
            sys.exit(1)

        if len(targets) > 1:
            print(f"[INFO] {len(targets)} servidores com canal configurado — enviando para todos.\n")

    ok = 0
    for guild_id, channel_id in targets:
        label = f"guild {guild_id} -> canal {channel_id}" if guild_id else f"canal {channel_id}"
        print(f"[*] Enviando para {label} ...")
        status, err = send_to_discord(token, channel_id, title, body, args.tipo, args.mention)
        if status in (200, 201):
            print(f"    [OK] Enviado!")
            ok += 1
        else:
            print(f"    [ERRO] HTTP {status}: {err}")

    print(f"\n[OK] {ok}/{len(targets)} servidor(es) receberam o anuncio.\n")


if __name__ == "__main__":
    main()
