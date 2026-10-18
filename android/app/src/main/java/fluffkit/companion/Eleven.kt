package fluffkit.companion

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Mono audio, samples in -1..1. */
class Clip(val rate: Int, val data: FloatArray) {
    val seconds get() = data.size.toDouble() / rate

    fun toPcm16(): ByteArray {
        val b = ByteBuffer.allocate(data.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (v in data) b.putShort((v.coerceIn(-1f, 1f) * 32767).toInt().toShort())
        return b.array()
    }

    companion object {
        fun fromPcm16(rate: Int, bytes: ByteArray, off: Int = 0): Clip {
            val sb = ByteBuffer.wrap(bytes, off, bytes.size - off).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
            return Clip(rate, FloatArray(sb.remaining()) { sb.get(it) / 32768f })
        }

        /** Cached clips on disk: 4-byte sample rate, then 16-bit PCM. */
        fun load(f: File): Clip? = try {
            val b = f.readBytes(); fromPcm16(ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).int, b, 4)
        } catch (_: Exception) { null }
    }

    fun save(f: File) {
        f.parentFile?.mkdirs()
        val tmp = File(f.path + ".tmp")
        tmp.writeBytes(ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(rate).array() + toPcm16())
        tmp.renameTo(f)
    }
}

/**
 * ElevenLabs: flash TTS, sound effects, Scribe speech to text. The subscription allows 6 concurrent requests;
 * stay at 4 (fillers, story sentences and effects all queue here).
 */
class Eleven(private val settings: Settings, private val cacheDir: File) {
    private val slots = Semaphore(4)

    private suspend fun post(path: String, body: ByteArray, type: String): ByteArray = slots.withPermit {
        withContext(Dispatchers.IO) {
            val key = settings.elevenKey
            if (key.isBlank()) { Log.i("anna ElevenLabs-avain asetuksissa"); error("no key") }
            val c = URL("https://api.elevenlabs.io$path").openConnection() as HttpURLConnection
            c.requestMethod = "POST"; c.doOutput = true
            c.connectTimeout = 10_000; c.readTimeout = 60_000
            c.setRequestProperty("xi-api-key", key)
            c.setRequestProperty("Content-Type", type)
            c.outputStream.use { it.write(body) }
            if (c.responseCode !in 200..299) {
                val t = c.errorStream?.bufferedReader()?.readText() ?: ""
                Log.i("ElevenLabs ${c.responseCode}: ${t.take(200)}")
                error("ElevenLabs ${c.responseCode}")
            }
            c.inputStream.use { it.readBytes() }
        }
    }

    // pcm_24000 needs no decoding; anything that still comes back as mp3 goes through MediaCodec
    private fun toClip(bytes: ByteArray, rate: Int): Clip = if (isMp3(bytes)) decode(bytes) else Clip.fromPcm16(rate, bytes)

    suspend fun tts(text: String, cfg: Config): Clip {
        val body = JSONObject()
            .put("text", text).put("model_id", cfg.ttsModel)
            // language_code pins Finnish: without it short lines ("Hetkinen…") get read with a foreign accent
            .put("language_code", cfg.ttsLang)
            .put("voice_settings", JSONObject().put("speed", cfg.speed).put("stability", cfg.stability)
                .put("similarity_boost", cfg.similarity))
        val b = post("/v1/text-to-speech/${cfg.voiceId}?output_format=pcm_24000", body.toString().toByteArray(), "application/json")
        return toClip(b, 24000)
    }

    suspend fun sfx(prompt: String, seconds: Double = 1.5): Clip {
        val body = JSONObject().put("text", prompt).put("duration_seconds", seconds).put("prompt_influence", 0.7)
        val b = post("/v1/sound-generation?output_format=pcm_24000", body.toString().toByteArray(), "application/json")
        return toClip(b, 24000)
    }

    /** Scribe: language pinned (noisy kid speech came back as Igbo or Chinese), no [clicking] / [noise] events. */
    suspend fun stt(wav: ByteArray): String {
        val bnd = "----furby" + System.nanoTime()
        val out = ByteArrayOutputStream()
        fun field(name: String, value: String) =
            out.write("--$bnd\r\nContent-Disposition: form-data; name=\"$name\"\r\n\r\n$value\r\n".toByteArray())
        field("model_id", "scribe_v2")
        field("language_code", "fin")
        field("tag_audio_events", "false")
        out.write("--$bnd\r\nContent-Disposition: form-data; name=\"file\"; filename=\"puhe.wav\"\r\nContent-Type: audio/wav\r\n\r\n".toByteArray())
        out.write(wav)
        out.write("\r\n--$bnd--\r\n".toByteArray())
        val r = post("/v1/speech-to-text", out.toByteArray(), "multipart/form-data; boundary=$bnd")
        return JSONObject(String(r)).optString("text", "")
    }

    private fun isMp3(b: ByteArray) = b.size > 3 &&
        ((b[0] == 'I'.code.toByte() && b[1] == 'D'.code.toByte() && b[2] == '3'.code.toByte()) ||
            (b[0] == 0xff.toByte() && (b[1].toInt() and 0xe0) == 0xe0))

    private fun decode(mp3: ByteArray): Clip {
        val f = File.createTempFile("dec", ".mp3", cacheDir)
        try {
            f.writeBytes(mp3)
            val ex = MediaExtractor(); ex.setDataSource(f.path)
            val fmt = ex.getTrackFormat(0); ex.selectTrack(0)
            val rate = fmt.getInteger(MediaFormat.KEY_SAMPLE_RATE)
            val ch = fmt.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
            val codec = MediaCodec.createDecoderByType(fmt.getString(MediaFormat.KEY_MIME)!!)
            codec.configure(fmt, null, null, 0); codec.start()
            val pcm = ByteArrayOutputStream(); val info = MediaCodec.BufferInfo()
            var inDone = false
            while (true) {
                if (!inDone) {
                    val i = codec.dequeueInputBuffer(10_000)
                    if (i >= 0) {
                        val n = ex.readSampleData(codec.getInputBuffer(i)!!, 0)
                        if (n < 0) { codec.queueInputBuffer(i, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM); inDone = true }
                        else { codec.queueInputBuffer(i, 0, n, ex.sampleTime, 0); ex.advance() }
                    }
                }
                val o = codec.dequeueOutputBuffer(info, 10_000)
                if (o >= 0) {
                    val buf = codec.getOutputBuffer(o)!!
                    val bytes = ByteArray(info.size); buf.get(bytes); pcm.write(bytes)
                    codec.releaseOutputBuffer(o, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                }
            }
            codec.stop(); codec.release(); ex.release()
            val all = Clip.fromPcm16(rate, pcm.toByteArray())
            if (ch == 1) return all
            return Clip(rate, FloatArray(all.data.size / ch) { i -> (0 until ch).map { all.data[i * ch + it] }.average().toFloat() })
        } finally { f.delete() }
    }
}
