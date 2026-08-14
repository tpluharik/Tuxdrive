package io.github.tuxindrive.mobile

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.util.Base64
import java.util.zip.InflaterInputStream
import java.util.zip.ZipException

data class ProfileQrProgress(
    val received: Int,
    val total: Int,
    val profile: ByteArray? = null,
)

class ProfileQrAssembler {
    private var transferId = ""
    private var expectedTotal = 0
    private var expectedDigest = ""
    private val chunks = mutableMapOf<Int, String>()

    fun reset() {
        transferId = ""
        expectedTotal = 0
        expectedDigest = ""
        chunks.clear()
    }

    fun add(value: String): ProfileQrProgress {
        val parts = value.split('/', limit = 7)
        require(parts.size == 7 && parts[0] == "TUXINDRIVE-PROFILE" && parts[1] == "1") {
            "This is not a TuxInDrive profile QR frame"
        }
        val id = parts[2]
        val index = parts[3].toIntOrNull() ?: 0
        val total = parts[4].toIntOrNull() ?: 0
        val digest = parts[5]
        val chunk = parts[6]
        require(id.matches(Regex("[0-9a-f]{16}")) && digest.matches(Regex("[0-9a-f]{64}"))) {
            "The profile QR identity is invalid"
        }
        require(total in 1..256 && index in 1..total && chunk.length in 1..1400 &&
            chunk.matches(Regex("[A-Za-z0-9_-]+"))) {
            "The profile QR frame is outside the safety limits"
        }
        if (transferId.isBlank()) {
            transferId = id
            expectedTotal = total
            expectedDigest = digest
        }
        require(id == transferId && total == expectedTotal && digest == expectedDigest) {
            "This frame belongs to a different profile transfer; reset the scan first"
        }
        chunks[index] = chunk
        if (chunks.size != expectedTotal) return ProfileQrProgress(chunks.size, expectedTotal)
        val encoded = (1..expectedTotal).joinToString("") { chunks.getValue(it) }
        val padding = "=".repeat((4 - encoded.length % 4) % 4)
        val compressed = try {
            Base64.getUrlDecoder().decode(encoded + padding)
        } catch (_: IllegalArgumentException) {
            throw IllegalArgumentException("The profile QR data is invalid")
        }
        val profile = try {
            boundedInflate(compressed)
        } catch (_: ZipException) {
            throw IllegalArgumentException("The profile QR data is invalid")
        }
        val actual = MessageDigest.getInstance("SHA-256").digest(profile)
            .joinToString("") { "%02x".format(it) }
        require(actual == expectedDigest && actual.startsWith(transferId)) {
            "The profile QR transfer failed its integrity check"
        }
        return ProfileQrProgress(chunks.size, expectedTotal, profile)
    }

    private fun boundedInflate(compressed: ByteArray): ByteArray {
        val output = ByteArrayOutputStream()
        InflaterInputStream(ByteArrayInputStream(compressed)).use { input ->
            val buffer = ByteArray(16 * 1024)
            var total = 0
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                total += count
                require(total <= 2 * 1024 * 1024) { "The QR profile exceeds the 2 MiB safety limit" }
                output.write(buffer, 0, count)
            }
        }
        return output.toByteArray()
    }
}
