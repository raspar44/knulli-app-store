# Tienda Knulli — PORTABLE KNULLI APPS

Catálogo e instalador de apps para consolas **Knulli / Batocera**
(probado en Anbernic RG40XX-H). Una app pygame que lista las apps del
paquete *PORTABLE KNULLI APPS*, las descarga desde los Releases de este
repo y las instala en `/userdata/roms/tools/`.

Hecho por **YSG** · `@ YSG 2026 @`

---

## Apps incluidas

| App | Qué hace |
|-----|----------|
| Radio Internet | Emisoras online + reconocimiento de canciones |
| YouTube | Buscar y reproducir/descargar vídeos |
| iVoox | Podcasts en streaming y descarga offline |
| AllPlay (VAPIS) | Reproductor multimedia / explorador |
| Ticker | Cotizaciones bolsa/cripto en tiempo real |
| Reloj | Reloj mundial, alarmas, cuenta atrás |
| Torrent | Cliente torrent (aria2c) |
| ProtonVPN | Cliente OpenVPN |
| RGB Settings | Configura los LEDs RGB del mando |
| Pantalla | Test y diagnóstico del LCD |
| Disco Duro | Info de almacenamiento |
| RAMfaster | Optimización de RAM |
| Tienda | Esta misma app (se auto-actualiza) |

---

## Instalar la Tienda por primera vez

La Tienda necesita estar una vez en la consola; luego instala/actualiza
todo lo demás (incluida ella misma) desde su propia interfaz.

1. Copia `store/store.py` y `store/Tienda.sh` a `/userdata/roms/tools/`
   de tu consola (por SSH, o metiendo la SD en el PC).
2. Reinicia EmulationStation. Aparecerá **Tienda** en el carrusel Tools.
3. Ábrela con la consola conectada a una WiFi **con internet**.
4. Pulsa **B** sobre cualquier app para instalarla.

> Controles: **D-pad** navegar · **B** instalar/actualizar ·
> **X** desinstalar · **Y** info · **START** refrescar · **A** salir.

---

## Claves de API (Ticker y Radio)

Algunas funciones necesitan claves de API GRATUITAS de terceros
(cotizaciones, reconocimiento de canciones). **No se incluyen claves.**
Cada usuario pone las suyas:

1. Copia `api_keys.example.json` a `/userdata/roms/tools/api_keys.json`.
2. Rellena las claves que quieras (todas son gratuitas):
   - Ticker: finnhub, twelvedata, coinmarketcap, alphavantage, fmp,
     polygon, marketstack, tiingo, eodhd
   - Radio (reconocer canciones): acoustid, audd
3. Las apps funcionan sin claves, pero con funciones reducidas.

---

## Estructura del repo

```
apps.json              Manifiesto que lee la Tienda
icons/<id>.png         Miniaturas de cada app
api_keys.example.json  Plantilla de claves (vacía)
store/                 Código fuente de la Tienda
release_assets/        Zips de cada app (se suben al Release, no a git)
```

Los `.zip` de las apps se publican como **assets del Release**
`apps-v1`. La Tienda los descarga de ahí.

---

## Licencia / aviso

Proyecto personal de uso doméstico. Las apps de terceros (aria2c,
yt-dlp, certificados ProtonVPN públicos) conservan sus respectivas
licencias. No se distribuye ninguna credencial ni clave personal.
