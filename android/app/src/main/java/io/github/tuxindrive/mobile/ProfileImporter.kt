package io.github.tuxindrive.mobile

import android.content.Context
import android.net.Uri
import org.bouncycastle.crypto.generators.SCrypt
import org.json.JSONObject
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

data class ImportedProfile(
    val configuration: ByteArray,
    val configurationPassword: String,
)

class ProfileImporter(private val context: Context) {
    fun import(uri: Uri, password: String): ImportedProfile {
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
        return decode(encoded, password)
    }

    companion object {
        fun decode(encoded: ByteArray, password: String): ImportedProfile {
            require(encoded.isNotEmpty() && encoded.size <= 128 * 1024 * 1024) {
                "The profile exceeds the 128 MiB safety limit"
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
            val salt: ByteArray
            val nonce: ByteArray
            val ciphertext: ByteArray
            try {
                salt = decoder.decode(envelope.getString("salt"))
                nonce = decoder.decode(envelope.getString("nonce"))
                ciphertext = decoder.decode(envelope.getString("ciphertext"))
            } catch (_: Exception) {
                throw IllegalArgumentException("The profile contains invalid encrypted data")
            }
            require(salt.size == 16 && nonce.size == 12 && ciphertext.size <= 128 * 1024 * 1024) {
                "The profile encryption parameters are invalid"
            }
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
                val configuration = decoder.decode(secrets.getString("rclone_config"))
                require(configuration.isNotEmpty() && configuration.size <= 2 * 1024 * 1024) {
                    "The cloud configuration exceeds the 2 MiB safety limit"
                }
                val configurationPassword = secrets.optString("rclone_config_password")
                require(configurationPassword.isNotBlank() && configurationPassword.length <= 1024) {
                    "This profile was created by an older version without the mobile unlock key; create a new credential-enabled profile on desktop"
                }
                ImportedProfile(configuration, configurationPassword)
            } catch (_: Exception) {
                throw IllegalArgumentException(
                    "The profile does not contain a complete mobile cloud configuration; create a new credential-enabled profile on desktop"
                )
            }
        }
    }
}
