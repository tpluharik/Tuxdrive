"""Small, dependency-free UI localization layer.

Keys are intentionally stable and centrally reviewed. Missing translations fall
back to English instead of exposing identifiers or crashing a dialog.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    flag: str
    name: str


LANGUAGES = (
    Language("en", "🇬🇧", "English"),
    Language("de", "🇩🇪", "Deutsch"),
    Language("fr", "🇫🇷", "Français"),
    Language("es", "🇪🇸", "Español"),
)
LANGUAGE_CODES = {item.code for item in LANGUAGES}

_STRINGS = {
    "en": {
        "subtitle": "Cloud sync, streaming, and encrypted peer sharing",
        "connect_cloud": "Connect cloud account", "peer_folders": "Peer-to-peer shared folders",
        "health": "Sync health, peer audit timeline, and provider capabilities", "settings": "Settings",
        "help": "User documentation and how-to guides", "language": "Language",
        "cloud_accounts": "Cloud accounts", "connect_account": "Connect account",
        "synced_folders": "Synchronized folders", "add_folder": "Add folder", "live_log": "Live activity log",
        "connected": "Connected", "synchronizing": "Synchronizing", "attention": "Needs attention",
        "peer_settings": "Peer settings", "open_online": "Open online", "reconnect": "Reconnect / refresh credentials",
        "remove_account": "Remove account", "empty_jobs": "Connect an account, then add a synchronized folder or virtual drive.",
        "automatic_sync": "Enable automatic synchronization", "open_drive": "Open drive",
        "start_streaming": "Start streaming", "sync_now": "Sync now", "disconnect": "Disconnect", "stop": "Stop",
        "open_folder": "Open folder", "share_link": "Share link", "history": "History", "verify": "Verify",
        "conflicts": "Conflicts", "rename": "Rename", "edit": "Edit", "view_log": "View log",
        "remove_sync": "Remove synchronization", "cloud_storage": "Cloud storage",
        "stream_hint": "Show cloud files immediately; download content only when a file is opened",
        "choose_provider": "Connect cloud storage", "choose_provider_heading": "Choose a storage provider",
        "provider_hint": "All providers support selective folder sync and files-on-demand mounting.",
        "create_vault": "Create encrypted vault on a connected account", "cancel": "Cancel",
        "documentation": "TuxDrive User Documentation", "documentation_intro": "Functions, safe operating guidance, and practical how-to instructions",
        "search_help": "Search documentation…", "all_topics": "All topics", "close": "Close",
        "preparing": "Preparing the cloud transfer engine…", "loaded": "TuxDrive loaded and is running in the tray.",
    },
    "de": {
        "subtitle": "Cloud-Synchronisierung, Streaming und verschlüsselte Peer-Freigabe",
        "connect_cloud": "Cloud-Konto verbinden", "peer_folders": "Peer-to-Peer-Freigaben",
        "health": "Synchronisierungsstatus, Peer-Prüfprotokoll und Anbieterfunktionen", "settings": "Einstellungen",
        "help": "Benutzerdokumentation und Anleitungen", "language": "Sprache",
        "cloud_accounts": "Cloud-Konten", "connect_account": "Konto verbinden",
        "synced_folders": "Synchronisierte Ordner", "add_folder": "Ordner hinzufügen", "live_log": "Live-Aktivitätsprotokoll",
        "connected": "Verbunden", "synchronizing": "Wird synchronisiert", "attention": "Aktion erforderlich",
        "peer_settings": "Peer-Einstellungen", "open_online": "Online öffnen", "reconnect": "Anmeldedaten erneuern",
        "remove_account": "Konto entfernen", "empty_jobs": "Verbinden Sie ein Konto und fügen Sie einen synchronisierten Ordner oder ein virtuelles Laufwerk hinzu.",
        "automatic_sync": "Automatische Synchronisierung aktivieren", "open_drive": "Laufwerk öffnen",
        "start_streaming": "Streaming starten", "sync_now": "Jetzt synchronisieren", "disconnect": "Trennen", "stop": "Stoppen",
        "open_folder": "Ordner öffnen", "share_link": "Link teilen", "history": "Verlauf", "verify": "Prüfen",
        "conflicts": "Konflikte", "rename": "Umbenennen", "edit": "Bearbeiten", "view_log": "Protokoll",
        "remove_sync": "Synchronisierung entfernen", "cloud_storage": "Cloud-Speicher",
        "stream_hint": "Cloud-Dateien sofort anzeigen; Inhalte erst beim Öffnen herunterladen",
        "choose_provider": "Cloud-Speicher verbinden", "choose_provider_heading": "Speicheranbieter auswählen",
        "provider_hint": "Alle Anbieter unterstützen selektive Synchronisierung und Dateien bei Bedarf.",
        "create_vault": "Verschlüsselten Tresor auf einem verbundenen Konto erstellen", "cancel": "Abbrechen",
        "documentation": "TuxDrive-Benutzerdokumentation", "documentation_intro": "Funktionen, sicherer Betrieb und praktische Anleitungen",
        "search_help": "Dokumentation durchsuchen…", "all_topics": "Alle Themen", "close": "Schließen",
        "preparing": "Cloud-Übertragungsmodul wird vorbereitet…", "loaded": "TuxDrive läuft im Infobereich.",
    },
    "fr": {
        "subtitle": "Synchronisation cloud, streaming et partage pair-à-pair chiffré",
        "connect_cloud": "Connecter un compte cloud", "peer_folders": "Dossiers pair-à-pair",
        "health": "Santé des synchronisations, audit des pairs et capacités", "settings": "Paramètres",
        "help": "Documentation et guides pratiques", "language": "Langue",
        "cloud_accounts": "Comptes cloud", "connect_account": "Connecter un compte",
        "synced_folders": "Dossiers synchronisés", "add_folder": "Ajouter un dossier", "live_log": "Journal d’activité",
        "connected": "Connecté", "synchronizing": "Synchronisation", "attention": "Intervention requise",
        "peer_settings": "Paramètres du pair", "open_online": "Ouvrir en ligne", "reconnect": "Actualiser les identifiants",
        "remove_account": "Supprimer le compte", "empty_jobs": "Connectez un compte, puis ajoutez un dossier synchronisé ou un lecteur virtuel.",
        "automatic_sync": "Activer la synchronisation automatique", "open_drive": "Ouvrir le lecteur",
        "start_streaming": "Démarrer le streaming", "sync_now": "Synchroniser", "disconnect": "Déconnecter", "stop": "Arrêter",
        "open_folder": "Ouvrir le dossier", "share_link": "Lien de partage", "history": "Historique", "verify": "Vérifier",
        "conflicts": "Conflits", "rename": "Renommer", "edit": "Modifier", "view_log": "Voir le journal",
        "remove_sync": "Supprimer la synchronisation", "cloud_storage": "Stockage cloud",
        "stream_hint": "Afficher immédiatement les fichiers cloud et télécharger leur contenu à l’ouverture",
        "choose_provider": "Connecter un stockage cloud", "choose_provider_heading": "Choisir un fournisseur",
        "provider_hint": "Tous les fournisseurs permettent la sélection de dossiers et les fichiers à la demande.",
        "create_vault": "Créer un coffre chiffré sur un compte connecté", "cancel": "Annuler",
        "documentation": "Documentation utilisateur TuxDrive", "documentation_intro": "Fonctions, conseils de sécurité et guides pratiques",
        "search_help": "Rechercher dans la documentation…", "all_topics": "Tous les sujets", "close": "Fermer",
        "preparing": "Préparation du moteur de transfert…", "loaded": "TuxDrive fonctionne dans la zone de notification.",
    },
    "es": {
        "subtitle": "Sincronización cloud, streaming y uso compartido cifrado entre pares",
        "connect_cloud": "Conectar cuenta cloud", "peer_folders": "Carpetas entre pares",
        "health": "Estado de sincronización, auditoría y capacidades", "settings": "Configuración",
        "help": "Documentación y guías prácticas", "language": "Idioma",
        "cloud_accounts": "Cuentas cloud", "connect_account": "Conectar cuenta",
        "synced_folders": "Carpetas sincronizadas", "add_folder": "Añadir carpeta", "live_log": "Registro de actividad",
        "connected": "Conectado", "synchronizing": "Sincronizando", "attention": "Requiere atención",
        "peer_settings": "Configuración del par", "open_online": "Abrir en línea", "reconnect": "Actualizar credenciales",
        "remove_account": "Eliminar cuenta", "empty_jobs": "Conecte una cuenta y añada una carpeta sincronizada o unidad virtual.",
        "automatic_sync": "Activar sincronización automática", "open_drive": "Abrir unidad",
        "start_streaming": "Iniciar streaming", "sync_now": "Sincronizar", "disconnect": "Desconectar", "stop": "Detener",
        "open_folder": "Abrir carpeta", "share_link": "Compartir enlace", "history": "Historial", "verify": "Verificar",
        "conflicts": "Conflictos", "rename": "Renombrar", "edit": "Editar", "view_log": "Ver registro",
        "remove_sync": "Eliminar sincronización", "cloud_storage": "Almacenamiento cloud",
        "stream_hint": "Mostrar archivos cloud inmediatamente y descargar el contenido solo al abrirlo",
        "choose_provider": "Conectar almacenamiento cloud", "choose_provider_heading": "Elegir proveedor",
        "provider_hint": "Todos los proveedores permiten selección de carpetas y archivos bajo demanda.",
        "create_vault": "Crear bóveda cifrada en una cuenta conectada", "cancel": "Cancelar",
        "documentation": "Documentación de usuario de TuxDrive", "documentation_intro": "Funciones, uso seguro y guías prácticas",
        "search_help": "Buscar en la documentación…", "all_topics": "Todos los temas", "close": "Cerrar",
        "preparing": "Preparando el motor de transferencia…", "loaded": "TuxDrive se está ejecutando en la bandeja.",
    },
}

_current = "en"


def set_language(code: str) -> str:
    global _current
    _current = code if code in LANGUAGE_CODES else "en"
    return _current


def get_language() -> str:
    return _current


def tr(key: str, **values: object) -> str:
    value = _STRINGS.get(_current, {}).get(key, _STRINGS["en"].get(key, key))
    return value.format(**values) if values else value
