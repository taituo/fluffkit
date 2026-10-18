package fluffkit.companion

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.Calendar

/**
 * Furby's brain over an OpenAI-compatible endpoint (e.g. taituo/opencode-go-gateway), like phone/brain.py:
 * the persona is the system prompt with the time of day appended, the history lives here (12 turns, reset after
 * 30 min idle), and the answer streams token by token.
 */
class Brain(private val settings: Settings, private val config: () -> Config) {
    private val keep = 12
    private val idleResetMs = 30 * 60 * 1000L
    private val history = mutableListOf<JSONObject>()
    private var session = "furby-${System.currentTimeMillis() / 1000}"
    private var last = 0L
    private val lock = Mutex()
    private var style = ""

    // models pick the same register every time when asked to "vary", so the style is drawn here:
    // weighted, never the same twice in a row (phone/brain.py)
    private fun nextStyle(): String {
        val options = STYLES.filter { it.first != style }
        var r = Math.random() * options.sumOf { it.second }
        val (name, _, how) = options.firstOrNull { r -= it.second; r <= 0 } ?: options.last()
        style = name
        return "(Vastaa nyt tyylillä $name: $how Jos lapsi pyytää tarinaa, kerro tarina. " +
            "Olet jo ääntellyt miettimistä, joten älä aloita sanoilla hmm, hetkinen tai mietitään.)"
    }

    private fun system(): String {
        val c = Calendar.getInstance()
        val h = c.get(Calendar.HOUR_OF_DAY)
        val wd = WEEKDAYS[(c.get(Calendar.DAY_OF_WEEK) + 5) % 7]      // Calendar: Sunday = 1
        val m = "%02d".format(c.get(Calendar.MINUTE))
        return settings.persona(config()) + "\n\n## Nyt\n\nKello on $h.$m, $wd, ${dayPart(h)}.\n"
    }

    fun reset() { history.clear() }

    suspend fun ask(text: String, context: String = "", style: Boolean = true, onChunk: (String) -> Unit): String = lock.withLock {
        withContext(Dispatchers.IO) {
            val now = System.currentTimeMillis()
            if (now - last > idleResetMs) { history.clear(); session = "furby-${now / 1000}" }   // a new play session starts fresh
            last = now
            val msgs = JSONArray().put(JSONObject().put("role", "system").put("content", system()))
            history.takeLast(2 * keep).forEach { msgs.put(it) }
            // state and style ride on this turn only; the history keeps the child's own words
            val extra = if (context.isNotEmpty()) "$context " else ""
            msgs.put(JSONObject().put("role", "user").put("content", if (style) "$text\n\n$extra${nextStyle()}" else "$text $extra".trim()))
            val responses = settings.llmApi == "responses"
            val body = JSONObject().put("model", settings.llmModel).put("stream", true)
            if (responses) {
                // no output cap: with Muse Spark a 400-token cap was eaten by reasoning and no text came back
                val input = org.json.JSONArray(); for (i in 1 until msgs.length()) input.put(msgs.get(i))
                body.put("instructions", msgs.getJSONObject(0).getString("content")).put("input", input)
                if (settings.llmEffort.isNotBlank()) body.put("reasoning", JSONObject().put("effort", settings.llmEffort))
            } else body.put("max_tokens", 400).put("messages", msgs)

            val c = URL(settings.llmUrl.trimEnd('/') + if (responses) "/responses" else "/chat/completions").openConnection() as HttpURLConnection
            c.requestMethod = "POST"; c.doOutput = true
            c.connectTimeout = 10_000; c.readTimeout = 60_000
            c.setRequestProperty("Authorization", "Bearer ${settings.llmBearer}")
            c.setRequestProperty("Content-Type", "application/json")
            c.setRequestProperty("x-session-id", session)       // the gateway keeps a conversation on one account
            c.outputStream.use { it.write(body.toString().toByteArray()) }
            if (c.responseCode !in 200..299) {
                val t = c.errorStream?.bufferedReader()?.readText() ?: ""
                error("${c.responseCode} ${t.take(200)}")
            }
            val answer = StringBuilder()
            c.inputStream.bufferedReader().useLines { lines ->
                for (raw in lines) {
                    val line = raw.trim()
                    if (!line.startsWith("data:") || line.endsWith("[DONE]")) continue
                    val d = JSONObject(line.substring(5))
                    val pieces = if (responses) {
                        if (d.optString("type") == "response.output_text.delta") listOf(d.optString("delta")) else emptyList()
                    } else {
                        val choices = d.optJSONArray("choices")
                        List(choices?.length() ?: 0) { choices!!.getJSONObject(it).optJSONObject("delta")?.optString("content", "") ?: "" }
                    }
                    for (piece in pieces) if (piece.isNotEmpty() && piece != "null") { answer.append(piece); onChunk(piece) }
                }
            }
            history += JSONObject().put("role", "user").put("content", text)
            history += JSONObject().put("role", "assistant").put("content", answer.toString())
            answer.toString().trim()
        }
    }

    companion object {
        val STYLES = listOf(
            Triple("ytimekäs", 30, "Vain YKSI lyhyt, napakka ja hauska lause. Ei kysymystä perään."),
            Triple("täysi innostus", 25, "Räjähdä riemusta: 3–4 hyvin lyhyttä huudahdusta täynnä isoja tunteita, ja ainakin yksi [liike]."),
            Triple("laulu", 15, "Ala laulaa: aloita 'La-la-laa!' ja laula 3–4 lyhyttä riimittelevää säettä aiheesta omilla sanoillasi."),
            Triple("nautiskelu", 15, "Pysähdy nauttimaan: aloita 'Mmm…' ja sano 2 hidasta, nautiskelevaa lausetta."),
            Triple("tavallinen jutustelu", 15, "2–3 lyhyttä lausetta ja yksi kysymys takaisin."),
        )
        val WEEKDAYS = listOf("maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai")
        fun dayPart(h: Int) = when (h) {
            in 6..9 -> "aamu"
            in 10..16 -> "päivä"
            in 17..19 -> "ilta"
            in 20..21 -> "nukkumaanmenoaika"
            else -> "yö"
        }
    }
}
