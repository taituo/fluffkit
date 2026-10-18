package fluffkit.companion

import android.app.Application
import android.os.Handler
import android.os.Looper
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.CopyOnWriteArrayList

/** Process-wide singletons: the companion lives as long as the process, the service only keeps it awake. */
class App : Application() {
    lateinit var settings: Settings
    lateinit var companion: FurbyCompanion

    val version: String by lazy { packageManager.getPackageInfo(packageName, 0).versionName ?: "?" }

    override fun onCreate() {
        super.onCreate()
        instance = this
        Log.i("Furby companion $version")
        settings = Settings(this)
        settings.importFromFile()
        companion = FurbyCompanion(this, settings)
    }

    companion object {
        lateinit var instance: App
    }
}

/** The log the debug screen shows (also mirrored to logcat under the tag "Furby"). */
object Log {
    private const val MAX = 400
    private val lines = ArrayDeque<String>()
    private val listeners = CopyOnWriteArrayList<() -> Unit>()
    private val main = Handler(Looper.getMainLooper())
    private val fmt = SimpleDateFormat("HH:mm:ss", Locale.ROOT)

    fun i(text: String) {
        android.util.Log.i("Furby", text)
        synchronized(lines) {
            lines.addLast(fmt.format(Date()) + "  " + text)
            while (lines.size > MAX) lines.removeFirst()
        }
        main.post { listeners.forEach { it() } }
    }

    fun text(): String = synchronized(lines) { lines.joinToString("\n") }
    fun listen(f: () -> Unit) = listeners.add(f)
    fun unlisten(f: () -> Unit) = listeners.remove(f)
}
