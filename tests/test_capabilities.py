import unittest

from tuxdrive.capabilities import CAPABILITIES, capabilities_for
from tuxdrive.models import Provider, SyncMode


class ProviderCapabilityTests(unittest.TestCase):
    def test_every_provider_has_an_explicit_capability_record(self):
        self.assertEqual(set(CAPABILITIES), set(Provider))

    def test_adaptive_modes_hide_peer_streaming(self):
        self.assertFalse(capabilities_for(Provider.PEER).supports_mode(SyncMode.VIRTUAL_DRIVE))
        self.assertTrue(capabilities_for(Provider.GOOGLE_DRIVE).supports_mode(SyncMode.VIRTUAL_DRIVE))

    def test_proton_limits_unsafe_ui_actions(self):
        proton = capabilities_for(Provider.PROTON_DRIVE)
        self.assertFalse(proton.share_links)
        self.assertFalse(proton.hashes)
