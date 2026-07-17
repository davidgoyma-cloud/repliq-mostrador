# -*- coding: utf-8 -*-
"""Búsqueda de candidatos OTC/parafarmacia por síntoma sobre el catálogo real.
Solo devuelve productos que existen en el catálogo (en stock/surtido)."""
import json, unicodedata, re
from pathlib import Path

_CAT = None

def _cargar():
    global _CAT
    if _CAT is None:
        p = Path(__file__).parent / "catalogo_otc.json"
        try:
            _CAT = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _CAT = []
    return _CAT

def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return s.lower()

# Síntoma (palabras clave) -> trozos de categoría/nombre a buscar (ya normalizados).
# La clave se busca como subcadena en el texto normalizado del síntoma.
SINONIMOS = {
    "alergia": ["alergia", "antihistamin"],
    "estornud": ["alergia", "descongestivo nasal"],
    "rinitis": ["alergia", "descongestivo nasal"],
    "moco": ["descongestivo nasal", "catarro", "gripe", "mucolit", "tos"],
    "mucosidad": ["descongestivo nasal", "catarro", "gripe", "mucolit", "tos"],
    "congestion": ["descongestivo nasal", "catarro", "gripe"],
    "nariz": ["descongestivo nasal", "catarro"],
    "resfri": ["catarro", "gripe", "descongestivo nasal", "tos"],
    "constipad": ["catarro", "gripe", "descongestivo nasal"],
    "catarro": ["catarro", "gripe", "descongestivo nasal", "tos"],
    "gripe": ["gripe", "dolor oral", "dolorf"],
    "tos": ["tos", "garganta"],
    "garganta": ["garganta", "caramelos"],
    "faringe": ["garganta"],
    "angina": ["garganta"],
    "afonia": ["garganta"],
    "dolor": ["dolor oral", "dolorf", "dolor topico"],
    "fiebre": ["dolor oral", "dolorf", "gripe"],
    "cabeza": ["dolor oral", "dolorf"],
    "cefalea": ["dolor oral", "dolorf"],
    "regla": ["dolor oral", "dolorf"],
    "muscular": ["dolor topico", "botiquin"],
    "contractura": ["dolor topico"],
    "espalda": ["dolor topico", "dolor oral"],
    "golpe": ["dolor topico", "circulacion topico", "botiquin"],
    "contusion": ["dolor topico", "circulacion topico", "botiquin"],
    "hematoma": ["dolor topico", "circulacion topico", "botiquin"],
    "moraton": ["dolor topico", "circulacion topico", "botiquin"],
    "morado": ["dolor topico", "circulacion topico", "botiquin"],
    "esguince": ["dolor topico", "botiquin"],
    "diarrea": ["diarrea", "probiotico"],
    "descompos": ["diarrea", "probiotico"],
    "acidez": ["antiacido", "digestivo"],
    "ardor": ["antiacido", "digestivo"],
    "estomago": ["antiacido", "digestivo"],
    "reflujo": ["antiacido", "digestivo"],
    "digestion": ["antiacido", "digestivo"],
    "empacho": ["antiacido", "digestivo"],
    "gases": ["antiacido", "digestivo"],
    "estreñi": ["laxante"],
    "estreni": ["laxante"],
    "hongo": ["hongos", "pies"],
    "candidiasis": ["hongos", "intimo"],
    "micosis": ["hongos", "pies"],
    "cistitis": ["infecc orina"],
    "orina": ["infecc orina"],
    "orinar": ["infecc orina"],
    "picadura": ["mosquitos", "alergia topica", "botiquin"],
    "mosquito": ["mosquitos"],
    "insecto": ["mosquitos"],
    "piojo": ["piojos"],
    "liendre": ["piojos"],
    "ojo": ["ojos", "ojo"],
    "conjuntiv": ["ojos", "ojo alergia"],
    "ocular": ["ojos"],
    "legaña": ["ojos"],
    "vista": ["ojos"],
    "sueño": ["sueño", "animo"],
    "sueno": ["sueño", "animo"],
    "insomnio": ["sueño"],
    "dormir": ["sueño"],
    "nervios": ["sueño", "animo"],
    "ansiedad": ["sueño", "animo"],
    "estres": ["sueño", "animo"],
    "quemadura": ["solar", "corporal"],
    "sol": ["solar", "corporal"],
    "aftersun": ["solar", "corporal"],
    "insolacion": ["solar"],
    "grano": ["acne", "higiene facial"],
    "acne": ["acne", "higiene facial"],
    "espinilla": ["acne", "higiene facial"],
    "hemorroide": ["hemorroidal"],
    "almorrana": ["hemorroidal"],
    "herpes": ["labiales", "botiquin"],
    "calentura": ["labiales", "botiquin"],
    "afta": ["aftas", "bucal"],
    "llaga": ["aftas", "bucal"],
    "boca": ["bucal", "aftas"],
    "encia": ["encias", "bucal"],
    "tabaco": ["tabaco"],
    "fumar": ["tabaco"],
    "oido": ["tapones oido"],
    "tapon": ["tapones oido"],
    "cansancio": ["multivitaminas", "dietetica"],
    "fatiga": ["multivitaminas", "dietetica"],
    "astenia": ["multivitaminas", "dietetica"],
    "defensas": ["multivitaminas", "probiotico"],
    "vitamina": ["multivitaminas"],
    "callo": ["pies", "bazar pies"],
    "dureza": ["pies", "bazar pies"],
    "verruga": ["botiquin", "pies"],
    "herida": ["botiquin", "tiritas"],
    "corte": ["botiquin", "tiritas"],
    "quemazon": ["botiquin"],
    "menopausia": ["menopausia"],
    "sofoco": ["menopausia"],
    # clases de producto (sobre todo para el buscador por tipo)
    "antihistamin": ["alergia"],
    "mucolit": ["tos", "descongestivo nasal"],
    "expectorante": ["tos"],
    "antitusiv": ["tos"],
    "analges": ["dolor oral", "dolorf"],
    "antiinflam": ["dolor"],
    "descongest": ["descongestivo nasal"],
    "antiacid": ["antiacido"],
    "antifung": ["hongos"],
    "antisept": ["botiquin"],
    "protector solar": ["solar"],
    "probiotic": ["probiotico", "inmun"],
    "antigripal": ["gripe", "descongestivo nasal"],
    "gripal": ["gripe"],
}

# Palabras vacías para el emparejamiento por palabra suelta.
_STOP = set("de la el en los las y o para por con un una que se me te su al del mas muy tengo tiene "
            "cliente dame algo cosa mucho poco dias dia".split())

def buscar_candidatos(sintoma, limite=40):
    cat = _cargar()
    ns = _norm(sintoma)
    terminos = set()
    for clave, cats in SINONIMOS.items():
        # coincidencia al inicio de palabra (evita que "tos" case dentro de "granitos")
        if re.search(r"\b" + re.escape(_norm(clave)), ns):
            terminos.update(cats)
    # palabras sueltas del síntoma (por si no está en el mapa)
    for w in re.findall(r"[a-zñ]{4,}", ns):
        if w not in _STOP:
            terminos.add(w)
    if not terminos:
        return []
    scored = []
    for p in cat:
        cc = _norm(p.get("c", ""))
        nn = _norm(p.get("n", ""))
        en_cat = any(t in cc for t in terminos)
        en_nom = any(t in nn for t in terminos)
        if not (en_cat or en_nom):
            continue
        s_rel = 0 if en_cat else 1          # match en la categoría es más relevante
        s_efp = 0 if cc.startswith("efp") else 1
        scored.append(((s_rel, s_efp, -(p.get("m", 0) or 0)), p))
    scored.sort(key=lambda x: x[0])
    return [p for _, p in scored[:limite]]


def buscar_tipo(texto, limite=100):
    """Buscador por TIPO/clase de producto: devuelve TODOS los del catálogo que
    encajan, ordenados de mejor a peor Calidad € (para colocar balda y pedir)."""
    cat = _cargar()
    ns = _norm(texto)
    terminos = set()
    for clave, cats in SINONIMOS.items():
        if re.search(r"\b" + re.escape(_norm(clave)), ns):
            terminos.update(cats)
    for w in re.findall(r"[a-zñ]{3,}", ns):
        if w not in _STOP:
            terminos.add(w)
    if not terminos:
        return []
    scored = []
    for p in cat:
        cc = _norm(p.get("c", "")); nn = _norm(p.get("n", ""))
        en_cat = any(t in cc for t in terminos)
        if en_cat or any(t in nn for t in terminos):
            # primero los que casan por CATEGORÍA (más precisos), luego mejor Calidad €
            scored.append(((0 if en_cat else 1, -(p.get("e") or 0)), p))
    scored.sort(key=lambda x: x[0])
    return [p for _, p in scored[:limite]]


def contexto_candidatos(prods):
    if not prods:
        return ""
    lineas = []
    for p in prods:
        d = f"{p['n']} [CN {p['cn']}] cat:{p.get('c','')} stock:{p.get('s','?')}"
        if p.get("e") is not None:
            d += f" deja {p['e']}EUR/{p.get('m','?')}%"
        if p.get("u"):
            d += f" ubic {p['u']}"
        lineas.append(d)
    return " ; ".join(lineas)


if __name__ == "__main__":
    for s in ["alergia, granitos por la alergia", "mucosidad en los senos y vias altas",
              "dolor de garganta", "diarrea", "quemadura de sol", "hongos en el pie",
              "no puedo dormir", "picadura de mosquito", "acidez de estomago", "moraton en el ojo"]:
        c = buscar_candidatos(s, 6)
        print("\n===", s, "-> ", len(c), "candidatos")
        for p in c:
            print("   ", p.get("c", "")[:22], "|", p["n"][:40], "| stock", p.get("s"))
