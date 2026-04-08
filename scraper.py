"""
Radar Remates - Scraper de remates judiciales y tributarios del Perú
Fuentes: SUNAT Remates, REMAJU (Poder Judicial), PRONABI
Autor: Alexis / Los Coquetines
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime
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
        "carabayllo", "lurigancho"
    ],
    "categorias": ["inmuebles", "vehiculos"],  # inmuebles, vehiculos, electrodomesticos, mercaderia-variada
    "precio_max": 500000,  # S/ máximo (tasación)
    "solo_tercera_convocatoria": False,  # True = solo 3ra convocatoria (sin precio base en SUNAT)
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

DATA_FILE = "data/seen.json"
REMATES_FILE = "data/remates.json"  # Para el dashboard


def load_seen():
    """Carga IDs ya vistos para no repetir alertas"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"sunat": [], "remaju": [], "pronabi": []}


def save_seen(seen):
    """Guarda IDs vistos"""
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(seen, f, indent=2)


# ═══════════════════════════════════════════════════════════════
# FUENTE 1: SUNAT REMATES TRIBUTARIOS
# ═══════════════════════════════════════════════════════════════

def scrape_sunat():
    """Scrapea rematestributarios.sunat.gob.pe"""
    items = []
    
    for categoria in FILTROS["categorias"]:
        url = f"https://rematestributarios.sunat.gob.pe/{categoria}"
        
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Cada remate es un <li> con estructura conocida
            articles = soup.select("li")
            
            for article in articles:
                # Buscar el link al nodo
                link_tag = article.select_one("a[href*='/node/']")
                if not link_tag:
                    continue
                
                href = link_tag.get("href", "")
                node_id = href.split("/")[-1] if "/node/" in href else None
                if not node_id:
                    continue
                
                titulo = link_tag.get_text(strip=True)
                
                # Buscar precio de tasación
                precio = 0
                precio_text = article.get_text()
                precio_match = re.search(r'S/\s*([\d,]+(?:\.\d{2})?)', precio_text)
                if precio_match:
                    precio_str = precio_match.group(1).replace(",", "")
                    try:
                        precio = float(precio_str)
                    except:
                        precio = 0
                
                # Buscar fecha
                fecha = ""
                fecha_patterns = [
                    r'(\d{1,2}/\d{1,2}/\d{4})',
                    r'((?:lunes|martes|miércoles|jueves|viernes|sábado|domingo),?\s+\d{1,2}\s+\w+\s+\d{4})',
                ]
                for pattern in fecha_patterns:
                    fecha_match = re.search(pattern, precio_text, re.IGNORECASE)
                    if fecha_match:
                        fecha = fecha_match.group(1)
                        break
                
                # Buscar dependencia
                dependencia = ""
                dep_link = article.select_one("a[href*='sunat.gob.pe/']:not([href*='/node/'])")
                if dep_link:
                    dependencia = dep_link.get_text(strip=True)
                
                # Detectar convocatoria
                convocatoria = ""
                text_lower = precio_text.lower()
                if "tercer" in text_lower or "tercera" in text_lower:
                    convocatoria = "3ra"
                elif "segundo" in text_lower or "segunda" in text_lower:
                    convocatoria = "2da"
                elif "primer" in text_lower or "primera" in text_lower:
                    convocatoria = "1ra"
                
                if titulo and len(titulo) > 10:
                    items.append({
                        "id": f"sunat_{node_id}",
                        "fuente": "SUNAT",
                        "titulo": titulo[:200],
                        "categoria": categoria,
                        "precio_tasacion": precio,
                        "fecha": fecha,
                        "dependencia": dependencia,
                        "convocatoria": convocatoria,
                        "url": f"https://rematestributarios.sunat.gob.pe/node/{node_id}",
                    })
            
            # Revisar página 2
            page2_url = f"{url}?page=1"
            try:
                resp2 = requests.get(page2_url, headers=HEADERS, timeout=30)
                if resp2.status_code == 200:
                    soup2 = BeautifulSoup(resp2.text, "html.parser")
                    for article in soup2.select("li"):
                        link_tag = article.select_one("a[href*='/node/']")
                        if not link_tag:
                            continue
                        href = link_tag.get("href", "")
                        node_id = href.split("/")[-1] if "/node/" in href else None
                        if not node_id:
                            continue
                        titulo = link_tag.get_text(strip=True)
                        if titulo and len(titulo) > 10:
                            # Precio
                            precio = 0
                            precio_text = article.get_text()
                            precio_match = re.search(r'S/\s*([\d,]+(?:\.\d{2})?)', precio_text)
                            if precio_match:
                                try:
                                    precio = float(precio_match.group(1).replace(",", ""))
                                except:
                                    pass
                            
                            items.append({
                                "id": f"sunat_{node_id}",
                                "fuente": "SUNAT",
                                "titulo": titulo[:200],
                                "categoria": categoria,
                                "precio_tasacion": precio,
                                "fecha": "",
                                "dependencia": "",
                                "convocatoria": "",
                                "url": f"https://rematestributarios.sunat.gob.pe/node/{node_id}",
                            })
            except:
                pass
                
        except Exception as e:
            print(f"[SUNAT] Error scrapeando {categoria}: {e}")
    
    # Deduplicar por ID
    seen_ids = set()
    unique = []
    for item in items:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            unique.append(item)
    
    print(f"[SUNAT] {len(unique)} remates encontrados")
    return unique


# ═══════════════════════════════════════════════════════════════
# FUENTE 2: REMAJU - Remates Judiciales del Poder Judicial
# ═══════════════════════════════════════════════════════════════

def scrape_remaju():
    """Scrapea remaju.pj.gob.pe - homepage con listado de remates activos"""
    items = []
    url = "https://remaju.pj.gob.pe/remaju/"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Los remates están en elementos del carousel/listado
        # Cada item tiene: tipo (REMATE SIMPLE/MÚLTIPLE), distrito, fecha
        # Buscamos todos los textos que matcheen el patrón
        
        text_blocks = soup.find_all(string=re.compile(r'REMATE\s+(SIMPLE|MÚLTIPLE)', re.IGNORECASE))
        
        current_items = []
        for text_block in text_blocks:
            parent = text_block.find_parent()
            if not parent:
                continue
            
            # Navegar al contenedor del item
            container = parent
            for _ in range(5):
                if container.parent:
                    container = container.parent
                    container_text = container.get_text(separator="|", strip=True)
                    if "REMATE" in container_text and len(container_text) > 20:
                        break
            
            container_text = container.get_text(separator="|", strip=True)
            parts = [p.strip() for p in container_text.split("|") if p.strip()]
            
            tipo = ""
            distrito = ""
            fecha = ""
            
            for part in parts:
                if "REMATE" in part.upper():
                    tipo = part.strip()
                elif re.match(r'\d{2}/\d{2}/\d{4}', part):
                    fecha = part.strip()
                elif part not in ["Detalle", "* ÚLTIMO DÍA DE INSCRIPCIÓN"] and len(part) > 2:
                    if not distrito:  # Primer texto no-tipo es el distrito
                        distrito = part.strip()
            
            if distrito and fecha:
                item_id = f"remaju_{distrito}_{fecha}".lower().replace(" ", "_")
                current_items.append({
                    "id": item_id,
                    "fuente": "REMAJU",
                    "titulo": f"{tipo} - {distrito}",
                    "categoria": "inmuebles",  # REMAJU es principalmente inmuebles
                    "precio_tasacion": 0,  # No disponible en listado
                    "fecha": fecha,
                    "dependencia": distrito,
                    "convocatoria": "",
                    "url": "https://remaju.pj.gob.pe/remaju/",
                })
        
        # Deduplicar
        seen_ids = set()
        for item in current_items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                items.append(item)
        
    except Exception as e:
        print(f"[REMAJU] Error: {e}")
    
    print(f"[REMAJU] {len(items)} remates encontrados")
    return items


# ═══════════════════════════════════════════════════════════════
# FUENTE 3: PRONABI - Bienes incautados (check periódico)
# ═══════════════════════════════════════════════════════════════

def scrape_pronabi():
    """Revisa si hay subastas nuevas de PRONABI en gob.pe"""
    items = []
    url = "https://www.gob.pe/busquedas?term=subasta+pronabi&institucion=minjus&tipo_norma=&sheet=1"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Buscar resultados de búsqueda
        results = soup.select("li.search-result, div.search-result, a[href*='pronabi']")
        
        for result in results[:10]:
            link = result if result.name == "a" else result.select_one("a")
            if not link:
                continue
            
            href = link.get("href", "")
            titulo = link.get_text(strip=True)
            
            if "subasta" in titulo.lower() or "remate" in titulo.lower():
                item_id = f"pronabi_{href.split('/')[-1]}" if "/" in href else f"pronabi_{hash(titulo)}"
                items.append({
                    "id": item_id,
                    "fuente": "PRONABI",
                    "titulo": titulo[:200],
                    "categoria": "varios",
                    "precio_tasacion": 0,
                    "fecha": "",
                    "dependencia": "Nacional",
                    "convocatoria": "",
                    "url": f"https://www.gob.pe{href}" if href.startswith("/") else href,
                })
        
    except Exception as e:
        print(f"[PRONABI] Error: {e}")
    
    print(f"[PRONABI] {len(items)} resultados encontrados")
    return items


# ═══════════════════════════════════════════════════════════════
# FILTROS Y NOTIFICACIÓN
# ═══════════════════════════════════════════════════════════════

def aplicar_filtros(items):
    """Filtra items según configuración"""
    filtered = []
    
    for item in items:
        # Filtro de zona
        zona_match = False
        item_text = f"{item['titulo']} {item['dependencia']}".lower()
        
        for zona in FILTROS["zonas_interes"]:
            if zona.lower() in item_text:
                zona_match = True
                break
        
        # Si no matchea ninguna zona, skip (a menos que sea PRONABI que es nacional)
        if not zona_match and item["fuente"] != "PRONABI":
            continue
        
        # Filtro de precio
        if item["precio_tasacion"] > 0 and item["precio_tasacion"] > FILTROS["precio_max"]:
            continue
        
        # Filtro de convocatoria
        if FILTROS["solo_tercera_convocatoria"] and item["convocatoria"] and item["convocatoria"] != "3ra":
            continue
        
        filtered.append(item)
    
    return filtered


def format_alert(item):
    """Formatea un item para mensaje de Telegram"""
    emoji = {
        "SUNAT": "🏛️",
        "REMAJU": "⚖️",
        "PRONABI": "🔒",
    }
    
    convocatoria_emoji = ""
    if item["convocatoria"] == "3ra":
        convocatoria_emoji = " 🔥 3RA CONVOCATORIA"
    elif item["convocatoria"] == "2da":
        convocatoria_emoji = " ⚡ 2da conv."
    
    precio_str = f"S/ {item['precio_tasacion']:,.2f}" if item["precio_tasacion"] > 0 else "Ver detalle"
    
    msg = f"""{emoji.get(item['fuente'], '📋')} *{item['fuente']}*{convocatoria_emoji}

📍 {item['dependencia']}
📝 {item['titulo'][:150]}
💰 Tasación: {precio_str}
📅 Fecha: {item['fecha'] or 'Ver enlace'}
🔗 {item['url']}"""
    
    return msg


def main():
    print(f"\n{'='*50}")
    print(f"🔍 RADAR REMATES - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")
    
    seen = load_seen()
    all_new = []
    
    # Scrapear todas las fuentes
    sunat_items = scrape_sunat()
    remaju_items = scrape_remaju()
    pronabi_items = scrape_pronabi()
    
    all_items = sunat_items + remaju_items + pronabi_items
    
    # Aplicar filtros
    filtered = aplicar_filtros(all_items)
    print(f"\n[FILTROS] {len(filtered)} items pasan los filtros de {len(all_items)} totales")
    
    # Detectar nuevos
    all_seen_ids = set(seen["sunat"] + seen["remaju"] + seen["pronabi"])
    
    for item in filtered:
        if item["id"] not in all_seen_ids:
            all_new.append(item)
    
    print(f"[NUEVOS] {len(all_new)} remates nuevos detectados")
    
    # Notificar
    if all_new:
        # Header
        header = f"🚨 *RADAR REMATES* — {len(all_new)} nuevo(s)\n_{datetime.now().strftime('%d/%m/%Y %H:%M')}_\n"
        send_telegram(header)
        
        # Cada item
        for item in all_new[:15]:  # Máx 15 notificaciones por corrida
            msg = format_alert(item)
            send_telegram(msg)
            
            # Guardar como visto
            source_key = item["fuente"].lower()
            if source_key == "remaju":
                seen["remaju"].append(item["id"])
            elif source_key == "pronabi":
                seen["pronabi"].append(item["id"])
            else:
                seen["sunat"].append(item["id"])
        
        if len(all_new) > 15:
            send_telegram(f"⚠️ _+{len(all_new) - 15} remates más no mostrados_")
    else:
        print("[INFO] Sin remates nuevos. Todo tranquilo.")
    
    # Limpiar seen viejo (mantener solo últimos 500 por fuente)
    for key in seen:
        if len(seen[key]) > 500:
            seen[key] = seen[key][-500:]
    
    save_seen(seen)
    
    # Guardar TODOS los remates filtrados para el dashboard
    dashboard_data = {
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(filtered),
        "nuevos": len(all_new),
        "remates": filtered,
    }
    os.makedirs("data", exist_ok=True)
    with open(REMATES_FILE, "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Listo. {len(filtered)} remates en dashboard, estado guardado.")


if __name__ == "__main__":
    main()
