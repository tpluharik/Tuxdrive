package io.github.tuxindrive.mobile

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MobileNetworkControllerTest {
    @Test
    fun networkOperationsAreSerialized() {
        val running = AtomicInteger(0)
        val maximum = AtomicInteger(0)
        val started = CountDownLatch(2)
        val pool = Executors.newFixedThreadPool(2)
        repeat(2) {
            pool.submit {
                started.countDown()
                MobileNetworkController.exclusive {
                    val active = running.incrementAndGet()
                    maximum.updateAndGet { old -> maxOf(old, active) }
                    Thread.sleep(20)
                    running.decrementAndGet()
                }
            }
        }
        assertTrue(started.await(1, TimeUnit.SECONDS))
        pool.shutdown()
        assertTrue(pool.awaitTermination(2, TimeUnit.SECONDS))
        assertEquals(1, maximum.get())
    }

    @Test
    fun exceptionDoesNotLeakTheNetworkPermit() {
        runCatching {
            MobileNetworkController.exclusive { error("stop") }
        }
        assertEquals("next", MobileNetworkController.exclusive { "next" })
    }
}
