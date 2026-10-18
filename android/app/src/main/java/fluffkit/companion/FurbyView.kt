package fluffkit.companion

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.view.View
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.ln
import kotlin.math.sin

/**
 * A drawn Furby that shows the companion's state: the fur takes the antenna colour of the moment (fading smoothly),
 * it breathes while listening, pulses while it hears speech, tilts while thinking, moves its beak while speaking
 * and closes its eyes while asleep. Plain Canvas at ~30 fps, only while on screen.
 */
class FurbyView(ctx: Context, private val mood: () -> FurbyCompanion.Mood) : View(ctx) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val path = Path()
    private val oval = RectF()
    private var colour = floatArrayOf(255f, 120f, 190f)
    private val start = System.nanoTime()
    private var nextBlink = 2.0

    private fun target(m: FurbyCompanion.Mood): Int = when (m) {
        FurbyCompanion.Mood.IDLE -> 0xFFB39DDB.toInt()
        FurbyCompanion.Mood.LISTENING -> 0xFF5ED6A0.toInt()
        FurbyCompanion.Mood.HEARING -> 0xFF22C55E.toInt()
        FurbyCompanion.Mood.THINKING -> 0xFFFFB020.toInt()
        FurbyCompanion.Mood.SPEAKING -> 0xFFFF3D9A.toInt()
        FurbyCompanion.Mood.SLEEPING -> 0xFF6D5BD0.toInt()
    }

    private val frame = object : Runnable {
        override fun run() { invalidate(); if (isAttachedToWindow && windowVisibility == VISIBLE) postOnAnimationDelayed(this, 33) }
    }

    override fun onAttachedToWindow() { super.onAttachedToWindow(); post(frame) }
    override fun onWindowVisibilityChanged(v: Int) { super.onWindowVisibilityChanged(v); if (v == VISIBLE) { removeCallbacks(frame); post(frame) } }

    override fun onDraw(c: Canvas) {
        val t = (System.nanoTime() - start) / 1e9
        val m = mood()
        val tc = target(m)
        val goal = floatArrayOf(Color.red(tc).toFloat(), Color.green(tc).toFloat(), Color.blue(tc).toFloat())
        for (i in 0..2) colour[i] += (goal[i] - colour[i]) * 0.08f              // smooth fade between states
        val fur = Color.rgb(colour[0].toInt(), colour[1].toInt(), colour[2].toInt())
        val furDark = Color.rgb((colour[0] * 0.78f).toInt(), (colour[1] * 0.78f).toInt(), (colour[2] * 0.78f).toInt())

        val w = width.toFloat(); val h = height.toFloat()
        val r0 = minOf(w, h) * 0.30f
        val breath = when (m) {
            FurbyCompanion.Mood.HEARING -> 1f + 0.05f * sin(t * 2 * PI * 3).toFloat()
            FurbyCompanion.Mood.SLEEPING -> 1f + 0.03f * sin(t * 2 * PI * 0.25).toFloat()
            FurbyCompanion.Mood.SPEAKING -> 1f + 0.015f * sin(t * 2 * PI * 4).toFloat()
            else -> 1f + 0.025f * sin(t * 2 * PI * 0.6).toFloat()
        }
        val r = r0 * breath
        val cx = w / 2
        val cy = h * 0.56f + if (m == FurbyCompanion.Mood.THINKING) 6f * sin(t * 2 * PI * 1.2).toFloat() else 0f
        val tilt = if (m == FurbyCompanion.Mood.THINKING) 8f * sin(t * 2 * PI * 0.6).toFloat() else 0f

        // glow ring while it hears speech or talks
        if (m == FurbyCompanion.Mood.HEARING || m == FurbyCompanion.Mood.SPEAKING) {
            p.color = fur; p.alpha = (60 + 40 * sin(t * 2 * PI * 2)).toInt()
            c.drawCircle(cx, cy, r * 1.22f, p)
            p.alpha = 255
        }

        c.save(); c.rotate(tilt, cx, cy)
        // ears: two tall leaves that wiggle
        val swing = when (m) {
            FurbyCompanion.Mood.SLEEPING -> 0f
            FurbyCompanion.Mood.SPEAKING, FurbyCompanion.Mood.HEARING -> 10f * sin(t * 2 * PI * 2.5).toFloat()
            else -> 4f * sin(t * 2 * PI * 0.5).toFloat()
        }
        val droop = if (m == FurbyCompanion.Mood.SLEEPING) 35f else 0f
        for (side in listOf(-1f, 1f)) {
            c.save()
            c.rotate(side * (28f + droop) + side * swing, cx + side * r * 0.45f, cy - r * 0.75f)
            oval.set(cx + side * r * 0.45f - r * 0.2f, cy - r * 1.75f, cx + side * r * 0.45f + r * 0.2f, cy - r * 0.6f)
            p.color = furDark; c.drawOval(oval, p)
            oval.inset(r * 0.07f, r * 0.12f); p.color = 0xFFFFD6E8.toInt(); c.drawOval(oval, p)
            c.restore()
        }
        // body with a lighter belly
        p.color = furDark; c.drawCircle(cx, cy, r, p)
        p.color = fur; c.drawCircle(cx - r * 0.06f, cy - r * 0.06f, r * 0.93f, p)
        p.color = Color.argb(70, 255, 255, 255); c.drawCircle(cx, cy + r * 0.38f, r * 0.5f, p)

        // eyes: white, big pupils, blinking; closed arcs while asleep
        if (t > nextBlink + 0.15) nextBlink = t + 2.5 + (t * 7.3 % 3.0)
        val blinking = t > nextBlink && m != FurbyCompanion.Mood.SLEEPING
        for (side in listOf(-1f, 1f)) {
            val ex = cx + side * r * 0.36f; val ey = cy - r * 0.22f
            if (m == FurbyCompanion.Mood.SLEEPING || blinking) {
                p.color = 0xFF2A1B3D.toInt(); p.style = Paint.Style.STROKE; p.strokeWidth = r * 0.05f; p.strokeCap = Paint.Cap.ROUND
                oval.set(ex - r * 0.2f, ey - r * 0.12f, ex + r * 0.2f, ey + r * 0.12f)
                c.drawArc(oval, 10f, 160f, false, p)
                p.style = Paint.Style.FILL
            } else {
                p.color = Color.WHITE; oval.set(ex - r * 0.24f, ey - r * 0.28f, ex + r * 0.24f, ey + r * 0.28f); c.drawOval(oval, p)
                val look = if (m == FurbyCompanion.Mood.THINKING) -r * 0.08f else r * 0.03f * sin(t * 0.7).toFloat()
                p.color = 0xFF2A1B3D.toInt(); c.drawCircle(ex + look, ey + r * 0.04f, r * 0.13f, p)
                p.color = Color.WHITE; c.drawCircle(ex + look + r * 0.045f, ey - r * 0.03f, r * 0.04f, p)
            }
        }
        // beak: opens and closes while speaking
        val open = if (m == FurbyCompanion.Mood.SPEAKING) r * 0.12f * abs(sin(t * 2 * PI * 3.3)).toFloat() else 0f
        val by = cy + r * 0.14f
        p.color = 0xFFFF9F1C.toInt()
        path.reset(); path.moveTo(cx - r * 0.17f, by); path.lineTo(cx + r * 0.17f, by); path.lineTo(cx, by + r * 0.16f); path.close()
        c.save(); c.translate(0f, -open * 0.3f); c.drawPath(path, p); c.restore()
        p.color = 0xFFE07A00.toInt()
        path.reset(); path.moveTo(cx - r * 0.13f, by + r * 0.05f + open); path.lineTo(cx + r * 0.13f, by + r * 0.05f + open)
        path.lineTo(cx, by + r * 0.2f + open); path.close(); c.drawPath(path, p)
        c.restore()

        if (m == FurbyCompanion.Mood.SLEEPING) {                    // floating z's
            p.color = 0xFF6D5BD0.toInt(); p.textSize = r * 0.28f; p.isFakeBoldText = true
            for (k in 0..2) {
                val ph = ((t * 0.4 + k / 3.0) % 1.0).toFloat()
                p.alpha = ((1 - ph) * 255).toInt()
                c.drawText("z", cx + r * (0.7f + ph * 0.5f), cy - r * (0.8f + ph * 0.8f), p)
            }
            p.alpha = 255
        }
    }
}

/** Mic level on a log scale with the threshold marked, so you can see where speech lands. */
class LevelMeter(ctx: Context, private val level: () -> Float, private val peak: () -> Float, private val threshold: () -> Float) : View(ctx) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rect = RectF()

    override fun onDraw(c: Canvas) {
        val w = width.toFloat(); val h = height.toFloat(); val rad = h / 2
        rect.set(0f, 0f, w, h); p.color = 0xFFFCE4F1.toInt(); c.drawRoundRect(rect, rad, rad, p)
        val lv = level(); val thr = threshold()
        rect.set(0f, 0f, maxOf(h, w * pos(lv)), h)
        p.color = if (lv > thr) 0xFF22C55E.toInt() else 0xFFFF7AB8.toInt(); c.drawRoundRect(rect, rad, rad, p)
        p.color = 0x99FF3D9A.toInt(); val px = w * pos(peak()); c.drawRect(px - 2, h * 0.2f, px + 2, h * 0.8f, p)
        p.color = 0xFF2A1B3D.toInt(); val tx = w * pos(thr); c.drawRoundRect(tx - 4, -2f, tx + 4, h + 2, 4f, 4f, p)
        postInvalidateDelayed(66)
    }

    companion object {
        const val MIN = 0.001f; const val MAX = 0.2f
        /** 0..1 position of a level on the log scale shared with the slider. */
        fun pos(v: Float) = ((ln(v.coerceIn(MIN, MAX)) - ln(MIN)) / (ln(MAX) - ln(MIN)))
        fun value(pos: Float) = kotlin.math.exp(ln(MIN) + pos.coerceIn(0f, 1f) * (ln(MAX) - ln(MIN)))
    }
}
