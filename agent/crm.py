# agent/crm.py
import os
import re
import httpx
import logging

logger = logging.getLogger("agentkit")

def extraer_nombre(historial: list) -> str:
    for msg in reversed(historial):
        if msg["role"] == "assistant":
            texto = msg["content"].lower()
            # Buscar cuando Matías confirma el nombre
            if "listo" in texto or "perfecto" in texto or "gracias" in texto:
                # El mensaje anterior del usuario probablemente tiene el nombre
                idx = historial.index(msg)
                if idx > 0 and historial[idx-1]["role"] == "user":
                    nombre = historial[idx-1]["content"].strip()
                    # Limpiar si viene con teléfono
                    nombre = nombre.split("y")[0].split(",")[0].strip()
                    if len(nombre) < 40:
                        return nombre
    return "Lead WhatsApp"

def extraer_telefono(telefono: str) -> str:
    return telefono.replace("@s.whatsapp.net", "").replace("@c.us", "")

def extraer_notas(historial: list, telefono: str) -> str:
    datos = []
    conversacion = " ".join([m["content"] for m in historial if m["role"] == "user"])
    medidas = re.findall(r'\d+\s*[xX]\s*\d+', conversacion)
    if medidas:
        datos.append(f"Medidas: {medidas[0]}")
    for tipo in ["terraza", "estacionamiento", "quincho", "piscina", "cochera"]:
        if tipo in conversacion.lower():
            datos.append(f"Tipo: {tipo}")
            break
    comunas = ["las condes", "vitacura", "providencia", "nunoa", "santiago",
               "maipu", "rancagua", "valparaiso", "vina del mar", "huechuraba",
               "lo barnechea", "la reina", "penalolen", "macul", "san miguel"]
    for comuna in comunas:
        if comuna in conversacion.lower():
            datos.append(f"Comuna: {comuna.title()}")
            break
    datos.append(f"WhatsApp: {extraer_telefono(telefono)}")
    return " | ".join(datos) if datos else "Lead desde WhatsApp"

async def enviar_lead_crm(telefono: str, nombre: str, historial: list) -> bool:
    crm_url = os.getenv("CRM_WEBHOOK_URL")
    if not crm_url:
        logger.warning("CRM_WEBHOOK_URL no configurado")
        return False
    telefono_limpio = extraer_telefono(telefono)
    payload = {
        "name": nombre or extraer_nombre(historial) or f"Lead {telefono_limpio}",
        "phone": telefono_limpio,
        "source": "WhatsApp - Matias",
        "notes": extraer_notas(historial, telefono)
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(crm_url, json=payload, timeout=10)
            if r.status_code in [200, 201]:
                logger.info(f"Lead enviado al CRM: {telefono_limpio}")
                return True
            else:
                logger.error(f"Error CRM: {r.status_code} - {r.text}")
                return False
    except Exception as e:
        logger.error(f"Error enviando al CRM: {e}")
        return False
