# Use a imagem oficial do Python 3.11 Slim como base para um tamanho reduzido
FROM python:3.11-slim

# Define o diretório de trabalho dentro do container
WORKDIR /usr/src/app

# Copia o arquivo de requisitos e instala as dependências
# Isso usa o cache do Docker, então se os requisitos não mudarem, a instalação é mais rápida
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código para o diretório de trabalho
# Isso inclui o diretório 'src', 'data', e scripts na raiz
COPY . .

# Roda migrações e inicia o bot
# update_db.py é idempotente: ignora colunas que já existem
CMD ["sh", "-c", "python update_db.py && python -m src.main"]