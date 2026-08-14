package io.github.tuxindrive.mobile

import java.util.concurrent.Semaphore

object MobileNetworkController {
    private val gate = Semaphore(1, true)

    fun <T> exclusive(operation: () -> T): T {
        gate.acquire()
        return try {
            operation()
        } finally {
            gate.release()
        }
    }
}
