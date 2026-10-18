package fluffkit.companion

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.tanh
import kotlin.random.Random

/** Speaker output, and the "Furby filter" of phone/index.html: toy-speaker band, drive, bitcrush, stutter. */
object Voice {
    /** Play one clip to the end. [onStart] runs the moment the sound starts, so a gesture can go out with it. */
    fun play(clip: Clip, rate: Float = 1f, onStart: (seconds: Double) -> Unit = {}) {
        if (clip.data.isEmpty()) return
        val pcm = clip.toPcm16()
        val track = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setAudioFormat(AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setSampleRate(clip.rate).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
            .setTransferMode(AudioTrack.MODE_STATIC)
            .setBufferSizeInBytes(pcm.size)
            .build()
        try {
            track.write(pcm, 0, pcm.size)
            if (rate != 1f) track.playbackRate = (clip.rate * rate).roundToInt()
            val frames = clip.data.size
            val secs = clip.seconds / rate
            track.play()
            onStart(secs)
            val deadline = System.currentTimeMillis() + (secs * 1000).toLong() + 1500
            while (track.playbackHeadPosition < frames && System.currentTimeMillis() < deadline) Thread.sleep(15)
        } finally {
            try { track.stop() } catch (_: Exception) {}
            track.release()
        }
    }

    // repeat one 60-90 ms grain 2-3 times at a random spot: "U-u-urho!"
    private fun stutter(d: FloatArray, sr: Int, chance: Double): FloatArray {
        if (Random.nextDouble() > chance || d.size < sr) return d
        val g = (sr * (0.06 + Random.nextDouble() * 0.03)).toInt()
        val reps = 2 + Random.nextInt(2)
        val at = (d.size * (0.1 + Random.nextDouble() * 0.6)).toInt()
        val out = FloatArray(d.size + g * reps)
        System.arraycopy(d, 0, out, 0, at + g)
        for (r in 1..reps) System.arraycopy(d, at, out, at + g * r, g)
        System.arraycopy(d, at + g, out, at + g * (reps + 1), d.size - at - g)
        return out
    }

    /** RBJ biquad, the same shapes as Web Audio's highpass / lowpass (Q = 1/√2). */
    private fun biquad(d: FloatArray, sr: Int, hz: Double, high: Boolean) {
        val w = 2 * PI * hz.coerceIn(10.0, sr / 2.0 - 10) / sr
        val alpha = sin(w) / (2 * 0.7071)
        val cw = cos(w)
        val b0 = if (high) (1 + cw) / 2 else (1 - cw) / 2
        val b1 = if (high) -(1 + cw) else 1 - cw
        val a0 = 1 + alpha; val a1 = -2 * cw; val a2 = 1 - alpha
        var x1 = 0.0; var x2 = 0.0; var y1 = 0.0; var y2 = 0.0
        for (i in d.indices) {
            val x = d[i].toDouble()
            val y = (b0 * x + b1 * x1 + b0 * x2 - a1 * y1 - a2 * y2) / a0
            x2 = x1; x1 = x; y2 = y1; y1 = y
            d[i] = y.toFloat()
        }
    }

    fun furbyFx(c: Clip, cfg: Config): Clip {
        val d = stutter(c.data, c.rate, cfg.glitchChance).copyOf()
        biquad(d, c.rate, cfg.lowHz, high = true)
        biquad(d, c.rate, cfg.highHz, high = false)
        val norm = tanh(cfg.drive)
        for (i in d.indices) d[i] = (tanh(cfg.drive * d[i].coerceIn(-1f, 1f)) / norm).toFloat()
        // bitcrush + sample-and-hold (codec-like grit)
        val q = 2.0.pow(cfg.bits - 1)
        var i = 0
        while (i < d.size) {
            val v = ((Math.round(d[i] * q) / q) * 0.9).toFloat()
            for (k in 0 until cfg.hold) if (i + k < d.size) d[i + k] = v
            i += cfg.hold
        }
        return Clip(c.rate, d)
    }
}
