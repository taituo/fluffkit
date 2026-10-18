package fluffkit.companion

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Handler
import android.os.HandlerThread
import java.util.UUID
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit

/**
 * Furby Connect over BLE (PyFluff / bluefluff): one GATT link, writes one at a time, keepalive 20 06 every 3 s,
 * reconnect forever by address once Furby has been found by a scan.
 */
@SuppressLint("MissingPermission")
class Furby(private val ctx: Context, private val settings: Settings) {
    enum class State { DISCONNECTED, SCANNING, CONNECTING, CONNECTED }

    @Volatile var state = State.DISCONNECTED
        private set(v) { field = v; onState(v) }
    var onState: (State) -> Unit = {}

    private val adapter: BluetoothAdapter? = (ctx.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
    private val thread = HandlerThread("furby-ble").apply { start() }
    private val h = Handler(thread.looper)
    private var gatt: BluetoothGatt? = null
    private var gpw: BluetoothGattCharacteristic? = null
    private var wanted = false          // true while the app wants a link; false after stop()

    // one write at a time: Android drops a write issued before the previous one finished
    private val writes = LinkedBlockingQueue<ByteArray>()
    private val written = Semaphore(0)
    private val writer = Thread({
        while (true) {
            val bytes = writes.take()
            val g = gatt; val c = gpw
            if (g == null || c == null) continue
            written.drainPermits()
            c.writeType = if (c.properties and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE != 0)
                BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE else BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            @Suppress("DEPRECATION")
            c.value = bytes
            @Suppress("DEPRECATION")
            if (g.writeCharacteristic(c)) written.tryAcquire(500, TimeUnit.MILLISECONDS)
            else Log.i("write: epäonnistui ${hex(bytes)}")
        }
    }, "furby-writer").apply { isDaemon = true; start() }

    fun send(vararg bytes: Int) = send(ByteArray(bytes.size) { bytes[it].toByte() })
    fun send(bytes: ByteArray) { if (gpw != null) writes.offer(bytes) }

    val connected get() = state == State.CONNECTED

    /** Connect to the remembered Furby, or scan for one named "Furby…" first. */
    fun start() {
        wanted = true
        h.post {
            if (gatt != null) return@post
            val addr = settings.furbyAddress
            if (addr != null) connect(adapter!!.getRemoteDevice(addr)) else scan()
        }
    }

    /** Forget the remembered address and look for a Furby again. */
    fun rescan() {
        h.post { settings.furbyAddress = null; close(); wanted = true; scan() }
    }

    fun stop() { wanted = false; h.post { close(); state = State.DISCONNECTED } }

    private fun close() {
        h.removeCallbacksAndMessages(null)
        try { adapter?.bluetoothLeScanner?.stopScan(scanCb) } catch (_: Exception) {}
        gpw = null
        gatt?.close(); gatt = null
    }

    private val scanCb = object : ScanCallback() {
        override fun onScanResult(type: Int, r: ScanResult) {
            val name = r.scanRecord?.deviceName ?: r.device.name ?: return
            if (!name.startsWith("Furby")) return
            h.post {
                if (state != State.SCANNING) return@post
                adapter?.bluetoothLeScanner?.stopScan(this)
                Log.i("löytyi $name ${r.device.address}")
                settings.furbyAddress = r.device.address
                connect(r.device)
            }
        }
        override fun onScanFailed(code: Int) { Log.i("haku epäonnistui: $code"); retry() }
    }

    private fun scan() {
        val sc = adapter?.bluetoothLeScanner
        if (adapter?.isEnabled != true || sc == null) { Log.i("Bluetooth on pois päältä"); retry(); return }
        state = State.SCANNING
        Log.i("etsitään Furbya…")
        sc.startScan(null, ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), scanCb)
        h.postDelayed({ if (state == State.SCANNING) { sc.stopScan(scanCb); Log.i("Furbya ei löytynyt; herätä se"); retry() } }, 20_000)
    }

    private fun connect(d: BluetoothDevice) {
        state = State.CONNECTING
        gatt?.close()
        gatt = d.connectGatt(ctx, false, cb, BluetoothDevice.TRANSPORT_LE)
        // a direct connect gives up by itself after ~30 s (status 133); don't wait forever on a sleeping Furby
        h.postDelayed({ if (state == State.CONNECTING) { Log.i("yhdistys aikakatkaistiin"); drop() } }, 15_000)
    }

    private fun drop() {
        gpw = null; gatt?.close(); gatt = null
        state = State.DISCONNECTED
        retry()
    }

    // Furby drops the link when it sleeps or restarts; keep retrying while the app wants it
    private fun retry() {
        if (!wanted) return
        h.postDelayed({
            if (!wanted || gatt != null) return@postDelayed
            val addr = settings.furbyAddress
            if (addr != null) connect(adapter!!.getRemoteDevice(addr)) else scan()
        }, 4_000)
    }

    private val keepalive = object : Runnable {
        override fun run() { if (state == State.CONNECTED) { send(0x20, 0x06); h.postDelayed(this, 3_000) } }
    }

    private val cb = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            h.post {
                if (g != gatt) { g.close(); return@post }
                if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                    g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
                    g.discoverServices()
                } else {
                    if (state == State.CONNECTED) Log.i("yhteys katkesi ($status)")
                    drop()
                }
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            h.post {
                val svc = g.getService(SVC)
                val w = svc?.getCharacteristic(GP_W); val n = svc?.getCharacteristic(GP_N)
                if (w == null || n == null) { Log.i("Furbyn palvelua ei löytynyt"); drop(); return@post }
                g.setCharacteristicNotification(n, true)
                n.getDescriptor(CCCD)?.let {
                    @Suppress("DEPRECATION")
                    it.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    @Suppress("DEPRECATION")
                    g.writeDescriptor(it)
                }
                gpw = w
                state = State.CONNECTED
                Log.i("yhdistetty: ${g.device.name ?: g.device.address}")
                h.postDelayed(keepalive, 3_000)
            }
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) { written.release() }
        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, status: Int) { written.release() }

        @Deprecated("API < 33")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION") notified(c.value ?: return)
        }
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) = notified(value)
    }

    private fun notified(d: ByteArray) {
        if (d.isEmpty() || d[0] == 0x21.toByte() || d[0] == 0x22.toByte()) return      // sensors / keepalive status
        val msg = if (d[0] == 0x20.toByte() && d.size > 1) MSG[d[1].toInt() and 0xff] ?: "" else ""
        Log.i("← ${hex(d)}  $msg")
    }

    companion object {
        val SVC: UUID = UUID.fromString("dab91435-b5a1-e29c-b041-bcd562613bde")
        val GP_W: UUID = UUID.fromString("dab91383-b5a1-e29c-b041-bcd562613bde")
        val GP_N: UUID = UUID.fromString("dab91382-b5a1-e29c-b041-bcd562613bde")
        val CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        val MSG = mapOf(0x06 to "RESPONSE_PLAYED", 0x07 to "SPEECH_PLAYING", 0x0c to "SEQUENCE_PLAYING",
            0x0e to "SEQUENCE_ENDED", 0x0f to "INPUT_OUT_OF_RANGE", 0x19 to "GROUP_NOT_ACTIVE")
        fun hex(b: ByteArray) = b.joinToString(":") { "%02x".format(it) }
    }
}
