import json
import subprocess
import sys
import os
import shutil
import time
import atexit
import signal

# --- Konfiguration ---
INSTALL_FILE = "packages.json"
BUILD_DIR_PREFIX = "/tmp/install_temp_" # Wird weiterhin für temporäre Dinge wie jq-Installation genutzt
MAX_RETRY_ATTEMPTS = 3
REQUIRED_GLOBAL_GROUP = "global"
FLATHUB_REMOTE = "flathub"
FLATHUB_URL = "https://flathub.org/repo/flathub.flatpakrepo"

# --- Farben für die Ausgabe (ANSI Escape Codes) ---
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'
    NC = '\033[0m' # No Color

# --- Globale Variable für das Build-Verzeichnis und ein Flag, ob das Skript beendet wird ---
BUILD_DIR = None
_SCRIPT_EXITING = False # Neues Flag, um doppelte Exit-Aufrufe zu vermeiden
INSTALLATION_SUMMARY = [] # Liste zur Speicherung des Installationsstatus

# --- Cleanup-Funktion ---
def cleanup(exit_code=0):
    global _SCRIPT_EXITING
    if _SCRIPT_EXITING: # Verhindere, dass cleanup mehrmals aufgerufen wird, wenn bereits beendet
        return

    _SCRIPT_EXITING = True # Setze das Flag, um anzuzeigen, dass das Skript beendet wird

    # Überschreibe die letzte Fortschrittsanzeige, bevor die Zusammenfassung oder Aufräumarbeiten beginnen
    sys.stdout.write(f"\r{' ' * 80}\r") # Leert die Zeile
    sys.stdout.flush()

    if BUILD_DIR and os.path.exists(BUILD_DIR):
        print(f"\n{Colors.YELLOW}Räume temporäres Verzeichnis ({BUILD_DIR}) auf...{Colors.NC}")
        shutil.rmtree(BUILD_DIR)

    if exit_code != 0:
        sys.exit(exit_code) # Beende das Skript mit dem übergebenen Exit-Code


# Registriere Cleanup für den normalen Programmexit
atexit.register(cleanup)

# Für SIGINT (Strg+C) und SIGTERM:
def signal_handler(signum, frame):
    print(f"\n{Colors.RED}Signal {signum} ({signal.Signals(signum).name}) empfangen. Beende Skript...{Colors.NC}")
    display_summary() # Zeige Zusammenfassung auch bei Abbruch
    cleanup(1) # Hier cleanup mit Exit-Code aufrufen, um einen Fehler zu signalisieren

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# --- Hilfsfunktionen ---
def print_colored(text, color):
    print(f"{color}{text}{Colors.NC}")

def check_command(cmd, essential=True):
    """
    Prüft, ob ein Befehl installiert ist.
    Args:
        cmd (str): Der Name des zu prüfenden Befehls.
        essential (bool): Wenn True, wird das Skript beendet, wenn der Befehl fehlt.
                          Wenn False, wird nur eine Warnung ausgegeben.
    """
    if shutil.which(cmd) is None:
        if cmd == "jq":
            print_colored(f"'{cmd}' ist nicht installiert. Versuche, '{cmd}' automatisch zu installieren...", Colors.YELLOW)
            try:
                subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "jq"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                print_colored(f"'{cmd}' erfolgreich installiert.", Colors.GREEN)
                return True
            except subprocess.CalledProcessError as e:
                print_colored(f"Fehler: Konnte '{cmd}' nicht automatisch installieren. Details: {e.returncode}", Colors.RED)
                print_colored(f"stdout: {e.stdout.decode()}", Colors.RED)
                print_colored(f"stderr: {e.stderr.decode()}", Colors.RED)
                print_colored(f"Bitte installieren Sie '{cmd}' manuell mit: {Colors.CYAN}sudo pacman -S jq{Colors.NC}", Colors.RED)
                cleanup(1)
            except FileNotFoundError:
                print_colored(f"Fehler: 'pacman' Befehl nicht gefunden. Kann '{cmd}' nicht installieren.", Colors.RED)
                cleanup(1)
        elif essential:
            print_colored(f"Fehler: '{cmd}' ist nicht installiert. Dieses Tool ist für die Funktion des Skripts unerlässlich.", Colors.RED)
            print_colored(f"Bitte installieren Sie '{cmd}' und versuchen Sie es erneut. Zum Beispiel: {Colors.CYAN}sudo pacman -S {cmd}{Colors.NC}", Colors.RED)
            cleanup(1)
        else:
            print_colored(f"Warnung: '{cmd}' ist nicht installiert. Das Skript wird fortgesetzt, aber die Installation wird empfohlen.", Colors.YELLOW)
            return False
    return True

def check_network():
    print_colored("Überprüfe Internetverbindung...", Colors.YELLOW)
    try:
        subprocess.run(["ping", "-c", "1", "8.8.8.8"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print_colored("Internetverbindung verfügbar.", Colors.GREEN)
    except subprocess.CalledProcessError:
        print_colored("Fehler: Keine Internetverbindung. Bitte stellen Sie sicher, dass Sie online sind und versuchen Sie es erneut.", Colors.RED)
        cleanup(1)

def show_progress(current, total, bar_length=50, prefix="Gesamtfortschritt", color=Colors.CYAN):
    progress = (current * 100) // total
    filled_length = (bar_length * progress) // 100
    empty_length = bar_length - filled_length
    bar = '#' * filled_length + '-' * empty_length
    sys.stdout.write(f"\r{color}{prefix}: [{bar}] {progress}% ({current}/{total}){Colors.NC}")
    sys.stdout.flush()

def ensure_flatpak_ready():
    """
    Stellt sicher, dass Flatpak installiert und Flathub konfiguriert ist.
    """
    print_colored("\nÜberprüfe Flatpak-Installation und -Konfiguration...", Colors.BLUE)

    # 1. Flatpak überprüfen und installieren (falls nötig)
    if shutil.which("flatpak") is None:
        print_colored("Flatpak ist nicht installiert. Versuche Installation via pacman...", Colors.YELLOW)
        try:
            subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "flatpak"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print_colored("Flatpak erfolgreich installiert.", Colors.GREEN)
        except subprocess.CalledProcessError as e:
            print_colored(f"Fehler: Konnte Flatpak nicht installieren. Exit-Code: {e.returncode}", Colors.RED)
            print_colored(f"stdout: {e.stdout.decode()}", Colors.RED)
            print_colored(f"stderr: {e.stderr.decode()}", Colors.RED)
            cleanup(1)
        except FileNotFoundError:
            print_colored("Fehler: 'pacman' Befehl nicht gefunden. Kann Flatpak nicht installieren.", Colors.RED)
            cleanup(1)
    else:
        print_colored("Flatpak ist bereits installiert.", Colors.GREEN)

    # 2. Flathub Remote hinzufügen (falls nicht vorhanden)
    print_colored(f"Überprüfe {FLATHUB_REMOTE} remote...", Colors.YELLOW)
    try:
        result = subprocess.run(["flatpak", "remotes", "--user"], check=True, text=True, capture_output=True)
        if FLATHUB_REMOTE not in result.stdout:
            print_colored(f"{FLATHUB_REMOTE} remote nicht gefunden. Füge {FLATHUB_REMOTE} hinzu...", Colors.YELLOW)
            subprocess.run(["flatpak", "remote-add", "--if-not-exists", FLATHUB_REMOTE, FLATHUB_URL], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print_colored(f"{FLATHUB_REMOTE} erfolgreich hinzugefügt.", Colors.GREEN)
        else:
            print_colored(f"{FLATHUB_REMOTE} remote ist bereits konfiguriert.", Colors.GREEN)
    except subprocess.CalledProcessError as e:
        print_colored(f"Fehler beim Konfigurieren des Flatpak Remotes. Exit-Code: {e.returncode}", Colors.RED)
        print_colored(f"stdout: {e.stdout.decode()}", Colors.RED)
        print_colored(f"stderr: {e.stderr.decode()}", Colors.RED)
        cleanup(1)
    except FileNotFoundError:
        print_colored("Fehler: 'flatpak' Befehl nicht gefunden. Ist Flatpak korrekt installiert?", Colors.RED)
        cleanup(1)

    print_colored("Flatpak ist einsatzbereit.", Colors.GREEN)

def install_package(package_name, method, current_group_package_num, total_group_packages):
    global INSTALLATION_SUMMARY

    command = []
    installer_name = ""

    if method == "pacman":
        command = ["sudo", "pacman", "-S", "--noconfirm", package_name]
        installer_name = "pacman"
    elif method == "flatpak":
        command = ["flatpak", "install", "-y", FLATHUB_REMOTE, package_name]
        installer_name = "flatpak"
    else:
        # Dies sollte nicht passieren, wenn die Logik korrekt ist
        print_colored(f"Fehler: Unbekannte Installationsmethode '{method}' für Paket '{package_name}'.", Colors.RED)
        INSTALLATION_SUMMARY.append({"package": package_name, "method": method, "status": "Fehlgeschlagen (Unbekannte Methode)"})
        return False

    attempt = 1
    while attempt <= MAX_RETRY_ATTEMPTS:
        print(f"\r{Colors.YELLOW}  -> Installiere Paket: {package_name} mit {installer_name} (Versuch {attempt}/{MAX_RETRY_ATTEMPTS}){Colors.NC}           ", end='')
        show_progress(current_group_package_num, total_group_packages, bar_length=30, prefix="  Gruppe", color=Colors.PURPLE)

        try:
            # capture_output=True unterdrückt die Ausgabe auf stdout/stderr
            result = subprocess.run(command, check=True, text=True, capture_output=True)

            sys.stdout.write(f"\r{' ' * 120}\r") # Leert die Zeile komplett
            sys.stdout.flush()
            print_colored(f"  -> {package_name} erfolgreich installiert.", Colors.GREEN)

            INSTALLATION_SUMMARY.append({"package": package_name, "method": installer_name, "status": "Erfolgreich"})
            return True
        except subprocess.CalledProcessError as e:
            sys.stdout.write(f"\r{' ' * 120}\r") # Leert die Zeile
            sys.stdout.flush()
            print_colored(f"  -> Fehler beim Installieren von {package_name} mit {installer_name}. Exit-Code: {e.returncode}", Colors.RED)
            print_colored(f"  stdout: \n{e.stdout}", Colors.RED)
            print_colored(f"  stderr: \n{e.stderr}", Colors.RED)

            attempt += 1
            time.sleep(2)
        except FileNotFoundError:
            sys.stdout.write(f"\r{' ' * 120}\r") # Leert die Zeile
            sys.stdout.flush()
            print_colored(f"Fehler: '{installer_name}' Befehl nicht gefunden. Ist {installer_name} korrekt installiert und im PATH?", Colors.RED)
            INSTALLATION_SUMMARY.append({"package": package_name, "method": installer_name, "status": f"Fehlgeschlagen ({installer_name} nicht gefunden)"})
            return False

    sys.stdout.write(f"\r{' ' * 120}\r") # Leert die Zeile
    sys.stdout.flush()
    print_colored(f"  -> Fehler: Installation von {package_name} fehlgeschlagen nach {MAX_RETRY_ATTEMPTS} Versuchen. Bitte manuell überprüfen.", Colors.RED)
    INSTALLATION_SUMMARY.append({"package": package_name, "method": installer_name, "status": "Fehlgeschlagen (max. Versuche)"})
    return False

# --- Funktion zur Anzeige der Zusammenfassung ---
def display_summary():
    sys.stdout.write(f"\r{' ' * 120}\r")
    sys.stdout.flush()

    if not INSTALLATION_SUMMARY:
        print_colored("\nKeine Pakete zur Installation verfolgt.", Colors.YELLOW)
        return

    print(f"\n{Colors.BLUE}--- Installationszusammenfassung ---{Colors.NC}")

    header_package = "Paketname"
    header_method = "Methode"
    header_status = "Status"

    max_len_package = max(len(header_package), max(len(item['package']) for item in INSTALLATION_SUMMARY))
    max_len_method = max(len(header_method), max(len(item['method']) for item in INSTALLATION_SUMMARY))
    max_len_status = max(len(header_status), max(len(item['status']) for item in INSTALLATION_SUMMARY))

    separator = f"+-{'-' * max_len_package}-+-{'-' * max_len_method}-+-{'-' * max_len_status}-+"

    print(separator)
    print(f"| {header_package:<{max_len_package}} | {header_method:<{max_len_method}} | {header_status:<{max_len_status}} |")
    print(separator)

    for item in INSTALLATION_SUMMARY:
        package = item['package']
        method = item['method']
        status = item['status']

        status_color = Colors.GREEN if status == "Erfolgreich" else Colors.RED

        print(f"| {package:<{max_len_package}} | {method:<{max_len_method}} | {status_color}{status:<{max_len_status}}{Colors.NC} |")

    print(separator)
    print_colored("\nBitte überprüfen Sie die vollständige Ausgabe für Details zu fehlgeschlagenen Installationen.", Colors.YELLOW)


# --- Hauptlogik ---
def main():
    global BUILD_DIR
    BUILD_DIR = f"{BUILD_DIR_PREFIX}{int(time.time())}"

    print_colored("Starte das Installationsskript für Garuda Linux...", Colors.BLUE)

    check_command("pacman")
    check_command("jq", essential=True)
    check_command("curl")
    check_command("git")
    check_command("ping")
    check_command("makepkg") # Beibehalten, falls es im System konfiguriert ist oder für andere Zwecke wichtig

    check_network()

    print_colored("Hinweis: Sie werden möglicherweise aufgefordert, Ihr sudo-Passwort einzugeben.", Colors.YELLOW)

    try:
        subprocess.run(["sudo", "-v"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        print_colored("Fehler: sudo-Authentifizierung fehlgeschlagen oder nicht autorisiert. Das Skript wird beendet.", Colors.RED)
        cleanup(1)

    print_colored("Das Skript unterstützt nun die Installation über pacman und Flatpak.", Colors.YELLOW)
    print_colored("Bitte beachten Sie: Flatpak-Anwendungen (flatpak: true) müssen über ihren App-ID-Namen angegeben werden (z.B. org.mozilla.firefox).", Colors.YELLOW)


    os.makedirs(BUILD_DIR, exist_ok=True)

    if not os.path.exists(INSTALL_FILE):
        print_colored(f"Fehler: Installationsdatei '{INSTALL_FILE}' nicht gefunden.", Colors.RED)
        cleanup(1)

    try:
        with open(INSTALL_FILE, 'r') as f:
            package_groups = json.load(f)
    except json.JSONDecodeError as e:
        print_colored(f"Fehler beim Parsen der JSON-Datei '{INSTALL_FILE}': {e}", Colors.RED)
        cleanup(1)
    except Exception as e:
        print_colored(f"Ein unerwarteter Fehler beim Lesen der JSON-Datei ist aufgetreten: {e}", Colors.RED)
        cleanup(1)

    if REQUIRED_GLOBAL_GROUP not in package_groups:
        print_colored(f"Fehler: Die obligatorische Gruppe '{REQUIRED_GLOBAL_GROUP}' wurde in '{INSTALL_FILE}' nicht gefunden.", Colors.RED)
        print_colored(f"Bitte stellen Sie sicher, dass Ihre JSON-Datei eine Gruppe namens '{REQUIRED_GLOBAL_GROUP}' enthält, auch wenn sie leer ist.", Colors.YELLOW)
        cleanup(1)

    total_packages_overall = sum(len(packages) for packages in package_groups.values())
    current_package_overall = 0

    sorted_group_names = sorted(package_groups.keys(), key=lambda k: (0 if k == REQUIRED_GLOBAL_GROUP else 1, k))

    # Eine Liste, um zu verfolgen, ob Flatpak-Installationen anstehen
    flatpak_packages_exist = any(
        package.get("flatpak", False)
        for group in package_groups.values()
        for package in group
    )

    if flatpak_packages_exist:
        ensure_flatpak_ready() # Führt die Flatpak-Checks/Installation einmalig durch

    for group_name in sorted_group_names:
        print(f"\n{Colors.BLUE}--- Verarbeite Gruppe: {group_name} ---{Colors.NC}")

        group_packages = package_groups[group_name]
        total_packages_in_group = len(group_packages)
        current_package_in_group = 0

        if total_packages_in_group == 0:
            print_colored(f"  -> Gruppe '{group_name}' ist leer. Überspringe.", Colors.YELLOW)
            continue

        for package_info in group_packages:
            current_package_overall += 1
            current_package_in_group += 1

            package_name = package_info.get("name")
            if not package_name:
                print_colored(f"Warnung: Ungültiges Paketobjekt in Gruppe '{group_name}'. 'name'-Eigenschaft fehlt.", Colors.YELLOW)
                INSTALLATION_SUMMARY.append({"package": "UNBEKANNT (ungültig)", "method": "N/A", "status": "Fehlgeschlagen"})
                continue

            # Neue Logik: Bestimme die Installationsmethode basierend auf dem 'flatpak'-Property
            if package_info.get("flatpak", False):
                installation_method = "flatpak"
            else:
                installation_method = "pacman"

            success = install_package(package_name, installation_method, current_package_in_group, total_packages_in_group)
            if not success:
                pass # Fehlermeldung wird bereits in install_package ausgegeben

        sys.stdout.write(f"\r{' ' * 120}\r") # Leert die Zeile
        sys.stdout.flush()
        print_colored(f"\n--- Gruppe '{group_name}' abgeschlossen. ---", Colors.GREEN)

    print_colored("\nInstallation aller Pakete und Gruppen abgeschlossen.", Colors.GREEN)
    print_colored("Bitte überprüfen Sie die Ausgaben für eventuelle Fehler oder manuelle Schritte.", Colors.GREEN)

    display_summary() # Zeige die Zusammenfassung am Ende

if __name__ == "__main__":
    main()
