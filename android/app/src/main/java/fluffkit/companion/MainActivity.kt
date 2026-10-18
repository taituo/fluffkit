package fluffkit.companion

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings as SysSettings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import kotlinx.coroutines.launch

/**
 * No forms: a few big buttons, a subtitle mode (the phone stands in front of Furby and shows in large text what it
 * heard and what Urho says), and a hidden log. Keys and config come from the Mac (secrets.json / the remote).
 */
class MainActivity : Activity() {
    private val app get() = application as App
    private val c get() = app.companion
    private val ui = Handler(Looper.getMainLooper())
    private val dp get() = resources.displayMetrics.density

    private lateinit var state: TextView
    private lateinit var level: ProgressBar
    private lateinit var listenBtn: Button
    private lateinit var logView: TextView
    private lateinit var logScroll: ScrollView
    private lateinit var main: View
    private lateinit var subs: View
    private lateinit var subHeard: TextView
    private lateinit var subSaying: TextView
    private var subtitles = false
    private val logListener = { refreshLog() }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        val root = FrameLayout(this)
        main = buildMain()
        subs = buildSubtitles()
        root.addView(main); root.addView(subs)
        setContentView(root)
        showSubtitles(app.getSharedPreferences("prefs", MODE_PRIVATE).getBoolean("subtitles", false))
        startIfAllowed()
    }

    private fun big(label: String, colour: Int, f: () -> Unit) = Button(this).apply {
        text = label; textSize = 22f; isAllCaps = false; setTextColor(Color.WHITE)
        background = GradientDrawable().apply { cornerRadius = 18 * dp; setColor(colour) }
        setOnClickListener { f() }
    }

    private fun buildMain(): View {
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val p = (16 * dp).toInt(); setPadding(p, p, p, p)
        }
        state = TextView(this).apply { textSize = 20f; gravity = Gravity.CENTER }
        col.addView(state)
        level = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 1000 }
        col.addView(level, LinearLayout.LayoutParams(MATCH_PARENT, (14 * dp).toInt()).apply { bottomMargin = (12 * dp).toInt() })

        fun row(vararg v: View) = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            v.forEach { addView(it, LinearLayout.LayoutParams(0, (96 * dp).toInt(), 1f).apply { val m = (5 * dp).toInt(); setMargins(m, m, m, m) }) }
            col.addView(this)
        }
        listenBtn = big("", 0xFF1F8A4C.toInt()) { c.setListening(!c.listener.on) }
        row(listenBtn)
        row(big("🌙 Nukkumaan", 0xFF3B3B98.toInt()) { c.scope.launch { c.sleepFurby() } },
            big("☀️ Herää", 0xFFDD8800.toInt()) { c.scope.launch { c.wakeFurby() } })
        row(big("💃 Tanssi", 0xFFD6338A.toInt()) { Commands.run(c, "tag", "tanssi") },
            big("🌈 Vilkku", 0xFF7B2FBE.toInt()) { Commands.run(c, "tag", "vilkku") })
        row(big("💬 Tekstitys", 0xFF444444.toInt()) { showSubtitles(true) })

        // the log and the one-off setup buttons stay out of the way
        val more = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE }
        col.addView(Button(this).apply {
            text = "Loki ja huolto"; isAllCaps = false
            setOnClickListener { more.visibility = if (more.visibility == View.GONE) View.VISIBLE else View.GONE }
        })
        col.addView(more)
        fun small(t: String, f: () -> Unit) = Button(this).apply { text = t; isAllCaps = false; setOnClickListener { f() } }
        more.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            listOf(small("Akku: ei rajoituksia") { askBattery() }, small("Etsi Furby") { c.furby.rescan() },
                small("Lataa asetukset") { c.reload() }).forEach { addView(it, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f)) }
        })
        more.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            listOf(small("Käynnistä / pysäytä") { if (CompanionService.running) CompanionService.stop(this@MainActivity) else startIfAllowed() },
                small("Unohda keskustelu") { c.brain.reset(); Log.i("keskustelu nollattu") })
                .forEach { addView(it, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f)) }
        })
        more.addView(TextView(this).apply {
            textSize = 12f
            text = "Avaimet ja asetukset tulevat koneelta: android/furby_remote.py (tai secrets.json / furby-config.json " +
                "kansioon ${app.settings.dir})."
        })
        logView = TextView(this).apply { typeface = Typeface.MONOSPACE; textSize = 11f; setTextIsSelectable(true) }
        more.addView(logView)

        logScroll = ScrollView(this).apply { addView(col) }
        return logScroll
    }

    private fun buildSubtitles(): View {
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
            setBackgroundColor(Color.BLACK)
            val p = (20 * dp).toInt(); setPadding(p, p, p, p)
            setOnClickListener { showSubtitles(false) }           // tap anywhere to leave
        }
        subHeard = TextView(this).apply { textSize = 22f; setTextColor(0xFF9A9AA8.toInt()); gravity = Gravity.CENTER }
        subSaying = TextView(this).apply { textSize = 40f; setTextColor(Color.WHITE); gravity = Gravity.CENTER; setTypeface(typeface, Typeface.BOLD) }
        col.addView(subHeard, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { bottomMargin = (24 * dp).toInt() })
        col.addView(subSaying, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        return col
    }

    private fun showSubtitles(on: Boolean) {
        subtitles = on
        app.getSharedPreferences("prefs", MODE_PRIVATE).edit().putBoolean("subtitles", on).apply()
        subs.visibility = if (on) View.VISIBLE else View.GONE
        main.visibility = if (on) View.GONE else View.VISIBLE
        // subtitles keep the screen on; otherwise the phone may sleep under Furby
        if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private val tick = object : Runnable {
        @SuppressLint("SetTextI18n")
        override fun run() {
            val f = when (c.furby.state) {
                Furby.State.CONNECTED -> if (c.sleeping) "😴 nukkuu" else "🟢 yhdistetty"
                Furby.State.CONNECTING -> "🟡 yhdistää…"; Furby.State.SCANNING -> "🟡 etsii…"
                Furby.State.DISCONNECTED -> "🔴 ei yhteyttä"
            }
            val mic = when { !CompanionService.running -> "pysäytetty"; !c.listener.on -> "mikki pois"; c.busy -> "miettii"
                c.listener.recording -> "kuulee puhetta"; else -> "kuuntelee" }
            state.text = "Furby $f · $mic\nversio ${app.version}"
            level.progress = (c.listener.level / 0.15f * 1000).toInt().coerceAtMost(1000)
            listenBtn.text = if (c.listener.on) "👂 Kuuntelee — paina: pois" else "🔇 Ei kuuntele — paina: päälle"
            (listenBtn.background as GradientDrawable).setColor(if (c.listener.on) 0xFF1F8A4C.toInt() else 0xFF8A1F2C.toInt())
            if (subtitles) {
                subHeard.text = c.heard.takeIf { it.isNotEmpty() }?.let { "“$it”" } ?: ""
                subSaying.text = c.saying.ifEmpty { if (c.busy) "…" else "" }
            }
            ui.postDelayed(this, 150)
        }
    }

    override fun onResume() { super.onResume(); Log.listen(logListener); refreshLog(); ui.post(tick) }
    override fun onPause() { super.onPause(); Log.unlisten(logListener); ui.removeCallbacks(tick) }

    private fun refreshLog() {
        if (!::logView.isInitialized) return
        logView.text = Log.text().lines().takeLast(120).joinToString("\n")
    }

    private fun needed(): List<String> = buildList {
        add(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= 31) { add(Manifest.permission.BLUETOOTH_SCAN); add(Manifest.permission.BLUETOOTH_CONNECT) }
        else add(Manifest.permission.ACCESS_FINE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
    }.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }

    private fun startIfAllowed() {
        val missing = needed()
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)
        else if (!CompanionService.running) CompanionService.start(this)
    }

    override fun onRequestPermissionsResult(code: Int, perms: Array<out String>, res: IntArray) {
        if (needed().isEmpty()) CompanionService.start(this) else Log.i("luvat puuttuvat: ${needed().joinToString()}")
    }

    @SuppressLint("BatteryLife")
    private fun askBattery() {
        val pm = getSystemService(PowerManager::class.java)
        if (pm.isIgnoringBatteryOptimizations(packageName)) Log.i("akun optimointi on jo pois")
        else startActivity(Intent(SysSettings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
    }
}
