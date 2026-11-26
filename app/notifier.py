from datetime import datetime, timezone
import os
import re
import sqlite3
import time
import requests

# Configurações de Ambiente
CLIENT_NAME = os.environ.get("CLIENT_NAME", "NOMECLIENTEEXEMPLO").upper()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_URL = os.environ.get(
    "API_URL", "http://ha-devices-api:8000/devices/offline"
)
API_KEY = os.environ.get("API_KEY", "")
DB_PATH = os.environ.get("DB_PATH", "/app/data/tuya_historico.db")
LOG_HA_PATH = os.environ.get("LOG_HA_PATH", "/homeassistant/home-assistant.log")

# Mapeamento completo de categorias de erro do Home Assistant
CATEGORIAS_ERRO = {
    "autenticacao_nuvem": {
        "titulo": "🔐 ERRO DE AUTENTICAÇÃO NA NUVEM",
        "padroes": [
            r"401 Unauthorized",
            r"Invalid Credentials",
            r"Authentication failed",
            r"token.*expired",
            r"sign invalid",
        ],
    },
    "rate_limit": {
        "titulo": "⏳ LIMITE DE REQUISIÇÕES EXCEDIDO (RATE LIMIT)",
        "padroes": [
            r"Too Many Requests",
            r"Rate Limit Exceeded",
            r"429",
            r"quota.*exceeded",
            r"flow control",
        ],
    },
    "falha_setup": {
        "titulo": "⚙️ FALHA DE CONFIGURAÇÃO OU SETUP",
        "padroes": [
            r"Setup failed for\s+[\w_]+",
            r"Error setting up entry",
            r"Unable to prepare setup for platform",
        ],
    },
    "conexao_local": {
        "titulo": "🌐 ERRO DE CONEXÃO / TIMEOUT LOCAL",
        "padroes": [
            r"TimeoutError",
            r"Cannot connect to host",
            r"Connection refused",
            r"ClientConnectorError",
        ],
    },
    "banco_dados": {
        "titulo": "💾 ERRO DE BANCO DE DADOS (SQLITE)",
        "padroes": [
            r"database is locked",
            r"Disk I/O Error",
            r"sqlite3\.OperationalError",
        ],
    },
    "dependencia_modulo": {
        "titulo": "📦 ERRO DE DEPENDÊNCIA PYTHON (IMPORT)",
        "padroes": [
            r"ModuleNotFoundError",
            r"ImportError",
            r"No module named",
        ],
    },
}

# Inicializa apontando para o final do arquivo atual para não enviar logs antigos ao reiniciar
if os.path.exists(LOG_HA_PATH):
  ultimo_tamanho_log = os.path.getsize(LOG_HA_PATH)
else:
  ultimo_tamanho_log = 0


def inicializar_banco():
  """Garante que a pasta e a tabela de histórico offline existem no SQLite."""
  print(f"[{CLIENT_NAME}] Tentando abrir o banco de dados em: {DB_PATH}")

  diretorio = os.path.dirname(DB_PATH)
  if diretorio and not os.path.exists(diretorio):
    try:
      os.makedirs(diretorio, exist_ok=True)
    except Exception as e:
      print(f"Aviso ao criar diretório: {e}")

  conn = sqlite3.connect(DB_PATH)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS historico_offline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            entity_id TEXT,
            name TEXT,
            status TEXT
        )
    """)
  conn.commit()
  conn.close()
  print(f"[{CLIENT_NAME}] Banco de dados inicializado com sucesso!")


def verificar_novos_erros_ha():
  """Lê novas linhas do log do Home Assistant e envia alerta imediato se encontrar erros."""
  global ultimo_tamanho_log
  if not os.path.exists(LOG_HA_PATH):
    return

  try:
    tamanho_atual = os.path.getsize(LOG_HA_PATH)
    if tamanho_atual < ultimo_tamanho_log:
      ultimo_tamanho_log = 0

    if tamanho_atual == ultimo_tamanho_log:
      return

    with open(LOG_HA_PATH, "r", encoding="utf-8", errors="replace") as f:
      f.seek(ultimo_tamanho_log)
      novas_linhas = f.readlines()
      ultimo_tamanho_log = f.tell()

    for linha in novas_linhas:
      linha_str = linha.strip()
      if not linha_str:
        continue

      for chave, info in CATEGORIAS_ERRO.items():
        for padrao in info["padroes"]:
          if re.search(padrao, linha_str, re.IGNORECASE):
            enviar_alerta_erro_telegram(info["titulo"], linha_str)
            break
  except Exception as e:
    print(f"Erro ao ler log do HA: {e}")


def enviar_alerta_erro_telegram(titulo, detalhe):
  if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    return

  # Limpa eventuais crases do log original para não quebrar o bloco de código do Markdown
  detalhe_limpo = detalhe[:350].replace("`", "'")

  mensagem = (
      f"🚨 *ALERTA HOME ASSISTANT DE {CLIENT_NAME}*\n\n"
      f"*{titulo.upper()}*\n"
      f"- Detalhe:\n"
      f"`{detalhe_limpo}`"
  )

  url_telegram = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  try:
    requests.post(
        url_telegram,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensagem,
            "parse_mode": "Markdown",
        },
        timeout=10,
    )
  except Exception as e:
    print(f"Erro ao enviar alerta de erro para o Telegram: {e}")


def varredura_horaria():
  """Executado a cada 1 hora: coleta o status atual e salva no SQLite."""
  agora = datetime.now(timezone.utc).isoformat()
  print(
      f"[{agora}] [{CLIENT_NAME}] Iniciando varredura horária de"
      " dispositivos..."
  )

  headers = {"x-api-key": API_KEY} if API_KEY else {}

  try:
    response = requests.get(API_URL, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()

    devices = data.get("devices", [])

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for dev in devices:
      name = dev.get("name")
      unavailable_count = dev.get("unavailable_entities", 1)
      status = f"Offline ({unavailable_count} entidades)"
      entity_id = name.lower().replace(" ", "_")

      cursor.execute(
          """
                INSERT INTO historico_offline (timestamp, entity_id, name, status)
                VALUES (?, ?, ?, ?)
            """,
          (agora, entity_id, name, status),
      )
    conn.commit()
    conn.close()
    print(f"Varredura concluída. {len(devices)} registros offline salvos.")

  except Exception as e:
    print(f"Erro na varredura horária: {e}")


def limpar_registros_antigos():
  """Apaga do SQLite registros com mais de 2 dias para otimizar o espaço."""
  try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
            DELETE FROM historico_offline 
            WHERE datetime(timestamp) < datetime('now', '-2 days')
        """)
    linhas_removidas = cursor.rowcount
    conn.commit()
    cursor.execute("VACUUM")
    conn.close()
    if linhas_removidas > 0:
      print(f"Limpeza de banco: {linhas_removidas} registros antigos removidos.")
  except Exception as e:
    print(f"Erro ao limpar registros antigos do banco: {e}")


def formatar_duracao(minutos_totais):
  if minutos_totais >= 60:
    horas = int(minutos_totais // 60)
    mins = int(minutos_totais % 60)
    return f"{horas}h {mins}m"
  return f"{minutos_totais:.1f} min"


def enviar_relatorio_matinal_8am():
  print(f"[{CLIENT_NAME}] Gerando relatório matinal consolidado...")
  headers = {"x-api-key": API_KEY} if API_KEY else {}
  dispositivos_continuos = []
  nomes_continuos = set()

  try:
    resp = requests.get(API_URL, headers=headers, timeout=10)
    if resp.status_code == 200:
      dados_api = resp.json().get("devices", [])
      for dev in dados_api:
        nome = dev.get("name")
        offline_ha = (
            dev.get("offline_since")
            or dev.get("offline_duration")
            or "mais de 24h"
        )
        dispositivos_continuos.append((nome, offline_ha))
        nomes_continuos.add(nome.lower())
  except Exception as e:
    print(f"Erro ao consultar API para offline contínuo: {e}")

  conn = sqlite3.connect(DB_PATH)
  cursor = conn.cursor()
  cursor.execute("""
        SELECT name, COUNT(*) * 5.0 as minutos_offline
        FROM historico_offline
        WHERE datetime(timestamp) >= datetime('now', '-24 hours')
        GROUP BY name
        ORDER BY minutos_offline DESC
    """)
  quedas_24h = cursor.fetchall()
  conn.close()

  mensagem = (
      f"☀️ *Relatório Matinal - {CLIENT_NAME} (24h)*\n\n"
  )
  instabilidades_filtradas = [
      (nome, mins)
      for nome, mins in quedas_24h
      if nome.lower() not in nomes_continuos
  ]

  if instabilidades_filtradas:
    mensagem += "⚠️ *Dispositivos com instabilidade nas últimas 24h:*\n"
    for nome, mins in instabilidades_filtradas:
      mensagem += f"• *{nome}*: indisponível por *{formatar_duracao(mins)}*\n"
    mensagem += "\n"
  else:
    mensagem += "✅ *Nenhuma queda pontual nas últimas 24h.*\n\n"

  if dispositivos_continuos:
    mensagem += "🔴 *Dispositivos offline continuamente (> 24h/48h):*\n"
    for nome, tempo in dispositivos_continuos:
      mensagem += f"• *{nome}* (offline há {tempo})\n"
  else:
    mensagem += "🟢 *Nenhum dispositivo offline de longa duração.*"

  if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
    url_telegram = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown",
    }
    try:
      requests.post(url_telegram, json=payload, timeout=10)
      print("Relatório matinal enviado com sucesso!")
    except Exception as e:
      print(f"Erro ao enviar Telegram: {e}")


if __name__ == "__main__":
  print(f"Iniciando container de notificação para o cliente: {CLIENT_NAME}...")
  inicializar_banco()

  while True:
    agora = datetime.now()

    # 1. Verifica erros novos no log do Home Assistant a cada ciclo
    verificar_novos_erros_ha()

    # 2. Executa a varredura horária (no minuto 0)
    if agora.minute == 0:
      varredura_horaria()
      limpar_registros_antigos()
      time.sleep(60)

    # 3. Executa o relatório diário exatamente às 08:00
    if agora.hour == 8 and agora.minute == 0:
      enviar_relatorio_matinal_8am()
      time.sleep(60)

    time.sleep(30)
