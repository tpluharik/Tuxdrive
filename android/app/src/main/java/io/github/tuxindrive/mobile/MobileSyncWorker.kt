package io.github.tuxindrive.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.documentfile.provider.DocumentFile
import androidx.work.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.TimeUnit

class MobileSyncWorker(
    appContext: Context,
    parameters: WorkerParameters,
) : CoroutineWorker(appContext, parameters) {
    private val repository = (appContext.applicationContext as TuxInDriveMobileApp).repository
    private val preferences = appContext.getSharedPreferences("mobile-state", Context.MODE_PRIVATE)

    override suspend fun doWork(): Result = syncMutex.withLock { withContext(Dispatchers.IO) {
        setForeground(foregroundInfo("Preparing synchronization…"))
        val treeValue = repository.selectedTree()
        val remote = repository.syncRemote()
        if (treeValue.isBlank() || remote.isBlank()) {
            return@withContext failure("Choose an offline folder and cloud account first")
        }
        val tree = DocumentFile.fromTreeUri(applicationContext, Uri.parse(treeValue))
            ?: return@withContext failure("The selected Android folder is no longer available")
        val root = File(applicationContext.noBackupFilesDir, "sync")
        val mirror = File(root, "mirror")
        val incoming = File(root, "incoming")
        val baseline = File(root, "baseline.ready")
        val workdir = File(root, "bisync")
        return@withContext runCatching {
            incoming.deleteRecursively()
            incoming.mkdirs()
            copyFromDocuments(tree, incoming)
            guardMassDeletion(mirror, incoming)
            mirror.deleteRecursively()
            if (!incoming.renameTo(mirror)) {
                incoming.copyRecursively(mirror, overwrite = true)
                incoming.deleteRecursively()
            }
            setForeground(foregroundInfo("Synchronizing cloud files…"))
            repository.runBisync(mirror, remote, repository.syncRemotePath(), workdir, !baseline.exists())
            setForeground(foregroundInfo("Updating offline folder…"))
            copyToDocuments(mirror, tree)
            baseline.parentFile?.mkdirs()
            baseline.writeText("ready\n")
            success("Synchronization complete")
        }.getOrElse { error ->
            failure(error.message ?: "Synchronization failed")
        }
    } }

    private fun copyFromDocuments(source: DocumentFile, destination: File) {
        for (document in source.listFiles()) {
            val name = document.name ?: continue
            if (name in setOf(".", "..") || '/' in name || '\\' in name) continue
            val target = File(destination, name)
            if (document.isDirectory) {
                target.mkdirs()
                copyFromDocuments(document, target)
            } else if (document.isFile) {
                applicationContext.contentResolver.openInputStream(document.uri).use { input ->
                    requireNotNull(input) { "Could not read $name" }
                    target.outputStream().use { output -> input.copyTo(output) }
                }
            }
        }
    }

    private fun copyToDocuments(source: File, destination: DocumentFile) {
        val existing = destination.listFiles().associateBy { it.name.orEmpty() }.toMutableMap()
        for (local in source.listFiles().orEmpty()) {
            val current = existing.remove(local.name)
            if (local.isDirectory) {
                val folder = if (current?.isDirectory == true) current else {
                    current?.delete()
                    destination.createDirectory(local.name)
                } ?: throw RcloneException("Could not create ${local.name}")
                copyToDocuments(local, folder)
            } else {
                val document = if (current?.isFile == true) current else {
                    current?.delete()
                    destination.createFile("application/octet-stream", local.name)
                } ?: throw RcloneException("Could not create ${local.name}")
                applicationContext.contentResolver.openOutputStream(document.uri, "rwt").use { output ->
                    requireNotNull(output) { "Could not write ${local.name}" }
                    local.inputStream().use { input -> input.copyTo(output) }
                }
            }
        }
        val removals = existing.values.toList()
        val removedCount = removals.sumOf(::documentCount)
        val total = removedCount + source.walkTopDown().count { it != source }
        if (removedCount >= 10 && removedCount * 100 > total.coerceAtLeast(1) * 25) {
            throw RcloneException("Safety stop: cloud changes would remove too many Android files")
        }
        removals.forEach { it.delete() }
    }

    private fun documentCount(document: DocumentFile): Int =
        1 + if (document.isDirectory) document.listFiles().sumOf(::documentCount) else 0

    private fun guardMassDeletion(previous: File, current: File) {
        if (!previous.exists()) return
        val before = previous.walkTopDown().filter { it.isFile }.map { it.relativeTo(previous).path }.toSet()
        val after = current.walkTopDown().filter { it.isFile }.map { it.relativeTo(current).path }.toSet()
        val removed = before - after
        if (removed.size >= 10 && removed.size * 100 > before.size.coerceAtLeast(1) * 25) {
            throw RcloneException("Safety stop: local changes would remove too many cloud files")
        }
    }

    private fun success(message: String): Result {
        preferences.edit().putString("last-sync-status", message).apply()
        return Result.success()
    }

    private fun failure(message: String): Result {
        preferences.edit().putString("last-sync-status", message).apply()
        return Result.failure()
    }

    private fun foregroundInfo(message: String): ForegroundInfo {
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "TuxInDrive synchronization", NotificationManager.IMPORTANCE_LOW),
            )
        }
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("TuxInDrive")
            .setContentText(message)
            .setOngoing(true)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(
                NOTIFICATION_ID,
                notification,
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        private const val CHANNEL = "tuxindrive-sync"
        private const val NOTIFICATION_ID = 253
        private val syncMutex = Mutex()

        fun enqueue(context: Context, wifiOnly: Boolean, chargingOnly: Boolean) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
                .setRequiresCharging(chargingOnly)
                .build()
            val request = OneTimeWorkRequestBuilder<MobileSyncWorker>()
                .setConstraints(constraints)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                "tuxindrive-mobile-sync",
                ExistingWorkPolicy.KEEP,
                request,
            )
        }

        fun schedule(context: Context, enabled: Boolean, wifiOnly: Boolean, chargingOnly: Boolean) {
            val manager = WorkManager.getInstance(context)
            if (!enabled) {
                manager.cancelUniqueWork("tuxindrive-mobile-periodic-sync")
                return
            }
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
                .setRequiresCharging(chargingOnly)
                .build()
            val request = PeriodicWorkRequestBuilder<MobileSyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()
            manager.enqueueUniquePeriodicWork(
                "tuxindrive-mobile-periodic-sync",
                ExistingPeriodicWorkPolicy.UPDATE,
                request,
            )
        }
    }
}
