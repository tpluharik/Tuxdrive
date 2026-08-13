package io.github.tuxindrive.mobile

import android.content.Context
import android.net.TrafficStats
import java.time.LocalDate

data class MobileNetworkUsage(
    val downloadRate: Long = 0,
    val uploadRate: Long = 0,
    val downloadedToday: Long = 0,
    val uploadedToday: Long = 0,
    val available: Boolean = true,
)

class NetworkUsageMeter(context: Context) {
    private val preferences = context.getSharedPreferences("network-usage", Context.MODE_PRIVATE)
    private var day = LocalDate.now().toString()
    private var downloaded = 0L
    private var uploaded = 0L
    private var previousRx = TrafficStats.getTotalRxBytes()
    private var previousTx = TrafficStats.getTotalTxBytes()
    private var previousTime = System.nanoTime()
    private var lastSavedTime = 0L

    init {
        if (preferences.getString("day", "") == day) {
            downloaded = preferences.getLong("downloaded", 0).coerceAtLeast(0)
            uploaded = preferences.getLong("uploaded", 0).coerceAtLeast(0)
            downloaded += delta(previousRx, preferences.getLong("rx", previousRx))
            uploaded += delta(previousTx, preferences.getLong("tx", previousTx))
        }
        save()
    }

    fun current(): MobileNetworkUsage = MobileNetworkUsage(
        downloadedToday = downloaded,
        uploadedToday = uploaded,
        available = countersAvailable(),
    )

    fun sample(): MobileNetworkUsage {
        val nowDay = LocalDate.now().toString()
        val rx = TrafficStats.getTotalRxBytes()
        val tx = TrafficStats.getTotalTxBytes()
        val now = System.nanoTime()
        if (nowDay != day) {
            day = nowDay
            downloaded = 0
            uploaded = 0
        }
        if (rx < 0 || tx < 0) return MobileNetworkUsage(
            downloadedToday = downloaded, uploadedToday = uploaded, available = false,
        )
        val elapsedSeconds = ((now - previousTime).coerceAtLeast(1) / 1_000_000_000.0)
        val downDelta = delta(rx, previousRx)
        val upDelta = delta(tx, previousTx)
        downloaded += downDelta
        uploaded += upDelta
        previousRx = rx
        previousTx = tx
        previousTime = now
        if (now - lastSavedTime >= 60_000_000_000L) save()
        return MobileNetworkUsage(
            (downDelta / elapsedSeconds).toLong(),
            (upDelta / elapsedSeconds).toLong(),
            downloaded, uploaded, true,
        )
    }

    fun save() {
        if (!countersAvailable()) return
        preferences.edit()
            .putString("day", day)
            .putLong("downloaded", downloaded)
            .putLong("uploaded", uploaded)
            .putLong("rx", previousRx)
            .putLong("tx", previousTx)
            .apply()
        lastSavedTime = System.nanoTime()
    }

    private fun countersAvailable() = previousRx >= 0 && previousTx >= 0
    private fun delta(current: Long, previous: Long) = if (current >= previous && previous >= 0) current - previous else 0
}
