package fluffkit.companion

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.Dialog
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
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
import android.view.ViewGroup
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import kotlinx.coroutines.launch

/**
 * Furby's own pink screen: an animated Furby in the antenna colour of the moment, status chips, subtitles,
 * a sensitivity slider over a live level meter, a few big buttons, and everything else in a bottom sheet.
 * No forms: keys and config come from the Mac (android/furby_remote.py).
 */
class MainActivity : Activity() {
    private val app get() = application as App
    private val c get() = app.companion
    private val ui = Handler(Looper.getMainLooper())
    private val dp get() = resources.displayMetrics.density
    private fun px(v: Int) = (v * dp).toInt()

    private lateinit var chipFurby: TextView
    private lateinit var chipBrain: TextView
    private lateinit var chipMic: TextView
    private lateinit var moodLabel: TextView
    private lateinit var heardText: TextView
    private lateinit var sayingText: TextView
    private lateinit var thrLabel: TextView
    private lateinit var slider: SeekBar
    private lateinit var listenCard: LinearLayout
    private lateinit var listenLabel: TextView
    private lateinit var main: View
    private lateinit var subs: View
    private lateinit var subHeard: TextView
    private lateinit var subSaying: TextView
    private var logView: TextView? = null
    private var subtitles = false
    private val logListener = { refreshLog() }

    private companion object {
        const val INK = 0xFF2A1B3D.toInt()
        const val MUTED = 0xFF8A6B86.toInt()
        const val PINK = 0xFFFF3D9A.toInt()
        const val CARD = 0xF2FFFFFF.toInt()
    }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        window.statusBarColor = 0xFFFF8CC6.toInt()
        window.navigationBarColor = 0xFFFFD1E8.toInt()
        val root = FrameLayout(this)
        main = buildMain(); subs = buildSubtitles()
        root.addView(main); root.addView(subs)
        setContentView(root)
        showSubtitles(app.getSharedPreferences("prefs", MODE_PRIVATE).getBoolean("subtitles", false))
        startIfAllowed()
    }

    // ---- building blocks ----

    private fun rounded(colour: Int, radius: Int) = GradientDrawable().apply { cornerRadius = px(radius).toFloat(); setColor(colour) }

    private fun text(t: String = "", size: Float, colour: Int = INK, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(colour); if (bold) typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
    }

    private fun card(parent: ViewGroup, pad: Int = 18): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = rounded(CARD, 28); elevation = px(6).toFloat()
        setPadding(px(pad), px(pad), px(pad), px(pad))
        parent.addView(this, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { setMargins(px(16), px(8), px(16), px(8)) })
    }

    private fun chip(): TextView = text("", 13f, INK, true).apply {
        background = rounded(0xCCFFFFFF.toInt(), 20); setPadding(px(12), px(6), px(12), px(6)); gravity = Gravity.CENTER
    }

    private fun bigButton(emoji: String, label: String, colour: Int, f: () -> Unit): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
        background = rounded(colour, 26); elevation = px(5).toFloat()
        setPadding(px(8), px(14), px(8), px(14))
        addView(text(emoji, 34f).apply { gravity = Gravity.CENTER })
        addView(text(label, 16f, Color.WHITE, true).apply { gravity = Gravity.CENTER })
        isClickable = true; isFocusable = true
        setOnClickListener { animate().scaleX(0.94f).scaleY(0.94f).setDuration(80).withEndAction { animate().scaleX(1f).scaleY(1f).setDuration(120) }; f() }
    }

    private fun buildMain(): View {
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, px(12), 0, px(28)) }

        // title row
        val title = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(px(22), px(4), px(16), px(4)) }
        title.addView(text("Urho", 34f, Color.WHITE, true))
        title.addView(text("  v${app.version}", 13f, 0xCCFFFFFF.toInt()), LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        title.addView(text("⚙", 26f, Color.WHITE).apply {
            gravity = Gravity.CENTER; background = rounded(0x33FFFFFF, 24); setPadding(px(12), px(4), px(12), px(4))
            setOnClickListener { openSheet() }
        })
        col.addView(title)

        // status chips
        val chips = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(px(16), px(6), px(16), px(6)) }
        chipFurby = chip(); chipBrain = chip(); chipMic = chip()
        listOf(chipFurby, chipBrain, chipMic).forEach {
            chips.addView(it, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f).apply { setMargins(px(4), 0, px(4), 0) })
        }
        col.addView(chips)

        // the Furby + subtitles
        val hero = card(col, 10)
        hero.addView(FurbyView(this) { c.mood }, LinearLayout.LayoutParams(MATCH_PARENT, px(250)))
        moodLabel = text("", 18f, PINK, true).apply { gravity = Gravity.CENTER }
        hero.addView(moodLabel)
        heardText = text("", 15f, MUTED).apply { gravity = Gravity.CENTER; setPadding(px(8), px(10), px(8), 0) }
        sayingText = text("", 22f, INK, true).apply { gravity = Gravity.CENTER; setPadding(px(8), px(4), px(8), px(8)) }
        hero.addView(heardText); hero.addView(sayingText)

        // sensitivity
        val sens = card(col)
        val sensHead = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        sensHead.addView(text("Kuulon herkkyys", 16f, INK, true), LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        thrLabel = text("", 13f, MUTED); sensHead.addView(thrLabel)
        sens.addView(sensHead)
        sens.addView(LevelMeter(this, { c.listener.level }, { c.listener.peak }, { c.threshold }),
            LinearLayout.LayoutParams(MATCH_PARENT, px(18)).apply { topMargin = px(10) })
        slider = SeekBar(this).apply {
            max = 1000
            progressTintList = ColorStateList.valueOf(PINK); thumbTintList = ColorStateList.valueOf(PINK)
            progressBackgroundTintList = ColorStateList.valueOf(0xFFFCE4F1.toInt())
            // the slider sits on the meter's log scale: its knob is the threshold mark
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(s: SeekBar, p: Int, user: Boolean) { if (user) app.settings.threshold = LevelMeter.value(p / 1000f) }
                override fun onStartTrackingTouch(s: SeekBar) {}
                override fun onStopTrackingTouch(s: SeekBar) { Log.i("kynnys %.4f".format(c.threshold)) }
            })
        }
        sens.addView(slider, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = px(6) })
        val ends = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        ends.addView(text("herkkä", 12f, MUTED), LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        ends.addView(text("kuulee vain kovaa puhetta", 12f, MUTED))
        sens.addView(ends)

        // big buttons
        val grid = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(px(12), px(4), px(12), 0) }
        fun row(vararg v: View) = grid.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            v.forEach { addView(it, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f).apply { setMargins(px(6), px(6), px(6), px(6)) }) }
        })
        listenCard = bigButton("👂", "", 0xFF22B573.toInt()) { c.setListening(!c.listener.on) }
        listenLabel = listenCard.getChildAt(1) as TextView
        row(listenCard, bigButton("💬", "Tekstitys", 0xFF9B5DE5.toInt()) { showSubtitles(true) })
        row(bigButton("🌙", "Nukkumaan", 0xFF5B4BC4.toInt()) { c.scope.launch { c.sleepFurby() } },
            bigButton("☀️", "Herää", 0xFFFF9F1C.toInt()) { c.scope.launch { c.wakeFurby() } })
        row(bigButton("💃", "Tanssi", PINK) { Commands.run(c, "tag", "tanssi") },
            bigButton("🌈", "Vilkku", 0xFFFF6B6B.toInt()) { Commands.run(c, "tag", "vilkku") })
        col.addView(grid)

        return ScrollView(this).apply {
            background = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, intArrayOf(0xFFFF8CC6.toInt(), 0xFFFFB3DA.toInt(), 0xFFFFE3F1.toInt()))
            addView(col); isFillViewport = true
        }
    }

    /** Settings and the log, tucked into a bottom sheet. */
    private fun openSheet() {
        val d = Dialog(this)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(px(20), px(12), px(20), px(24))
            background = GradientDrawable().apply {
                setColor(Color.WHITE); val r = px(28).toFloat(); cornerRadii = floatArrayOf(r, r, r, r, 0f, 0f, 0f, 0f)
            }
        }
        col.addView(View(this).apply { background = rounded(0xFFE5D3E0.toInt(), 3) },
            LinearLayout.LayoutParams(px(44), px(5)).apply { gravity = Gravity.CENTER_HORIZONTAL; bottomMargin = px(14) })
        col.addView(text("Asetukset", 20f, INK, true))
        fun item(emoji: String, label: String, f: () -> Unit) = col.addView(text("$emoji   $label", 17f).apply {
            setPadding(px(4), px(14), px(4), px(14)); setOnClickListener { f() }
        })
        item("🔋", "Akku: ei rajoituksia") { askBattery() }
        item("🔎", "Etsi Furby uudelleen") { c.furby.rescan(); d.dismiss() }
        item("🔄", "Lataa asetukset uudelleen") { c.reload(); d.dismiss() }
        item("🧽", "Unohda keskustelu") { c.brain.reset(); Log.i("keskustelu nollattu"); d.dismiss() }
        item("🎚", "Herkkyys asetustiedostosta") { app.settings.threshold = null; Log.i("kynnys asetustiedostosta"); d.dismiss() }
        item(if (CompanionService.running) "⏹" else "▶️", if (CompanionService.running) "Pysäytä Furby-palvelu" else "Käynnistä Furby-palvelu") {
            if (CompanionService.running) CompanionService.stop(this) else startIfAllowed(); d.dismiss()
        }
        col.addView(text("Loki", 15f, MUTED, true).apply { setPadding(px(4), px(12), 0, px(4)) })
        val log = text("", 11f, INK).apply { typeface = Typeface.MONOSPACE; setTextIsSelectable(true) }
        logView = log; refreshLog()
        col.addView(ScrollView(this).apply { addView(log); post { fullScroll(View.FOCUS_DOWN) } },
            LinearLayout.LayoutParams(MATCH_PARENT, px(220)))
        d.setContentView(col)
        d.window?.apply {
            setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
            setLayout(MATCH_PARENT, WRAP_CONTENT); setGravity(Gravity.BOTTOM)
        }
        d.setOnDismissListener { logView = null }
        d.show()
    }

    private fun buildSubtitles(): View {
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
            background = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, intArrayOf(0xFF2A1B3D.toInt(), 0xFF5B1F4F.toInt()))
            setPadding(px(22), px(22), px(22), px(22))
            setOnClickListener { showSubtitles(false) }           // tap anywhere to leave
        }
        subHeard = text("", 22f, 0xFFFFB3DA.toInt()).apply { gravity = Gravity.CENTER }
        subSaying = text("", 40f, Color.WHITE, true).apply { gravity = Gravity.CENTER }
        col.addView(subHeard, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { bottomMargin = px(24) })
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

    // ---- live state ----

    private fun chipColour(v: TextView, ok: Boolean?) {
        (v.background as GradientDrawable).setColor(when (ok) { true -> 0xFFD7F7E6.toInt(); false -> 0xFFFFD6DC.toInt(); null -> 0xFFFFF1C9.toInt() })
    }

    private val tick = object : Runnable {
        @SuppressLint("SetTextI18n")
        override fun run() {
            val st = c.furby.state
            chipFurby.text = when (st) {
                Furby.State.CONNECTED -> if (c.sleeping) "😴 nukkuu" else "🐣 Furby ✓"
                Furby.State.CONNECTING -> "🐣 yhdistää…"; Furby.State.SCANNING -> "🐣 etsii…"
                Furby.State.DISCONNECTED -> "🐣 ei yhteyttä"
            }
            chipColour(chipFurby, if (st == Furby.State.CONNECTED) true else if (st == Furby.State.DISCONNECTED) false else null)
            chipBrain.text = "🧠 ${c.brainStatus}"
            chipColour(chipBrain, when (c.brainStatus) { "virhe" -> false; "–" -> null; else -> true })
            chipMic.text = when { !CompanionService.running -> "🎤 seis"; !c.listener.on -> "🎤 pois"; else -> "🎤 päällä" }
            chipColour(chipMic, if (!CompanionService.running) false else if (c.listener.on) true else null)

            moodLabel.text = when (c.mood) {
                FurbyCompanion.Mood.IDLE -> "Lepää"; FurbyCompanion.Mood.LISTENING -> "Kuuntelee…"
                FurbyCompanion.Mood.HEARING -> "Kuulee sinua!"; FurbyCompanion.Mood.THINKING -> "Miettii…"
                FurbyCompanion.Mood.SPEAKING -> "Puhuu"; FurbyCompanion.Mood.SLEEPING -> "Nukkuu, zzz…"
            }
            heardText.text = c.heard.takeIf { it.isNotEmpty() }?.let { "“$it”" } ?: ""
            sayingText.text = c.saying
            thrLabel.text = "kynnys %.3f".format(c.threshold)
            if (!slider.isPressed) slider.progress = (LevelMeter.pos(c.threshold) * 1000).toInt()
            listenLabel.text = if (c.listener.on) "Kuuntelee" else "Ei kuuntele"
            (listenCard.background as GradientDrawable).setColor(if (c.listener.on) 0xFF22B573.toInt() else 0xFF9E9AA8.toInt())
            if (subtitles) {
                subHeard.text = c.heard.takeIf { it.isNotEmpty() }?.let { "“$it”" } ?: ""
                subSaying.text = c.saying.ifEmpty { if (c.busy) "…" else "" }
            }
            ui.postDelayed(this, 150)
        }
    }

    override fun onResume() { super.onResume(); Log.listen(logListener); ui.post(tick) }
    override fun onPause() { super.onPause(); Log.unlisten(logListener); ui.removeCallbacks(tick) }

    private fun refreshLog() { logView?.text = Log.text().lines().takeLast(150).joinToString("\n") }

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
