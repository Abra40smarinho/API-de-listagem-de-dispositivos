import os
import json
import secrets
from typing import Literal

import websockets
from fastapi import FastAPI, HTTPException, Depends, Header, Query

HA_URL = os.environ["HA_URL"]
HA_TOKEN = os.environ["HA_TOKEN"]
API_KEY = os.environ.get("API_KEY")  # se vazio, a API fica aberta

# Estados que o HA usa quando não consegue falar com o dispositivo
UNAVAILABLE_STATES = {"unavailable", "unknown"}

app = FastAPI(title="HA Devices API")


def check_key(x_api_key: str | None = Header(default=None)):
    if API_KEY and not secrets.compare_digest(x_api_key or "", API_KEY):
        raise HTTPException(401, "API key inválida")


async def ha_commands(commands: list[dict]) -> list:
    """Abre conexão, autentica, executa os comandos em ordem e devolve os resultados."""
    async with websockets.connect(HA_URL, max_size=None, open_timeout=10) as ws:
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
    integration: str | None = Query(None, description="ex: tuya, localtuya, alexa_devices"),
    area: str | None = None,
    include_disabled: bool = False,
    include_states: bool = Query(False, description="Inclui o estado atual de cada entidade"),
    only_unavailable: bool = Query(
        False,
        description="Lista só dispositivos com entidades unavailable/unknown",
    ),
    unavailable_match: Literal["all", "any"] = Query(
        "all",
        description=(
            "all: todas as entidades do dispositivo estão unavailable/unknown (offline). "
            "any: pelo menos uma está."
        ),
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
        raise HTTPException(401, str(e))
    except Exception as e:
        raise HTTPException(502, f"Erro ao falar com o HA: {e}")

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
        if d.get("entry_type") == "service":  # Sun, Backup etc.
            continue

        ents = ents_by_device.get(d["id"], [])

        # Integração descoberta pelo config_entry: funciona mesmo sem entidades
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
            # Só conta entidades habilitadas e que realmente têm estado no HA
            live = [
                e["entity_id"] for e in ents
                if not e.get("disabled_by") and e["entity_id"] in states
            ]
            bad = [eid for eid in live if states[eid] in UNAVAILABLE_STATES]

            if not live:
                status = "no_entities"   # ex.: Tuya (unsupported): o HA não tem estado
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


@app.get("/health")
async def health():
    return {"status": "ok"}
