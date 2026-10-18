package fluffkit.companion

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.sqrt

/**
 * Hands-free listening: start recording when the level stays over the threshold for start_ms, stop after
 * silence_ms of quiet (or max_ms). A short pre-roll keeps the first syllable. Muted while [muted] says so
 * (Furby's voice comes out of this phone's speaker, and nothing is heard while an answer is on its way).
 */
@SuppressLint("MissingPermission")
class Listener(
    private val threshold: () -> Float,
    private val config: () -> Config,
    private val muted: () -> Boolean,
    private val onUtterance: (wav: ByteArray) -> Unit,
) {
    @Volatile var level = 0f; private set
    /** Highest level over the last second, for calibrating listen.threshold. */
    @Volatile var peak = 0f; private set
    @Volatile var recording = false; private set
    @Volatile private var running = false
    private var thread: Thread? = null

    val on get() = running

    fun start() {
        if (running) return
        running = true
        thread = Thread(::loop, "furby-mic").apply { start() }
    }

    fun stop() { running = false; thread?.join(500); thread = null; level = 0f; recording = false }

    private fun loop() {
        val rate = RATE
        val frame = rate / 50                                  // 20 ms
        val min = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = try {
            // VOICE_COMMUNICATION is what Chrome's echo-cancelled getUserMedia uses; VOICE_RECOGNITION was ~10x quieter
            // on the Poco F1 (peaks 0.003-0.006 against Chrome's ~0.03)
            val src = if (config().micSource == "voice_recognition") MediaRecorder.AudioSource.VOICE_RECOGNITION
                else if (config().micSource == "mic") MediaRecorder.AudioSource.MIC else MediaRecorder.AudioSource.VOICE_COMMUNICATION
            AudioRecord(src, rate, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(min, frame * 2 * 10))
        } catch (e: Exception) { Log.i("mikki: ${e.message}"); running = false; return }
        if (rec.state != AudioRecord.STATE_INITIALIZED) { Log.i("mikki ei käynnisty (lupa?)"); rec.release(); running = false; return }
        val aec = if (AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(rec.audioSessionId)?.apply { enabled = true } else null
        val agc = if (AutomaticGainControl.isAvailable()) AutomaticGainControl.create(rec.audioSessionId)?.apply { enabled = true } else null
        val ns = if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(rec.audioSessionId)?.apply { enabled = true } else null
        rec.startRecording()
        Log.i("kuuntelee")

        val buf = ShortArray(frame)
        val pre = ArrayDeque<ShortArray>()                     // pre-roll: start_ms + 300 ms
        val utt = ArrayList<ShortArray>()
        var loudMs = 0; var quietMs = 0; var recMs = 0
        val peaks = FloatArray(50); var pi = 0                  // 50 × 20 ms = 1 s
        try {
            while (running) {
                val n = rec.read(buf, 0, frame)
                if (n <= 0) continue
                val gain = config().gain
                if (gain != 1f) for (i in 0 until n) buf[i] = (buf[i] * gain).toInt().coerceIn(-32768, 32767).toShort()
                var sum = 0.0
                for (i in 0 until n) { val v = buf[i] / 32768.0; sum += v * v }
                val rms = sqrt(sum / n).toFloat()
                level = rms
                peaks[pi] = rms; pi = (pi + 1) % peaks.size; peak = peaks.max()
                val thr = threshold(); val cfg = config()
                val chunk = buf.copyOf(n)

                if (muted()) {
                    loudMs = 0; pre.clear()
                    if (recording) { recording = false; utt.clear() }    // Furby started talking: drop what we had
                    continue
                }
                if (!recording) {
                    pre.addLast(chunk)
                    while (pre.size * 20 > cfg.startMs + 300) pre.removeFirst()
                    loudMs = if (rms > thr) loudMs + 20 else 0
                    if (loudMs > cfg.startMs) {
                        recording = true; utt.clear(); utt.addAll(pre); pre.clear()
                        recMs = 0; quietMs = 0
                    }
                } else {
                    utt.add(chunk); recMs += 20
                    quietMs = if (rms > thr * 0.7f) 0 else quietMs + 20
                    if (quietMs > cfg.silenceMs || recMs > cfg.maxMs) {
                        recording = false; loudMs = 0
                        val samples = utt.sumOf { it.size }
                        if (samples > rate * 4 / 10) onUtterance(wav(utt, rate))   // < 0.4 s is a bump, not speech
                        utt.clear()
                    }
                }
            }
        } finally {
            rec.stop(); rec.release(); aec?.release(); agc?.release(); ns?.release()
            level = 0f; recording = false
            Log.i("kuuntelu pois")
        }
    }

    companion object {
        const val RATE = 16000

        fun wav(chunks: List<ShortArray>, rate: Int): ByteArray {
            val n = chunks.sumOf { it.size }
            val b = ByteBuffer.allocate(44 + n * 2).order(ByteOrder.LITTLE_ENDIAN)
            b.put("RIFF".toByteArray()).putInt(36 + n * 2).put("WAVE".toByteArray())
            b.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(rate).putInt(rate * 2).putShort(2).putShort(16)
            b.put("data".toByteArray()).putInt(n * 2)
            for (c in chunks) for (s in c) b.putShort(s)
            return b.array()
        }
    }
}
