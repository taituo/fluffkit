package fluffkit.companion

import org.json.JSONObject

/**
 * Runs the parsing and audio code on the phone's own runtime without installing the APK (Android's ICU regex is
 * not Java's: "(?U)" crashed the app once):
 *
 *   adb push app-debug.apk /data/local/tmp/furby.apk
 *   adb shell CLASSPATH=/data/local/tmp/furby.apk app_process / fluffkit.companion.SelfTest
 */
object SelfTest {
    private var failed = 0
    private fun check(name: String, ok: Boolean, got: Any? = null) {
        println((if (ok) "ok   " else "FAIL ") + name + if (ok) "" else "  got: $got")
        if (!ok) failed++
    }

    @JvmStatic
    fun main(args: Array<String>) {
        val c = FurbyCompanion.Companion
        val buf = StringBuilder("Jee! [liike] Olipa kerran pieni Furby, joka asui suuressa metsässä ja söi mustikoita, aina vaan. Loppu")
        val segs = c.takeSegments(buf, false)
        check("sentences", segs.firstOrNull() == "Jee!" && segs.getOrNull(1) == "[liike]", segs)
        check("40-char pause cut", segs.getOrNull(2)?.endsWith(",") == true, segs)
        check("rest stays", c.takeSegments(buf, true).lastOrNull() == "Loppu", buf)
        check("tags", c.TAG.findAll("[nauru] x [valo: sininen] [efekti: boing] [röyhtäys]").count() == 4)
        check("heard: tags out", c.cleanHeard("[naurua] (taustaääni) Hei Urho") == "Hei Urho", c.cleanHeard("[naurua] (taustaääni) Hei Urho"))
        check("heard: noise", c.cleanHeard("[clicking]") == null)
        check("wake", c.WAKE_RE.containsMatchIn("Tää Urho") && c.WAKE_RE.containsMatchIn("herää!"))
        val rest = "Herää Urho!".replace(c.WAKE_WORDS, " ").replace(Regex("[^a-zåäö ]", RegexOption.IGNORE_CASE), " ").trim()
        check("bare wake call", rest.isEmpty(), rest)
        val cfg = Config(JSONObject("""{"fillers":{"items":[{"text":"Hmm…","weight":2,"kind":"hum"}]},"fx":{"glitchChance":1}}"""))
        check("config fillers", cfg.fillerItems.size == 1 && cfg.fillerItems[0].weight == 2.0)
        val clip = Clip(24000, FloatArray(48000) { kotlin.math.sin(it * 0.05).toFloat() * 0.5f })
        val fx = Voice.furbyFx(clip, cfg)
        check("fx", fx.data.size >= clip.data.size && fx.data.all { it in -1f..1f })
        check("pcm roundtrip", Clip.fromPcm16(24000, clip.toPcm16()).data.size == clip.data.size)
        check("brain day part", Brain.dayPart(21) == "nukkumaanmenoaika" && Brain.dayPart(7) == "aamu")
        val v = LevelMeter.value(LevelMeter.pos(0.02f))
        check("meter scale", kotlin.math.abs(v - 0.02f) < 0.0005f, v)
        check("classes load", listOf("MainActivity", "FurbyView", "Remote", "CompanionService").all {
            runCatching { Class.forName("fluffkit.companion.$it") }.isSuccess })
        val pc = Config(JSONObject("""{"persona":"selianne","voice":{"id":"a","speed":1.0},
            "personas":{"selianne":{"name":"Selianne","wake":["selianne","sel"],"voice":{"id":"b"}}}}"""))
        val (wr, ww) = c.wakeRegexes(pc)
        check("persona voice", pc.voiceId == "b" && pc.speed == 1.0, pc.voiceId)
        check("persona wake", wr.containsMatchIn("Herää Selianne") && !wr.containsMatchIn("Moi Urho"))
        check("persona bare wake", "Selianne herää!".replace(ww, " ").replace(Regex("[^a-zåäö ]", RegexOption.IGNORE_CASE), " ").isBlank())
        println(if (failed == 0) "ALL OK" else "$failed FAILED")
    }
}
