package fluffkit.companion

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kotlinx.coroutines.launch
import java.io.File

/**
 * Test hooks for adb (MIUI blocks `input tap`). Only the shell can send these: the receiver requires DUMP.
 *
 *   adb shell am broadcast -a fluffkit.companion.DEBUG --es cmd chat --es text "Kerro vitsi"
 *   cmd: say <text> · chat <text> · act <a/b/c/d> · tag <liike|nauru|tanssi|…> · antenna <state> ·
 *        listen on|off · reload · hear <wav path in the app's files dir> · sleep · wake
 */
class DebugReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val c = (ctx.applicationContext as App).companion
        val text = intent.getStringExtra("text") ?: ""
        Log.i("debug: ${intent.getStringExtra("cmd")} $text")
        when (intent.getStringExtra("cmd")) {
            "say" -> c.scope.launch { c.speak(text) }
            "chat" -> c.scope.launch { c.chat(text) }
            "act" -> c.act(text.split("/").map { it.trim().toInt() }.toIntArray(), "debug")
            "tag" -> c.scope.launch { c.chatScript("[$text]") }
            "antenna" -> c.antenna(text)
            "listen" -> c.setListening(text != "off")
            "reload" -> c.reload()
            "hear" -> c.hear(File(c.settings.dir, text).readBytes())
            "sleep" -> c.scope.launch { c.sleepFurby() }
            "wake" -> c.scope.launch { c.wakeFurby() }
        }
    }
}
