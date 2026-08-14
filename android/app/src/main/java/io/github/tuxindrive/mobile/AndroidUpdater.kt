package io.github.tuxindrive.mobile

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.time.OffsetDateTime
import java.util.Base64

data class AndroidUpdate(val version: String, val url: String, val sha256: String, val notes: String)

class AndroidUpdater(private val context: Context) {
    private val manifestUrl =
        "https://raw.githubusercontent.com/tpluharik/TuxInDrive/main/releases/android/latest-v2.json"
    private val publicKey = Base64.getDecoder().decode("3c0BtMjwCmlZR0nw2jdqsAQQm7nYyd68r8BtnK2XzyY=")
    private val trustedPrefix = "https://github.com/tpluharik/Tuxindrive/releases/download/"
    private val maxPackageSize = 1024L * 1024L * 1024L

    fun check(): AndroidUpdate? {
        val data = JSONObject(readUrl(manifestUrl, 128 * 1024))
        val version = data.getString("version")
        val url = data.getString("url")
        val sha256 = data.getString("sha256").lowercase()
        val notes = data.optString("notes")
        val expiresAt = data.getString("expires_at")
        val signature = Base64.getDecoder().decode(data.getString("signature"))
        val canonical = listOf(
            "expires_at" to expiresAt,
            "notes" to notes,
            "sha256" to sha256,
            "url" to url,
            "version" to version,
        ).joinToString(prefix = "{", postfix = "}") { (key, value) ->
            "${JSONObject.quote(key)}:${JSONObject.quote(value)}"
        }.toByteArray(Charsets.UTF_8)
        val verifier = Ed25519Signer().apply {
            init(false, Ed25519PublicKeyParameters(publicKey, 0))
            update(canonical, 0, canonical.size)
        }
        require(verifier.verifySignature(signature)) { "The Android update signature is invalid" }
        require(OffsetDateTime.parse(expiresAt).isAfter(OffsetDateTime.now())) { "The Android update channel has expired" }
        require(url.startsWith(trustedPrefix)) { "The Android update URL is not trusted" }
        require(url.substringAfterLast('/') == "TuxInDrive-$version-android.apk") {
            "The Android package filename does not match its signed version"
        }
        require(sha256.matches(Regex("[0-9a-f]{64}"))) { "The Android update checksum is invalid" }
        return AndroidUpdate(version, url, sha256, notes).takeIf {
            isNewer(it.version, BuildConfig.VERSION_NAME)
        }
    }

    fun download(update: AndroidUpdate): File {
        val directory = File(context.cacheDir, "updates").apply { mkdirs() }
        val target = File(directory, "TuxInDrive-${update.version}-android.apk")
        val part = File(directory, "${target.name}.part")
        val connection = URL(update.url).openConnection() as HttpURLConnection
        connection.connectTimeout = 20_000
        connection.readTimeout = 60_000
        connection.setRequestProperty("User-Agent", "TuxInDrive-Android-Updater")
        val digest = MessageDigest.getInstance("SHA-256")
        var received = 0L
        try {
            connection.inputStream.use { input ->
                part.outputStream().use { output ->
                    val buffer = ByteArray(1024 * 1024)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        received += count
                        require(received <= maxPackageSize) { "The Android update exceeded the 1 GiB limit" }
                        digest.update(buffer, 0, count)
                        output.write(buffer, 0, count)
                    }
                }
            }
            require(digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) } == update.sha256) {
                "The downloaded Android package failed verification"
            }
            target.delete()
            check(part.renameTo(target)) { "The verified Android update could not be saved" }
            return target
        } catch (error: Exception) {
            part.delete()
            throw error
        } finally {
            connection.disconnect()
        }
    }

    fun openInstaller(packageFile: File) {
        val uri = FileProvider.getUriForFile(context, "${BuildConfig.APPLICATION_ID}.files", packageFile)
        context.startActivity(Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        })
    }

    private fun readUrl(url: String, limit: Int): String {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 20_000
        connection.readTimeout = 20_000
        connection.setRequestProperty("User-Agent", "TuxInDrive-Android-Updater")
        return try {
            connection.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    require(output.size() + count <= limit) { "The Android update manifest is too large" }
                    output.write(buffer, 0, count)
                }
                output.toString(Charsets.UTF_8.name())
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun versionKey(value: String): List<Int> = value.removePrefix("v").split('.').map {
        it.toIntOrNull() ?: throw IllegalArgumentException("Invalid release version")
    }

    private fun isNewer(candidate: String, current: String): Boolean {
        val left = versionKey(candidate)
        val right = versionKey(current)
        for (index in 0 until maxOf(left.size, right.size)) {
            val comparison = left.getOrElse(index) { 0 }.compareTo(right.getOrElse(index) { 0 })
            if (comparison != 0) return comparison > 0
        }
        return false
    }
}
