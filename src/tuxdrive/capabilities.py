from __future__ import annotations

from dataclasses import dataclass

from .models import Provider, SyncMode


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    browser_oauth: bool
    streaming: bool
    polling: bool
    hashes: bool
    server_move: bool
    share_links: bool
    versions: bool
    notes: str = ""

    def supports_mode(self, mode: SyncMode) -> bool:
        return mode is not SyncMode.VIRTUAL_DRIVE or self.streaming


_DEFAULT = ProviderCapabilities(False, True, True, True, True, False, False)

CAPABILITIES: dict[Provider, ProviderCapabilities] = {
    Provider.GOOGLE_DRIVE: ProviderCapabilities(True, True, True, True, True, True, True, "Shared Drives and Shared with me are separate locations."),
    Provider.ONEDRIVE: ProviderCapabilities(True, True, True, True, True, True, True),
    Provider.DROPBOX: ProviderCapabilities(True, True, True, True, True, True, True),
    Provider.BOX: ProviderCapabilities(True, True, True, True, True, True, True),
    Provider.PCLOUD: ProviderCapabilities(True, True, False, True, True, True, True, "Change polling falls back to scheduled reconciliation."),
    Provider.MEGA: ProviderCapabilities(False, True, False, True, True, True, True, "Credential login; scheduled reconciliation is the safe default."),
    Provider.PROTON_DRIVE: ProviderCapabilities(False, True, False, False, True, False, True, "Beta backend; remote hash and sharing APIs are limited."),
    Provider.NEXTCLOUD: ProviderCapabilities(False, True, False, True, True, True, True, "Capabilities vary with server and WebDAV configuration."),
    Provider.PEER: ProviderCapabilities(False, False, True, True, True, False, True, "Direct authenticated peer transport with role controls."),
    Provider.VAULT: ProviderCapabilities(False, True, True, False, True, False, True, "Names and content are encrypted before upload."),
}


def capabilities_for(provider: Provider) -> ProviderCapabilities:
    return CAPABILITIES.get(provider, _DEFAULT)
