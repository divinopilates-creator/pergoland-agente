# agent/handoff.py - Handoff humano y recordatorios automáticos
# Timer se activa desde el CRM al cambiar etapa, NO desde stop matias

import asyncio
import logging
import re
from datetime import datetime, timedelta
from sqlalchemy import String, DateTime, Integer, Float, select, delete, text
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from agent.memory import Base, engine, async_session

logger = logging.getLogger("agentkit")

# ── Mensajes automáticos ──────────────────────────────────────
MSG_COTIZACION = (
    "Hola 👋 Soy Matías de Pergoland Chile. "
    "Quería saber si pudiste revisar la cotización que te enviamos "
    "y si tienes alguna consulta sobre tu proyecto. "
    "¡Estamos para ayudarte! 😊"
)

MSG_VISITA = (
    "Hola 👋 Matías de Pergoland Chile. "
    "Quería hacer un seguimiento post visita técnica. "
    "¿Pudiste revisar la propuesta con Gabriel? "
    "¡Cualquier duda estamos aquí! 🙌"
)


# ── Mensaje referencial 24hs ──────────────────────────────────
MSG_REFERENCIAL_TEMPLATE = (
    "Hola {nombre} 👋 Revisamos tu consulta sobre {descripcion}.\n\n"
    "Un valor referencial para ese proyecto parte desde *{precio}* neto s/IVA.\n\n"
    "Para prepararte una cotización exacta, te hago 3 preguntas rápidas:\n\n"
    "1️⃣ ¿Viste nuestro catálogo en pergoland.cl? ¿Algún modelo te llamó la atención?\n"
    "2️⃣ ¿Prefieres cubierta de *zinc aluminio* 🔲 (opaca, más aislada) "
    "o *policarbonato* ☀️ (translúcida, no pierde luz)?\n"
    "3️⃣ ¿El cielo lo imaginas en *madera natural* 🪵 o *WPC* ✨ (composite sin mantenimiento)?\n\n"
    "¡Con eso te armamos la cotización exacta! 🙌"
)

# Comunas fuera de RM que aplican viáticos
COMUNAS_FUERA_RM = [
    "viña", "valparaiso", "quilpue", "villa alemana", "concon", "quillota",
    "san antonio", "melipilla", "rancagua", "san fernando", "curico",
    "talca", "chillan", "concepcion", "temuco", "puerto montt",
    "calera de limache", "limache", "nogales", "quilicura fuera",
    "santo domingo", "cartagena", "el quisco", "algarrobo",
]


def es_fuera_rm(comuna: str) -> bool:
    """Detecta si la comuna está fuera de la RM y requiere viáticos."""
    if not comuna:
        return False
    c = comuna.lower()
    return any(f in c for f in COMUNAS_FUERA_RM)


def calcular_referencial(largo: float, ancho: float, comuna: str = "") -> int:
    """Calcula precio referencial siempre en Modelo A (conservador)."""
    area = largo * ancho
    estructura = area * 103_233
    cubierta   = area * 20_000
    cielo      = area * 30_556
    dias_mo    = max(4, round(area / 4))
    mo         = dias_mo * 220_000
    otros      = 350_000
    fee        = 1_200_000
    viaticos   = dias_mo * 120_000 if es_fuera_rm(comuna) else 0
    total      = estructura + cubierta + cielo + mo + otros + fee + viaticos
    return round(total)


def parsear_medidas(medidas_str: str) -> tuple[float, float] | None:
    """Extrae largo y ancho de strings como '5x5', '6x4', '7 x 3.5'."""
    if not medidas_str:
        return None
    patron = r"(\d+(?:[.,]\d+)?)\s*[xX×]\s*(\d+(?:[.,]\d+)?)"
    match = re.search(patron, medidas_str.replace(",", "."))
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def extraer_tag_lead(historial: list) -> dict | None:
    """Extrae los datos del tag [LEAD:...] más reciente del historial."""
    for msg in reversed(historial):
        if msg.get("role") == "assistant" and "[LEAD:" in msg.get("content", ""):
            contenido = msg["content"]
            match = re.search(r"\[LEAD:([^\]]+)\]", contenido)
            if match:
                datos = {}
                for par in match.group(1).split("|"):
                    if "=" in par:
                        k, v = par.split("=", 1)
                        datos[k.strip()] = v.strip()
                return datos
    return None


# ── Modelo de base de datos ───────────────────────────────────
class HandoffEstado(Base):
    """Estado de pausa y timer por contacto."""
    __tablename__ = "handoff_estado"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    pausado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    tipo_timer: Mapped[str] = mapped_column(String(20), default="stop")
    timer_activado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recordatorio_enviado: Mapped[str] = mapped_column(String(10), default="pendiente")


class LeadReferencial(Base):
    """Leads con medidas completas — pendientes de mensaje referencial 24hs."""
    __tablename__ = "lead_referencial"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), default="")
    tipo: Mapped[str] = mapped_column(String(50), default="")
    medidas: Mapped[str] = mapped_column(String(20), default="")
    comuna: Mapped[str] = mapped_column(String(100), default="")
    largo: Mapped[float] = mapped_column(Float, default=0.0)
    ancho: Mapped[float] = mapped_column(Float, default=0.0)
    precio_referencial: Mapped[int] = mapped_column(Integer, default=0)
    lead_detectado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    # Datos enriquecidos (etapa 2 — respuestas del cliente)
    cubierta: Mapped[str] = mapped_column(String(50), default="")
    cielo: Mapped[str] = mapped_column(String(50), default="")
    modelo_interes: Mapped[str] = mapped_column(String(50), default="")


async def inicializar_handoff_db():
    """Crea la tabla handoff_estado si no existe."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Tabla handoff_estado inicializada")

async def pausar_contacto(telefono: str):
    """Pausa a Matías SIN activar timer. El timer se activa desde el CRM."""
    async with async_session() as session:
        result = await session.execute(
            select(HandoffEstado).where(HandoffEstado.telefono == telefono)
        )
        existente = result.scalar_one_or_none()

        if existente:
            existente.pausado_en = datetime.utcnow()
            existente.tipo_timer = "stop"
            existente.timer_activado_en = None
            existente.recordatorio_enviado = "pendiente"
        else:
            session.add(HandoffEstado(
                telefono=telefono,
                pausado_en=datetime.utcnow(),
                tipo_timer="stop",
                timer_activado_en=None,
                recordatorio_enviado="pendiente",
            ))
        await session.commit()
    logger.info(f"Matías pausado para {telefono} — esperando trigger de CRM")


async def activar_timer(telefono: str, tipo: str):
    """Activa timer desde el CRM. tipo: 'cotizacion' (72hs) o 'visita' (120hs / 5 días)."""
    async with async_session() as session:
        result = await session.execute(
            select(HandoffEstado).where(HandoffEstado.telefono == telefono)
        )
        existente = result.scalar_one_or_none()

        if existente:
            existente.tipo_timer = tipo
            existente.timer_activado_en = datetime.utcnow()
            existente.recordatorio_enviado = "pendiente"
        else:
            session.add(HandoffEstado(
                telefono=telefono,
                pausado_en=datetime.utcnow(),
                tipo_timer=tipo,
                timer_activado_en=datetime.utcnow(),
                recordatorio_enviado="pendiente",
            ))
        await session.commit()
    logger.info(f"Timer {tipo} activado para {telefono}")


async def reanudar_contacto(telefono: str):
    """Reanuda a Matías — cancela pausa y timers."""
    async with async_session() as session:
        await session.execute(
            delete(HandoffEstado).where(HandoffEstado.telefono == telefono)
        )
        await session.commit()
    logger.info(f"Matías reanudado para {telefono}")


async def reanudar_masivo(excluir_grupos: bool = True) -> dict:
    """
    Libera a TODOS los contactos pausados de una vez, en una sola operación.
    No envía ningún mensaje — solo borra el estado de pausa.
    Por defecto excluye grupos (@g.us), ya que Matías no debería
    responder ahí de todas formas.
    """
    async with async_session() as session:
        result = await session.execute(select(HandoffEstado.telefono))
        todos = [row[0] for row in result.all()]

        if excluir_grupos:
            liberados = [t for t in todos if not t.endswith("@g.us")]
            omitidos = [t for t in todos if t.endswith("@g.us")]
        else:
            liberados = todos
            omitidos = []

        if liberados:
            await session.execute(
                delete(HandoffEstado).where(HandoffEstado.telefono.in_(liberados))
            )
            await session.commit()

    logger.info(f"Liberación masiva: {len(liberados)} contactos reanudados, {len(omitidos)} grupos omitidos")
    return {"liberados": liberados, "omitidos_grupos": omitidos}


async def esta_pausado(telefono: str) -> bool:
    """Verifica si Matías está pausado para un contacto."""
    async with async_session() as session:
        result = await session.execute(
            select(HandoffEstado).where(HandoffEstado.telefono == telefono)
        )
        return result.scalar_one_or_none() is not None


async def listar_pausados() -> list[dict]:
    """Devuelve todos los contactos actualmente pausados (diagnóstico)."""
    async with async_session() as session:
        result = await session.execute(select(HandoffEstado))
        estados = result.scalars().all()
        return [
            {
                "telefono": e.telefono,
                "pausado_en": e.pausado_en.isoformat() if e.pausado_en else None,
                "tipo_timer": e.tipo_timer,
                "timer_activado_en": e.timer_activado_en.isoformat() if e.timer_activado_en else None,
                "recordatorio_enviado": e.recordatorio_enviado,
            }
            for e in estados
        ]


async def es_comando_stop(texto: str) -> bool:
    texto_lower = texto.strip().lower()
    return texto_lower in ["stop matias", "stop matías", "parar matias", "parar matías"]


async def es_comando_start(texto: str) -> bool:
    texto_lower = texto.strip().lower()
    return any(cmd in texto_lower for cmd in [
        "start matias", "start matías",
        "iniciar matias", "activar matias",
        "start"
    ])


# ── Lead referencial 24hs ─────────────────────────────────────
async def registrar_lead_referencial(
    telefono: str,
    nombre: str,
    tipo: str,
    medidas: str,
    comuna: str,
) -> bool:
    """
    Registra un lead con medidas completas para enviar precio referencial a las 24hs.
    Retorna True si fue registrado, False si ya existía.
    """
    dims = parsear_medidas(medidas)
    if not dims:
        logger.warning(f"No se pudo parsear medidas '{medidas}' para {telefono}")
        return False

    largo, ancho = dims
    precio = calcular_referencial(largo, ancho, comuna)

    async with async_session() as session:
        result = await session.execute(
            select(LeadReferencial).where(LeadReferencial.telefono == telefono)
        )
        existente = result.scalar_one_or_none()
        if existente:
            logger.info(f"Lead referencial ya existe para {telefono} — no se duplica")
            return False

        session.add(LeadReferencial(
            telefono=telefono,
            nombre=nombre,
            tipo=tipo,
            medidas=medidas,
            comuna=comuna,
            largo=largo,
            ancho=ancho,
            precio_referencial=precio,
            lead_detectado_en=datetime.utcnow(),
            estado="pendiente",
        ))
        await session.commit()

    logger.info(f"Lead referencial registrado para {telefono} — área {largo}×{ancho}m → ${precio:,}")
    return True


async def enriquecer_lead_referencial(
    telefono: str,
    cubierta: str = "",
    cielo: str = "",
    modelo_interes: str = "",
) -> bool:
    """Guarda las respuestas del cliente (etapa 2) en el lead referencial."""
    async with async_session() as session:
        result = await session.execute(
            select(LeadReferencial).where(LeadReferencial.telefono == telefono)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            return False

        if cubierta:
            lead.cubierta = cubierta
        if cielo:
            lead.cielo = cielo
        if modelo_interes:
            lead.modelo_interes = modelo_interes
        if cubierta or cielo or modelo_interes:
            lead.estado = "datos_completos"

        await session.commit()
    logger.info(f"Lead {telefono} enriquecido: cubierta={cubierta} cielo={cielo} modelo={modelo_interes}")
    return True


def detectar_respuestas_referencial(texto: str) -> dict:
    """
    Detecta si el cliente está respondiendo las 3 preguntas del mensaje referencial.
    Retorna dict con cubierta, cielo, modelo_interes detectados.
    """
    texto_l = texto.lower()
    resultado = {}

    # Cubierta
    if any(p in texto_l for p in ["zinc", "aluminio", "metalica", "opaca", "chapa"]):
        resultado["cubierta"] = "zinc"
    elif any(p in texto_l for p in ["policarbonato", "policarb", "translucida", "luz", "transparente"]):
        resultado["cubierta"] = "policarbonato"

    # Cielo
    if any(p in texto_l for p in ["madera", "wood", "pino", "natural"]):
        resultado["cielo"] = "madera"
    elif any(p in texto_l for p in ["wpc", "composite", "sintetico", "sin mantenimiento"]):
        resultado["cielo"] = "wpc"

    # Modelo
    for modelo in ["modelo a", "modelo b", "modelo g", "modelo s", "modelo m"]:
        if modelo in texto_l:
            resultado["modelo_interes"] = modelo.upper()
            break

    return resultado


async def tiene_lead_referencial_activo(telefono: str) -> bool:
    """Verifica si hay un lead referencial en estado referencial_enviado para este teléfono."""
    async with async_session() as session:
        result = await session.execute(
            select(LeadReferencial).where(
                LeadReferencial.telefono == telefono,
                LeadReferencial.estado == "referencial_enviado"
            )
        )
        return result.scalar_one_or_none() is not None


# ── Scheduler de recordatorios ────────────────────────────────
async def scheduler_recordatorios(proveedor):
    """
    Revisa cada 5 minutos si hay recordatorios pendientes.
    Solo actúa si el timer fue activado desde el CRM.
    Envía UN SOLO mensaje y deja en pausa definitiva.
    """
    logger.info("Scheduler de recordatorios iniciado")
    while True:
        try:
            await asyncio.sleep(300)  # cada 5 minutos
            ahora = datetime.utcnow()

            async with async_session() as session:
                result = await session.execute(select(HandoffEstado))
                estados = result.scalars().all()

                for estado in estados:
                    if not estado.timer_activado_en:
                        continue
                    if estado.recordatorio_enviado != "pendiente":
                        continue

                    tiempo_desde_timer = ahora - estado.timer_activado_en

                    # Cotización → 72hs → 1 solo mensaje → pausa definitiva
                    if (estado.tipo_timer == "cotizacion" and
                            tiempo_desde_timer >= timedelta(hours=72)):
                        ok = await proveedor.enviar_mensaje(estado.telefono, MSG_COTIZACION)
                        if ok:
                            estado.recordatorio_enviado = "enviado"
                            estado.timer_activado_en = None
                            await session.commit()
                            logger.info(f"Recordatorio cotización enviado a {estado.telefono} — pausa definitiva")

                    # Visita → 120hs (5 días) → 1 solo mensaje → pausa definitiva
                    elif (estado.tipo_timer == "visita" and
                            tiempo_desde_timer >= timedelta(hours=120)):
                        ok = await proveedor.enviar_mensaje(estado.telefono, MSG_VISITA)
                        if ok:
                            estado.recordatorio_enviado = "enviado"
                            estado.timer_activado_en = None
                            await session.commit()
                            logger.info(f"Recordatorio visita enviado a {estado.telefono} — pausa definitiva")

            # ── Leads referenciales 24hs ──────────────────────
            try:
                result_leads = await session.execute(
                    select(LeadReferencial).where(
                        LeadReferencial.estado == "pendiente"
                    )
                )
                leads = result_leads.scalars().all()

                for lead in leads:
                    tiempo_desde_lead = ahora - lead.lead_detectado_en
                    if tiempo_desde_lead < timedelta(hours=24):
                        continue

                    # Construir mensaje personalizado
                    nombre = lead.nombre.split()[0] if lead.nombre else "cliente"
                    area = lead.largo * lead.ancho
                    descripcion = f"tu proyecto de {lead.tipo} de {lead.medidas}m en {lead.comuna}" if lead.tipo else f"tu proyecto de {lead.medidas}m en {lead.comuna}"
                    precio_fmt = f"${lead.precio_referencial:,}".replace(",", ".")

                    mensaje = MSG_REFERENCIAL_TEMPLATE.format(
                        nombre=nombre.capitalize(),
                        descripcion=descripcion,
                        precio=precio_fmt,
                    )

                    ok = await proveedor.enviar_mensaje(lead.telefono, mensaje)
                    if ok:
                        lead.estado = "referencial_enviado"
                        await session.commit()
                        logger.info(f"Precio referencial enviado a {lead.telefono} ({lead.medidas}m → {precio_fmt})")

            except Exception as e_ref:
                logger.error(f"Error procesando leads referenciales: {e_ref}")

        except Exception as e:
            logger.error(f"Error en scheduler recordatorios: {e}")
