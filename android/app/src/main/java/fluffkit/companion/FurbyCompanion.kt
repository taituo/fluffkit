package fluffkit.companion

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicInteger

/** One pack item from phone/packs.json: a Furby action, with its beak length (talk) or a body move (gesture). */
class Item(val key: String, val text: String, val action: IntArray, val talk: Double?, val gesture: Boolean)

/**
 * The companion of phone/index.html, without the page: hear → Scribe → brain (streamed) → sentence by sentence
 * flash TTS from the phone speaker, while Furby moves its beak for exactly that long and shows the state on its
 * antenna.
 */
class FurbyCompanion(ctx: Context, val settings: Settings) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    val furby = Furby(ctx, settings)
    private val eleven = Eleven(settings, ctx.cacheDir)
    val brain = Brain(settings) { cfg }
    private val voiceCache = File(ctx.filesDir, "voice")

    @Volatile var cfg: Config = settings.config(); private set
    @Volatile var items: List<Item> = loadItems(); private set
    @Volatile var packName = ""; private set

    // the mic stays shut while this phone plays sound (+400 ms of echo) and while a turn is being answered
    private val playing = AtomicInteger(0)
    @Volatile private var quietUntil = 0L
    @Volatile var busy = false; private set
    @Volatile private var thinkingNow = false
    private val speaker = Mutex()                       // one sound at a time

    /** Mic level that counts as speech: the slider, else listen.threshold in the config, else 0.03. */
    val threshold get() = settings.threshold ?: cfg.threshold ?: 0.03f

    val listener = Listener({ threshold }, { cfg },
        { busy || playing.get() > 0 || System.currentTimeMillis() < quietUntil }, ::onUtterance)

    private var fillers: List<Pair<Filler, Clip>> = emptyList()
    private val recentFillers = ArrayDeque<String>()
    private var lastFillerKind = ""; private var lastFillerAt = 0L
    private var laugh: Clip? = null

    init {
        furby.onSequenceEnded = { seqEnded.forEach { it.complete(Unit) }; seqEnded.clear() }
        furby.onState = { s ->
            if (s == Furby.State.CONNECTED) scope.launch { antennaNow = ""; delay(500); restingColour() }
        }
    }

    private val remote = Remote(this)

    fun start() {
        remote.start()
        furby.start()
        if (settings.listening) listener.start()
        scope.launch { prepareSounds() }
    }

    fun stop() { listener.stop(); furby.stop(); remote.stop() }

    fun setListening(on: Boolean) {
        settings.listening = on
        if (on) listener.start() else listener.stop()
        antennaNow = ""; restingColour()
    }

    /** For the status chip: "–" before the first answer, then the time to the first piece, or "virhe". */
    @Volatile var brainStatus = "–"; private set

    enum class Mood { IDLE, LISTENING, HEARING, THINKING, SPEAKING, SLEEPING }
    val mood: Mood get() = when {
        sleeping -> Mood.SLEEPING
        playing.get() > 0 && !thinkingNow -> Mood.SPEAKING
        busy -> Mood.THINKING
        listener.recording -> Mood.HEARING
        listener.on -> Mood.LISTENING
        else -> Mood.IDLE
    }

    // for the subtitle screen: what the mic heard, and the sentence Furby is saying now
    @Volatile var heard = ""; private set
    @Volatile var saying = ""; private set

    fun reload() {
        settings.importFromFile()
        if (CompanionService.running) remote.start()
        cfg = settings.config(); items = loadItems()
        if (listener.on) { listener.stop(); listener.start() }      // mic source may have changed
        Log.i("asetukset ladattu uudelleen: ${items.size} elettä paketista $packName")
        scope.launch { prepareSounds() }
    }

    private fun loadItems(): List<Item> {
        val packs = settings.packs()
        if (packs.length() == 0) return emptyList()
        val p = packs.getJSONObject(settings.pack.coerceIn(0, packs.length() - 1))
        packName = p.optString("name")
        val its = p.optJSONObject("items") ?: JSONObject()
        return its.keys().asSequence().map { k ->
            val v = its.getJSONObject(k)
            val a = v.getJSONArray("action")
            Item(k, v.optString("text"), IntArray(a.length()) { a.getInt(it) },
                if (v.has("talk")) v.getDouble("talk") else null, v.optBoolean("gesture"))
        }.toList()
    }

    // ---- Furby gestures and antenna ----

    // while Furby sleeps only the sleep/wake actions go out ("uni:" reasons); the phone keeps talking and listening
    @Volatile var sleeping = false; private set

    fun act(a: IntArray, why: String = "") {
        if (sleeping && !why.startsWith("uni")) return
        Log.i("→ ele ${a.joinToString("/")} $why")
        furby.send(byteArrayOf(0x13, 0x00) + ByteArray(a.size) { a[it].toByte() })
    }

    private fun talkFor(secs: Double): IntArray? {
        val t = items.filter { it.talk != null }.sortedBy { it.talk }
        return (t.firstOrNull { it.talk!! >= secs } ?: t.lastOrNull())?.action
    }

    private fun randomMove(): IntArray? = items.filter { it.gesture }.randomOrNull()?.action

    @Volatile private var antennaNow = ""
    fun antenna(state: String) {
        val c = cfg.antenna[state] ?: return
        if (antennaNow == state || !furby.connected) return
        antennaNow = state
        furby.send(byteArrayOf(0x14) + c)
    }

    fun restingColour() { if (!sleeping) antenna(if (listener.on) "listening" else "idle") }

    // ---- Urho's tools: Furby's own actions (bluefluff action list), sleep and wake, antenna light show ----

    private val seqEnded = java.util.concurrent.CopyOnWriteArrayList<kotlinx.coroutines.CompletableDeferred<Unit>>()

    /** A trick that uses Furby's own voice: wait for its SEQUENCE_ENDED (max 8 s) before the phone talks again. */
    private suspend fun trick(name: String) {
        val tr = TRICKS[name] ?: return
        if (sleeping) return
        val done = kotlinx.coroutines.CompletableDeferred<Unit>()
        if (!tr.first) seqEnded.add(done)
        act(tr.second.random(), name)
        if (!tr.first) { kotlinx.coroutines.withTimeoutOrNull(8_000) { done.await() }; seqEnded.remove(done) }
    }

    private suspend fun lightShow(spec: String) {
        if (sleeping) return
        if (spec == "vilkku") {
            for (c in listOf("punainen", "oranssi", "keltainen", "vihreä", "sininen", "violetti", "pinkki", "valkoinen")) {
                furby.send(byteArrayOf(0x14) + COLOURS.getValue(c)); delay(180)
            }
            antennaNow = ""; restingColour(); return
        }
        COLOURS[spec.trim().lowercase()]?.let { antennaNow = "custom"; furby.send(byteArrayOf(0x14) + it) }
    }

    suspend fun sleepFurby() {
        if (sleeping) return
        act(SLEEP_LINES.random(), "uni: hyvää yötä")
        delay(4_000)
        act(intArrayOf(30, 3, 0, 0), "uni: nukkumaan")
        sleeping = true
        furby.keepaliveOn = false
        antennaNow = "sleep"; furby.send(0x14, 0, 0, 0)
        Log.i("Furby nukkuu")
    }

    suspend fun wakeFurby() {
        if (!sleeping) return
        val h = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY)
        act((if (h in 6..9) MORNING_LINES else WAKE_LINES).random(), "uni: herätys")
        sleeping = false
        furby.keepaliveOn = true
        scope.launch { delay(2_000); antennaNow = ""; restingColour() }
        Log.i("Furby heräsi")
    }

    // ---- sound out ----

    enum class Kind { SPEECH, RAW, SFX }

    suspend fun play(clip: Clip, kind: Kind) = speaker.withLock {
        playing.incrementAndGet()
        try {
            withContext(Dispatchers.IO) {
                val fx = cfg.fxOn && kind != Kind.SFX
                val c = if (fx) Voice.furbyFx(clip, cfg) else clip
                Voice.play(c, if (kind == Kind.SFX) 1f else cfg.rate) { secs ->
                    when (kind) {                                   // the gesture goes out the moment the sound starts
                        Kind.SPEECH -> {
                            if (!thinkingNow) antenna("speaking")
                            talkFor(secs)?.let { act(it, "nokka %.1f s".format(secs)) }
                        }
                        Kind.SFX -> randomMove()?.let { act(it, "efekti") }
                        Kind.RAW -> {}
                    }
                }
            }
        } catch (e: Exception) {
            Log.i("ääni: ${e.message}")
        } finally {
            quietUntil = System.currentTimeMillis() + 400
            playing.decrementAndGet()
        }
    }

    suspend fun speak(text: String) {
        val c = try { eleven.tts(text, cfg) } catch (e: Exception) { return }
        play(c, Kind.SPEECH)
    }

    private fun hash(s: String) = MessageDigest.getInstance("SHA-1").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }

    // sounds Furby needs instantly, kept on disk per voice so each line is made once
    private suspend fun cached(key: String, make: suspend () -> Clip): Clip? {
        val f = File(voiceCache, hash(key) + ".pcm")
        Clip.load(f)?.let { return it }
        return try { make().also { it.save(f) } } catch (e: Exception) { null }
    }

    suspend fun prepareSounds() {
        if (settings.elevenKey.isBlank()) { Log.i("anna ElevenLabs-avain asetuksissa"); return }
        val c = cfg
        val tag = "/v/${c.voiceId}/${c.ttsModel}/${c.stability}/${c.speed}/${c.similarity}/${c.ttsLang}/"
        fillers = c.fillerItems.map { f -> scope.async { cached(tag + f.text) { eleven.tts(f.text, c) }?.let { f to it } } }.mapNotNull { it.await() }
        laugh = cached("/sfx/" + c.laugh) { eleven.sfx(c.laugh, 1.5) }
        Log.i("valmiina: ${fillers.size} täytettä, nauru ${if (laugh != null) "✓" else "–"}")
    }

    // the moment the child stops talking: thinking colour plus a short "hmm" with a quick beak flap
    private suspend fun thinking() {
        antenna("thinking")
        val f = pickFiller() ?: return
        thinkingNow = true
        try { play(f, if (cfg.fillerBeak) Kind.SPEECH else Kind.RAW) } finally { thinkingNow = false }
    }

    // weighted, none of the last few, and no "Hetkinen!" right after a "hmm"
    private fun pickFiller(): Clip? {
        val now = System.currentTimeMillis()
        var pool = fillers.filter { it.first.text !in recentFillers }
        if (lastFillerKind == "hum" && now - lastFillerAt < cfg.noWordAfterHumS * 1000L) pool = pool.filter { it.first.kind == "hum" }
        if (pool.isEmpty()) pool = fillers.filter { it.first.kind == "hum" }
        if (pool.isEmpty()) return null
        var r = Math.random() * pool.sumOf { it.first.weight }
        val (f, clip) = pool.firstOrNull { r -= it.first.weight; r <= 0 } ?: pool.last()
        recentFillers.addFirst(f.text); while (recentFillers.size > cfg.avoidLast) recentFillers.removeLast()
        lastFillerKind = f.kind; lastFillerAt = now
        return clip
    }

    /** Switch persona like tools/persona.py, then introduce the new one in its own voice. */
    fun switchPersona(id: String) {
        val p = cfg.personas[id] ?: run { Log.i("tuntematon persoona $id"); return }
        settings.switchPersona(id)
        brain.reset()
        reload()
        Log.i("persoona: ${p.name}")
        furby.send(byteArrayOf(0x14, android.graphics.Color.red(p.colour).toByte(), android.graphics.Color.green(p.colour).toByte(),
            android.graphics.Color.blue(p.colour).toByte()))
        antennaNow = "persona"
        scope.launch { speak("Hei, minä olen ${p.name}!"); delay(300); antennaNow = ""; restingColour() }
    }

    // ---- one turn ----

    private class Segment(val tags: List<Pair<String, Deferred<Clip?>?>>, val words: String, val speech: Deferred<Clip?>?)

    private fun prepare(seg: String): Segment {
        val tags = TAG.findAll(seg).map { it.groupValues[1].lowercase() }.map { t ->
            if (t.startsWith("efekti:")) "sfx" to scope.async { runCatching { eleven.sfx(t.substring(7).trim()) }.getOrNull() }
            else t to null
        }.toList()
        val words = seg.replace(TAG, " ").replace(Regex("\\s+"), " ").trim()
        val speech = if (Regex("[a-zåäö0-9]", RegexOption.IGNORE_CASE).containsMatchIn(words))
            scope.async { runCatching { eleven.tts(words, cfg) }.getOrNull() } else null   // starts fetching right away
        return Segment(tags, words, speech)
    }

    private suspend fun perform(s: Segment) {
        for ((kind, clip) in s.tags) when (kind) {
            "liike" -> randomMove()?.let { act(it, "liike") }
            "nauru" -> { randomMove()?.let { act(it, "nauru") }; laugh?.let { play(it, Kind.RAW) } }
            "sfx" -> clip?.await()?.let { play(it, Kind.SFX) }
            "nukkumaan" -> sleepFurby()
            "herää" -> wakeFurby()
            "vilkku" -> lightShow("vilkku")
            else -> if (kind.startsWith("valo:")) lightShow(kind.substring(5)) else trick(kind)
        }
        s.speech?.await()?.let { saying = s.words; play(it, Kind.SPEECH) }
    }

    suspend fun chat(text: String) {
        Log.i("sinä: $text")
        heard = text; saying = ""
        busy = true
        // waking Furby must not depend on the model: Scribe heard "Herää Urho" as "Tää Urho" / "Jaa urho?"
        val (wakeRe, wakeWords) = wakeRegexes(cfg)
        if (sleeping && wakeRe.containsMatchIn(text)) {
            wakeFurby()                                         // Furby's own wake-up line is the answer...
            val rest = text.replace(wakeWords, " ").replace(Regex("[^a-zåäö ]", RegexOption.IGNORE_CASE), " ").trim()
            if (rest.split(Regex("\\s+")).count { it.length > 1 } < 2) {   // ...unless the child said more than "herää Urho"
                quietUntil = System.currentTimeMillis() + 400; busy = false
                return
            }
        }
        val t0 = System.currentTimeMillis()
        try {
            val think = scope.async { thinking() }
            val queue = Channel<Segment>(Channel.UNLIMITED)
            val player = scope.launch { think.await(); for (s in queue) perform(s) }
            val buf = StringBuilder()
            var first = true
            try {
                val answer = brain.ask(text, if (sleeping) "Furby nukkuu nyt." else "") { piece ->
                    if (first) {
                        first = false
                        val ms = System.currentTimeMillis() - t0
                        Log.i("aivot: ensimmäinen pala $ms ms"); brainStatus = "%.1f s".format(ms / 1000.0)
                    }
                    buf.append(piece)
                    takeSegments(buf, false).forEach { queue.trySend(prepare(it)) }
                }
                takeSegments(buf, true).forEach { queue.trySend(prepare(it)) }
                Log.i("Furby: $answer")
            } catch (e: Exception) {
                Log.i("aivot: ${e.message}"); brainStatus = "virhe"
            }
            queue.close()
            player.join()
        } finally {
            restingColour()
            quietUntil = System.currentTimeMillis() + 400
            busy = false
        }
    }

    /** Perform a ready-made answer (tags and sentences) without the brain: for tests. */
    suspend fun chatScript(script: String) {
        busy = true
        try {
            val buf = StringBuilder(script)
            for (seg in takeSegments(buf, true)) perform(prepare(seg))
        } finally { restingColour(); quietUntil = System.currentTimeMillis() + 400; busy = false }
    }

    fun hear(wav: ByteArray) = onUtterance(wav)

    // called on the mic thread: mute right away, then transcribe and answer
    private fun onUtterance(wav: ByteArray) {
        busy = true
        scope.launch {
            try {
                val t0 = System.currentTimeMillis()
                val raw = eleven.stt(wav)
                val heard = cleanHeard(raw)
                Log.i("kuultu ${System.currentTimeMillis() - t0} ms: ${raw.trim()}")
                if (heard != null) chat(heard) else Log.i("(ei puhetta)")
            } catch (e: Exception) {
                Log.i("kuuntelu: ${e.message}")
            } finally {
                busy = false
            }
        }
    }

    companion object {
        val TAG = Regex("\\[(liike|nauru|nukkumaan|herää|tanssi|korvat|pieru|röyhtäys|hikka|furbylaulu|beatbox|vilkku|valo:[^\\]]*|efekti:[^\\]]*)\\]",
            RegexOption.IGNORE_CASE)
        private fun alt(words: List<String>) = words.joinToString("|") { Regex.escape(it.lowercase()) }

        /** Wake call (persona's wake words + generic) and the words a bare wake call consists of. */
        fun wakeRegexes(cfg: Config): Pair<Regex, Regex> {
            val names = (cfg.persona?.wake ?: listOf("urho")).filter { it.isNotBlank() }
            val n = if (names.isEmpty()) "" else alt(names) + "|"
            return Regex("\\b(${n}her[äa]{1,2}|herätys|huomen|huomenta|aamu|nouse|wake)", RegexOption.IGNORE_CASE) to
                Regex("\\b(${n}her[äa]+\\w*|herätys|huomen\\w*|aamu\\w*|nouse|wake|hei|tää|jaa|no|nyt|jo)\\b", RegexOption.IGNORE_CASE)
        }

        val WAKE_WORDS = Regex("\\b(urho|her[äa]+\\w*|herätys|huomen\\w*|aamu\\w*|nouse|wake|hei|tää|jaa|no|nyt|jo)\\b", RegexOption.IGNORE_CASE)
        val WAKE_RE = Regex("\\b(urho|her[äa]{1,2}|herätys|huomen|huomenta|aamu|nouse|wake)", RegexOption.IGNORE_CASE)

        private fun codes(vararg c: Int) = c
        private fun range(a: Int, b: Int, c: Int, from: Int, to: Int) = (from..to).map { intArrayOf(a, b, c, it) }
        val SLEEP_LINES = range(28, 0, 0, 1, 4)
        val WAKE_LINES = listOf(codes(27, 0, 0, 0), codes(27, 0, 0, 1), codes(27, 0, 0, 2), codes(27, 0, 0, 4))
        val MORNING_LINES = range(27, 2, 0, 1, 2)
        /** name → (silent, codes). Silent ones only move; the rest use Furby's own voice. */
        val TRICKS: Map<String, Pair<Boolean, List<IntArray>>> = mapOf(
            "tanssi" to (true to range(18, 0, 0, 1, 17)),
            "korvat" to (true to range(18, 0, 0, 1, 17)),
            "pieru" to (false to range(7, 0, 0, 0, 7) + range(7, 0, 1, 0, 3)),
            "röyhtäys" to (false to range(16, 0, 2, 0, 3)),
            "hikka" to (false to listOf(codes(16, 0, 0, 0))),
            "furbylaulu" to (false to range(17, 0, 0, 0, 4)),
            "beatbox" to (false to listOf(codes(17, 0, 0, 5), codes(18, 0, 1, 5))),
        )
        private fun rgb(r: Int, g: Int, b: Int) = byteArrayOf(r.toByte(), g.toByte(), b.toByte())
        val COLOURS = mapOf("punainen" to rgb(255, 0, 0), "sininen" to rgb(0, 60, 255), "vihreä" to rgb(0, 255, 40),
            "keltainen" to rgb(255, 200, 0), "pinkki" to rgb(255, 0, 150), "violetti" to rgb(150, 0, 255),
            "oranssi" to rgb(255, 90, 0), "valkoinen" to rgb(255, 255, 255), "turkoosi" to rgb(0, 220, 200))
        private val SENTENCE = Regex("^\\s*([\\s\\S]*?(?:[.!?…]+|\\]))(\\s+)")
        // a long sentence is also cut at its first pause (, ; : —) after 40 chars, so the first words start sooner
        private val PAUSE = Regex("^\\s*([^.!?…\\]]{40,}?[,;:—–])(\\s+)")

        /** Split the streamed answer into sentences and [tags]; a segment is ready once whitespace follows it. */
        fun takeSegments(buf: StringBuilder, final: Boolean): List<String> {
            val out = mutableListOf<String>()
            while (true) {
                val sm = SENTENCE.find(buf); val cm = PAUSE.find(buf)
                val m = (if (cm != null && (sm == null || cm.value.length < sm.value.length)) cm else sm) ?: break
                out += m.groupValues[1]
                buf.delete(0, m.value.length)
            }
            if (final && buf.isNotBlank()) { out += buf.toString().trim(); buf.clear() }
            return out
        }

        /** What the mic heard, minus [sound event] tags; null when nothing worth answering is left. */
        fun cleanHeard(raw: String?): String? {
            val s = (raw ?: "").replace(Regex("\\[[^\\]]*\\]|\\([^)]*\\)"), " ").replace(Regex("\\s+"), " ").trim()
            return if (Regex("[a-zåäö]", RegexOption.IGNORE_CASE).findAll(s).count() >= 3) s else null
        }
    }
}
