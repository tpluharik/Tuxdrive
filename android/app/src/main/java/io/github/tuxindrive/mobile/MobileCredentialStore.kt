package io.github.tuxindrive.mobile

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class MobileCredentialStore(context: Context) {
    private val preferences = context.getSharedPreferences("mobile-credentials", Context.MODE_PRIVATE)
    private val alias = "tuxindrive-rclone-config-key"

    fun store(password: String) {
        require(password.isNotBlank() && password.length <= 1024) { "The configuration key is invalid" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val ciphertext = cipher.doFinal(password.toByteArray(Charsets.UTF_8))
        require(preferences.edit()
            .putString("nonce", Base64.getEncoder().encodeToString(cipher.iv))
            .putString("ciphertext", Base64.getEncoder().encodeToString(ciphertext))
            .commit()) { "The protected configuration key could not be stored" }
    }

    fun load(): String? {
        val nonce = preferences.getString("nonce", null) ?: return null
        val ciphertext = preferences.getString("ciphertext", null) ?: return null
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(
                Cipher.DECRYPT_MODE,
                key(),
                GCMParameterSpec(128, Base64.getDecoder().decode(nonce)),
            )
            cipher.doFinal(Base64.getDecoder().decode(ciphertext)).toString(Charsets.UTF_8)
                .takeIf { it.isNotBlank() && it.length <= 1024 }
        } catch (_: Exception) {
            clear()
            null
        }
    }

    fun clear() {
        preferences.edit().clear().commit()
    }

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec.Builder(
                    alias,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            generateKey()
        }
    }
}
