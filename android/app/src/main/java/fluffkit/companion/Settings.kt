package fluffkit.companion

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import kotlin.math.pow

/**
 * Two kinds of settings:
 * - phone/furby-config.json (voice, filter, listening, fillers, laugh, antenna colours), bundled in the APK and
 *   overridden key by key by an editable copy in /sdcard/Android/data/fluffkit.companion/files/furby-config.json.
 *   AGENTS.md and packs.json can be overridden the same way.
 * - keys and the brain endpoint, kept in EncryptedSharedPreferences. Typed in the settings screen, or pushed once
 *   as files/secrets.json (adb push), which is imported and deleted on the next start.
 */
class Settings(private val ctx: Context) {
    private val secure: SharedPreferences = try {
        val key = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        EncryptedSharedPreferences.create(ctx, "secrets", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM)
    } catch (e: Exception) {
        Log.i("salattu tallennus ei toimi: ${e.message}"); throw e
    }
    private val prefs: SharedPreferences = ctx.getSharedPreferences("prefs", Context.MODE_PRIVATE)
    val dir: File = ctx.getExternalFilesDir(null) ?: ctx.filesDir

    var elevenKey: String
        get() = secure.getString("eleven_key", "") ?: ""
        set(v) = secure.edit().putString("eleven_key", v).apply()
    var llmUrl: String
        get() = secure.getString("llm_url", null) ?: "http://127.0.0.1:8788/v1"
        set(v) = secure.edit().putString("llm_url", v).apply()
    var llmBearer: String
        get() = secure.getString("llm_bearer", "") ?: ""
        set(v) = secure.edit().putString("llm_bearer", v).apply()
    var llmModel: String
        get() = secure.getString("llm_model", null) ?: "muse-spark-1.3-contributor"
        set(v) = secure.edit().putString("llm_model", v).apply()

    /** "responses" (reasoning effort reaches the model: Muse Spark at "minimal" ~1.1 s to first words) or "chat". */
    var llmApi: String
        get() = secure.getString("llm_api", null) ?: "responses"
        set(v) = secure.edit().putString("llm_api", v).apply()
    var llmEffort: String
        get() = secure.getString("llm_effort", null) ?: "minimal"
        set(v) = secure.edit().putString("llm_effort", v).apply()

    /** Bearer for the remote-control HTTP endpoint (Remote.kt); none = remote off. */
    var remoteToken: String
        get() = secure.getString("remote_token", "") ?: ""
        set(v) = secure.edit().putString("remote_token", v).apply()

    /** The slider (or remote "threshold"); once set it wins over listen.threshold in the config. */
    var threshold: Float?
        get() = if (prefs.contains("vad_thr")) prefs.getFloat("vad_thr", 0.03f) else null
        set(v) = prefs.edit().apply { if (v == null) remove("vad_thr") else putFloat("vad_thr", v) }.apply()
    var furbyAddress: String?
        get() = prefs.getString("furby_addr", null)
        set(v) = prefs.edit().putString("furby_addr", v).apply()
    var pack: Int
        get() = prefs.getInt("pack", 0)
        set(v) = prefs.edit().putInt("pack", v).apply()
    var listening: Boolean
        get() = prefs.getBoolean("listening", true)
        set(v) = prefs.edit().putBoolean("listening", v).apply()

    fun importFromFile() {
        val f = File(dir, "secrets.json")
        if (!f.exists()) return
        try {
            val j = JSONObject(f.readText())
            j.optString("elevenlabs_key").takeIf { it.isNotBlank() }?.let { elevenKey = it.trim() }
            j.optString("llm_url").takeIf { it.isNotBlank() }?.let { llmUrl = it.trim() }
            j.optString("llm_bearer").takeIf { it.isNotBlank() }?.let { llmBearer = it.trim() }
            j.optString("llm_model").takeIf { it.isNotBlank() }?.let { llmModel = it.trim() }
            j.optString("llm_api").takeIf { it.isNotBlank() }?.let { llmApi = it.trim() }
            if (j.has("llm_effort")) llmEffort = j.optString("llm_effort").trim()
            j.optString("remote_token").takeIf { it.isNotBlank() }?.let { remoteToken = it.trim() }
            Log.i("avaimet tuotu tiedostosta secrets.json")
        } catch (e: Exception) {
            Log.i("secrets.json: ${e.message}")
        }
        f.delete()
    }

    private fun text(name: String): String {
        val f = File(dir, name)
        return if (f.exists()) f.readText() else ctx.assets.open(name).bufferedReader().readText()
    }

    private fun exists(name: String) = File(dir, name).exists() ||
        runCatching { ctx.assets.open(name).close() }.isSuccess

    /** The system prompt: personas/<persona>.md + common.md when the config names a persona, else AGENTS.md. */
    fun persona(cfg: Config): String {
        val id = cfg.personaId
        if (id != null && exists("personas/$id.md") && exists("common.md"))
            return text("personas/$id.md").trimEnd() + "\n\n" + text("common.md")
        return text("AGENTS.md")
    }

    /** What tools/persona.py does: name the persona in the device's furby-config.json and copy its voice there. */
    fun switchPersona(id: String) {
        val f = File(dir, "furby-config.json")
        val over = if (f.exists()) JSONObject(f.readText()) else JSONObject()
        val voice = config().personas[id]?.voice ?: JSONObject()
        val merged = over.optJSONObject("voice") ?: JSONObject()
        for (k in voice.keys()) merged.put(k, voice.get(k))
        over.put("persona", id).put("voice", merged)
        f.writeText(over.toString(2))
    }

    fun packs(): JSONArray = try { JSONArray(text("packs.json")) } catch (e: Exception) { Log.i("packs.json: ${e.message}"); JSONArray() }

    /** Bundled furby-config.json with the device copy merged over it. */
    fun config(): Config {
        val base = JSONObject(ctx.assets.open("furby-config.json").bufferedReader().readText())
        val over = File(dir, "furby-config.json")
        if (over.exists()) try { merge(base, JSONObject(over.readText())) } catch (e: Exception) { Log.i("furby-config.json: ${e.message}") }
        return Config(base)
    }

    private fun merge(into: JSONObject, from: JSONObject) {
        for (k in from.keys()) {
            val a = into.opt(k); val b = from.get(k)
            if (a is JSONObject && b is JSONObject) merge(a, b) else into.put(k, b)
        }
    }
}

class Filler(val text: String, val weight: Double, val kind: String)

class Persona(val id: String, val name: String, val wake: List<String>, val voice: JSONObject, val colour: Int)

/** furby-config.json, with the same defaults as phone/index.html. */
class Config(j: JSONObject) {
    val personas: Map<String, Persona> = buildMap {
        val ps = j.optJSONObject("personas") ?: JSONObject()
        val palette = listOf(0xFFFF3D9A, 0xFF9B5DE5, 0xFF22B573, 0xFFFF9F1C, 0xFF3A86FF).map { it.toInt() }
        var n = 0
        for (k in ps.keys()) {
            val o = ps.getJSONObject(k)
            val wake = o.optJSONArray("wake")?.let { a -> List(a.length()) { a.getString(it) } } ?: emptyList()
            val colour = o.optJSONArray("colour")?.let { android.graphics.Color.rgb(it.optInt(0), it.optInt(1), it.optInt(2)) }
                ?: palette[n % palette.size]
            put(k, Persona(k, o.optString("name", k), wake, o.optJSONObject("voice") ?: JSONObject(), colour)); n++
        }
    }
    val personaId: String? = j.optString("persona").takeIf { it.isNotBlank() }
    val persona: Persona? = personaId?.let { personas[it] }

    // the persona's voice wins over "voice", so a config that only names the persona still sounds right
    private val voice = (j.optJSONObject("voice") ?: JSONObject()).also { v ->
        persona?.voice?.let { pv -> for (k in pv.keys()) v.put(k, pv.get(k)) }
    }
    val voiceId: String = voice.optString("id", "TOQpwiUO86jXKNDkdC31")
    val ttsModel: String = voice.optString("model", "eleven_flash_v2_5")
    val ttsLang: String = voice.optString("language", "fi")
    val rate: Float = 2.0.pow(voice.optDouble("semitones", 0.0) / 12).toFloat()
    val speed: Double = voice.optDouble("speed", 1.0)
    val stability: Double = voice.optDouble("stability", 0.3)
    val similarity: Double = voice.optDouble("similarity", 0.85)

    private val fx = j.optJSONObject("fx") ?: JSONObject()
    val fxOn: Boolean = fx.optBoolean("on", true)
    val lowHz: Double = fx.optDouble("lowHz", 250.0)
    val highHz: Double = fx.optDouble("highHz", 4500.0)
    val drive: Double = fx.optDouble("drive", 6.0)
    val bits: Int = fx.optInt("bits", 7)
    val hold: Int = fx.optInt("hold", 3).coerceAtLeast(1)
    val glitchChance: Double = fx.optDouble("glitchChance", 0.15)

    private val listen = j.optJSONObject("listen") ?: JSONObject()
    val startMs: Int = listen.optInt("start_ms", 120)
    val silenceMs: Int = listen.optInt("silence_ms", 700)
    val maxMs: Int = listen.optInt("max_ms", 15000)
    /** voice_communication (default, like Chrome), voice_recognition or mic; software gain on top. */
    val micSource: String = listen.optString("source", "voice_communication")
    val gain: Float = listen.optDouble("gain", 1.0).toFloat()
    /** Mic level that counts as speech (0..1 RMS); the app's own setting when the config has none. */
    val threshold: Float? = if (listen.has("threshold")) listen.getDouble("threshold").toFloat() else null

    private val fillers = j.optJSONObject("fillers") ?: JSONObject()
    // {text, weight, kind: "hum" | "word"}; the older "texts" list counts as hums of weight 1
    val fillerItems: List<Filler> = fillers.optJSONArray("items")?.let { a ->
        List(a.length()) { a.getJSONObject(it).let { f -> Filler(f.getString("text"), f.optDouble("weight", 1.0), f.optString("kind", "hum")) } }
    } ?: fillers.optJSONArray("texts")?.let { a -> List(a.length()) { Filler(a.getString(it), 1.0, "hum") } }
        ?: listOf(Filler("Hmm…", 1.0, "hum"))
    val noWordAfterHumS: Int = fillers.optInt("no_word_after_hum_s", 30)
    val avoidLast: Int = fillers.optInt("avoid_last", 4)
    val fillerBeak: Boolean = fillers.optBoolean("beak", true)
    val laugh: String = j.optString("laugh", "goofy deep belly laugh of a silly cartoon creature, bouncy and joyful")

    val antenna: Map<String, ByteArray> = buildMap {
        put("idle", byteArrayOf(0, 0, 40)); put("listening", byteArrayOf(0, 255.toByte(), 40))
        put("thinking", byteArrayOf(255.toByte(), 170.toByte(), 0)); put("speaking", byteArrayOf(255.toByte(), 0, 150.toByte()))
        j.optJSONObject("antenna")?.let { a ->
            for (k in a.keys()) a.optJSONArray(k)?.let { c -> put(k, ByteArray(3) { c.optInt(it).toByte() }) }
        }
    }
}
