# agent/crm.py — Envío de leads calificados al CRM
import os
import httpx
import logging

logger = logging.getLogger("agentkit")

async def enviar_lead_crm(telefono: str, nombre: str, historial: list) -> bool:
    """Envía un lead calificado al auto-crm vía webhook."""
    crm_url = os.getenv("CRM_WEBHOOK_URL")
    if not crm_url:
        logger.warning("CRM_WEBHOOK_URL no configurado")
        return False

    payload = {
        "phone": telefono,
        "name": nombre or "Sin nombre",
        "source": "WhatsApp - Matías",
        "notes": extraer_datos_conversacion(historial)
    }

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(crm_url, json=payload, timeout=10)
            if r.status_code == 200:
                logger.info(f"Lead enviado al CRM: {telefono}")
                return True
            else:
                logger.error(f"Error CRM: {r.status_code} - {r.text}")
                return False
    except Exception as e:
        logger.error(f"Error enviando al CRM: {e}")
        return False

def extraer_datos_conversacion(historial: list) -> str:
    """Extrae un resumen de los datos del historial."""
    if not historial:
        return "Sin datos adicionales"
    resumen = []
    for msg in historial[-6:]:  # últimos 6 mensajes
        if msg["role"] == "user":
            resumen.append(f"Cliente: {msg['content']}")
    return " | ".join(resumen)