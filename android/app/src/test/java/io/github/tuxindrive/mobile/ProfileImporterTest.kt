package io.github.tuxindrive.mobile

import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import org.bouncycastle.crypto.generators.SCrypt
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ProfileImporterTest {
    private val profilePassword = "a-secure-password"
    private val configuration = "RCLONE_ENCRYPT_V0:\nexample".toByteArray()

    private fun profile(includeUnlockKey: Boolean = true): ByteArray {
        val format = "tuxindrive-encrypted-profile"
        val version = 1
        val n = 32768
        val r = 8
        val p = 1
        val salt = ByteArray(16) { it.toByte() }
        val nonce = ByteArray(12) { (it + 16).toByte() }
        val aad = "{" + listOf(
            "\"format\":${JSONObject.quote(format)}",
            "\"kdf\":\"scrypt\"",
            "\"n\":$n",
            "\"p\":$p",
            "\"r\":$r",
            "\"version\":$version",
        ).joinToString(",") + "}"
        val secrets = JSONObject().put("rclone_config", Base64.getEncoder().encodeToString(configuration))
        if (includeUnlockKey) secrets.put("rclone_config_password", "embedded-rclone-key")
        val clear = JSONObject().put("secrets", secrets).toString().toByteArray()
        val key = SCrypt.generate(profilePassword.toByteArray(), salt, n, r, p, 32)
        val ciphertext = Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
            updateAAD(aad.toByteArray())
            doFinal(clear)
        }
        return JSONObject()
            .put("format", format)
            .put("version", version)
            .put("kdf", "scrypt")
            .put("n", n)
            .put("r", r)
            .put("p", p)
            .put("salt", Base64.getEncoder().encodeToString(salt))
            .put("nonce", Base64.getEncoder().encodeToString(nonce))
            .put("ciphertext", Base64.getEncoder().encodeToString(ciphertext))
            .toString().toByteArray()
    }

    @Test
    fun importsTheConfigurationAndItsSeparateUnlockKey() {
        val imported = ProfileImporter.decode(profile(), profilePassword)
        assertArrayEquals(configuration, imported.configuration)
        assertEquals("embedded-rclone-key", imported.configurationPassword)
    }

    @Test
    fun oldCredentialProfileWithoutUnlockKeyFailsActionably() {
        val error = assertThrows(IllegalArgumentException::class.java) {
            ProfileImporter.decode(profile(includeUnlockKey = false), profilePassword)
        }
        assertTrue(error.message.orEmpty().contains("complete mobile cloud configuration"))
    }
}
