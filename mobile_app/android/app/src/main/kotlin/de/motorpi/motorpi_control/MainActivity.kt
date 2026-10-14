package de.motorpi.motorpi_control

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.input.InputManager
import android.os.Build
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity(), InputManager.InputDeviceListener {
    private var sink: EventChannel.EventSink? = null
    private var pending: MethodChannel.Result? = null
    private var forward = 0.0
    private var steer = 0.0
    private var held = false
    private var deviceId = -1
    private var name = "Kein Controller"

    override fun configureFlutterEngine(engine: FlutterEngine) {
        super.configureFlutterEngine(engine)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        (getSystemService(Context.INPUT_SERVICE) as InputManager).registerInputDeviceListener(this, null)
        EventChannel(engine.dartExecutor.binaryMessenger, "motorpi/gamepad").setStreamHandler(object: EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink) { sink = events; emit() }
            override fun onCancel(arguments: Any?) { sink = null }
        })
        MethodChannel(engine.dartExecutor.binaryMessenger, "motorpi/platform").setMethodCallHandler { call, result ->
            if (call.method != "bluetoothPermissions") { result.notImplemented() }
            else if (pending != null) { result.error("busy", "Permission request pending", null) }
            else {
                val permissions = if (Build.VERSION.SDK_INT >= 31) arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
                    else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
                val missing = permissions.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
                if (missing.isEmpty()) result.success(true)
                else { pending = result; requestPermissions(missing.toTypedArray(), 401) }
            }
        }
    }
    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code, permissions, results)
        if (code == 401) { pending?.success(results.isNotEmpty() && results.all { it == PackageManager.PERMISSION_GRANTED }); pending = null }
    }
    private fun emit(start: Boolean = false, stop: Boolean = false, connected: Boolean = true) {
        sink?.success(mapOf("forward" to forward, "steer" to steer, "held" to held,
            "start" to start, "stop" to stop, "connected" to connected, "name" to name))
    }
    private fun reset() { forward = 0.0; steer = 0.0; held = false; emit(stop = true) }
    override fun onGenericMotionEvent(event: MotionEvent): Boolean {
        if ((event.source and InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK && event.action == MotionEvent.ACTION_MOVE) {
            if (deviceId != -1 && deviceId != event.deviceId) reset()
            deviceId = event.deviceId; name = event.device?.name ?: "Gamecontroller"
            val x = event.getAxisValue(MotionEvent.AXIS_X).toDouble()
            val y = -event.getAxisValue(MotionEvent.AXIS_Y).toDouble()
            steer = if (kotlin.math.abs(x) < .08) 0.0 else x.coerceIn(-1.0, 1.0)
            forward = if (kotlin.math.abs(y) < .08) 0.0 else y.coerceIn(-1.0, 1.0)
            emit(); return true
        }
        return super.onGenericMotionEvent(event)
    }
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val gamepad = (event.source and InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD
        if (gamepad && event.keyCode in listOf(KeyEvent.KEYCODE_BUTTON_A, KeyEvent.KEYCODE_BUTTON_B, KeyEvent.KEYCODE_BUTTON_L1)) {
            if (deviceId != -1 && deviceId != event.deviceId) reset()
            deviceId = event.deviceId; name = event.device?.name ?: "Gamecontroller"
            val down = event.action == KeyEvent.ACTION_DOWN
            if (event.keyCode == KeyEvent.KEYCODE_BUTTON_L1) held = down
            if (event.repeatCount == 0) emit(start = down && event.keyCode == KeyEvent.KEYCODE_BUTTON_A,
                stop = down && event.keyCode == KeyEvent.KEYCODE_BUTTON_B)
            return true
        }
        return super.dispatchKeyEvent(event)
    }
    override fun onInputDeviceRemoved(id: Int) { if (id == deviceId) { reset(); deviceId = -1; name = "Controller getrennt"; emit(connected = false) } }
    override fun onInputDeviceAdded(id: Int) {}
    override fun onInputDeviceChanged(id: Int) { if (id == deviceId) reset() }
    override fun onPause() { reset(); super.onPause() }
    override fun onWindowFocusChanged(hasFocus: Boolean) { super.onWindowFocusChanged(hasFocus); if (!hasFocus) reset() }
    override fun onDestroy() { (getSystemService(Context.INPUT_SERVICE) as InputManager).unregisterInputDeviceListener(this); super.onDestroy() }
}
