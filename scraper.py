"""
Radar Remates - Scraper de remates judiciales y tributarios del Perú
Fuentes: SUNAT Remates Tributarios, REMAJU (Poder Judicial), PRONABI
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin
from notifier import send_telegram

# ─── CONFIG ──────────────────────────────────────────────────────
FILTROS = {
    "zonas_interes": [
        "lima", "san isidro", "miraflores", "surco", "santiago de surco",
        "san borja", "la molina", "jesus maria", "pueblo libre", "magdalena",
        "san miguel", "lince", "breña", "surquillo", "barranco",
        "chorrillos", "ate", "la victoria", "callao", "comas",
        "los olivos", "san martin de porres", "san juan de lurigancho",
        "villa el salvador", "villa maria del triunfo", "independencia",
        "carabayllo", "lurigancho", "huacho", "barranca", "cañete",
    ],
    "categorias_sunat": ["inmuebles", "vehiculos"],
    "precio_max": 2_000_000,
    "solo_tercera_convocatoria": False,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
}

DATA_DIR = "data"
SEEN_FILE = f"{DATA_DIR}/seen.json"
REMATES_FILE = f"{DATA_DIR}/remates.json"

SUNAT_BASE = "https://rematestributarios.sunat.gob.pe"


# ─── HELPERS ────────────────────────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"sunat": [], "remaju": [], "pronabi": []}


def save_seen(seen):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def parse_money(text):
    """Extrae el primer monto en S/ del texto."""
    if not text:
        return 0.0
    m = re.search(r"S/\s*([\d,]+(?:\.\d{1,2})?)", text)
    if not m:
        return 0.0
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return 0.0


def get(url, timeout=30):
    """GET con headers + manejo de errores."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f"  [HTTP] Error en {url}: {e}")
    return None


# ═══════════════════════════════════════════════════════════════
# FUENTE 1: SUNAT (listado + enriquecimiento por detalle)
# ═══════════════════════════════════════════════════════════════

def scrape_sunat_listado(categoria):
    """Parsea el listado completo extrayendo todos los datos del <li> contenedor."""
    html = get(f"{SUNAT_BASE}/{categoria}")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for h2 in soup.select("h2.title"):
        a = h2.select_one("a[href*='/node/']")
        if not a:
            continue
        m = re.search(r"/node/(\d+)", a.get("href", ""))
        if not m:
            continue
        node_id = m.group(1)
        titulo = a.get_text(strip=True)

        li = h2.find_parent("li")
        if not li:
            continue
        text = li.get_text(separator=" ", strip=True)

        # Precio tasación: "PRECIO DE TASACIÓN ... S/ NUMERO"
        precio_tasacion = 0.0
        m_t = re.search(r"PRECIO\s+DE\s+TASACI[OÓ]N[^S]*S/\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
        if m_t:
            precio_tasacion = float(m_t.group(1).replace(",", ""))

        # Precio base (puede estar en el detalle o no)
        precio_base = 0.0
        m_b = re.search(r"PRECIO\s+BASE[^S]*S/\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
        if m_b:
            precio_base = float(m_b.group(1).replace(",", ""))

        # Fecha "Mar, 14/04/2026 - 11:00"
        fecha = ""
        hora = ""
        m_f = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}:\d{2})", text)
        if m_f:
            fecha = m_f.group(1)
            hora = m_f.group(2)
        elif (mf := re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)):
            fecha = mf.group(1)

        # Convocatoria: "PRIMER REMATE", "SEGUNDO REMATE", "TERCER REMATE"
        convocatoria = ""
        if re.search(r"TERCER\s+REMATE", text, re.IGNORECASE):
            convocatoria = "3ra"
        elif re.search(r"SEGUNDO\s+REMATE", text, re.IGNORECASE):
            convocatoria = "2da"
        elif re.search(r"PRIMER\s+REMATE", text, re.IGNORECASE):
            convocatoria = "1ra"

        items.append({
            "node_id": node_id,
            "titulo": titulo,
            "precio_tasacion": precio_tasacion,
            "precio_base": precio_base,
            "fecha": fecha,
            "hora": hora,
            "convocatoria": convocatoria,
            "categoria": categoria,
        })
    return items


def detect_convocatoria(text):
    t = text.lower()
    # Buscar el orden importa: tercer antes que segundo
    if re.search(r"\btercer[oa]?\b|\b3ra?\b|\bterce?ra?\s+convocatoria\b", t):
        return "3ra"
    if re.search(r"\bsegund[oa]\b|\b2da?\b|\bsegunda\s+convocatoria\b", t):
        return "2da"
    if re.search(r"\bprimer[oa]?\b|\b1ra?\b|\bprimera\s+convocatoria\b", t):
        return "1ra"
    return ""


def parse_fecha_remate(text):
    """Intenta extraer fecha del remate del texto."""
    # Formato dd/mm/yyyy
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
    if m:
        return m.group(1)
    # Formato textual: "martes, 14 de abril de 2026"
    meses = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "setiembre": "09", "octubre": "10",
        "noviembre": "11", "diciembre": "12",
    }
    m2 = re.search(
        r"(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})",
        text, re.IGNORECASE,
    )
    if m2:
        d, mes, y = m2.group(1), m2.group(2).lower(), m2.group(3)
        return f"{int(d):02d}/{meses[mes]}/{y}"
    return ""


def scrape_sunat_detalle_extras(node_id):
    """Solo trae imagen, PDF, deudor, expediente, dependencia y precio_base si no estaba."""
    url = f"{SUNAT_BASE}/node/{node_id}"
    html = get(url)
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("article, .node, main") or soup
    text = body.get_text(separator=" ", strip=True)

    extras = {}

    # Imagen
    img = body.select_one("img[src*='/sites/default/files']") or body.select_one("img[src]")
    if img:
        extras["imagen"] = urljoin(SUNAT_BASE, img.get("src", ""))

    # PDF
    pdf = body.select_one("a[href$='.pdf']")
    if pdf:
        extras["pdf"] = urljoin(SUNAT_BASE, pdf.get("href", ""))

    # Expediente coactivo: número de 8+ dígitos cerca de "expediente"
    m_exp = re.search(r"expediente\s*coactivo[^\d]{0,15}(\d{8,})", text, re.IGNORECASE)
    if m_exp:
        extras["expediente"] = m_exp.group(1)

    # Deudor (RUC seguido de nombre o "Deudor: NOMBRE")
    m_deu = re.search(r"RUC[^\d]*\d{11}\s*[\-:]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{5,60})", text)
    if m_deu:
        extras["deudor"] = m_deu.group(1).strip()

    # Dependencia: matchear contra lista de oficinas SUNAT conocidas
    SUNAT_OFICINAS = [
        "Lima", "Huacho", "Cañete", "Callao", "Ica", "Chincha", "Pisco",
        "Arequipa", "Tacna", "Moquegua", "Puno", "Cusco", "Madre de Dios",
        "Trujillo", "Chiclayo", "Piura", "Tumbes", "Cajamarca", "Chimbote",
        "Huaraz", "Ayacucho", "Huancavelica", "Huánuco", "Tarapoto", "Iquitos",
        "Pucallpa", "Junín", "Huancayo",
    ]
    for oficina in SUNAT_OFICINAS:
        if re.search(rf"SUNAT[\s\-]*{re.escape(oficina)}\b", text, re.IGNORECASE):
            extras["dependencia"] = oficina
            break

    return extras


def scrape_sunat():
    """Parsea el listado de cada categoría y enriquece con detalles."""
    by_id = {}
    for categoria in FILTROS["categorias_sunat"]:
        listado = scrape_sunat_listado(categoria)
        print(f"  [SUNAT/{categoria}] {len(listado)} items en listado")
        for it in listado:
            by_id.setdefault(it["node_id"], it)

    items = []
    print(f"  [SUNAT] Enriqueciendo {len(by_id)} detalles...")
    for nid, base in by_id.items():
        extras = scrape_sunat_detalle_extras(nid)
        time.sleep(0.3)

        precio_tasacion = base["precio_tasacion"]
        precio_base = base["precio_base"]
        descuento_pct = 0
        if precio_base > 0 and precio_tasacion > 0 and precio_base < precio_tasacion:
            descuento_pct = round((1 - precio_base / precio_tasacion) * 100)

        # Si no hay dependencia del detalle, intentar extraer del título
        dep = extras.get("dependencia", "")
        if not dep:
            UBIGEOS = ["Lima", "Callao", "Surco", "San Isidro", "Miraflores", "San Borja",
                       "La Molina", "San Miguel", "Barranca", "Huacho", "Supe", "Pativilca",
                       "Cañete", "Huaral", "Ica", "Tacna", "Arequipa", "Trujillo", "Piura",
                       "Cusco", "Pacasmayo", "Paramonga", "Ate", "Chorrillos", "San Martín"]
            for u in UBIGEOS:
                if re.search(rf"\b{re.escape(u)}\b", base["titulo"], re.IGNORECASE):
                    dep = u
                    break

        items.append({
            "id": f"sunat_{nid}",
            "fuente": "SUNAT",
            "titulo": base["titulo"][:240],
            "categoria": base["categoria"],
            "precio_tasacion": precio_tasacion,
            "precio_base": precio_base,
            "descuento_pct": descuento_pct,
            "fecha": base["fecha"],
            "hora": base["hora"],
            "dependencia": dep,
            "expediente": extras.get("expediente", ""),
            "deudor": extras.get("deudor", ""),
            "convocatoria": base["convocatoria"],
            "imagen": extras.get("imagen", ""),
            "pdf": extras.get("pdf", ""),
            "url": f"{SUNAT_BASE}/node/{nid}",
        })

    print(f"[SUNAT] {len(items)} remates procesados")
    return items


# ═══════════════════════════════════════════════════════════════
# FUENTE 2: REMAJU (carousel del home + Playwright opcional)
# ═══════════════════════════════════════════════════════════════

def scrape_remaju_home():
    """Scrapea el carousel del homepage de REMAJU (sin JS)."""
    items = []
    html = get("https://remaju.pj.gob.pe/remaju/")
    if not html:
        return items
    soup = BeautifulSoup(html, "html.parser")

    text_blocks = soup.find_all(string=re.compile(r"REMATE\s+(SIMPLE|MÚLTIPLE|MULTIPLE)", re.IGNORECASE))
    seen_local = set()

    for tb in text_blocks:
        container = tb.find_parent()
        for _ in range(5):
            if container and container.parent:
                container = container.parent
                ct = container.get_text(separator="|", strip=True)
                if "REMATE" in ct and len(ct) > 20:
                    break

        ct = container.get_text(separator="|", strip=True) if container else ""
        parts = [p.strip() for p in ct.split("|") if p.strip()]

        tipo = ""
        distrito = ""
        fecha = ""
        for part in parts:
            if "REMATE" in part.upper() and not tipo:
                tipo = part.strip()
            elif re.match(r"\d{1,2}/\d{1,2}/\d{4}", part) and not fecha:
                fecha = part[:10]
            elif part not in ("Detalle", "* ÚLTIMO DÍA DE INSCRIPCIÓN") and len(part) > 2 and not distrito:
                if "REMATE" not in part.upper():
                    distrito = part.strip()

        if not (distrito and fecha):
            continue

        item_id = f"remaju_{distrito}_{fecha}".lower().replace(" ", "_").replace("/", "")
        if item_id in seen_local:
            continue
        seen_local.add(item_id)

        items.append({
            "id": item_id,
            "fuente": "REMAJU",
            "titulo": f"{tipo} - {distrito}".strip(" -"),
            "categoria": "inmuebles",
            "precio_tasacion": 0,
            "precio_base": 0,
            "descuento_pct": 0,
            "fecha": fecha,
            "hora": "",
            "dependencia": distrito,
            "expediente": "",
            "deudor": "",
            "convocatoria": "",
            "imagen": "",
            "pdf": "",
            "url": "https://remaju.pj.gob.pe/remaju/",
        })

    return items


def scrape_remaju_playwright():
    """Usa Playwright para scrappear el listado completo (requiere chromium)."""
    items = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [REMAJU/PW] playwright no instalado, salteando")
        return items

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=HEADERS["User-Agent"])
            page = ctx.new_page()
            page.goto("https://remaju.pj.gob.pe/remaju/", wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(2000)

            # Intentar abrir el menú "Remates"
            try:
                page.click("text=Remates", timeout=5000)
                page.wait_for_timeout(2500)
            except Exception:
                pass

            # Extraer todo el HTML renderizado y buscar bloques REMATE
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            text_blocks = soup.find_all(string=re.compile(r"REMATE\s+(SIMPLE|MÚLTIPLE|MULTIPLE)", re.IGNORECASE))
            seen_local = set()
            for tb in text_blocks:
                container = tb.find_parent()
                for _ in range(5):
                    if container and container.parent:
                        container = container.parent
                        ct = container.get_text(separator="|", strip=True)
                        if "REMATE" in ct and len(ct) > 20:
                            break
                ct = container.get_text(separator="|", strip=True) if container else ""
                parts = [p.strip() for p in ct.split("|") if p.strip()]
                tipo = distrito = fecha = ""
                for part in parts:
                    if "REMATE" in part.upper() and not tipo:
                        tipo = part.strip()
                    elif re.match(r"\d{1,2}/\d{1,2}/\d{4}", part) and not fecha:
                        fecha = part[:10]
                    elif part not in ("Detalle", "* ÚLTIMO DÍA DE INSCRIPCIÓN") and len(part) > 2 and not distrito:
                        if "REMATE" not in part.upper():
                            distrito = part.strip()
                if not (distrito and fecha):
                    continue
                item_id = f"remaju_{distrito}_{fecha}".lower().replace(" ", "_").replace("/", "")
                if item_id in seen_local:
                    continue
                seen_local.add(item_id)
                items.append({
                    "id": item_id,
                    "fuente": "REMAJU",
                    "titulo": f"{tipo} - {distrito}".strip(" -"),
                    "categoria": "inmuebles",
                    "precio_tasacion": 0,
                    "precio_base": 0,
                    "descuento_pct": 0,
                    "fecha": fecha,
                    "hora": "",
                    "dependencia": distrito,
                    "expediente": "",
                    "deudor": "",
                    "convocatoria": "",
                    "imagen": "",
                    "pdf": "",
                    "url": "https://remaju.pj.gob.pe/remaju/",
                })

            browser.close()
    except Exception as e:
        print(f"  [REMAJU/PW] Error: {e}")

    return items


def scrape_remaju():
    """Combina home estático + Playwright si está disponible."""
    items = scrape_remaju_home()
    pw_items = scrape_remaju_playwright()
    # Merge dedup
    by_id = {i["id"]: i for i in items}
    for i in pw_items:
        by_id.setdefault(i["id"], i)
    final = list(by_id.values())
    print(f"[REMAJU] {len(final)} remates encontrados (home={len(items)}, pw={len(pw_items)})")
    return final


# ═══════════════════════════════════════════════════════════════
# FUENTE 3: PRONABI (vía búsqueda en gob.pe)
# ═══════════════════════════════════════════════════════════════

def scrape_pronabi():
    """Busca subastas activas de PRONABI en gob.pe."""
    items = []
    urls = [
        "https://www.gob.pe/busquedas?contenido[]=campa%C3%B1as&institucion[]=pronabi&sheet=1&sort_by=recent",
        "https://www.gob.pe/busquedas?contenido[]=noticias&institucion[]=pronabi&term=subasta&sheet=1&sort_by=recent",
    ]
    seen_local = set()
    for url in urls:
        html = get(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='/institucion/pronabi/']"):
            href = a.get("href", "")
            titulo = a.get_text(strip=True)
            if not titulo or len(titulo) < 10:
                continue
            tl = titulo.lower()
            if not ("subasta" in tl or "remate" in tl or "puja" in tl):
                continue
            full = urljoin("https://www.gob.pe", href)
            if full in seen_local:
                continue
            seen_local.add(full)
            slug = href.rstrip("/").split("/")[-1]
            items.append({
                "id": f"pronabi_{slug}",
                "fuente": "PRONABI",
                "titulo": titulo[:240],
                "categoria": "varios",
                "precio_tasacion": 0,
                "precio_base": 0,
                "descuento_pct": 0,
                "fecha": "",
                "hora": "",
                "dependencia": "Nacional",
                "expediente": "",
                "deudor": "",
                "convocatoria": "",
                "imagen": "",
                "pdf": "",
                "url": full,
            })
    print(f"[PRONABI] {len(items)} subastas encontradas")
    return items


# ═══════════════════════════════════════════════════════════════
# FILTROS, NOTIFICACIÓN, MAIN
# ═══════════════════════════════════════════════════════════════

def aplicar_filtros(items):
    out = []
    for item in items:
        haystack = f"{item.get('titulo','')} {item.get('dependencia','')} {item.get('deudor','')}".lower()
        zona_match = any(z in haystack for z in FILTROS["zonas_interes"])
        if not zona_match and item["fuente"] != "PRONABI":
            continue
        if item.get("precio_tasacion", 0) > FILTROS["precio_max"] > 0:
            continue
        if FILTROS["solo_tercera_convocatoria"] and item.get("convocatoria") and item["convocatoria"] != "3ra":
            continue
        out.append(item)
    return out


def format_alert(item):
    emoji = {"SUNAT": "🏛️", "REMAJU": "⚖️", "PRONABI": "🔒"}
    conv = ""
    if item["convocatoria"] == "3ra":
        conv = " 🔥 3RA CONVOCATORIA"
    elif item["convocatoria"] == "2da":
        conv = " ⚡ 2da conv."

    if item.get("precio_base") and item.get("descuento_pct"):
        precio_str = f"S/ {item['precio_base']:,.0f} (-{item['descuento_pct']}% de tasación)"
    elif item.get("precio_tasacion"):
        precio_str = f"S/ {item['precio_tasacion']:,.0f} (tasación)"
    else:
        precio_str = "Ver detalle"

    fecha_str = item["fecha"] or "Ver enlace"
    if item.get("hora"):
        fecha_str += f" {item['hora']}"

    return f"""{emoji.get(item['fuente'], '📋')} *{item['fuente']}*{conv}

📍 {item.get('dependencia', '—')}
📝 {item['titulo'][:200]}
💰 {precio_str}
📅 {fecha_str}
🔗 {item['url']}"""


def main():
    print(f"\n{'='*50}")
    print(f"🔍 RADAR REMATES - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    seen = load_seen()

    sunat_items = scrape_sunat()
    remaju_items = scrape_remaju()
    pronabi_items = scrape_pronabi()
    all_items = sunat_items + remaju_items + pronabi_items

    filtered = aplicar_filtros(all_items)
    print(f"\n[FILTROS] {len(filtered)} pasan filtros de {len(all_items)} totales")

    all_seen_ids = set(seen["sunat"] + seen["remaju"] + seen["pronabi"])
    nuevos = [i for i in filtered if i["id"] not in all_seen_ids]
    print(f"[NUEVOS] {len(nuevos)} remates nuevos")

    if nuevos:
        send_telegram(f"🚨 *RADAR REMATES* — {len(nuevos)} nuevo(s)\n_{datetime.now().strftime('%d/%m/%Y %H:%M')}_")
        for item in nuevos[:15]:
            send_telegram(format_alert(item))
            key = item["fuente"].lower()
            if key in seen:
                seen[key].append(item["id"])
        if len(nuevos) > 15:
            send_telegram(f"⚠️ _+{len(nuevos)-15} remates más no mostrados_")
    else:
        print("[INFO] Sin remates nuevos.")

    for k in seen:
        if len(seen[k]) > 500:
            seen[k] = seen[k][-500:]
    save_seen(seen)

    # Ordenar: 3ra conv primero, luego 2da, luego por fecha
    orden = {"3ra": 0, "2da": 1, "1ra": 2, "": 3}
    filtered.sort(key=lambda x: (orden.get(x.get("convocatoria", ""), 3), x.get("fecha", "")))

    dashboard = {
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(filtered),
        "nuevos": len(nuevos),
        "remates": filtered,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REMATES_FILE, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Listo. {len(filtered)} remates en dashboard.")


if __name__ == "__main__":
    main()
