# agent/tools.py — Herramientas del agente PERGOLAND CHILE SPA
# Generado por AgentKit

import os
import yaml
import logging

logger = logging.getLogger("agentkit")

# Zonas de cobertura
COMUNAS_RM = True  # Todas las comunas de la RM

COMUNAS_V_REGION = {
    "valparaíso", "valparaiso", "viña del mar", "vina del mar", "quilpué", "quilpue",
    "villa alemana", "san antonio", "melipilla", "casablanca", "quillota", "los andes",
    "san felipe", "limache", "olmué", "olmue", "algarrobo", "el quisco", "el tabo",
    "cartagena", "santo domingo", "llaillay", "catemu", "panquehue", "putaendo",
    "santa maría", "santa maria", "hijuelas", "la calera", "la cruz", "nogales",
    "puchuncaví", "puchuncavi", "quintero", "zapallar", "papudo", "petorca",
    "cabildo", "llay-llay", "llay llay",
}

COMUNAS_VI_REGION = {
    "rancagua", "machalí", "machali", "graneros", "requínoa", "requinoa", "rengo",
    "coinco", "coltauco", "doñihue", "donihue", "olivar", "mostazal", "codegua",
    "malloa", "san vicente", "peumo", "las cabras", "pichidegua", "san fernando",
    "chimbarongo", "placilla", "nancagua", "palmilla", "santa cruz", "lolol",
    "pumanque", "chépica", "chepica", "paredones", "pichilemu", "litueche",
    "la estrella", "marchigüe", "marchigue", "navidad", "peralillo",
    "san francisco de mostazal",
}

URL_CATALOGO = "https://storage.googleapis.com/msgsndr/dV4ZS4jWE1wOqNSmucWh/media/693abe14eac0a87afbfc4d39.pdf"


def cargar_info_negocio() -> dict:
    """Carga la información del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def obtener_horario() -> dict:
    """Retorna el horario de atención del negocio."""
    info = cargar_info_negocio()
    return {
        "horario": info.get("negocio", {}).get("horario", "No disponible"),
    }


def verificar_cobertura(comuna: str) -> dict:
    """
    Verifica si una comuna está dentro de la zona de cobertura de Pergoland.

    Args:
        comuna: Nombre de la comuna a verificar

    Returns:
        dict con 'cubre' (bool) y 'mensaje' (str)
    """
    comuna_lower = comuna.lower().strip()

    # Todas las comunas de RM están cubiertas
    # Para simplificar, si no está en VI ni V, y no es claramente fuera, asumimos RM
    if comuna_lower in COMUNAS_V_REGION or comuna_lower in COMUNAS_VI_REGION:
        return {
            "cubre": True,
            "mensaje": f"Sí, cubrimos {comuna}. ¡Perfecto para avanzar con tu proyecto!"
        }

    # Comunas claramente fuera de cobertura
    fuera = {
        "concepción", "concepcion", "temuco", "la serena", "antofagasta",
        "iquique", "puerto montt", "punta arenas", "arica", "calama",
        "copiapó", "copiapo", "coquimbo", "valdivia", "osorno", "chillán", "chillan",
    }
    if comuna_lower in fuera:
        return {
            "cubre": False,
            "mensaje": f"Actualmente operamos en RM, V y VI Región hasta 200km de Santiago. {comuna} quedaría fuera de nuestra cobertura actual."
        }

    # Si hay duda, pedir confirmación
    return {
        "cubre": None,
        "mensaje": f"Déjame confirmar cobertura en {comuna} con el equipo de Pergoland. ¿Me podés dar tu dirección o comuna exacta?"
    }


def obtener_url_catalogo() -> str:
    """Retorna la URL del catálogo de Pergoland."""
    return URL_CATALOGO


def registrar_lead(telefono: str, datos: dict) -> str:
    """
    Registra un lead calificado con los datos del proyecto.

    Args:
        telefono: Número del cliente
        datos: dict con medidas, tipo_estructura, comuna, nombre, contacto

    Returns:
        Resumen del lead registrado
    """
    resumen = f"Lead registrado — Tel: {telefono}"
    for k, v in datos.items():
        resumen += f" | {k}: {v}"
    logger.info(resumen)
    return resumen
