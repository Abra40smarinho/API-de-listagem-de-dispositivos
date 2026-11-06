import os
import json
import asyncio
import websockets
from fastapi import FastAPI, HTTPException

HA_URL = os.environ["HA_URL"]          # ex: ws://192.168.1.10:8123/api/websocket
HA_TOKEN = os.environ["HA_TOKEN"]

app = FastAPI(title="HA Devices API")


async def ha_commands(commands: list[dict]) -> list:
    """Abre conexão, autentica, executa comandos e devolve os resultados."""
    async with websockets.connect(HA_URL, max_size=None) as ws:
        msg = json.loads(await ws.recv())
        if msg["type"] != "auth_required":
            raise RuntimeError(f"Resposta inesperada: {msg}")

        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        msg = json.loads(await ws.recv())
        if msg["type"] != "auth_ok":
            raise PermissionError("Token inválido")

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


@app.get("/devices")
async def list_devices():
    try:
        devices, entities, areas = await ha_commands([
            {"type": "config/device_registry/list"},
            {"type": "config/entity_registry/list"},
            {"type": "config/area_registry/list"},
        ])
    except PermissionError as e:
        raise HTTPException(401, str(e))
    except Exception as e:
        raise HTTPException(502, f"Erro ao falar com o HA: {e}")

    area_names = {a["area_id"]: a["name"] for a in areas}

    ents_by_device: dict[str, list[str]] = {}
    for e in entities:
        if e.get("device_id"):
            ents_by_device.setdefault(e["device_id"], []).append(e["entity_id"])

    return [
        {
            "id": d["id"],
            "name": d.get("name_by_user") or d.get("name"),
            "manufacturer": d.get("manufacturer"),
            "model": d.get("model"),
            "area": area_names.get(d.get("area_id")),
            "disabled": d.get("disabled_by") is not None,
            "entities": ents_by_device.get(d["id"], []),
        }
        for d in devices
    ]


@app.get("/health")
async def health():
    return {"status": "ok"}