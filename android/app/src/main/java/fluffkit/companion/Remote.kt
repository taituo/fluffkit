package fluffkit.companion

import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream
import java.net.ServerSocket
import java.net.Socket
import java.security.MessageDigest
import kotlin.concurrent.thread

/** The commands the remote, the adb receiver and the buttons share. Returns a short status. */
object Commands {
    val FILES = setOf("furby-config.json", "AGENTS.md", "packs.json")

    fun run(c: FurbyCompanion, cmd: String, text: String = ""): String {
        when (cmd) {
            "say" -> c.scope.launch { c.speak(text) }
            "chat" -> c.scope.launch { c.chat(text) }
            "tag" -> c.scope.launch { c.chatScript(if (text.startsWith("[")) text else "[$text]") }
            "act" -> c.act(text.split("/").map { it.trim().toInt() }.toIntArray(), "remote")
            "antenna" -> c.antenna(text)
            "listen" -> c.setListening(text != "off")
            "threshold" -> { c.settings.threshold = text.toFloat() }
            "sleep" -> c.scope.launch { c.sleepFurby() }
            "wake" -> c.scope.launch { c.wakeFurby() }
            "reload" -> c.reload()
            "forget" -> c.brain.reset()
            "rescan" -> c.furby.rescan()
            "connect" -> c.furby.start()
            "hear" -> c.hear(File(c.settings.dir, text).readBytes())
            else -> return "unknown command: $cmd"
        }
        return "ok"
    }

    fun state(c: FurbyCompanion): JSONObject = JSONObject()
        .put("version", App.instance.version)
        .put("furby", c.furby.state.name.lowercase())
        .put("service", CompanionService.running)
        .put("listening", c.listener.on)
        .put("recording", c.listener.recording)
        .put("level", c.listener.level.toDouble())
        .put("busy", c.busy)
        .put("sleeping", c.sleeping)
        .put("heard", c.heard)
        .put("saying", c.saying)
        .put("pack", c.packName)
}

/**
 * Remote control over HTTP, so nobody has to touch the phone in the backpack. Plain HTTP on port 8770 (adb forward,
 * the LAN or Tailscale), every request needs `Authorization: Bearer <remote_token>`; without a token it stays off.
 *
 *   GET  /state                       JSON: Furby link, listening, sleeping, what was heard / is being said
 *   GET  /log                         the debug log
 *   POST /cmd   {"cmd": "say", "text": "Hei!"}      (see Commands.run)
 *   PUT  /file/furby-config.json      body = file; also AGENTS.md, packs.json. Reloads.
 *   POST /secrets {"elevenlabs_key": …, "llm_url": …, "llm_bearer": …, "llm_model": …}
 */
class Remote(private val c: FurbyCompanion) {
    private var server: ServerSocket? = null

    fun start() {
        if (server != null) return
        if (c.settings.remoteToken.isBlank()) { Log.i("etäohjaus pois (ei remote_token)"); return }
        val s = try { ServerSocket(PORT) } catch (e: Exception) { Log.i("etäohjaus: ${e.message}"); return }
        server = s
        Log.i("etäohjaus portissa $PORT")
        thread(name = "furby-remote", isDaemon = true) {
            while (!s.isClosed) {
                val sock = try { s.accept() } catch (_: Exception) { break }
                thread(isDaemon = true) { sock.use { handle(it) } }
            }
        }
    }

    fun stop() { server?.close(); server = null }

    private fun handle(sock: Socket) {
        sock.soTimeout = 10_000
        val inp = BufferedInputStream(sock.getInputStream())
        val reqLine = readLine(inp) ?: return
        val headers = mutableMapOf<String, String>()
        while (true) {
            val l = readLine(inp) ?: return
            if (l.isEmpty()) break
            val i = l.indexOf(':')
            if (i > 0) headers[l.substring(0, i).trim().lowercase()] = l.substring(i + 1).trim()
        }
        val len = headers["content-length"]?.toIntOrNull() ?: 0
        if (len > 2_000_000) return reply(sock, 413, "too large")
        val body = ByteArray(len).also { var n = 0; while (n < len) { val r = inp.read(it, n, len - n); if (r < 0) break; n += r } }
        val (method, path) = reqLine.split(" ").let { (it.getOrNull(0) ?: "") to (it.getOrNull(1) ?: "") }

        val token = headers["authorization"]?.removePrefix("Bearer ")?.trim() ?: ""
        if (!MessageDigest.isEqual(token.toByteArray(), c.settings.remoteToken.toByteArray())) return reply(sock, 401, "unauthorized")

        try {
            when {
                method == "GET" && (path == "/state" || path == "/status") -> reply(sock, 200, Commands.state(c).toString(), "application/json")
                method == "GET" && path == "/log" -> reply(sock, 200, Log.text())
                method == "POST" && path == "/cmd" -> {
                    val j = JSONObject(String(body))
                    val r = Commands.run(c, j.optString("cmd"), j.optString("text"))
                    reply(sock, if (r == "ok") 200 else 400, r)
                }
                // short forms: POST /say {"text"} · /chat {"text"} · /sleep · /wake · /trick {"name"} ·
                // /light {"colour"} ("vilkku" = rainbow) · /listen {"on": bool} · /config (reload) · /connect
                method == "POST" && path in SHORT -> {
                    val j = if (body.isEmpty()) JSONObject() else JSONObject(String(body))
                    val r = when (path) {
                        "/say", "/chat" -> Commands.run(c, path.drop(1), j.optString("text"))
                        "/sleep", "/wake" -> Commands.run(c, path.drop(1))
                        "/trick" -> Commands.run(c, "tag", j.optString("name"))
                        "/light" -> j.optString("colour", j.optString("color")).let {
                            Commands.run(c, "tag", if (it == "vilkku") "vilkku" else "valo: $it") }
                        "/listen" -> Commands.run(c, "listen", if (j.optBoolean("on", true)) "on" else "off")
                        "/config" -> Commands.run(c, "reload")
                        else -> Commands.run(c, "connect")
                    }
                    reply(sock, if (r == "ok") 200 else 400, r)
                }
                method == "PUT" && path.startsWith("/file/") -> {
                    val name = path.removePrefix("/file/")
                    if (name !in Commands.FILES) return reply(sock, 400, "allowed: ${Commands.FILES}")
                    if (name.endsWith(".json")) String(body).trim().let { if (it.startsWith("[")) org.json.JSONArray(it) else JSONObject(it) }
                    File(c.settings.dir, name).writeBytes(body)
                    c.reload()
                    reply(sock, 200, "saved $name")
                }
                method == "POST" && path == "/secrets" -> {
                    JSONObject(String(body))
                    File(c.settings.dir, "secrets.json").writeBytes(body)
                    c.reload()                                      // imports and deletes it
                    reply(sock, 200, "ok")
                }
                else -> reply(sock, 404, "not found")
            }
        } catch (e: Exception) {
            reply(sock, 400, e.message ?: "error")
        }
    }

    private fun readLine(inp: InputStream): String? {
        val b = ByteArrayOutputStream()
        while (true) {
            val ch = inp.read()
            if (ch < 0) return if (b.size() > 0) b.toString("UTF-8") else null
            if (ch == '\n'.code) return b.toString("UTF-8").trimEnd('\r')
            if (b.size() > 8192) return null
            b.write(ch)
        }
    }

    private fun reply(sock: Socket, code: Int, text: String, type: String = "text/plain; charset=utf-8") {
        val body = text.toByteArray()
        val head = "HTTP/1.1 $code ${if (code == 200) "OK" else "Error"}\r\nContent-Type: $type\r\n" +
            "Content-Length: ${body.size}\r\nConnection: close\r\n\r\n"
        sock.getOutputStream().apply { write(head.toByteArray()); write(body); flush() }
    }

    companion object {
        const val PORT = 8770
        val SHORT = setOf("/say", "/chat", "/sleep", "/wake", "/trick", "/light", "/listen", "/config", "/connect")
    }
}
