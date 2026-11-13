import json
import os
import secrets
from typing import Literal

import websockets
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="HA Devices API")

# Define o caminho absoluto correto dentro do ambiente Linux do container
STATIC_DIR = "/app/static"

# Monta o diretório e desativa a checagem rígida na inicialização
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")

@app.get("/")
def serve_root():
    """Serve a página principal do painel"""
    painel_path = os.path.join(STATIC_DIR, "painel.html")
    if os.path.exists(painel_path):
        return FileResponse(painel_path)
    return {"message": "API rodando com sucesso. Coloque o painel.html na pasta static."}


# --- Configurações do Home Assistant ---
HA_URL = os.environ.get("HA_URL", "ws://homeassistant.local:8123/api/websocket")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
API_KEY = os.environ.get("API_KEY")  # Se vazio, a API fica aberta

UNAVAILABLE_STATES = {"unavailable", "unknown"}


def check_key(x_api_key: str | None = Header(default=None)):
    """Valida a chave de API caso esteja configurada nas variáveis de ambiente"""
    if API_KEY and not secrets.compare_digest(x_api_key or "", API_KEY):
        raise HTTPException(status_code=401, detail="API key inválida")


async def ha_commands(commands: list[dict]) -> list:
    """Abre conexão WebSocket, autentica e executa os comandos no Home Assistant."""
    async with websockets.connect(HA_URL, max_size=None, open_timeout=10) as ws:
        msg = json.loads(await ws.recv())
        if msg["type"] != "auth_required":
            raise RuntimeError(f"Resposta inesperada: {msg}")

        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        msg = json.loads(await ws.recv())
        if msg["type"] != "auth_ok":
            raise PermissionError("Token inválido no Home Assistant")

        results = []
        for i, cmd in enumerate(commands, start=1):
            await ws.send(json.dumps({"id": i, **cmd}))
            while True:
                resp = json.loads(await ws.recv())
                if resp.get("id") == i:
                    if not resp.get("success"):
                        raise RuntimeError(resp.get("error"))
                    results.append(resp["result"])
                    break
        return results


@app.get("/devices", dependencies=[Depends(check_key)])
async def list_devices(
    manufacturer: str | None = Query(None, description="ex: Tuya"),
    integration: str | None = Query(None, description="ex: tuya, localtuya"),
    area: str | None = None,
    include_disabled: bool = False,
    include_states: bool = Query(False, description="Inclui o estado atual de cada entidade"),
    only_unavailable: bool = Query(
        False,
        description="Lista só dispositivos com entidades unavailable/unknown",
    ),
    unavailable_match: Literal["all", "any"] = Query(
        "all",
        description="all: todas as entidades offline. any: pelo menos uma.",
    ),
):
    need_states = include_states or only_unavailable

    cmds = [
        {"type": "config/device_registry/list"},
        {"type": "config/entity_registry/list"},
        {"type": "config/area_registry/list"},
        {"type": "config_entries/get"},
    ]
    if need_states:
        cmds.append({"type": "get_states"})

    try:
        res = await ha_commands(cmds)
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao falar com o HA: {e}")

    devices, entities, areas, entries = res[0], res[1], res[2], res[3]
    states = {s["entity_id"]: s["state"] for s in res[4]} if need_states else {}

    area_names = {a["area_id"]: a["name"] for a in areas}
    entry_domain = {e["entry_id"]: e["domain"] for e in entries}

    ents_by_device: dict[str, list[dict]] = {}
    for e in entities:
        if e.get("device_id"):
            ents_by_device.setdefault(e["device_id"], []).append(e)

    out = []
    for d in devices:
        if d.get("disabled_by") and not include_disabled:
            continue
        if d.get("entry_type") == "service":
            continue

        ents = ents_by_device.get(d["id"], [])
        platforms = sorted({
            entry_domain[c] for c in d.get("config_entries", []) if c in entry_domain
        })
        area_name = area_names.get(d.get("area_id"))

        if manufacturer and (d.get("manufacturer") or "").strip().lower() != manufacturer.lower():
            continue
        if integration and integration not in platforms:
            continue
        if area and (area_name or "").lower() != area.lower():
            continue

        item = {
            "id": d["id"],
            "name": (d.get("name_by_user") or d.get("name") or "").strip(),
            "manufacturer": d.get("manufacturer"),
            "model": d.get("model"),
            "area": area_name,
            "integrations": platforms,
            "entities": [e["entity_id"] for e in ents],
        }

        if need_states:
            live = [
                e["entity_id"] for e in ents
                if not e.get("disabled_by") and e["entity_id"] in states
            ]
            bad = [eid for eid in live if states[eid] in UNAVAILABLE_STATES]

            if not live:
                status = "no_entities"
            elif len(bad) == len(live):
                status = "unavailable"
            elif bad:
                status = "partial"
            else:
                status = "ok"

            if only_unavailable:
                wanted = {"unavailable"} if unavailable_match == "all" else {"unavailable", "partial"}
                if status not in wanted:
                    continue

            item["status"] = status
            item["unavailable_entities"] = bad
            if include_states:
                item["states"] = {eid: states.get(eid) for eid in item["entities"]}

        out.append(item)

    return out


@app.get("/devices/offline", dependencies=[Depends(check_key)])
async def offline_summary(
    manufacturer: str | None = None,
    integration: str | None = None,
    unavailable_match: Literal["all", "any"] = "all",
):
    devices = await list_devices(
        manufacturer=manufacturer,
        integration=integration,
        area=None,
        include_disabled=False,
        include_states=False,
        only_unavailable=True,
        unavailable_match=unavailable_match,
    )
    return {
        "count": len(devices),
        "names": [d["name"] for d in devices],
        "devices": [
            {
                "name": d["name"],
                "model": d["model"],
                "integrations": d["integrations"],
                "unavailable_entities": len(d.get("unavailable_entities", [])),
            }
            for d in devices
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
