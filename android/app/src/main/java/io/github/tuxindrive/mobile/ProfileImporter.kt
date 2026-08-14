package io.github.tuxindrive.mobile

import android.content.Context
import android.net.Uri
import org.bouncycastle.crypto.generators.SCrypt
import org.json.JSONObject
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

class ProfileImporter(private val context: Context) {
    fun rcloneConfiguration(uri: Uri, password: String): ByteArray {
        val encoded = context.contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Selected TuxInDrive profile could not be opened" }
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                total += count
                require(total <= 128 * 1024 * 1024) { "The profile exceeds the 128 MiB safety limit" }
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        }
        val envelope = JSONObject(encoded.toString(Charsets.UTF_8))
        val format = envelope.getString("format")
        val version = envelope.getInt("version")
        val n = envelope.getInt("n")
        val r = envelope.getInt("r")
        val p = envelope.getInt("p")
        require(format in setOf("tuxindrive-encrypted-profile", "tuxdrive-encrypted-profile")) {
            "This is not a TuxInDrive profile backup"
        }
        require(version in setOf(1, 2) && envelope.getString("kdf") == "scrypt") {
            "Unsupported profile backup format"
        }
        val minimumPasswordLength = if (version == 1) 10 else 14
        require(password.length >= minimumPasswordLength) {
            "Enter the profile backup password (at least $minimumPasswordLength characters)"
        }
        require(n == (if (version == 1) 32768 else 131072) && r == 8 && p == 1) {
            "Unsupported profile key-derivation settings"
        }
        val aad = "{" + listOf(
            "\"format\":${JSONObject.quote(format)}",
            "\"kdf\":\"scrypt\"",
            "\"n\":$n",
            "\"p\":$p",
            "\"r\":$r",
            "\"version\":$version",
        ).joinToString(",") + "}"
        val decoder = Base64.getDecoder()
        val salt = decoder.decode(envelope.getString("salt"))
        val nonce = decoder.decode(envelope.getString("nonce"))
        val ciphertext = decoder.decode(envelope.getString("ciphertext"))
        val key = SCrypt.generate(password.toByteArray(Charsets.UTF_8), salt, n, r, p, 32)
        val clear = try {
            Cipher.getInstance("AES/GCM/NoPadding").run {
                init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
                updateAAD(aad.toByteArray(Charsets.UTF_8))
                doFinal(ciphertext)
            }
        } catch (_: Exception) {
            throw IllegalArgumentException("The profile password is wrong or the backup was changed")
        }
        val secrets = JSONObject(clear.toString(Charsets.UTF_8)).optJSONObject("secrets")
            ?: throw IllegalArgumentException("This backup excludes credentials; create one with credentials enabled for Android")
        return try {
            decoder.decode(secrets.getString("rclone_config"))
        } catch (_: Exception) {
            throw IllegalArgumentException("The profile does not contain a valid cloud configuration")
        }
    }
}
