package io.github.tuxindrive.mobile

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import org.rclone.gomobile.Gomobile
import java.io.File

data class CloudItem(
    val name: String,
    val path: String,
    val size: Long,
    val isDirectory: Boolean,
)

class RcloneException(message: String) : RuntimeException(message)

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

    fun importConfiguration(uri: Uri) {
        val temporary = File(configuration.parentFile, "rclone.conf.new")
        context.contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Selected configuration could not be opened" }
            temporary.outputStream().use { output ->
                val buffer = ByteArray(64 * 1024)
                var total = 0
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    total += count
                    if (total > 2 * 1024 * 1024) {
                        temporary.delete()
                        throw RcloneException("The configuration exceeds the 2 MiB safety limit")
                    }
                    output.write(buffer, 0, count)
                }
            }
        }
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

    fun initialize() = core.initialize()
    fun engineVersion() = core.version()
    fun importConfiguration(uri: Uri) = core.importConfiguration(uri)
    fun unlock(password: String) = core.unlock(password)
    fun remotes() = core.listRemotes()
    fun files(remote: String, path: String = "") = core.list(remote, path)
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
    ) = core.bisync(local, remote, remotePath, workDirectory, firstRun)
}
