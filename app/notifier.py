import os
import time
import sqlite3
from datetime import datetime, timezone
import requests
import schedule

# Configurações de Ambiente
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_URL = os.environ.get("API_URL", "http://ha-devices-api:8000/devices/offline")
API_KEY = os.environ.get("API_KEY", "")

# Caminho do Banco SQLite (mapeado para volume persistente no Docker)
DB_PATH = os.environ.get("DB_PATH", "/app/data/tuya_historico.db")

def inicializar_banco():
    """Garante que a pasta e a tabela de histórico offline existem no SQLite."""
    print(f"Tentando abrir o banco de dados em: {DB_PATH}")
    
    # Extrai o diretório (ex: /app/data ou /app)
    diretorio = os.path.dirname(DB_PATH)
    
    # Se houver um diretório especificado, cria ele e subpastas recursivamente
    if diretorio and not os.path.exists(diretorio):
        try:
            os.makedirs(diretorio, exist_ok=True)
            print(Diretório criado com sucesso: {diretorio})
        except Exception as e:
            print(f"Aviso ao criar diretório: {e}")

    # Abre a conexão (se a pasta existir e tiver permissão, vai funcionar)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico_offline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            entity_id TEXT,
            name TEXT,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()
    print("Banco de dados inicializado com sucesso!")
def varredura_horaria():
    """Executado a cada 1 hora: coleta o status atual e salva no SQLite."""
    agora = datetime.now(timezone.utc).isoformat()
    print(f"[{agora}] Iniciando varredura horária de dispositivos...")
    
    headers = {"x-api-key": API_KEY} if API_KEY else {}
    
    try:
        response = requests.get(API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        devices = data.get("devices", [])
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Salva cada dispositivo que estiver offline/unavailable na varredura atual
        for dev in devices:
            entity_id = dev.get("id")
            name = dev.get("name")
            status = dev.get("status")
            
            cursor.execute('''
                INSERT INTO historico_offline (timestamp, entity_id, name, status)
                VALUES (?, ?, ?, ?)
            ''', (agora, entity_id, name, status))
            
        conn.commit()
        conn.close()
        print(f"Varredura concluída. {len(devices)} registros offline salvos.")
        
    except Exception as e:
        print(f"Erro na varredura horária: {e}")

def enviar_relatorio_matinal_8am():
    """Executado todo dia às 08:00: calcula as últimas 24h e envia o resumo para o Telegram."""
    print("Gerando relatório matinal das 08:00...")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Consulta registros das últimas 24 horas
    # Como rodamos de 1 em 1 hora, cada registro offline equivale a ~1 hora de indisponibilidade
    cursor.execute('''
        name, entity_id, COUNT(*) as total_horas
        FROM historico_offline
        WHERE datetime(timestamp) >= datetime('now', '-24 hours')
        GROUP BY entity_id
        ORDER BY total_horas DESC
    ''')
    
    resultados = cursor.fetchall()
    conn.close()
    
    # Monta a mensagem para o Telegram
    mensagem = f"☀️ *Relatório Matinal - Central de Operações* (08:00)\n\n"
    
    if not resultados:
        mensagem += "✅ Nenhum registro de instabilidade nas últimas 24 horas! Todos 100% online."
    else:
        mensagem += "⚠️ *Dispositivos com tempo offline nas últimas 24h:*\n\n"
        for name, entity_id, horas in resultados:
            mensagem += f"• *{name}*: Aproximadamente *{horas}h* offline (`{entity_id}`)\n"
            
    # Envia o relatório via API do Telegram
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url_telegram = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensagem,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url_telegram, json=payload, timeout=10)
            print("Relatório matinal enviado com sucesso para o Telegram.")
        except Exception as e:
            print(f"Erro ao enviar mensagem para o Telegram: {e}")
    else:
        print("Credenciais do Telegram não configuradas no notifier.")

if __name__ == "__main__":
    print("Iniciando container de notificação e histórico...")
    inicializar_banco()
    
    # Agenda a varredura a cada 1 hora
    schedule.every(1).hours.do(varredura_horaria)
    
    # Agenda o envio do relatório consolidado para todo dia às 08:00
    schedule.every().day.at("08:00").do(enviar_relatorio_matinal_8am)
    
    # Loop contínuo de execução em segundo plano
    while True:
        schedule.run_pending()
        time.sleep(1)
def limpar_registros_antigos():
    """Apaga do SQLite registros com mais de 2 dias para otimizar o espaço."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Deleta registros onde o timestamp for menor que 2 dias atrás
        cursor.execute('''
            DELETE FROM historico_offline 
            WHERE datetime(timestamp) < datetime('now', '-2 days')
        ''')
        
        linhas_removidas = cursor.rowcount
        conn.commit()
        
        # O comando VACUUM recupera o espaço em disco liberado pelo SQLite
        cursor.execute('VACUUM')
        conn.close()
        
        if linhas_removidas > 0:
            print(f"Limpeza de banco: {linhas_removidas} registros antigos (> 2 dias) foram removidos.")
    except Exception as e:
        print(f"Erro ao limpar registros antigos do banco: {e}")
