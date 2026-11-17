package dev.mtc;

/**
 * Host copy of the native surface, for the smoke test.
 *
 * <p>JNI resolves a symbol by the declaring class's name, so this must stay
 * {@code dev.mtc.Mtc} with the same method names and parameter types as the app's
 * {@code Mtc}. It deliberately has no Android imports, so it compiles and runs
 * against the same Rust library on a desktop JVM — which is how the marshalling
 * gets checked without a phone.
 */
public final class Mtc {
    static {
        System.loadLibrary("mtcjni");
    }

    private Mtc() {
    }

    public static native byte[] encodeRgba(byte[] rgba, int width, int height, int quality);

    public static native byte[] encodeYuv(byte[] y, byte[] u, byte[] v,
                                          int width, int height,
                                          int yRowStride, int uvRowStride, int uvPixelStride,
                                          int quality, boolean fullRange, int rotation,
                                          boolean mirror);

    public static native byte[] decodeRgba(byte[] mtc, int maxSide);

    public static native String info(byte[] mtc);
}
