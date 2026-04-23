# agent/crm.py
import os
import re
import httpx
import logging

logger = logging.getLogger("agentkit")

def extraer_telefono(telefono: str) -> str:
    return telefono.replace("@s.whatsapp.net", "").replace("@c.us", "")

def extraer_datos_tag(historial: list) -> dict:
    for msg in reversed(historial):
        if msg["role"] == "assistant":
            match = re.search(r'\[LEAD:([^\]]+)\]', msg["content"])
            if match:
                datos = {}
                for par in match.group(1).split("|"):
                    if "=" in par:
                        clave, valor = par.split("=", 1)
                        datos[clave.strip()] = valor.strip()
                return datos
    return {}

async def enviar_lead_crm(telefono: str, nombre: str, historial: list) -> bool:
    crm_url = os.getenv("CRM_WEBHOOK_URL")
    if not crm_url:
        logger.warning("CRM_WEBHOOK_URL no configurado")
        return False

    telefono_limpio = extraer_telefono(telefono)
    datos = extraer_datos_tag(historial)

    nombre_final = datos.get("nombre") or nombre or f"Lead {telefono_limpio}"
    comuna = datos.get("comuna", "")
    medidas = datos.get("medidas", "")
    tipo = datos.get("tipo", "")
    email = datos.get("email", "")

    notas = " | ".join(filter(None, [
        f"Comuna: {comuna}" if comuna else "",
        f"Medidas: {medidas}" if medidas else "",
        f"Tipo: {tipo}" if tipo else "",
        f"WhatsApp: {telefono_limpio}"
    ]))

    payload = {
        "name": nombre_final,
        "phone": telefono_limpio,
        "email": email or None,
        "source": "WhatsApp - Matias",
        "notes": notas
    }

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(crm_url, json=payload, timeout=10)
            if r.status_code in [200, 201]:
                logger.info(f"Lead enviado al CRM: {telefono_limpio} - {nombre_final}")
                return True
            else:
                logger.error(f"Error CRM: {r.status_code} - {r.text}")
                return False
    except Exception as e:
        logger.error(f"Error enviando al CRM: {e}")
        return False
