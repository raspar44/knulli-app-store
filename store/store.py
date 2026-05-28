#!/usr/bin/env python3
"""Tienda de Apps Knulli - catalogo e instalador de las apps del paquete
PORTABLE KNULLI APPS. Lee un manifiesto apps.json publicado en GitHub,
muestra las apps disponibles con su estado (instalada / actualizable /
disponible) y permite instalar, actualizar y desinstalar cada una.

Las apps se descargan como .zip desde los Releases del repo y se
extraen en /userdata/roms/tools/. Tras instalar, la entrada del juego
se anade a gamelist.xml para que aparezca en el carrusel Tools.

NO incluye API keys ni datos personales: cada app que necesite claves
(Ticker, Shazam de Radio) trae un api_keys.example.json que el usuario
rellena.

Controles:
  D-pad    navegar
  B        instalar / actualizar la app seleccionada
  X        desinstalar
  Y        ver descripcion completa
  START    refrescar catalogo
  A        salir (A x2 / pop-up)
  MENU+START salir a EmulationStation
"""
from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import pygame

# ---------------------------------------------------------------------------
# Plataforma + rutas
# ---------------------------------------------------------------------------
ON_HANDHELD = Path("/userdata").is_dir()
IS_WINDOWS = sys.platform.startswith("win")

if ON_HANDHELD:
    USERDATA = Path("/userdata")
    DATA_DIR = Path("/userdata/system/appstore")
    TMP_DIR = Path("/tmp")
else:
    USERDATA = Path.home() / ".local" / "share" / "knulli-userdata"
    DATA_DIR = Path.home() / ".local" / "share" / "knulli-appstore"
    TMP_DIR = Path(os.environ.get("TEMP", "/tmp"))
TOOLS_DIR = USERDATA / "roms" / "tools"
IMAGES_DIR = TOOLS_DIR / "images"
GAMELIST = TOOLS_DIR / "gamelist.xml"
DATA_DIR.mkdir(parents=True, exist_ok=True)
THUMBS_DIR = DATA_DIR / "thumbs"
THUMBS_DIR.mkdir(parents=True, exist_ok=True)
INSTALLED_FILE = DATA_DIR / "installed.json"
LOG_FILE = TMP_DIR / "appstore.log"

# ---------------------------------------------------------------------------
# Repo de la tienda (raspar44/knulli-app-store)
# ---------------------------------------------------------------------------
GH_USER = "raspar44"
GH_REPO = "knulli-app-store"
RAW_BASE = f"https://raw.githubusercontent.com/{GH_USER}/{GH_REPO}/main"
MANIFEST_URL = f"{RAW_BASE}/apps.json"
ICON_BASE = f"{RAW_BASE}/icons"

SCREEN_W, SCREEN_H = 640, 480
FPS = 30
USER_AGENT = "knulli-appstore/1.0"

# Paleta VAPIS
V_BG          = (12, 14, 22)
V_CARD        = (24, 28, 40)
V_CARD_ACTIVE = (38, 46, 66)
V_TEXT        = (235, 238, 245)
V_TEXT_DIM    = (150, 158, 175)
V_ACCENT      = (255, 165, 80)
V_VIOLET      = (180, 130, 255)
V_GOLD        = (240, 200, 80)
V_GREEN       = (90, 220, 130)
V_DANGER      = (240, 90, 90)
V_CYAN        = (90, 200, 240)
V_DIVIDER     = (60, 70, 90)
BLACK         = (0, 0, 0)
WHITE         = (255, 255, 255)

# Botones RG40XX-H
BTN_OK     = {4}
BTN_BACK   = {3, 0}
BTN_Y      = {5}
BTN_X      = {6}
BTN_L1     = {7}
BTN_R1     = {8}
BTN_SELECT = {9}
BTN_START  = {10}
BTN_MENU   = {11}
EXIT_COMBO = {10, 11}
KEY_OK    = (pygame.K_RETURN, pygame.K_SPACE)
KEY_BACK  = (pygame.K_ESCAPE, pygame.K_BACKSPACE)


def dbg(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_get(url, timeout=20):
    """GET con urllib; devuelve bytes o None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=_ssl_ctx()) as r:
            return r.read()
    except Exception as e:
        dbg(f"http_get {url}: {e}")
        return None


def download_to(url, dest, progress_cb=None, timeout=60):
    """Descarga url a dest mostrando progreso. Devuelve True si OK."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=_ssl_ctx()) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            tmp = str(dest) + ".part"
            with open(tmp, "wb") as f:
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total)
            os.replace(tmp, dest)
        return True
    except Exception as e:
        dbg(f"download {url}: {e}")
        return False


# ---------------------------------------------------------------------------
# Estado de instalacion (que apps + version tenemos)
# ---------------------------------------------------------------------------
def load_installed():
    try:
        with open(INSTALLED_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_installed(d):
    try:
        with open(INSTALLED_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except OSError as e:
        dbg(f"save_installed: {e}")


# ---------------------------------------------------------------------------
# Gamelist: anadir / quitar la entrada <game> de una app
# ---------------------------------------------------------------------------
def _gamelist_text():
    try:
        return GAMELIST.read_text(encoding="utf-8")
    except OSError:
        return '<?xml version="1.0"?>\n<gameList>\n</gameList>\n'


def gamelist_add(entry):
    """Inserta/reemplaza un <game> en gamelist.xml. entry es un dict con
    path, name, desc, image, marquee, genre."""
    import re
    txt = _gamelist_text()
    path = entry.get("path", "")
    # Quitar entrada previa con el mismo path
    txt = re.sub(
        r"\s*<game>(?:(?!</game>).)*?<path>" + re.escape(path)
        + r"</path>.*?</game>", "", txt, flags=re.DOTALL)
    block = (
        "\t<game>\n"
        f"\t\t<path>{entry.get('path','')}</path>\n"
        f"\t\t<name>{_xml_escape(entry.get('name',''))}</name>\n"
        f"\t\t<desc>{_xml_escape(entry.get('desc',''))}</desc>\n"
        f"\t\t<image>{entry.get('image','')}</image>\n"
        f"\t\t<marquee>{entry.get('marquee','')}</marquee>\n"
        f"\t\t<thumbnail>{entry.get('image','')}</thumbnail>\n"
        "\t\t<developer>YSG</developer>\n"
        f"\t\t<genre>{_xml_escape(entry.get('genre','Utility'))}</genre>\n"
        "\t\t<lang>es</lang>\n"
        "\t\t<releasedate>19700101T010000</releasedate>\n"
        "\t</game>\n"
    )
    if "</gameList>" in txt:
        txt = txt.replace("</gameList>", block + "</gameList>")
    else:
        txt = txt.rstrip() + "\n" + block
    try:
        GAMELIST.parent.mkdir(parents=True, exist_ok=True)
        GAMELIST.write_text(txt, encoding="utf-8")
    except OSError as e:
        dbg(f"gamelist_add: {e}")


def gamelist_remove(path):
    import re
    txt = _gamelist_text()
    txt = re.sub(
        r"\s*<game>(?:(?!</game>).)*?<path>" + re.escape(path)
        + r"</path>.*?</game>", "", txt, flags=re.DOTALL)
    try:
        GAMELIST.write_text(txt, encoding="utf-8")
    except OSError as e:
        dbg(f"gamelist_remove: {e}")


def _xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# Instalacion / desinstalacion de una app
# ---------------------------------------------------------------------------
def install_app(app, installed, progress_cb=None, status_cb=None):
    """Descarga el zip de la app y lo extrae en TOOLS_DIR. Registra los
    archivos extraidos para poder desinstalar. Devuelve True si OK."""
    appid = app["id"]
    url = app["url"]
    zip_path = TMP_DIR / f"appstore_{appid}.zip"
    if status_cb:
        status_cb(f"Descargando {app['name']}...")
    if not download_to(url, zip_path, progress_cb=progress_cb):
        if status_cb:
            status_cb("Error de descarga")
        return False
    if status_cb:
        status_cb("Instalando...")
    extracted = []
    try:
        USERDATA.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            for member in z.namelist():
                if member.endswith("/"):
                    continue
                # Los zips estan organizados relativos a /userdata/, p.ej.
                # roms/tools/radio.py, system/torrent/aria2c. Seguridad:
                # nada de rutas absolutas ni '..'.
                safe = member.replace("\\", "/").lstrip("/")
                if ".." in safe.split("/"):
                    continue
                dest = USERDATA / safe
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                extracted.append(safe)
                # .sh y binarios ejecutables
                if (safe.endswith(".sh") or "/aria2c" in safe
                        or "/yt-dlp" in safe) and not IS_WINDOWS:
                    try:
                        os.chmod(dest, 0o755)
                    except OSError:
                        pass
    except Exception as e:
        dbg(f"install_app {appid}: {e}")
        if status_cb:
            status_cb("Error al extraer")
        return False
    finally:
        try:
            zip_path.unlink()
        except OSError:
            pass
    # gamelist
    gl = app.get("gamelist")
    if gl:
        gamelist_add(gl)
    # registrar
    installed[appid] = {
        "version": app.get("version", "1.0"),
        "files": extracted,
        "gamelist_path": (gl or {}).get("path", ""),
        "ts": int(time.time()),
    }
    save_installed(installed)
    if status_cb:
        status_cb(f"{app['name']} instalada")
    return True


def uninstall_app(app, installed, status_cb=None):
    appid = app["id"]
    rec = installed.get(appid)
    if not rec:
        return False
    # Borrar archivos (excepto los compartidos que otras apps usan:
    # _rgb_joystick.py, _vpn_indicator.py, gamelist.xml).
    SHARED = {"_rgb_joystick.py", "_vpn_indicator.py", "gamelist.xml"}
    for rel in rec.get("files", []):
        base = rel.split("/")[-1]
        if base in SHARED:
            continue
        p = USERDATA / rel
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass
    glp = rec.get("gamelist_path", "")
    if glp:
        gamelist_remove(glp)
    installed.pop(appid, None)
    save_installed(installed)
    if status_cb:
        status_cb(f"{app['name']} desinstalada")
    return True


# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------
def _font(size, bold=True):
    paths = [
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return pygame.font.Font(p, size)
    return pygame.font.Font(None, size)


# ---------------------------------------------------------------------------
# App principal
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        pygame.init()
        pygame.joystick.init()
        flags = pygame.FULLSCREEN if ON_HANDHELD else 0
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        pygame.display.set_caption("Tienda Knulli")
        pygame.mouse.set_visible(False)
        self.clock = pygame.time.Clock()
        self.joys = []
        for i in range(pygame.joystick.get_count()):
            j = pygame.joystick.Joystick(i)
            j.init()
            self.joys.append(j)
        self.f_title = _font(30)
        self.f_h = _font(22)
        self.f_item = _font(19)
        self.f_small = _font(15, bold=False)
        self.f_tiny = _font(12, bold=False)

        self.running = True
        self.state = "splash"
        self.splash_until = time.time() + 1.5
        self.apps = []
        self.installed = load_installed()
        self.sel = 0
        self.scroll = 0
        self.loading = True
        self.load_error = ""
        self.status_msg = ""
        self.status_until = 0.0
        self.busy = False           # instalando/desinstalando
        self.busy_label = ""
        self.busy_pct = 0
        self.exit_yes = False
        self.detail_app = None      # app cuyo desc completo se muestra
        self.pressed = set()
        self._thumb_cache = {}      # id -> Surface | None
        self.btn_log = []           # test de botones (SELECT)
        self._btn_start_hold = 0.0
        # Cargar catalogo en background
        threading.Thread(target=self._load_manifest, daemon=True).start()

    # ----- carga del catalogo -----
    def _load_manifest(self):
        self.loading = True
        self.load_error = ""
        data = http_get(MANIFEST_URL)
        if not data:
            self.load_error = "Sin conexion o repo no disponible"
            self.loading = False
            return
        try:
            man = json.loads(data.decode("utf-8"))
            self.apps = man.get("apps", [])
        except Exception as e:
            dbg(f"parse manifest: {e}")
            self.load_error = "Manifiesto invalido"
        self.loading = False
        # thumbs en background
        threading.Thread(target=self._fetch_thumbs, daemon=True).start()

    def _fetch_thumbs(self):
        for app in self.apps:
            appid = app["id"]
            dest = THUMBS_DIR / f"{appid}.png"
            if not dest.exists():
                icon = app.get("icon") or f"{ICON_BASE}/{appid}.png"
                download_to(icon, dest, timeout=20)

    def _thumb(self, appid):
        if appid in self._thumb_cache:
            return self._thumb_cache[appid]
        p = THUMBS_DIR / f"{appid}.png"
        surf = None
        if p.exists():
            try:
                img = pygame.image.load(str(p)).convert_alpha()
                surf = pygame.transform.smoothscale(img, (64, 48))
            except Exception:
                surf = None
        self._thumb_cache[appid] = surf
        return surf

    # ----- estado de cada app -----
    def app_status(self, app):
        """'installed' | 'update' | 'available'."""
        appid = app["id"]
        rec = self.installed.get(appid)
        launcher = app.get("launcher", "")
        on_disk = bool(launcher) and (TOOLS_DIR / launcher).exists()
        if rec or on_disk:
            inst_ver = (rec or {}).get("version", "?")
            if rec and inst_ver != app.get("version", "1.0"):
                return "update"
            return "installed"
        return "available"

    def set_status(self, msg, dur=2.5):
        self.status_msg = msg
        self.status_until = time.time() + dur

    # ----- acciones -----
    def _do_install(self, app):
        self.busy = True
        self.busy_label = f"Instalando {app['name']}"
        self.busy_pct = 0

        def prog(done, total):
            self.busy_pct = int(done * 100 / total) if total else 0

        def status(msg):
            self.busy_label = msg

        def worker():
            ok = install_app(app, self.installed, progress_cb=prog,
                             status_cb=status)
            self.busy = False
            self.set_status(
                f"{app['name']} instalada" if ok else "Fallo la instalacion",
                2.5)
            self._thumb_cache.pop(app["id"], None)
        threading.Thread(target=worker, daemon=True).start()

    def _do_uninstall(self, app):
        self.busy = True
        self.busy_label = f"Desinstalando {app['name']}"
        self.busy_pct = 100

        def worker():
            ok = uninstall_app(app, self.installed)
            self.busy = False
            self.set_status(
                f"{app['name']} desinstalada" if ok else "Fallo",
                2.5)
        threading.Thread(target=worker, daemon=True).start()

    def _btn_log(self, msg):
        self.btn_log.append(msg)
        if len(self.btn_log) > 40:
            self.btn_log = self.btn_log[-40:]
        dbg("BTNTEST " + msg)

    # ----- input -----
    def handle_events(self):
        for ev in pygame.event.get():
            # Modo test de botones: captura TODO evento crudo y lo muestra.
            # Util cuando algun boton "no responde" para ver su codigo real.
            if self.state == "buttons":
                if ev.type == pygame.JOYBUTTONDOWN:
                    self._btn_log(f"JOYBUTTONDOWN  button={ev.button}")
                elif ev.type == pygame.JOYBUTTONUP:
                    self._btn_log(f"JOYBUTTONUP    button={ev.button}")
                elif ev.type == pygame.JOYHATMOTION:
                    self._btn_log(f"JOYHATMOTION   value={ev.value}")
                elif ev.type == pygame.JOYAXISMOTION:
                    if abs(ev.value) > 0.5:
                        self._btn_log(
                            f"JOYAXISMOTION  axis={ev.axis} val={ev.value:+.2f}")
                elif ev.type == pygame.KEYDOWN:
                    self._btn_log(
                        f"KEYDOWN        key={ev.key} ({pygame.key.name(ev.key)})")
                # Salir del test: mantener START 2s, o Esc en PC
                if ev.type == pygame.JOYBUTTONDOWN and ev.button in BTN_START:
                    self._btn_start_hold = time.time()
                if ev.type == pygame.JOYBUTTONUP and ev.button in BTN_START:
                    held = time.time() - getattr(self, "_btn_start_hold", 0.0)
                    if held >= 2.0:
                        self.state = "list"
                        self._btn_start_hold = 0.0
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    self.state = "list"
                continue
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.JOYBUTTONDOWN:
                self.pressed.add(ev.button)
                if EXIT_COMBO.issubset(self.pressed):
                    self.running = False
                    return
                self._button(ev.button)
            elif ev.type == pygame.JOYBUTTONUP:
                self.pressed.discard(ev.button)
            elif ev.type == pygame.JOYHATMOTION:
                x, y = ev.value
                if y == 1:
                    self._nav(-1)
                elif y == -1:
                    self._nav(1)
                if x == -1:
                    self._action("left")
                elif x == 1:
                    self._action("right")
            elif ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_UP,):
                    self._nav(-1)
                elif ev.key in (pygame.K_DOWN,):
                    self._nav(1)
                elif ev.key in (pygame.K_LEFT,):
                    self._action("left")
                elif ev.key in (pygame.K_RIGHT,):
                    self._action("right")
                elif ev.key in KEY_OK:
                    self._action("ok")
                elif ev.key in KEY_BACK:
                    self._action("back")
                elif ev.key == pygame.K_x:
                    self._action("x")
                elif ev.key == pygame.K_y:
                    self._action("y")
                elif ev.key == pygame.K_s:
                    self._action("select")
                elif ev.key == pygame.K_F5:
                    self._action("start")

    def _button(self, b):
        if b in BTN_OK:
            self._action("ok")
        elif b in BTN_BACK:
            self._action("back")
        elif b in BTN_X:
            self._action("x")
        elif b in BTN_Y:
            self._action("y")
        elif b in BTN_START:
            self._action("start")
        elif b in BTN_SELECT:
            self._action("select")

    def _nav(self, delta):
        if self.busy or self.state != "list" or not self.apps:
            return
        self.sel = (self.sel + delta) % len(self.apps)

    def _action(self, a):
        if self.state == "splash":
            self.state = "list"
            return
        if self.busy:
            return
        if self.state == "detail":
            if a in ("back", "ok", "y"):
                self.state = "list"
            return
        if self.state == "exit_confirm":
            if a in ("left", "right"):
                self.exit_yes = not self.exit_yes
            elif a == "ok":
                if self.exit_yes:
                    self.running = False
                else:
                    self.state = "list"
            elif a == "back":
                self.state = "list"
            return
        # estado list
        if a == "select":
            self.btn_log = []
            self._btn_start_hold = 0.0
            self.state = "buttons"
        elif a == "back":
            self.exit_yes = False
            self.state = "exit_confirm"
        elif a == "start":
            self.loading = True
            threading.Thread(target=self._load_manifest, daemon=True).start()
            self.set_status("Refrescando catalogo...", 1.5)
        elif not self.apps:
            return
        elif a == "ok":
            app = self.apps[self.sel]
            st = self.app_status(app)
            if st == "installed":
                self.set_status("Ya instalada (B reinstala)", 1.5)
                self._do_install(app)
            else:
                self._do_install(app)
        elif a == "x":
            app = self.apps[self.sel]
            if self.app_status(app) != "available":
                self._do_uninstall(app)
            else:
                self.set_status("No esta instalada", 1.5)
        elif a == "y":
            self.detail_app = self.apps[self.sel]
            self.state = "detail"

    # ----- render -----
    def draw(self):
        self.screen.fill(V_BG)
        if self.state == "splash":
            self._draw_splash()
        elif self.state == "buttons":
            self._draw_buttons()
        elif self.state == "detail":
            self._draw_list()
            self._draw_detail()
        elif self.state == "exit_confirm":
            self._draw_list()
            self._draw_exit()
        else:
            self._draw_list()
        if self.busy:
            self._draw_busy()
        self._draw_toast()
        pygame.display.flip()

    def _draw_buttons(self):
        self._header("TEST DE BOTONES")
        s = self.f_small.render(
            "Pulsa cualquier boton. Veras su codigo real aqui.",
            True, V_TEXT_DIM)
        self.screen.blit(s, (16, 60))
        ref = self.f_tiny.render(
            "Esperado RG40XX-H: B=4 A=3 X=6 Y=5 L1=7 R1=8 "
            "SELECT=9 START=10 MENU=11", True, V_CYAN)
        self.screen.blit(ref, (16, 86))
        # ultimas pulsaciones
        y = 116
        for line in self.btn_log[-14:]:
            ls = self.f_item.render(line, True, V_TEXT)
            self.screen.blit(ls, (20, y))
            y += 24
        if not self.btn_log:
            ws = self.f_item.render("(esperando pulsaciones...)", True,
                                    V_TEXT_DIM)
            self.screen.blit(ws, (20, 120))
        self._footer("Manten START 2s para salir  (Esc en PC)")

    def _header(self, title, subtitle=""):
        pygame.draw.rect(self.screen, V_CARD, (0, 0, SCREEN_W, 50))
        pygame.draw.line(self.screen, V_ACCENT, (0, 50), (SCREEN_W, 50), 2)
        t = self.f_h.render(title, True, V_ACCENT)
        self.screen.blit(t, (16, 14))
        if subtitle:
            s = self.f_small.render(subtitle, True, V_TEXT_DIM)
            self.screen.blit(s, (SCREEN_W - s.get_width() - 16, 20))

    def _footer(self, hint):
        h = self.f_tiny.render(hint, True, V_TEXT_DIM)
        self.screen.blit(h, ((SCREEN_W - h.get_width()) // 2,
                             SCREEN_H - h.get_height() - 5))

    def _draw_splash(self):
        self.screen.fill(BLACK)
        t = self.f_title.render("Tienda Knulli", True, V_ACCENT)
        self.screen.blit(t, ((SCREEN_W - t.get_width()) // 2,
                             SCREEN_H // 2 - 40))
        s = self.f_small.render("Apps de PORTABLE KNULLI APPS", True, V_TEXT_DIM)
        self.screen.blit(s, ((SCREEN_W - s.get_width()) // 2,
                             SCREEN_H // 2 + 6))
        c = self.f_tiny.render("@ YSG 2026 @", True, V_VIOLET)
        self.screen.blit(c, ((SCREEN_W - c.get_width()) // 2,
                             SCREEN_H - 30))

    def _draw_list(self):
        n_inst = sum(1 for a in self.apps
                     if self.app_status(a) != "available")
        self._header("TIENDA KNULLI",
                     f"{n_inst}/{len(self.apps)} instaladas" if self.apps else "")
        if self.loading:
            ts = self.f_item.render("Cargando catalogo...", True, V_ACCENT)
            self.screen.blit(ts, ((SCREEN_W - ts.get_width()) // 2, 210))
            self._footer("Conectando con GitHub...")
            return
        if self.load_error:
            ts = self.f_item.render(self.load_error, True, V_DANGER)
            self.screen.blit(ts, ((SCREEN_W - ts.get_width()) // 2, 200))
            h = self.f_small.render("START para reintentar", True, V_TEXT_DIM)
            self.screen.blit(h, ((SCREEN_W - h.get_width()) // 2, 230))
            self._footer("Necesita internet (WiFi de casa)")
            return
        if not self.apps:
            ts = self.f_item.render("Catalogo vacio", True, V_TEXT_DIM)
            self.screen.blit(ts, ((SCREEN_W - ts.get_width()) // 2, 210))
            return
        # lista
        y_top, y_bot = 58, SCREEN_H - 28
        item_h = 56
        gap = 4
        per = item_h + gap
        visible = max(1, (y_bot - y_top) // per)
        self.scroll = max(0, min(self.sel - visible + 1, len(self.apps) - visible))
        self.scroll = max(0, self.scroll)
        for vis in range(visible):
            idx = self.scroll + vis
            if idx >= len(self.apps):
                break
            app = self.apps[idx]
            y = y_top + vis * per
            r = pygame.Rect(10, y, SCREEN_W - 20, item_h)
            active = (idx == self.sel)
            pygame.draw.rect(self.screen,
                             V_CARD_ACTIVE if active else V_CARD,
                             r, border_radius=8)
            if active:
                pygame.draw.rect(self.screen, V_ACCENT, r, width=1,
                                 border_radius=8)
            # thumb
            th = self._thumb(app["id"])
            tx = r.x + 8
            if th:
                self.screen.blit(th, (tx, r.y + 4))
            else:
                pygame.draw.rect(self.screen, V_BG,
                                 (tx, r.y + 4, 64, 48), border_radius=4)
            text_x = tx + 74
            # nombre
            nm = self.f_item.render(app.get("name", app["id"])[:34], True,
                                    V_TEXT if active else V_TEXT_DIM)
            self.screen.blit(nm, (text_x, r.y + 6))
            # desc corta
            desc = app.get("desc", "")
            ds = self.f_tiny.render(desc[:52], True, V_TEXT_DIM)
            self.screen.blit(ds, (text_x, r.y + 30))
            # badge estado
            st = self.app_status(app)
            if st == "installed":
                badge, col = "INSTALADA", V_GREEN
            elif st == "update":
                badge, col = "ACTUALIZAR", V_GOLD
            else:
                badge, col = "INSTALAR", V_CYAN
            bs = self.f_tiny.render(badge, True, col)
            self.screen.blit(bs, (r.right - bs.get_width() - 12, r.y + 8))
            # version
            vs = self.f_tiny.render("v" + str(app.get("version", "1.0")),
                                    True, V_TEXT_DIM)
            self.screen.blit(vs, (r.right - vs.get_width() - 12, r.y + 32))
        # scrollbar
        if len(self.apps) > visible:
            bar_h = int((y_bot - y_top) * visible / len(self.apps))
            bar_y = y_top + int((y_bot - y_top) * self.scroll / len(self.apps))
            pygame.draw.rect(self.screen, V_DIVIDER,
                             (SCREEN_W - 6, y_top, 3, y_bot - y_top))
            pygame.draw.rect(self.screen, V_ACCENT,
                             (SCREEN_W - 6, bar_y, 3, bar_h))
        self._footer("B instalar  X desinstalar  Y info  START refrescar  "
                     "SELECT test botones  A salir")

    def _draw_detail(self):
        app = self.detail_app or {}
        ov = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        self.screen.blit(ov, (0, 0))
        box = pygame.Rect(30, 50, SCREEN_W - 60, SCREEN_H - 100)
        pygame.draw.rect(self.screen, V_CARD, box, border_radius=12)
        pygame.draw.rect(self.screen, V_ACCENT, box, width=2, border_radius=12)
        nm = self.f_h.render(app.get("name", "")[:30], True, V_ACCENT)
        self.screen.blit(nm, (box.x + 16, box.y + 14))
        meta = self.f_tiny.render(
            f"v{app.get('version','1.0')}  ·  {app.get('size_mb','?')} MB  ·  "
            f"{app.get('genre','Utility')}", True, V_TEXT_DIM)
        self.screen.blit(meta, (box.x + 16, box.y + 44))
        # desc con wrap
        desc = app.get("desc_long") or app.get("desc", "")
        y = box.y + 72
        for line in self._wrap(desc, self.f_small, box.w - 32)[:10]:
            s = self.f_small.render(line, True, V_TEXT)
            self.screen.blit(s, (box.x + 16, y))
            y += s.get_height() + 3
        self._footer("A / B volver")

    def _draw_exit(self):
        ov = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        self.screen.blit(ov, (0, 0))
        bw, bh = 360, 150
        box = pygame.Rect((SCREEN_W - bw) // 2, (SCREEN_H - bh) // 2, bw, bh)
        pygame.draw.rect(self.screen, V_CARD, box, border_radius=10)
        pygame.draw.rect(self.screen, V_ACCENT, box, width=2, border_radius=10)
        t = self.f_h.render("¿Salir de la Tienda?", True, V_ACCENT)
        self.screen.blit(t, (box.x + (bw - t.get_width()) // 2, box.y + 22))
        bw2, bh2 = 120, 42
        gap = 20
        total = bw2 * 2 + gap
        bx = box.x + (bw - total) // 2
        by = box.y + 84
        for i, (lbl, val) in enumerate([("SI", True), ("NO", False)]):
            r = pygame.Rect(bx + i * (bw2 + gap), by, bw2, bh2)
            act = (self.exit_yes == val)
            pygame.draw.rect(self.screen, V_ACCENT if act else V_CARD_ACTIVE,
                             r, border_radius=8)
            ts = self.f_h.render(lbl, True, BLACK if act else V_TEXT)
            self.screen.blit(ts, (r.x + (r.w - ts.get_width()) // 2,
                                  r.y + (r.h - ts.get_height()) // 2))
        self._footer("◀/▶ elegir   B confirmar   A cancelar")

    def _draw_busy(self):
        ov = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 200))
        self.screen.blit(ov, (0, 0))
        t = self.f_h.render(self.busy_label[:40], True, V_ACCENT)
        self.screen.blit(t, ((SCREEN_W - t.get_width()) // 2, 200))
        bx, by, bw, bh = 80, 250, SCREEN_W - 160, 22
        pygame.draw.rect(self.screen, V_CARD, (bx, by, bw, bh),
                         border_radius=11)
        fill = int(bw * self.busy_pct / 100)
        if fill > 0:
            pygame.draw.rect(self.screen, V_ACCENT, (bx, by, fill, bh),
                             border_radius=11)
        ps = self.f_small.render(f"{self.busy_pct}%", True, V_TEXT)
        self.screen.blit(ps, ((SCREEN_W - ps.get_width()) // 2, by + 30))

    def _draw_toast(self):
        if self.status_msg and time.time() < self.status_until:
            ts = self.f_small.render(self.status_msg, True, V_TEXT)
            pad = 10
            w = ts.get_width() + pad * 2
            h = ts.get_height() + pad
            x = (SCREEN_W - w) // 2
            yy = SCREEN_H - h - 26
            pygame.draw.rect(self.screen, V_CARD_ACTIVE, (x, yy, w, h),
                             border_radius=6)
            pygame.draw.rect(self.screen, V_ACCENT, (x, yy, w, h), width=1,
                             border_radius=6)
            self.screen.blit(ts, (x + pad, yy + pad // 2))

    def _wrap(self, text, font, max_w):
        words = (text or "").split()
        lines, cur = [], ""
        for w in words:
            cand = (cur + " " + w).strip()
            if font.size(cand)[0] <= max_w:
                cur = cand
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def run(self):
        try:
            while self.running:
                self.handle_events()
                if self.state == "splash" and time.time() > self.splash_until:
                    self.state = "list"
                self.draw()
                self.clock.tick(FPS)
        finally:
            pygame.quit()


def main():
    try:
        Store().run()
    except Exception:
        import traceback
        dbg("EXC main:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
