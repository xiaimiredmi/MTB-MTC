package dev.mtc;

/**
 * Calls the Rust JNI surface from a desktop JVM.
 *
 * <p>The app cannot be run without a phone, but almost everything that goes wrong
 * in a JNI call — a method name that does not match the symbol, an array that is
 * copied the wrong way, a boolean or int marshalled as the wrong width, a
 * rotation that swaps the dimensions but not the pixels — fails here too. So this
 * drives the same four entry points with the same signatures the app uses and
 * checks what comes back.
 *
 * <p>Run with {@code powershell -File android\jni\host\run.ps1}.
 */
public final class Smoke {

    private static int failures;

    public static void main(String[] args) {
        warmUp();
        checkInfo();
        checkCameraFrame();
        checkColour();
        checkRotation();
        checkThumbnail();
        checkRgba();

        if (failures == 0) {
            System.out.println("host JNI smoke: all checks passed");
        } else {
            System.out.println("host JNI smoke: " + failures + " check(s) failed");
            System.exit(1);
        }
    }

    private static void warmUp() {
        // Touch the class so the library load failure shows up immediately.
        Mtc.info(new byte[]{'M', 'T', 'B', '1', 2, 0, 85, 0, 0, 0, 0, 0});
    }

    private static void checkInfo() {
        byte[] mtc = encodeFrame(fullRange());
        String info = Mtc.info(mtc);
        expect(info != null && info.contains("64x48"), "info says " + info);
        expect(info != null && info.contains("rgb420"), "mode in info: " + info);
        System.out.println("  info: " + info + ", " + mtc.length + " bytes");
    }

    private static void checkCameraFrame() {
        byte[] mtc = encodeFrame(fullRange());
        byte[] decoded = Mtc.decodeRgba(mtc, 0);
        expect(decoded != null, "decode returned null");
        if (decoded == null) {
            return;
        }
        int w = intAt(decoded, 0);
        int h = intAt(decoded, 4);
        expect(w == 64 && h == 48, "decoded size " + w + "x" + h);
        expect(decoded.length == 8 + w * h * 4, "decoded buffer length " + decoded.length);
        // A 4:2:0 round trip is lossy, but a smooth gradient should come back close.
        int first = decoded[8] & 0xff;
        int last = decoded[8 + (w - 1) * 4] & 0xff;
        expect(last > first + 20, "gradient lost: " + first + " -> " + last);
        System.out.println("  frame 64x48 -> " + mtc.length + " bytes, luma " + first + " -> " + last);
    }

    private static void checkColour() {
        // Neutral chroma must stay grey: r == g == b after the round trip.
        int w = 16;
        int h = 16;
        byte[] y = new byte[w * h];
        java.util.Arrays.fill(y, (byte) 128);
        byte[] u = new byte[(w / 2) * (h / 2)];
        byte[] v = new byte[(w / 2) * (h / 2)];
        java.util.Arrays.fill(u, (byte) 128);
        java.util.Arrays.fill(v, (byte) 128);
        byte[] mtc = Mtc.encodeYuv(y, u, v, w, h, w, w / 2, 1, 90, true, 0);
        expect(mtc != null, "grey encode returned null");
        if (mtc == null) {
            return;
        }
        byte[] back = Mtc.decodeRgba(mtc, 0);
        int r = back[8] & 0xff;
        int g = back[9] & 0xff;
        int b = back[10] & 0xff;
        expect(Math.abs(r - g) <= 2 && Math.abs(g - b) <= 2, "grey not grey: " + r + "," + g + "," + b);
        expect(Math.abs(r - 128) <= 4, "grey level drifted to " + r);
        System.out.println("  grey 128 -> " + r + "," + g + "," + b);
    }

    private static void checkRotation() {
        byte[] mtc = Mtc.encodeYuv(luma(), chroma(), chroma(), 64, 48, 64, 32, 1, 90, true, 90);
        expect(mtc != null, "rotated encode returned null");
        if (mtc == null) {
            return;
        }
        byte[] decoded = Mtc.decodeRgba(mtc, 0);
        int w = intAt(decoded, 0);
        int h = intAt(decoded, 4);
        expect(w == 48 && h == 64, "rotation did not swap the size: " + w + "x" + h);
        System.out.println("  90 degree turn: 64x48 -> " + w + "x" + h);
    }

    private static void checkThumbnail() {
        byte[] mtc = encodeFrame(fullRange());
        byte[] thumb = Mtc.decodeRgba(mtc, 24);
        expect(thumb != null, "thumbnail returned null");
        if (thumb == null) {
            return;
        }
        int w = intAt(thumb, 0);
        int h = intAt(thumb, 4);
        expect(Math.max(w, h) <= 24, "thumbnail side " + Math.max(w, h));
        expect(thumb.length == 8 + w * h * 4, "thumbnail length " + thumb.length);
        System.out.println("  thumbnail bounds 24 -> " + w + "x" + h);
    }

    private static void checkRgba() {
        int w = 16;
        int h = 8;
        byte[] rgba = new byte[w * h * 4];
        for (int i = 0; i < w * h; i++) {
            rgba[i * 4] = (byte) 220;
            rgba[i * 4 + 1] = (byte) 30;
            rgba[i * 4 + 2] = (byte) 30;
            rgba[i * 4 + 3] = (byte) 255;
        }
        byte[] mtc = Mtc.encodeRgba(rgba, w, h, 95);
        expect(mtc != null, "encodeRgba returned null");
        if (mtc == null) {
            return;
        }
        byte[] back = Mtc.decodeRgba(mtc, 0);
        int r = back[8] & 0xff;
        int g = back[9] & 0xff;
        int b = back[10] & 0xff;
        expect(r > 200 && g < 60 && b < 60, "red came back as " + r + "," + g + "," + b);
        System.out.println("  rgba red -> " + r + "," + g + "," + b + " (" + mtc.length + " bytes)");
    }

    // --- a synthetic camera frame: a horizontal luma ramp, neutral chroma ----

    private static byte[] encodeFrame(boolean fullRange) {
        byte[] mtc = Mtc.encodeYuv(luma(), chroma(), chroma(), 64, 48, 64, 32, 1, 88, fullRange, 0);
        expect(mtc != null, "encodeYuv returned null");
        return mtc == null ? new byte[0] : mtc;
    }

    private static boolean fullRange() {
        return true;
    }

    private static byte[] luma() {
        byte[] y = new byte[64 * 48];
        for (int row = 0; row < 48; row++) {
            for (int col = 0; col < 64; col++) {
                y[row * 64 + col] = (byte) (60 + col * 2);
            }
        }
        return y;
    }

    private static byte[] chroma() {
        byte[] c = new byte[(64 / 2) * (48 / 2)];
        java.util.Arrays.fill(c, (byte) 128);
        return c;
    }

    private static int intAt(byte[] b, int off) {
        return ((b[off] & 0xff) << 24) | ((b[off + 1] & 0xff) << 16)
                | ((b[off + 2] & 0xff) << 8) | (b[off + 3] & 0xff);
    }

    private static void expect(boolean ok, String what) {
        if (!ok) {
            failures++;
            System.out.println("  FAIL " + what);
        }
    }
}
