package fluffkit.companion

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings as SysSettings
import android.text.InputType
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import kotlinx.coroutines.launch

/** The small debug screen: state, log, test buttons and the keys. Everything real happens in the service. */
class MainActivity : Activity() {
    private val app get() = application as App
    private val c get() = app.companion
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var state: TextView
    private lateinit var level: ProgressBar
    private lateinit var logView: TextView
    private lateinit var scroll: ScrollView
    private lateinit var serviceBtn: Button
    private lateinit var listenBtn: Button
    private val logListener = { refreshLog() }

    @SuppressLint("SetTextI18n")
    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        val dp = resources.displayMetrics.density
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding((16 * dp).toInt(), (12 * dp).toInt(), (16 * dp).toInt(), (40 * dp).toInt()) }
        scroll = ScrollView(this).apply { addView(root); isFillViewport = true }
        setContentView(scroll)

        fun row(vararg v: View) = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            v.forEach { addView(it, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f)) }
            root.addView(this)
        }
        fun button(t: String, f: () -> Unit) = Button(this).apply { text = t; isAllCaps = false; setOnClickListener { f() } }
        fun heading(t: String) = root.addView(TextView(this).apply { text = t; textSize = 13f; setPadding(0, (14 * dp).toInt(), 0, (4 * dp).toInt()); setTypeface(typeface, Typeface.BOLD) })
        fun field(hint: String, password: Boolean = false) = EditText(this).apply {
            this.hint = hint; isSingleLine = true
            inputType = if (password) InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD else InputType.TYPE_CLASS_TEXT
        }

        state = TextView(this).apply { textSize = 18f }
        root.addView(state)
        level = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 1000 }
        root.addView(level, LinearLayout.LayoutParams(MATCH_PARENT, (16 * dp).toInt()))

        serviceBtn = button("") { if (CompanionService.running) CompanionService.stop(this) else startIfAllowed() }
        listenBtn = button("") { c.setListening(!c.listener.on) }
        row(serviceBtn, listenBtn)
        row(button("Etsi Furby uudelleen") { c.furby.rescan() }, button("Akku: ei rajoituksia") { askBattery() })

        val thrLabel = TextView(this)
        val thr = SeekBar(this).apply {
            max = 29; progress = ((app.settings.threshold - 0.005f) / 0.005f).toInt()
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(s: SeekBar, p: Int, user: Boolean) {
                    val v = 0.005f + p * 0.005f
                    if (user) app.settings.threshold = v
                    thrLabel.text = "kynnys %.3f".format(v)
                }
                override fun onStartTrackingTouch(s: SeekBar) {}
                override fun onStopTrackingTouch(s: SeekBar) {}
            })
        }
        thrLabel.text = "kynnys %.3f".format(app.settings.threshold)
        root.addView(thrLabel); root.addView(thr)

        heading("Juttele")
        val chat = field("Kysy Furbylta jotain…")
        row(chat).addView(button("Kysy") { val t = chat.text.toString().trim(); chat.setText(""); if (t.isNotEmpty()) c.scope.launch { c.chat(t) } })
        val say = field("Mitä Furby sanoo?")
        row(say).addView(button("Sano") { val t = say.text.toString().trim(); if (t.isNotEmpty()) c.scope.launch { c.speak(t) } })

        heading("Testit")
        row(button("Nokka 2 s") { c.items.firstOrNull { it.talk == 2.0 }?.let { c.act(it.action, "testi") } },
            button("Liike") { c.items.filter { it.gesture }.randomOrNull()?.let { c.act(it.action, "testi") } },
            button("Nauru") { c.scope.launch { c.chat("Naura kerran isosti.") } })
        row(button("🟢") { c.furby.send(0x14, 0, 255, 40) }, button("🟠") { c.furby.send(0x14, 255, 170, 0) },
            button("🩷") { c.furby.send(0x14, 255, 0, 150) }, button("⚫") { c.furby.send(0x14, 0, 0, 0) })
        row(button("Lataa asetukset") { c.reload() }, button("Unohda keskustelu") { c.brain.reset(); Log.i("keskustelu nollattu") })

        heading("Avaimet (salattuna vain tässä puhelimessa)")
        val s = app.settings
        val key = field(if (s.elevenKey.isBlank()) "ElevenLabs API key" else "ElevenLabs: tallennettu ✓", password = true)
        val url = field("aivot: URL").apply { setText(s.llmUrl) }
        val bearer = field(if (s.llmBearer.isBlank()) "aivot: bearer" else "bearer: tallennettu ✓", password = true)
        val model = field("aivot: malli").apply { setText(s.llmModel) }
        listOf(key, url, bearer, model).forEach { root.addView(it) }
        root.addView(button("Tallenna") {
            key.text.toString().trim().takeIf { it.isNotEmpty() }?.let { s.elevenKey = it; key.setText(""); key.hint = "ElevenLabs: tallennettu ✓" }
            bearer.text.toString().trim().takeIf { it.isNotEmpty() }?.let { s.llmBearer = it; bearer.setText(""); bearer.hint = "bearer: tallennettu ✓" }
            url.text.toString().trim().takeIf { it.isNotEmpty() }?.let { s.llmUrl = it }
            model.text.toString().trim().takeIf { it.isNotEmpty() }?.let { s.llmModel = it }
            Log.i("asetukset tallennettu")
            c.scope.launch { c.prepareSounds() }
        })
        root.addView(TextView(this).apply {
            textSize = 12f
            text = "Muokattavat tiedostot: ${s.dir}/ furby-config.json, AGENTS.md, packs.json (Lataa asetukset). " +
                "secrets.json tuodaan ja poistetaan käynnistyksessä."
        })

        heading("Loki")
        logView = TextView(this).apply { typeface = Typeface.MONOSPACE; textSize = 11f; setTextIsSelectable(true) }
        root.addView(logView)

        startIfAllowed()
    }

    private val tick = object : Runnable {
        @SuppressLint("SetTextI18n")
        override fun run() {
            val f = when (c.furby.state) {
                Furby.State.CONNECTED -> "🟢 yhdistetty"; Furby.State.CONNECTING -> "🟡 yhdistää…"
                Furby.State.SCANNING -> "🟡 etsii…"; Furby.State.DISCONNECTED -> "🔴 ei yhteyttä"
            }
            val mic = when { !c.listener.on -> "mikki pois"; c.busy -> "miettii"; c.listener.recording -> "kuulee puhetta"; else -> "kuuntelee" }
            state.text = "Furby $f · $mic"
            level.progress = (c.listener.level / 0.15f * 1000).toInt().coerceAtMost(1000)
            serviceBtn.text = if (CompanionService.running) "Pysäytä" else "Käynnistä"
            listenBtn.text = "👂 Kuuntelu: " + if (c.listener.on) "päällä" else "pois"
            ui.postDelayed(this, 100)
        }
    }

    override fun onResume() { super.onResume(); Log.listen(logListener); refreshLog(); ui.post(tick) }
    override fun onPause() { super.onPause(); Log.unlisten(logListener); ui.removeCallbacks(tick) }

    private fun refreshLog() {
        val atEnd = scroll.scrollY + scroll.height >= scroll.getChildAt(0).height - 50
        logView.text = Log.text()
        if (atEnd) scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
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
