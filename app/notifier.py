import os
import time
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_URL = os.environ.get("API_URL", "http://ha-devices-api:8000/devices/offline")
API_KEY = os.environ.get("API_KEY", "")
INTERVALO_SEGUNDOS = int(os.environ.get("INTERVALO_SEGUNDOS", 3600))

def enviar_alerta_telegram():
    headers = {"x-api-key": API_KEY} if API_KEY else {}
    params = {"integration": "tuya"}
    
    # Tenta se conectar à API com retries caso ela esteja subindo
    max_tentativas = 5
    for tentativa in range(1, max_tentativas + 1):
        try:
            response = requests.get(API_URL, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            break
        except requests.exceptions.ConnectionError:
            if tentativa < max_tentativas:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] API indisponível, tentando novamente em 5s (Tentativa {tentativa}/{max_tentativas})...")
                time.sleep(5)
            else:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Erro: Não foi possível conectar à API após {max_tentativas} tentativas.")
                return
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Erro na verificação: {e}")
            return

    count = data.get("count", 0)
    if count == 0:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Nenhum dispositivo offline.")
        return

    mensagem = f"🚨 *Alerta: Dispositivos Offline* 🚨\n\n"
    mensagem += f"Foram encontrados *{count}* dispositivos indisponíveis:\n\n"
    
    for dev in data.get("devices", []):
        mensagem += f"• *{dev['name']}* (`{dev['model']}`)\n"
        
    url_telegram = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }
    
    try:
        res_tg = requests.post(url_telegram, json=payload, timeout=10)
        res_tg.raise_for_status()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Alerta enviado ao Telegram com sucesso!")
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Erro ao enviar para o Telegram: {e}")

if __name__ == "__main__":
    print("Iniciando serviço de monitoramento para o Telegram...")
    # Aguarda 10 segundos iniciais para garantir que a API subiu por completo
    time.sleep(10)
    
    enviar_alerta_telegram()
    while True:
        time.sleep(INTERVALO_SEGUNDOS)
        enviar_alerta_telegram()
