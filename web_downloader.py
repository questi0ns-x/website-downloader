#!/usr/bin/env python3
"""
web_downloader.py  —  Netlifes Web Downloader
Descarga completa de un sitio web con interfaz CLI interactiva.

Dependencias:
    pip install requests beautifulsoup4 tqdm colorama
"""

import os
import re
import sys
import time
import mimetypes
import urllib.parse
from pathlib import Path
from collections import deque
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from colorama import Fore, Back, Style, init

init(autoreset=True)

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTES Y DEFAULTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION = "1.0.0"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

FOLDER_MAP = {
    "images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
               ".ico", ".bmp", ".tiff", ".avif"},
    "css":    {".css"},
    "js":     {".js", ".mjs"},
    "fonts":  {".woff", ".woff2", ".ttf", ".eot", ".otf"},
    "videos": {".mp4", ".webm", ".ogg", ".mov", ".avi"},
    "docs":   {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"},
    "html":   {".html", ".htm", ".xhtml"},
}

PRESETS = {
    "1": {"label": "Rápido  — Solo imágenes + HTML",
          "max_pages": 50,  "delay": 0.1, "assets": ["images", "html"]},
    "2": {"label": "Normal  — Web completa (recomendado)",
          "max_pages": 300, "delay": 0.3, "assets": list(FOLDER_MAP.keys())},
    "3": {"label": "Profundo — Sin límite de páginas",
          "max_pages": 0,   "delay": 0.5, "assets": list(FOLDER_MAP.keys())},
    "4": {"label": "Custom  — Configuro yo mismo",
          "max_pages": None, "delay": None, "assets": None},
}

MAX_RETRIES = 3
TIMEOUT     = 15

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS DE UI
# ══════════════════════════════════════════════════════════════════════════════

W  = 62   # ancho del marco

def cls():
    os.system("cls" if os.name == "nt" else "clear")

def line(char="─"):
    print(Fore.CYAN + char * W)

def blank():
    print()

def header():
    cls()
    print(Fore.CYAN + "╔" + "═" * (W - 2) + "╗")
    title = "🌐  NETLIFES  ·  Web Downloader  v" + VERSION
    pad   = (W - 2 - len(title)) // 2
    print(Fore.CYAN + "║" + " " * pad + Fore.WHITE + Style.BRIGHT + title
          + " " * (W - 2 - pad - len(title)) + Fore.CYAN + "║")
    print(Fore.CYAN + "╚" + "═" * (W - 2) + "╝")
    blank()

def section(title: str):
    blank()
    line()
    print(Fore.YELLOW + Style.BRIGHT + f"  {title}")
    line()

def ok(msg):   print(Fore.GREEN  + "  ✔  " + Style.RESET_ALL + msg)
def warn(msg): print(Fore.YELLOW + "  ⚠  " + Style.RESET_ALL + msg)
def err(msg):  print(Fore.RED    + "  ✗  " + Style.RESET_ALL + msg)
def info(msg): print(Fore.CYAN   + "  ›  " + Style.RESET_ALL + msg)

def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        val = input(Fore.WHITE + f"  → {prompt}{hint}: " + Style.RESET_ALL).strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print()
        goodbye()
        sys.exit(0)

def confirm(prompt: str, default: bool = True) -> bool:
    hint = "S/n" if default else "s/N"
    raw  = ask(f"{prompt} ({hint})")
    if not raw:
        return default
    return raw.lower() in ("s", "si", "sí", "y", "yes")

def menu(options: dict) -> str:
    """Muestra un menú numerado y devuelve la clave elegida."""
    for key, label in options.items():
        print(Fore.CYAN + f"    [{key}]" + Style.RESET_ALL + f"  {label}")
    blank()
    keys = list(options.keys())
    while True:
        choice = ask(f"Elige una opción ({'/'.join(keys)})")
        if choice in keys:
            return choice
        warn(f"Opción no válida. Introduce {' o '.join(keys)}.")

def goodbye():
    blank()
    line("═")
    print(Fore.CYAN + "  Hasta luego — Netlifes Web Downloader")
    line("═")
    blank()

def spinner_msg(msg: str):
    print(Fore.CYAN + "  ⟳  " + Style.RESET_ALL + msg, end="\r")

# ══════════════════════════════════════════════════════════════════════════════
#  LÓGICA DE DESCARGA
# ══════════════════════════════════════════════════════════════════════════════

def normalize_url(raw: str) -> str:
    raw = raw.strip().rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw

def same_domain(url: str, base_netloc: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc == base_netloc or parsed.netloc == ""

def resolve_url(base: str, href: str):
    try:
        url    = urllib.parse.urljoin(base, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        return urllib.parse.urlunparse(parsed._replace(fragment=""))
    except Exception:
        return None

def get_extension(url: str, content_type: str = "") -> str:
    path = urllib.parse.urlparse(url).path
    ext  = Path(path).suffix.lower()
    if not ext and content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
    return ext

def dest_folder(ext: str, allowed: list) -> str:
    for folder, exts in FOLDER_MAP.items():
        if ext in exts:
            return folder if folder in allowed else "other"
    return "other"

def safe_filename(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path   = parsed.path.lstrip("/") or "index"
    if path.endswith("/"):
        path += "index.html"
    if parsed.query:
        safe_q = re.sub(r"[^\w\-]", "_", parsed.query)[:40]
        root, ext = os.path.splitext(path)
        path = f"{root}__{safe_q}{ext}"
    path = re.sub(r'[<>:"\\|?*]', "_", path)
    return path

def download_file(session, url, output_dir, allowed_assets, stats):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
            r.raise_for_status()
            content_type = r.headers.get("content-type", "")
            ext          = get_extension(url, content_type)
            folder_name  = dest_folder(ext, allowed_assets)
            rel_path     = safe_filename(url)
            if ext and not rel_path.lower().endswith(ext):
                rel_path += ext
            if folder_name != "html":
                file_path = output_dir / folder_name / Path(rel_path).name
            else:
                file_path = output_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            with open(file_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    size += len(chunk)
            stats["bytes"] += size
            stats["files"] += 1
            return file_path
        except requests.RequestException:
            if attempt == MAX_RETRIES:
                stats["errors"] += 1
                return None
            time.sleep(1)

def extract_assets(soup, page_url):
    assets = []
    for tag in soup.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src"):
            if tag.get(attr): assets.append(tag[attr])
        if tag.get("srcset"):
            for part in tag["srcset"].split(","):
                assets.append(part.strip().split()[0])
    for tag in soup.find_all("link", href=True):  assets.append(tag["href"])
    for tag in soup.find_all("script", src=True): assets.append(tag["src"])
    for tag in soup.find_all("source"):
        for attr in ("src", "srcset"):
            if tag.get(attr): assets.append(tag[attr])
    for tag in soup.find_all(["video", "audio"], src=True): assets.append(tag["src"])
    for style_tag in soup.find_all("style"):
        for m in re.findall(r'url\(["\']?([^"\')\s]+)["\']?\)', style_tag.string or ""):
            assets.append(m)
    return [u for h in assets if (u := resolve_url(page_url, h))]

def extract_links(soup, page_url, base_netloc):
    links = []
    for tag in soup.find_all("a", href=True):
        url = resolve_url(page_url, tag["href"])
        if url and same_domain(url, base_netloc):
            ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
            if ext in FOLDER_MAP["html"] or ext == "":
                links.append(url)
    return links

def human_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def crawl(start_url, output_dir, config):
    session     = requests.Session()
    base_netloc = urllib.parse.urlparse(start_url).netloc
    visited_pages  = set()
    visited_assets = set()
    queue          = deque([start_url])
    stats = {"pages": 0, "files": 0, "bytes": 0, "errors": 0}
    max_pages      = config["max_pages"]
    delay          = config["delay"]
    allowed_assets = config["assets"]
    start_time     = time.time()

    blank()
    line()
    info(f"Iniciando descarga de {Fore.YELLOW}{base_netloc}")
    info(f"Carpeta: {Fore.YELLOW}{output_dir.resolve()}")
    info(f"Modo:    {Fore.YELLOW}{config['preset_label']}")
    line()
    blank()

    try:
        while queue:
            page_url = queue.popleft()
            if page_url in visited_pages:
                continue
            if max_pages and stats["pages"] >= max_pages:
                warn(f"Límite de {max_pages} páginas alcanzado.")
                break

            visited_pages.add(page_url)
            stats["pages"] += 1

            label = page_url.replace(start_url, "") or "/"
            print(
                Fore.GREEN + f"  [{stats['pages']:>4}]" +
                Style.RESET_ALL + f" {label[:W - 10]}"
            )

            try:
                time.sleep(delay)
                r = session.get(page_url, headers=HEADERS, timeout=TIMEOUT)
                r.raise_for_status()
            except requests.RequestException as e:
                err(f"No se pudo obtener: {e}")
                stats["errors"] += 1
                continue

            content_type = r.headers.get("content-type", "")
            if "text/html" not in content_type:
                if page_url not in visited_assets:
                    visited_assets.add(page_url)
                    download_file(session, page_url, output_dir, allowed_assets, stats)
                continue

            # Guarda HTML
            rel = safe_filename(page_url)
            if not rel.lower().endswith((".html", ".htm")):
                rel += ".html"
            html_path = output_dir / rel
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_bytes(r.content)
            stats["bytes"] += len(r.content)

            soup   = BeautifulSoup(r.content, "html.parser")
            assets = extract_assets(soup, page_url)
            links  = extract_links(soup, page_url, base_netloc)

            for link in links:
                if link not in visited_pages:
                    queue.append(link)

            new_assets = [a for a in assets if a not in visited_assets]
            if new_assets:
                for asset_url in tqdm(
                    new_assets,
                    desc=Fore.BLUE + "       assets" + Style.RESET_ALL,
                    leave=False, unit="arch", colour="blue",
                ):
                    visited_assets.add(asset_url)
                    time.sleep(0.05)
                    download_file(session, asset_url, output_dir, allowed_assets, stats)

    except KeyboardInterrupt:
        blank()
        warn("Descarga interrumpida por el usuario.")

    elapsed = time.time() - start_time
    blank()
    line("═")
    print(Fore.GREEN + Style.BRIGHT + "  ✔  DESCARGA COMPLETADA")
    line("═")
    print(f"  {'Páginas HTML':<22} {Fore.YELLOW}{stats['pages']}")
    print(f"  {'Archivos descargados':<22} {Fore.YELLOW}{stats['files']}")
    print(f"  {'Tamaño total':<22} {Fore.YELLOW}{human_size(stats['bytes'])}")
    print(f"  {'Errores':<22} {Fore.RED if stats['errors'] else Fore.GREEN}{stats['errors']}")
    print(f"  {'Tiempo':<22} {Fore.YELLOW}{elapsed:.1f}s")
    print(f"  {'Carpeta':<22} {Fore.YELLOW}{output_dir.resolve()}")
    line("═")
    blank()
    return stats

# ══════════════════════════════════════════════════════════════════════════════
#  PANTALLAS DE LA INTERFAZ
# ══════════════════════════════════════════════════════════════════════════════

def screen_welcome():
    header()
    print(Fore.WHITE + "  Bienvenido a Netlifes Web Downloader.")
    print("  Esta herramienta descarga un sitio web completo")
    print("  y organiza los archivos por tipo de forma automática.")
    blank()
    line()
    opts = {"1": "Iniciar nueva descarga", "2": "Acerca de", "3": "Salir"}
    choice = menu(opts)
    if choice == "1": return "download"
    if choice == "2": return "about"
    return "exit"

def screen_about():
    header()
    section("Acerca de")
    blank()
    info(f"Versión     : {VERSION}")
    info(f"Proyecto    : Netlifes Web Downloader")
    info(f"Descripción : Descarga completa de sitios web")
    blank()
    info("Estructura de carpetas generada:")
    print(f"  {'sitios/<dominio>/'}")
    for folder in FOLDER_MAP:
        print(f"    {'├──' if folder != 'html' else '└──'} {folder}/")
    blank()
    ask("Pulsa ENTER para volver al menú")
    return "menu"

def screen_input_url():
    header()
    section("Paso 1 — Dominio a descargar")
    blank()
    info("Escribe el dominio o URL del sitio que quieres descargar.")
    info("Ejemplos:  ejemplo.com   |   https://blog.ejemplo.com")
    blank()

    while True:
        raw = ask("URL o dominio")
        if not raw:
            warn("Debes introducir una URL.")
            continue
        url = normalize_url(raw)
        # Verificación rápida
        spinner_msg(f"Verificando conexión con {url} ...")
        try:
            r = requests.head(url, headers=HEADERS, timeout=8, allow_redirects=True)
            print(" " * 60, end="\r")  # limpia spinner
            ok(f"Sitio accesible  [{r.status_code}]  →  {url}")
            return url
        except requests.RequestException as e:
            print(" " * 60, end="\r")
            warn(f"No se pudo conectar: {e}")
            if not confirm("¿Quieres intentarlo igualmente?", default=False):
                return None

def screen_preset(url: str):
    header()
    section("Paso 2 — Modo de descarga")
    blank()
    info(f"Sitio: {Fore.YELLOW}{url}")
    blank()

    opts = {k: v["label"] for k, v in PRESETS.items()}
    choice = menu(opts)
    preset = PRESETS[choice]

    if choice == "4":
        blank()
        section("Configuración personalizada")
        blank()
        max_p = ask("Máximo de páginas HTML a rastrear (0 = sin límite)", "200")
        delay = ask("Delay entre peticiones en segundos", "0.3")
        blank()
        info("¿Qué tipos de archivos descargar?")
        all_folders = list(FOLDER_MAP.keys())
        selected = []
        for f in all_folders:
            if confirm(f"  ¿Descargar {f}?", default=True):
                selected.append(f)
        preset = {
            "label": "Custom",
            "max_pages": int(max_p) if max_p.isdigit() else 200,
            "delay": float(delay) if delay else 0.3,
            "assets": selected or all_folders,
        }

    preset["preset_label"] = preset.get("label", "Custom")
    return preset

def screen_output_dir(netloc: str):
    header()
    section("Paso 3 — Carpeta de destino")
    blank()
    default_dir = str(Path("sitios") / netloc)
    info(f"Por defecto se guardará en:  {Fore.YELLOW}{Path(default_dir).resolve()}")
    blank()
    raw = ask("Carpeta de destino (ENTER para usar la de arriba)", default_dir)
    output_dir = Path(raw)
    output_dir.mkdir(parents=True, exist_ok=True)
    ok(f"Carpeta lista: {output_dir.resolve()}")
    return output_dir

def screen_confirm(url, output_dir, config):
    header()
    section("Paso 4 — Confirmación")
    blank()
    print(f"  {'Sitio':<22} {Fore.YELLOW}{url}")
    print(f"  {'Carpeta destino':<22} {Fore.YELLOW}{output_dir.resolve()}")
    print(f"  {'Modo':<22} {Fore.YELLOW}{config['preset_label']}")
    print(f"  {'Máx. páginas':<22} {Fore.YELLOW}{config['max_pages'] or 'Sin límite'}")
    print(f"  {'Delay':<22} {Fore.YELLOW}{config['delay']}s")
    print(f"  {'Archivos a descargar':<22} {Fore.YELLOW}{', '.join(config['assets'])}")
    blank()
    return confirm("¿Todo correcto? ¿Empezamos la descarga?", default=True)

def screen_done(stats, output_dir):
    blank()
    if confirm("¿Abrir la carpeta de destino?", default=True):
        path = str(output_dir.resolve())
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')

    blank()
    if confirm("¿Descargar otro sitio?", default=False):
        return "download"
    return "exit"

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════

def main():
    state = "menu"

    while True:
        if state == "menu":
            state = screen_welcome()

        elif state == "about":
            state = screen_about()

        elif state == "download":
            url = screen_input_url()
            if not url:
                state = "menu"
                continue

            netloc     = urllib.parse.urlparse(url).netloc
            config     = screen_preset(url)
            output_dir = screen_output_dir(netloc)

            if not screen_confirm(url, output_dir, config):
                warn("Descarga cancelada.")
                blank()
                if confirm("¿Volver al menú principal?", default=True):
                    state = "menu"
                else:
                    state = "exit"
                continue

            stats = crawl(url, output_dir, config)
            state = screen_done(stats, output_dir)

        elif state == "exit":
            goodbye()
            sys.exit(0)

if __name__ == "__main__":
    main()
