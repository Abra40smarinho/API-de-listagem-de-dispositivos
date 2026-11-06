import os
import json
import websockets
from fastapi import FastAPI, HTTPException, Depends, Header, Query

HA_URL = os.environ["HA_URL"]
HA_TOKEN = os.environ["HA_TOKEN"]
API_KEY = os.environ.get("API_KEY")  # se vazio, a API fica aberta

app = FastAPI(title="HA Devices API")


def check_key(x_api_key: str | None = Header(default=None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "API key inválida")


async def ha_commands(commands: list[dict]) -> list:
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


@app.get("/devices", dependencies=[Depends(check_key)])
async def list_devices(
    manufacturer: str | None = Query(None, description="ex: Tuya"),
    integration: str | None = Query(None, description="ex: tuya, alexa_devices"),
    area: str | None = None,
    include_disabled: bool = False,
    include_states: bool = False,
):
    cmds = [
        {"type": "config/device_registry/list"},
        {"type": "config/entity_registry/list"},
        {"type": "config/area_registry/list"},
    ]
    if include_states:
        cmds.append({"type": "get_states"})

    try:
        res = await ha_commands(cmds)
    except PermissionError as e:
        raise HTTPException(401, str(e))
    except Exception as e:
        raise HTTPException(502, f"Erro ao falar com o HA: {e}")

    devices, entities, areas = res[0], res[1], res[2]
    states = {s["entity_id"]: s["state"] for s in res[3]} if include_states else {}
    area_names = {a["area_id"]: a["name"] for a in areas}

    ents_by_device: dict[str, list[dict]] = {}
    for e in entities:
        if e.get("device_id"):
            ents_by_device.setdefault(e["device_id"], []).append(e)

    out = []
    for d in devices:
        if d.get("disabled_by") and not include_disabled:
            continue
        if d.get("entry_type") == "service":   # Sun, Backup, etc.
            continue

        ents = ents_by_device.get(d["id"], [])
        platforms = sorted({e["platform"] for e in ents})
        area_name = area_names.get(d.get("area_id"))

        if manufacturer and (d.get("manufacturer") or "").lower() != manufacturer.lower():
            continue
        if integration and integration not in platforms:
            continue
        if area and (area_name or "").lower() != area.lower():
            continue

        item = {
            "id": d["id"],
            "name": d.get("name_by_user") or d.get("name"),
            "manufacturer": d.get("manufacturer"),
            "model": d.get("model"),
            "area": area_name,
            "integrations": platforms,
            "entities": [e["entity_id"] for e in ents],
        }
        if include_states:
            item["states"] = {e["entity_id"]: states.get(e["entity_id"]) for e in ents}
        out.append(item)

    return out


@app.get("/health")
async def health():
    return {"status": "ok"}
