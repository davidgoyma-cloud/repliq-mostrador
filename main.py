"""
Mini-app independiente: buscador de VENTA CRUZADA para el mostrador.

No necesita Farmatic ni base de datos: solo IA (Claude) + una lista de reglas.
Pensada para desplegar en el VPS (EasyPanel) y que los terminales la abran 24/7.

Necesita la variable de entorno ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Mostrador · Venta cruzada")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

MODELO = "claude-haiku-4-5-20251001"

VENTA_CRUZADA = [
    {"cuando": "Antibiótico oral", "ofrece": "Probiótico", "motivo": "Repone la flora intestinal que el antibiótico daña y evita diarreas."},
    {"cuando": "Gotas para el oído (p. ej. Cetraxal Plus)", "ofrece": "Tapones para los oídos", "motivo": "Protegen el oído del agua durante el tratamiento."},
    {"cuando": "Ibuprofeno / antiinflamatorio (AINE)", "ofrece": "Protector gástrico (omeprazol)", "motivo": "Protege el estómago del efecto irritante del AINE."},
    {"cuando": "Antihistamínico (alergia)", "ofrece": "Suero fisiológico / spray nasal", "motivo": "Limpia la mucosa nasal y mejora los síntomas."},
    {"cuando": "Protector solar", "ofrece": "Aftersun / hidratante corporal", "motivo": "Calma e hidrata la piel tras la exposición al sol."},
    {"cuando": "Colirio antibiótico", "ofrece": "Lágrima artificial", "motivo": "Alivia la sequedad y las molestias oculares."},
    {"cuando": "Antidiarreico", "ofrece": "Suero oral / probiótico", "motivo": "Repone sales minerales y flora intestinal."},
    {"cuando": "Jarabe para la tos", "ofrece": "Pastillas de garganta / miel", "motivo": "Alivio local que complementa el jarabe."},
    {"cuando": "Paracetamol / antigripal", "ofrece": "Vitamina C y sueros/líquidos", "motivo": "Refuerza defensas e hidratación."},
    {"cuando": "Antifúngico para el pie", "ofrece": "Polvos / calcetines antitranspirantes", "motivo": "Evita la recaída manteniendo el pie seco."},
    {"cuando": "Hierro oral", "ofrece": "Vitamina C", "motivo": "Mejora la absorción del hierro."},
    {"cuando": "Tratamiento antiacné", "ofrece": "Hidratante no comedogénico + SPF", "motivo": "Contrarresta la sequedad y la fotosensibilidad del tratamiento."},
]

# Parafarmacia de más margen (generada desde Farmatic; se refresca al redesplegar).
_ARCHIVO_MARGEN = Path(__file__).parent / "top_margen.json"
try:
    TOP_MARGEN = json.loads(_ARCHIVO_MARGEN.read_text(encoding="utf-8"))
except Exception:  # noqa: BLE001
    TOP_MARGEN = []

# Tabla Código Nacional -> nombre (para buscar también por CN sin fallo).
_ARCHIVO_CN = Path(__file__).parent / "cn_nombres.json"
try:
    CN_NOMBRES = json.loads(_ARCHIVO_CN.read_text(encoding="utf-8"))
except Exception:  # noqa: BLE001
    CN_NOMBRES = {}


def resolver_producto(texto: str):
    """
    Si el texto es un Código Nacional, lo traduce a nombre del producto.
    Devuelve None si parece un CN pero no existe; devuelve el propio texto si
    es un nombre.
    """
    t = texto.strip()
    clave = t.replace(" ", "")
    if clave.isdigit():
        for cand in (clave, clave.zfill(6), clave.zfill(7)):
            if cand in CN_NOMBRES:
                return f"{CN_NOMBRES[cand]} (CN {cand})"
        return None
    return t


def venta_cruzada(producto: str, api_key: str, top_margen: list | None = None) -> str:
    import anthropic

    contexto = ""
    if top_margen:
        items = "; ".join(
            f"{p['producto']} [CN {p.get('cn','')}] (stock {p.get('stock','?')} ud, deja {p.get('euro','?')} €/ud · {p.get('margen','?')}%, {p.get('categoria','')}"
            + (f", ubicación {p['situacion']}" if p.get('situacion') else "") + ")"
            for p in top_margen)
        contexto = (
            "\n\nLista de productos de nuestra farmacia con lo que deja cada uno (€/ud = PVP "
            "− coste, y % de margen) y su ubicación física en la farmacia. Si alguno encaja "
            "de forma clínicamente apropiada (NUNCA fuerces algo que no aporte valor). Al "
            "citar un producto de la lista muestra sus datos SIEMPRE con este formato EXACTO "
            "(negritas incluidas): «**NOMBRE PRODUCTO** · Calidad €: 5,04 € · Margen: 73% · "
            "CN **701637** · 📍**E5**». Pon en NEGRITA el nombre, el CN y la ubicación (📍), y "
            "usa literalmente 'Calidad €:' y 'Margen:'. Cuando des varias opciones para lo "
            "mismo, SEÑALA cuál es **mejor en Calidad €** y cuál **mejor en Margen** para que "
            "el farmacéutico elija lo que considere: " + items)

    cliente = anthropic.Anthropic(api_key=api_key)
    respuesta = cliente.messages.create(
        model=MODELO,
        max_tokens=320,
        system=(
            "Eres farmacéutico en España, experto en venta cruzada RESPONSABLE (que "
            "aporta valor al paciente, nunca venta forzada). Dado un medicamento o "
            "producto, propones 3-4 productos complementarios que tenga sentido ofrecer. "
            "Responde MUY BREVE: UNA línea por producto (nombre + motivo corto), sin "
            "encabezados ni párrafos largos."
        ),
        messages=[{"role": "user", "content": (
            ([{"type": "text", "text": contexto,
               "cache_control": {"type": "ephemeral"}}] if contexto else [])
            + [{"type": "text", "text":
                f"¿Qué venta cruzada tiene sentido si un cliente se lleva: {producto}?"}]
        )}],
    )
    return "".join(b.text for b in respuesta.content if b.type == "text").strip()


def _terminos_busqueda(sintoma: str, api_key: str) -> list:
    """Pide a la IA términos de búsqueda (activos, tipos, marcas OTC) para el síntoma,
    para encontrar el producto real en el catálogo aunque no esté en el mapa de palabras."""
    import anthropic
    try:
        c = anthropic.Anthropic(api_key=api_key)
        r = c.messages.create(
            model=MODELO, max_tokens=120,
            system=("Eres farmacéutico. Dado un síntoma, devuelve SOLO términos para buscar el "
                    "producto en un catálogo de farmacia: principio activo, tipo de producto, "
                    "formato y marcas OTC habituales en España. 6-10 términos separados por comas, "
                    "sin frases ni explicaciones."),
            messages=[{"role": "user", "content": sintoma}],
        )
        txt = "".join(b.text for b in r.content if b.type == "text")
        return [t.strip() for t in re.split(r"[,\n;]+", txt) if t.strip()]
    except Exception:  # noqa: BLE001
        return []


def recomendar_sintoma(sintoma: str, api_key: str, top_margen: list | None = None) -> str:
    """Recomienda OTC/parafarmacia para un síntoma leve, SOLO con productos que la
    farmacia tiene en stock. Combina búsqueda por palabras + términos que genera la IA."""
    import anthropic
    from retrieval import buscar_candidatos, buscar_por_terminos, contexto_candidatos

    cands = buscar_candidatos(sintoma, limite=22)
    vistos = {c["cn"] for c in cands}
    for p in buscar_por_terminos(_terminos_busqueda(sintoma, api_key), limite=22):
        if p["cn"] not in vistos:
            cands.append(p); vistos.add(p["cn"])
    ctx = contexto_candidatos(cands[:40])
    if ctx:
        user = ("PRODUCTOS REALES DE LA FARMACIA para este caso (OTC/parafarmacia, EN STOCK). "
                "Usa SOLO estos; no inventes otros productos ni CN:\n" + ctx +
                "\n\nSíntoma del cliente: " + sintoma + "\n¿Qué le recomiendo?")
    else:
        user = ("Síntoma del cliente: " + sintoma + "\nNo tengo lista de stock para este caso: "
                "nombra el tipo de producto OTC habitual, SIN inventar CN ni cifras.\n"
                "¿Qué le recomiendo?")

    cliente = anthropic.Anthropic(api_key=api_key)
    respuesta = cliente.messages.create(
        model=MODELO,
        max_tokens=420,
        system=(
            "Eres farmacéutico en España en el mostrador. Recomiendas productos SIN receta "
            "(OTC/parafarmacia); NUNCA medicación financiada de receta. "
            "PASO 1 — TRATAMIENTO DE PRIMERA LÍNEA: di primero el producto que un farmacéutico "
            "vende de verdad para ese síntoma (alergia -> antihistamínico oral; mucosidad o "
            "congestión -> descongestivo o mucolítico; dolor o fiebre -> analgésico; diarrea -> "
            "loperamida; acidez -> antiácido; picadura -> antihistamínico tópico; etc.). "
            "PASO 2: añade 1-2 complementos apropiados. "
            "USA SOLO los productos de la lista «PRODUCTOS REALES» que te paso (son los que la "
            "farmacia TIENE EN STOCK). Para CADA producto recomendado muéstralo con este "
            "formato EXACTO (negritas): «**NOMBRE** · Calidad €: X € · Margen: Y% · CN **ZZZ** "
            "· 📍**SIT** — para qué (corto)». Cuando haya 2-3 opciones válidas, SEÑALA cuál es "
            "mejor en Calidad € y cuál en Margen. "
            "Si en la lista NO hay nada clínicamente apropiado para ese síntoma, DILO claramente "
            "('no lo tengo en stock') y nombra el tipo de producto necesario, SIN inventar CN "
            "ni marcas. JAMÁS recomiendes algo que no encaje con el síntoma (nunca "
            "anticonceptivos, antiedad, aparatos ni ortopedia por su margen). "
            "Responde MUY BREVE: una línea por opción, sin párrafos largos. Termina con UNA "
            "línea: «⚠️ Derivar al médico si… » (breve)."
        ),
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in respuesta.content if b.type == "text").strip()


def _fmt(texto: str | None) -> str | None:
    """Convierte el markdown que devuelve la IA en HTML sencillo y seguro."""
    if not texto:
        return texto
    out = html.escape(texto)
    # **negrita** -> <strong>
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    # Encabezados ## -> línea en negrita (sin las almohadillas)
    lineas = []
    for ln in out.split("\n"):
        m = re.match(r"\s*#{1,6}\s+(.*)", ln)
        lineas.append(f'<strong class="text-brand-800">{m.group(1)}</strong>' if m else ln)
    return "\n".join(lineas)


def _ctx(**kw):
    base = {"cruzada": VENTA_CRUZADA, "top_margen": TOP_MARGEN,
            "reco": None, "error": None, "producto": "",
            "reco_sint": None, "error_sint": None, "sintoma": "",
            "tipo": "", "tipo_res": None, "tipo_nores": False}
    base.update(kw)
    return base


@app.post("/tipo", response_class=HTMLResponse)
def tipo(request: Request, tipo: str = Form("")):
    from retrieval import buscar_tipo
    t = tipo.strip()
    res = buscar_tipo(t) if t else []
    return templates.TemplateResponse(request, "mostrador.html",
        _ctx(tipo=t, tipo_res=res, tipo_nores=bool(t) and not res))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "mostrador.html", _ctx())


@app.post("/cruzada", response_class=HTMLResponse)
def cruzada(request: Request, producto: str = Form("")):
    clave = os.getenv("ANTHROPIC_API_KEY")
    reco = error = None
    entrada = producto.strip()
    prod = entrada
    if not entrada:
        error = "Escribe un producto o Código Nacional."
    else:
        resuelto = resolver_producto(entrada)
        if resuelto is None:
            error = "No encuentro ese Código Nacional. Prueba escribiendo el nombre del producto."
        elif not clave:
            error = "Falta configurar la clave de IA (ANTHROPIC_API_KEY)."
        else:
            prod = resuelto
            try:
                reco = venta_cruzada(resuelto, clave, TOP_MARGEN)
            except Exception as exc:  # noqa: BLE001
                error = "No se pudo generar: " + str(exc)[:200]
    return templates.TemplateResponse(request, "mostrador.html",
                                      _ctx(reco=_fmt(reco), error=error, producto=prod))


@app.post("/sintoma", response_class=HTMLResponse)
def sintoma(request: Request, sintoma: str = Form("")):
    clave = os.getenv("ANTHROPIC_API_KEY")
    reco = error = None
    sint = sintoma.strip()
    if not sint:
        error = "Escribe un síntoma o patología (ej: dolor de oído, vómitos...)."
    elif not clave:
        error = "Falta configurar la clave de IA (ANTHROPIC_API_KEY)."
    else:
        try:
            reco = recomendar_sintoma(sint, clave, TOP_MARGEN)
        except Exception as exc:  # noqa: BLE001
            error = "No se pudo generar: " + str(exc)[:200]
    return templates.TemplateResponse(request, "mostrador.html",
                                      _ctx(reco_sint=_fmt(reco), error_sint=error, sintoma=sint))
