package fluffkit.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.ServiceCompat

/**
 * Keeps the companion running with the screen off: a foreground service (Bluetooth + microphone), a partial
 * wake lock so the CPU keeps listening, and a Wi-Fi lock so the radio does not doze between turns.
 */
class CompanionService : Service() {
    private var wake: PowerManager.WakeLock? = null
    private var wifi: WifiManager.WifiLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { stopSelf(); return START_NOT_STICKY }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Furby", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, CompanionService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_furby)
            .setContentTitle("Furby kuuntelee")
            .setContentText("Yhteys Furbyyn ja mikrofoni päällä")
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Lopeta", stop).build())
            .setOngoing(true)
            .build()
        ServiceCompat.startForeground(this, 1, n,
            ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)

        if (wake == null) {
            wake = (getSystemService(Context.POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "furby:companion").apply { acquire() }
            @Suppress("DEPRECATION")
            wifi = (applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager)
                .createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "furby:companion").apply { acquire() }
            running = true
            (application as App).companion.start()
            Log.i("palvelu käynnissä")
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        (application as App).companion.stop()
        wake?.release(); wifi?.release()
        Log.i("palvelu pysäytetty")
        super.onDestroy()
    }

    companion object {
        const val CHANNEL = "furby"
        const val ACTION_STOP = "stop"
        @Volatile var running = false

        fun start(ctx: Context) = ctx.startForegroundService(Intent(ctx, CompanionService::class.java))
        fun stop(ctx: Context) = ctx.stopService(Intent(ctx, CompanionService::class.java))
    }
}
