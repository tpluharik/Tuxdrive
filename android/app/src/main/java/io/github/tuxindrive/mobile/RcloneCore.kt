package io.github.tuxindrive.mobile

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import org.rclone.gomobile.Gomobile
import java.io.File
import java.util.concurrent.Semaphore

data class CloudItem(
    val name: String,
    val path: String,
    val size: Long,
    val isDirectory: Boolean,
)

class RcloneException(message: String) : RuntimeException(message)

object MobileNetworkController {
    private val gate = Semaphore(1, true)

    fun <T> exclusive(operation: () -> T): T {
        gate.acquire()
        return try {
            operation()
        } finally {
            gate.release()
        }
    }
}

class RcloneCore(private val context: Context) {
    private val configuration = File(context.noBackupFilesDir, "rclone.conf")
    private var initialized = false

    @Synchronized
    fun initialize() {
        if (initialized) return
        Gomobile.rcloneInitialize()
        initialized = true
        rpc("config/setpath", JSONObject().put("path", configuration.absolutePath))
    }

    @Synchronized
    fun close() {
        if (initialized) {
            Gomobile.rcloneFinalize()
            initialized = false
        }
    }

    fun version(): String = rpc("core/version").optString("version", "rclone")

    fun setBandwidthLimit(rate: String) {
        rpc("core/bwlimit", JSONObject().put("rate", rate.ifBlank { "off" }))
    }

    fun importConfiguration(uri: Uri) {
        replaceConfiguration(readConfiguration(uri, 2 * 1024 * 1024))
    }

    fun importProfile(uri: Uri, password: String) {
        replaceConfiguration(ProfileImporter(context).rcloneConfiguration(uri, password))
    }

    private fun readConfiguration(uri: Uri, limit: Int): ByteArray {
        val bytes = context.contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Selected configuration could not be opened" }
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                total += count
                if (total > limit) throw RcloneException("The configuration exceeds the 2 MiB safety limit")
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        }
        return bytes
    }

    private fun replaceConfiguration(bytes: ByteArray) {
        require(bytes.size <= 2 * 1024 * 1024) { "The cloud configuration exceeds the 2 MiB safety limit" }
        val temporary = File(configuration.parentFile, "rclone.conf.new")
        temporary.writeBytes(bytes)
        if (!temporary.renameTo(configuration)) {
            temporary.copyTo(configuration, overwrite = true)
            temporary.delete()
        }
        rpc("config/setpath", JSONObject().put("path", configuration.absolutePath))
    }

    fun unlock(password: String) {
        if (password.isBlank()) throw RcloneException("Enter the configuration password")
        rpc("config/unlock", JSONObject().put("configPassword", password))
    }

    fun listRemotes(): List<String> {
        val values = rpc("config/listremotes").optJSONArray("remotes") ?: JSONArray()
        return (0 until values.length()).map { values.getString(it).removeSuffix(":") }
    }

    fun list(remote: String, path: String = ""): List<CloudItem> {
        val input = JSONObject()
            .put("fs", "${remote.removeSuffix(":")}:")
            .put("remote", path)
            .put("opt", JSONObject().put("showHash", false))
        val values = rpc("operations/list", input).optJSONArray("list") ?: JSONArray()
        return (0 until values.length()).map { index ->
            val item = values.getJSONObject(index)
            CloudItem(
                name = item.optString("Name", item.optString("Path")),
                path = item.optString("Path"),
                size = item.optLong("Size"),
                isDirectory = item.optBoolean("IsDir"),
            )
        }.sortedWith(compareBy<CloudItem> { !it.isDirectory }.thenBy { it.name.lowercase() })
    }

    fun bisync(local: File, remote: String, remotePath: String, workDirectory: File, firstRun: Boolean) {
        setBandwidthLimit(
            context.getSharedPreferences("mobile-state", Context.MODE_PRIVATE)
                .getString("global-bandwidth-limit", "10M").orEmpty(),
        )
        local.mkdirs()
        workDirectory.mkdirs()
        val destination = "${remote.removeSuffix(":")}:$remotePath"
        val input = JSONObject()
            .put("path1", local.absolutePath)
            .put("path2", destination)
            .put("workdir", workDirectory.absolutePath)
            .put("resilient", true)
            .put("recover", true)
            .put("maxDelete", 25)
            .put("conflictResolve", "none")
            .put("conflictLoser", "num")
            .put("createEmptySrcDirs", true)
        if (firstRun) {
            input.put("resync", true)
            input.put("resyncMode", "newer")
        }
        rpc("sync/bisync", input)
    }

    private fun rpc(method: String, input: JSONObject = JSONObject()): JSONObject {
        initialize()
        val result = Gomobile.rcloneRPC(method, input.toString())
        val output = result.output.orEmpty()
        if (result.status !in 200..299) {
            val message = runCatching {
                JSONObject(output).optString("error").ifBlank { output }
            }.getOrDefault(output)
            throw RcloneException(message.ifBlank { "$method failed (${result.status})" })
        }
        return if (output.isBlank()) JSONObject() else JSONObject(output)
    }
}

class MobileRepository(context: Context) {
    private val appContext = context.applicationContext
    private val core = RcloneCore(appContext)
    private val preferences = appContext.getSharedPreferences("mobile-state", Context.MODE_PRIVATE)
    private val updater = AndroidUpdater(appContext)

    fun initialize() {
        core.initialize()
        core.setBandwidthLimit(bandwidthLimit())
    }
    fun engineVersion() = core.version()
    fun checkUpdate() = MobileNetworkController.exclusive { updater.check() }
    fun downloadUpdate(update: AndroidUpdate) =
        MobileNetworkController.exclusive { updater.download(update) }
    fun installUpdate(packageFile: File) = updater.openInstaller(packageFile)
    fun importConfiguration(uri: Uri) = core.importConfiguration(uri)
    fun importProfile(uri: Uri, password: String) = core.importProfile(uri, password)
    fun unlock(password: String) = core.unlock(password)
    fun remotes() = core.listRemotes()
    fun files(remote: String, path: String = "") =
        MobileNetworkController.exclusive { core.list(remote, path) }
    fun selectedTree(): String = preferences.getString("selected-tree", "").orEmpty()

    fun selectTree(uri: Uri) {
        appContext.contentResolver.takePersistableUriPermission(
            uri,
            android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or
                android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
        )
        preferences.edit().putString("selected-tree", uri.toString()).apply()
    }

    fun saveSyncTarget(remote: String, remotePath: String) {
        preferences.edit()
            .putString("sync-remote", remote.removeSuffix(":"))
            .putString("sync-remote-path", remotePath.trim('/'))
            .apply()
    }

    fun syncRemote(): String = preferences.getString("sync-remote", "").orEmpty()
    fun syncRemotePath(): String = preferences.getString("sync-remote-path", "").orEmpty()
    fun lastSyncStatus(): String = preferences.getString("last-sync-status", "Not synchronized yet").orEmpty()
    fun wifiOnly(): Boolean = preferences.getBoolean("wifi-only", true)
    fun chargingOnly(): Boolean = preferences.getBoolean("charging-only", false)
    fun automaticSync(): Boolean = preferences.getBoolean("automatic-sync", false)
    fun showNetworkUsage(): Boolean = preferences.getBoolean("show-network-usage", true)
    fun bandwidthLimit(): String = preferences.getString("global-bandwidth-limit", "10M").orEmpty()

    fun setBandwidthLimit(value: String): Boolean {
        val normalized = value.trim()
        val valid = normalized.isBlank() || normalized.split(':').let { parts ->
            parts.size <= 2 && parts.all { part ->
                part.equals("off", ignoreCase = true) ||
                    Regex("\\d+(?:\\.\\d+)?[BKMGTP]?", RegexOption.IGNORE_CASE).matches(part)
            }
        }
        if (!valid) return false
        preferences.edit().putString("global-bandwidth-limit", normalized).apply()
        runCatching { core.setBandwidthLimit(normalized) }
        return true
    }

    fun setShowNetworkUsage(enabled: Boolean) {
        preferences.edit().putBoolean("show-network-usage", enabled).apply()
    }

    fun enqueueSync(wifiOnly: Boolean, chargingOnly: Boolean) {
        preferences.edit()
            .putBoolean("wifi-only", wifiOnly)
            .putBoolean("charging-only", chargingOnly)
            .apply()
        MobileSyncWorker.enqueue(appContext, wifiOnly, chargingOnly)
    }

    fun configureAutomaticSync(enabled: Boolean, wifiOnly: Boolean, chargingOnly: Boolean) {
        preferences.edit()
            .putBoolean("automatic-sync", enabled)
            .putBoolean("wifi-only", wifiOnly)
            .putBoolean("charging-only", chargingOnly)
            .apply()
        MobileSyncWorker.schedule(appContext, enabled, wifiOnly, chargingOnly)
    }

    fun runBisync(
        local: File,
        remote: String,
        remotePath: String,
        workDirectory: File,
        firstRun: Boolean,
    ) = MobileNetworkController.exclusive {
        core.bisync(local, remote, remotePath, workDirectory, firstRun)
    }
}
