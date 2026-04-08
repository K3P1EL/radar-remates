# 🔍 Radar Remates

Bot personal que scrapea remates y subastas del Estado peruano cada 3 horas y te avisa por Telegram cuando hay algo nuevo en tu zona.

## Fuentes

| Fuente | URL | Qué scrapea |
|--------|-----|-------------|
| **SUNAT** | rematestributarios.sunat.gob.pe | Bienes embargados por deudas tributarias |
| **REMAJU** | remaju.pj.gob.pe | Remates judiciales del Poder Judicial |
| **PRONABI** | gob.pe/pronabi | Bienes incautados por delitos contra el Estado |

## Setup (5 minutos)

### 1. Crear bot de Telegram

1. Abre Telegram y busca `@BotFather`
2. Envía `/newbot`
3. Ponle nombre: `Radar Remates` (o lo que quieras)
4. Copia el **token** que te da (tipo `123456:ABCdefGhI...`)
5. Abre tu bot y envíale cualquier mensaje (para activar el chat)
6. Ve a `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
7. Busca el `"chat":{"id":` — ese número es tu **CHAT_ID**

### 2. Configurar el repo

1. Fork o sube este repo a tu GitHub
2. Ve a **Settings > Secrets and variables > Actions**
3. Agrega estos 2 secrets:
   - `TELEGRAM_BOT_TOKEN` → el token del paso 1
   - `TELEGRAM_CHAT_ID` → el chat_id del paso 1

### 3. Listo

El bot corre automáticamente cada 3 horas (7am-11pm hora Perú).

Para probarlo manualmente: **Actions > Radar Remates > Run workflow**

## Personalizar filtros

Edita las primeras líneas de `scraper.py`:

```python
FILTROS = {
    "zonas_interes": ["lima", "san isidro", "miraflores", ...],
    "categorias": ["inmuebles", "vehiculos"],
    "precio_max": 500000,           # S/ máximo
    "solo_tercera_convocatoria": False,  # True = solo chollos sin precio base
}
```

## Costo

**S/ 0.** GitHub Actions da 2,000 minutos gratis/mes. Este bot usa ~2 min por corrida × 6 corridas/día × 30 días = ~360 min/mes.
