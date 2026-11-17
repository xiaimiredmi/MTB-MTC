package dev.mtc;

import android.content.Context;
import android.os.Environment;

import java.io.File;
import java.io.FileFilter;
import java.io.FileOutputStream;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * Where the pictures live.
 *
 * <p>App-specific external storage: no permission needed on any supported
 * Android version, visible over USB at
 * {@code Android/data/dev.mtc/files/Pictures}, and deleted with the app. That
 * keeps the camera usable without asking for storage access first.
 */
public final class Store {
    private Store() {
    }

    public static File dir(Context context) {
        File base = context.getExternalFilesDir(Environment.DIRECTORY_PICTURES);
        if (base == null) {
            base = new File(context.getFilesDir(), "Pictures");
        }
        if (!base.exists()) {
            //noinspection ResultOfMethodCallIgnored
            base.mkdirs();
        }
        return base;
    }

    /** Newest first. */
    public static List<File> list(Context context) {
        File[] files = dir(context).listFiles(new FileFilter() {
            @Override
            public boolean accept(File file) {
                return file.isFile()
                        && file.getName().toLowerCase(Locale.ROOT).endsWith(".mtc");
            }
        });
        List<File> out = new ArrayList<File>();
        if (files != null) {
            Collections.addAll(out, files);
        }
        Collections.sort(out, new Comparator<File>() {
            @Override
            public int compare(File a, File b) {
                return Long.compare(b.lastModified(), a.lastModified());
            }
        });
        return out;
    }

    public static long totalBytes(List<File> files) {
        long n = 0;
        for (int i = 0; i < files.size(); i++) {
            n += files.get(i).length();
        }
        return n;
    }

    public static File nextPhoto(Context context) {
        String stamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date());
        return new File(dir(context), "IMG_" + stamp + ".mtc");
    }

    public static boolean write(File file, byte[] data) {
        try {
            FileOutputStream out = new FileOutputStream(file);
            try {
                out.write(data);
                out.getFD().sync();
            } finally {
                out.close();
            }
            return true;
        } catch (IOException e) {
            return false;
        }
    }

    /**
     * The cached thumbnail for a picture.
     *
     * <p>Decoding a 12 MP file takes half a second; doing that for every cell of
     * the grid every time it is opened is not acceptable. The first view writes a
     * small PNG next to the picture and every later view reads that instead.
     */
    public static File thumbFile(File mtc) {
        return new File(mtc.getAbsolutePath() + ".thumb.png");
    }

    /** Build (or refresh) the cached thumbnail; returns false if it could not. */
    public static boolean writeThumbnail(File mtc, int side) {
        File thumb = thumbFile(mtc);
        android.graphics.Bitmap bmp = Mtc.thumbnail(mtc, side);
        if (bmp == null) {
            return false;
        }
        try {
            FileOutputStream out = new FileOutputStream(thumb);
            try {
                return bmp.compress(android.graphics.Bitmap.CompressFormat.PNG, 95, out);
            } finally {
                out.close();
                bmp.recycle();
            }
        } catch (IOException e) {
            return false;
        }
    }

    /** True when the cached thumbnail is at least as new as the picture. */
    public static boolean hasThumbnail(File mtc) {
        File thumb = thumbFile(mtc);
        return thumb.exists() && thumb.lastModified() >= mtc.lastModified();
    }

    public static void deleteWithThumbnail(File mtc) {
        //noinspection ResultOfMethodCallIgnored
        thumbFile(mtc).delete();
        //noinspection ResultOfMethodCallIgnored
        mtc.delete();
    }

    public static String human(long bytes) {
        if (bytes >= 1024L * 1024L) {
            return String.format(Locale.US, "%.2f MB", bytes / 1048576.0);
        }
        if (bytes >= 1024L) {
            return String.format(Locale.US, "%.1f KB", bytes / 1024.0);
        }
        return bytes + " B";
    }
}
