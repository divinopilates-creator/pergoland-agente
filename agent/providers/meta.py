# agent/providers/meta.py
import os
import logging
import httpx
from fastapi import Request
from fastapi.responses import PlainTextResponse
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")

class ProveedorMeta(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando Meta Cloud API."""

    def __init__(self):
        self.token = os.getenv("META_ACCESS_TOKEN")
        self.phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
        self.verify_token = os.getenv("META_VERIFY_TOKEN", "pergoland2026")
        self.api_url = f"https://graph.facebook.com/v19.0/{self.phone_number_id}/messages"

    async def validar_webhook(self, request: Request):
        """Verificacion GET del webhook de Meta."""
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        if mode == "subscribe" and token == self.verify_token:
            logger.info("Webhook Meta verificado correctamente")
            return PlainTextResponse(challenge)
        logger.warning("Webhook Meta: token incorrecto")
        return PlainTextResponse("Forbidden", status_code=403)

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload de Meta Cloud API."""
        body = await request.json()
        mensajes = []

        if body.get("object") != "whatsapp_business_account":
            return mensajes

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if change.get("field") != "messages":
                    continue

                contacts = {c["wa_id"]: c["profile"]["name"] for c in value.get("contacts", [])}

                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    texto = msg.get("text", {}).get("body", "")
                    if not texto:
                        continue
                    telefono = msg.get("from", "")
                    nombre = contacts.get(telefono, "")
                    mensajes.append(MensajeEntrante(
                        telefono=telefono,
                        texto=texto,
                        mensaje_id=msg.get("id", ""),
                        es_propio=False,
                        nombre=nombre,
                    ))

        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envia mensaje via Meta Cloud API."""
        if not self.token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurado")
            return False

        telefono_limpio = telefono.replace("@s.whatsapp.net", "").replace("@c.us", "")

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono_limpio,
            "type": "text",
            "text": {"body": mensaje},
        }

        async with httpx.AsyncClient() as client:
            r = await client.post(self.api_url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error Meta API: {r.status_code} - {r.text}")
            return r.status_code == 200
