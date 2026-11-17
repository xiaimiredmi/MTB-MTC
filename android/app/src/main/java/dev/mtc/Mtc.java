package dev.mtc;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;

import java.io.File;
import java.nio.ByteBuffer;

/**
 * The codec, through JNI.
 *
 * <p>Encoding takes either RGBA bytes or the three planes of a Camera2
 * {@code YUV_420_888} frame; decoding returns an 8-byte big-endian
 * width/height header followed by RGBA, which is exactly what
 * {@link Bitmap#copyPixelsFromBuffer} wants on Android (Skia stores
 * ARGB_8888 as RGBA bytes).
 */
public final class Mtc {
    static {
        System.loadLibrary("mtcjni");
    }

    private Mtc() {
    }

    /** Forces the native library to load, so the first capture does not pay for it. */
    public static void warmUp() {
    }

    public static native byte[] encodeRgba(byte[] rgba, int width, int height, int quality);

    public static native byte[] encodeYuv(byte[] y, byte[] u, byte[] v,
                                          int width, int height,
                                          int yRowStride, int uvRowStride, int uvPixelStride,
                                          int quality);

    public static native byte[] decodeRgba(byte[] mtc, int maxSide);

    public static native String info(byte[] mtc);

    public static int width(byte[] decoded) {
        return intAt(decoded, 0);
    }

    public static int height(byte[] decoded) {
        return intAt(decoded, 4);
    }

    private static int intAt(byte[] b, int off) {
        return ((b[off] & 0xff) << 24) | ((b[off + 1] & 0xff) << 16)
                | ((b[off + 2] & 0xff) << 8) | (b[off + 3] & 0xff);
    }

    /** Decoded buffer to a bitmap, or null if the payload was unusable. */
    public static Bitmap toBitmap(byte[] decoded) {
        if (decoded == null || decoded.length < 8) {
            return null;
        }
        int w = width(decoded);
        int h = height(decoded);
        if (w <= 0 || h <= 0 || decoded.length < 8 + w * h * 4) {
            return null;
        }
        Bitmap bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
        ByteBuffer buf = ByteBuffer.wrap(decoded, 8, w * h * 4);
        bmp.copyPixelsFromBuffer(buf);
        return bmp;
    }

    /** File bytes, or null when the file is missing or unreadable. */
    public static byte[] read(File file) {
        try {
            byte[] data = new byte[(int) file.length()];
            java.io.FileInputStream in = new java.io.FileInputStream(file);
            try {
                int off = 0;
                while (off < data.length) {
                    int n = in.read(data, off, data.length - off);
                    if (n < 0) {
                        break;
                    }
                    off += n;
                }
            } finally {
                in.close();
            }
            return data;
        } catch (java.io.IOException e) {
            return null;
        }
    }

    /** Thumbnail of a file, or null. Skips the JPEG path entirely. */
    public static Bitmap thumbnail(File file, int maxSide) {
        byte[] data = read(file);
        if (data == null) {
            return null;
        }
        return toBitmap(decodeRgba(data, maxSide));
    }

    /** Any ordinary image the codec cannot read yet (JPEG/PNG dropped in by hand). */
    public static Bitmap fallbackBitmap(File file, int maxSide) {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inSampleSize = 1;
        return BitmapFactory.decodeFile(file.getAbsolutePath(), o);
    }
}
