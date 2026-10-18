package fluffkit.companion

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * The same commands as the HTTP remote, for adb (MIUI blocks `input tap`). Only the shell can send these: the
 * receiver requires DUMP.
 *
 *   adb shell am broadcast -a fluffkit.companion.DEBUG --es cmd say --es text "Hei!"
 */
class DebugReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val cmd = intent.getStringExtra("cmd") ?: return
        val text = intent.getStringExtra("text") ?: ""
        Log.i("adb: $cmd $text")
        val r = Commands.run((ctx.applicationContext as App).companion, cmd, text)
        if (r != "ok") Log.i(r)
    }
}
