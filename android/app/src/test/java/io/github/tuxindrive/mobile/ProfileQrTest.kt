package io.github.tuxindrive.mobile

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ProfileQrTest {
    private val stableFrame =
        "TUXINDRIVE-PROFILE/1/6d353e2ec2700baa/1/1/" +
            "6d353e2ec2700baa6f76dfe31dce1e8637b205e81e26d505f899c92603c9ba1f/" +
            "eNpLLsovLtYtyEksScsvytUtKMpPy8xJBQBl9Qjb"

    @Test
    fun assemblesTheStableDesktopProtocolFrame() {
        val progress = ProfileQrAssembler().add(stableFrame)
        assertEquals(1, progress.received)
        assertEquals(1, progress.total)
        assertArrayEquals("cross-platform-profile".toByteArray(), progress.profile)
    }

    @Test
    fun rejectsForeignMalformedAndTamperedFrames() {
        val assembler = ProfileQrAssembler()
        assertThrows(IllegalArgumentException::class.java) { assembler.add("not-a-profile") }
        val tampered = stableFrame.dropLast(1) + "A"
        assertThrows(IllegalArgumentException::class.java) { assembler.add(tampered) }
    }
}
